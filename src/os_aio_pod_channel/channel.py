import asyncio
import inspect
from collections import namedtuple
from enum import Enum

from os_aio_pod_channel.exceptions import MiddlewareException
from os_aio_pod_channel.middleware import MiddlewareManager


class EventType(Enum):
    '''Regular transport events.'''
    FRONTEND_CONNECTED = 0
    FRONTEND_START_READING = 1
    BACKEND_CONNECTED = 2
    BACKEND_START_READING = 3
    BACKEND_READ_FINISHED = 4
    FRONTEND_CLOSE = 5
    FRONTEND_READ_FINISHED = 6
    BACKEND_CLOSE = 7
    CLEANUP_FINISHED = 8
    TRANSPOT_FINISHED = 9


class FailEventType(Enum):
    '''Regular fail events.'''
    FRONTEND_READ_TIMEOUT = 31
    BACKEND_READ_TIMEOUT = 32
    FRONTEND_WRITE_ERROR = 33
    BACKEND_WRITE_ERROR = 34
    FRONTEND_CLOSE_ERROR = 35
    BACKEND_CLOSE_ERROR = 36


class TaskEventType(Enum):
    '''Task events.'''
    FORWARD_TASK_START = 51
    BACKWARD_TASK_START = 52
    FORWARD_TASK_DONE = 53
    BACKWARD_TASK_DONE = 54
    FORWARD_TASK_ERROR = 53
    BACKWARD_TASK_ERROR = 54
    FORWARD_TASK_CANCELLED = 55
    BACKWARD_TASK_CANCELLED = 56


class ErrorEventType(Enum):
    '''Error events.'''
    MIDDLEWARE_ERROR = 77
    UNKONW = 99


ChannelEvent = namedtuple('ChannelEvent', 'event time exc')


class ChannelManager(object):

    def __init__(self, engine):
        self.engine = engine
        self.middleware = MiddlewareManager(engine)
        self.channels = {}
        self.loop = self.engine.context.loop
        self.closing = False
        self.channel_class = self.config.channel_class

    @property
    def config(self):
        return self.engine.config

    def new_channel(self, frontend, backend):
        assert not self.closing, 'Can not create new channel when closing'
        channel = self.channel_class(self, frontend, backend, loop=self.loop)
        self.channels[id(channel)] = channel
        return channel

    async def transport(self, frontend, backend):
        channel = self.new_channel(frontend, backend)
        try:
            await channel.transport()
        finally:
            await self.close_channel(channel, timeout=self.config.close_wait)

    async def close_channel(self, channel, timeout=None, now=None):
        try:
            if not channel.closed:
                await channel.close(timeout=timeout, now=now)
        finally:
            self.channels.pop(id(channel), None)

    async def close(self, timeout=None, now=None):
        self.closing = True
        if self.channels:
            await asyncio.wait(
                [self.close_channel(c, timeout=timeout)
                 for c in self.channels.values()])

    async def setup(self):
        await self.middleware.setup()

    async def cleanup(self):
        await self.middleware.cleanup()


class Channel(object):
    __slots__ = ('manager', 'frontend', 'backend',
                 'closed', 'loop', 'read_max',
                 'request', 'debug', 'events')

    def __init__(self, manager, frontend=None, backend=None, loop=None):
        self.manager = manager
        self.frontend = frontend
        self.backend = backend
        self.closed = False
        self.read_max = manager.config.read_max
        self.loop = asyncio.get_event_loop() if loop is None else loop
        self.debug = self.loop.get_debug()
        self.events = [] if self.debug else None

    def save_event(self, event, e=None):
        if self.debug:
            event = ChannelEvent(event, self.loop.time(), e)
            self.events.append(event)

    def set_backend(self, endpoint):
        pass

    async def transport(self):
        pass

    async def close(self, timeout=None, now=None):
        pass


class FullDuplexChannel(Channel):

    __slots__ = ('forward_task', 'backward_task',
                 'connected_event', 'closing_event', 'closing_trigger',
                 'forward_action', 'backward_action')

    def __init__(self, manager, frontend=None, backend=None, loop=None):
        super(FullDuplexChannel, self).__init__(
            manager, frontend=frontend, backend=backend, loop=loop)
        self.save_event(EventType.FRONTEND_CONNECTED)
        self.forward_task = self.backward_task = None
        self.connected_event = asyncio.Event(loop=self.loop)
        self.closing_event = asyncio.Event(loop=self.loop)
        self.closing_trigger = None
        self.forward_action = self._do_build_connection
        self.backward_action = self._do_wait_connection

        if backend:
            self.set_backend(backend)

    def set_backend(self, endpoint):
        assert not self.backend
        self.backend = endpoint
        self.save_event(EventType.BACKEND_CONNECTED)
        self.connected_event.set()

    @property
    def connected(self):
        return self.connected_event.is_set()

    def cancel(self):
        for task in (self.forward_task, self.backward_task):
            if not task.done():
                task.cancel()

    async def _close(self, timeout=None, now=None):
        if self.closed:
            return

        if timeout is None:
            if self.closing_trigger is not None:
                self.closing_trigger.cancel()
                self.closing_trigger = None
            self.cancel()
            return

        timeout = timeout - (self.loop.time() - now if now else 0)
        now = self.loop.time()
        if self.closing_trigger is not None:
            if self.closing_trigger._when <= now + timeout:
                return
            self.closing_trigger.cancel()
        self.closing_trigger = self.loop.call_later(timeout, self.cancel)

    async def close(self, timeout=None, now=None):
        if self.closed:
            return

        while not self.closing_event.is_set():
            await self._close(timeout=timeout, now=now)
            await self.closing_event.wait()

        if not self.closed:
            self.closed = True

    async def transport(self):

        await self._transport_startup()

        try:
            await self._transport_cleanup()
        finally:
            self.save_event(EventType.TRANSPOT_FINISHED)
            self.closed = True
            self.closing_event.set()

    async def _transport_startup(self):

        def save_status(finished_tasks):
            mapping = {self.forward_task: 'FORWARD_TASK_',
                       self.backward_task: 'BACKWARD_TASK_'}
            for task in finished_tasks:
                prefix = mapping[task]
                suffix = 'DONE'
                e = None
                if task.cancelled():
                    suffix = 'CANCELLED'
                elif task.exception():
                    suffix = 'ERROR'
                    e = task.exception()
                self.save_event(getattr(TaskEventType, prefix+suffix), e)

        done = []
        pending = []

        for name, done_callback in {'forward': self._do_close_backend,
                                    'backward': self._do_close_frontend}.items():
            task = asyncio.ensure_future(
                getattr(self, '_'+name)(), loop=self.loop)
            task.add_done_callback(done_callback)
            pending.append(task)
            setattr(self, name+'_task', task)

        while pending:
            done, pending = await asyncio.wait(pending, loop=self.loop,
                                               return_when=asyncio.FIRST_COMPLETED)
            if self.debug:
                save_status(done)

    async def _transport_cleanup(self):
        for name in ('frontend', 'backend'):
            endpoint = getattr(self, name)
            if endpoint.closed:
                continue
            endpoint.close()
            if self.debug:
                self.save_event(
                    getattr(EventType, name.upper() + '_CLOSE'))

        await self.manager.middleware.close(self)
        self.save_event(EventType.CLEANUP_FINISHED)

    async def _forward(self):
        self.save_event(TaskEventType.FORWARD_TASK_START)
        bypass = None
        while self.forward_action is not None:
            if inspect.iscoroutinefunction(self.forward_action):
                bypass = await self.forward_action(bypass=bypass)
            else:
                bypass = self.forward_action(bypass=bypass)

    async def _do_build_connection(self, bypass=None):
        middleware = self.manager.middleware
        self.save_event(EventType.FRONTEND_START_READING)
        while True:
            data = await self.frontend.read(self.read_max)
            if not data:
                self.save_event(EventType.FRONTEND_READ_FINISHED)
                break
            try:
                data = await middleware.forward(self, data)
            except MiddlewareException as e:
                self.save_event(ErrorEventType.MIDDLEWARE_ERROR, e)
                break
            except BaseException as e:
                self.save_event(ErrorEventType.UNKONW, e)
                break
            if self.connected:
                self.forward_action = self._do_forward
                return data

        self.forward_action = self._do_close_backend

    def _do_close_backend(self, bypass=None):
        if not self.backend.closed:
            self.save_event(EventType.BACKEND_CLOSE)
            self.backend.close()
        if not self.connected:
            self.connected_event.set()
        self.forward_action = None

    async def _do_forward(self, bypass=None):
        middleware = self.manager.middleware
        data = bypass
        while True:
            try:
                if data:
                    await self.backend.flush_write(data)
            except Exception as e:
                self.save_event(FailEventType.BACKEND_WRITE_ERROR, e)
                break
            data = await self.frontend.read(self.read_max)
            if not data:
                self.save_event(EventType.FRONTEND_READ_FINISHED)
                break
            try:
                data = await middleware.forward(self, data)
            except MiddlewareException as e:
                self.save_event(ErrorEventType.MIDDLEWARE_ERROR, e)
                break
            except BaseException as e:
                self.save_event(ErrorEventType.UNKONW, e)
                break

        self.forward_action = self._do_close_backend

    async def _backward(self):
        self.save_event(TaskEventType.BACKWARD_TASK_START)
        bypass = None
        while self.backward_action is not None:
            if inspect.iscoroutinefunction(self.backward_action):
                bypass = await self.backward_action(bypass=bypass)
            else:
                bypass = self.backward_action(bypass=bypass)

    async def _do_wait_connection(self, bypass=None):
        if not self.connected:
            await self.connected_event.wait()

        self.backward_action = self._do_backward

    def _do_close_frontend(self, bypass=None):
        if not self.frontend.closed:
            self.frontend.close()
            self.save_event(EventType.FRONTEND_CLOSE)

        self.backward_action = None

    async def _do_backward(self, bypass=None):
        if not self.backend.closed:
            middleware = self.manager.middleware
            while True:
                data = await self.backend.read(self.read_max)
                if not data:
                    self.save_event(EventType.BACKEND_READ_FINISHED)
                    break
                try:
                    data = await middleware.backend(self, data)
                except MiddlewareException as e:
                    self.save_event(ErrorEventType.MIDDLEWARE_ERROR, e)
                    break
                except BaseException as e:
                    self.save_event(ErrorEventType.UNKONW, e)
                    break
                try:
                    if data:
                        self.frontend.flush_write(data)
                except Exception as e:
                    self.save_event(FailEventType.FRONTEND_WRITE_ERROR, e)
                    break
        self.backward_action = self._do_close_frontend
