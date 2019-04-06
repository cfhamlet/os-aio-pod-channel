import asyncio
import functools
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
    FRONTEND_READ_ERROR = 33
    BACKEND_READ_ERROR = 34
    FRONTEND_WRITE_ERROR = 35
    BACKEND_WRITE_ERROR = 36
    FRONTEND_CLOSE_ERROR = 37
    BACKEND_CLOSE_ERROR = 38


class TaskEventType(Enum):
    '''Task events.'''
    UPSTREAM_TASK_START = 51
    DOWNSTREAM_TASK_START = 52
    UPSTREAM_TASK_DONE = 53
    DOWNSTREAM_TASK_DONE = 54
    UPSTREAM_TASK_ERROR = 53
    DOWNSTREAM_TASK_ERROR = 54
    UPSTREAM_TASK_CANCELLED = 55
    DOWNSTREAM_TASK_CANCELLED = 56


class ErrorEventType(Enum):
    '''Error events.'''
    MIDDLEWARE_ERROR = 77
    UNKONW = 99


ChannelEvent = namedtuple('ChannelEvent', 'event time exc')


class TimeHandler(namedtuple('TimeHandler', 'hander when')):

    def cancel(self):
        return self.handler.cancel()


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
                 'closed', 'loop', '_read_max',
                 '_debug', 'events')

    def __init__(self, manager, frontend=None, backend=None, loop=None):
        self.manager = manager
        self.frontend = frontend
        self.backend = backend
        self.closed = False
        self._read_max = manager.config.read_max
        self.loop = asyncio.get_event_loop() if loop is None else loop
        self._debug = self.loop.get_debug()
        self.events = [] if self._debug else None

    def save_event(self, event, e=None):
        if self._debug:
            event = ChannelEvent(event, self.loop.time(), e)
            self.events.append(event)

    def set_backend(self, endpoint):
        pass

    async def transport(self):
        pass

    async def close(self, timeout=None, now=None):
        pass


class FullDuplexChannel(Channel):

    __slots__ = ('_upstream_task', '_downstream_task',
                 '_connected_event', '_closing_event', '_closing_trigger',
                 '_upstream_action', '_downstream_action')

    def __init__(self, manager, frontend=None, backend=None, loop=None):
        super(FullDuplexChannel, self).__init__(
            manager, frontend=frontend, backend=backend, loop=loop)
        self.save_event(EventType.FRONTEND_CONNECTED)
        self._upstream_task = self._downstream_task = None
        self._connected_event = asyncio.Event(loop=self.loop)
        self._closing_event = asyncio.Event(loop=self.loop)
        self._closing_trigger = None
        self._upstream_action = self._do_build_connection
        self._downstream_action = self._do_wait_connection

        if backend:
            self.set_backend(backend)

    def set_backend(self, endpoint):
        assert not self.backend
        self.backend = endpoint
        self.save_event(EventType.BACKEND_CONNECTED)
        self._connected_event.set()

    @property
    def connected(self):
        return self._connected_event.is_set()

    def cancel(self):
        for task in (self._upstream_task, self._downstream_task):
            if task and not task.done():
                task.cancel()

    async def _close(self, timeout=None, now=None):
        if self.closed:
            return

        if timeout is None:
            if self._closing_trigger is not None:
                self._closing_trigger.cancel()
                self._closing_trigger = None
            self.cancel()
            return

        timeout = timeout - ((self.loop.time() - now) if now else 0)
        if self._closing_trigger is not None:
            if self._closing_trigger.when <= self.loop.time() + timeout:
                return
            self._closing_trigger.cancel()

        when = self.loop.time() + timeout
        self._closing_trigger = TimeHandler(
            self.loop.call_at(when, self.cancel), when)

    async def close(self, timeout=None, now=None):
        if self.closed:
            return

        while not self._closing_event.is_set():
            await self._close(timeout=timeout, now=now)
            await self._closing_event.wait()

        if not self.closed:
            self.closed = True

    async def transport(self):

        try:
            await self._transport_startup()
        finally:
            try:
                await self._transport_cleanup()
            finally:
                self.save_event(EventType.TRANSPOT_FINISHED)
                self.closed = True
                self._closing_event.set()

    def save_task_status(self, event_prefix, task):
        suffix = 'DONE'
        e = None
        if task.cancelled():
            suffix = 'CANCELLED'
        elif task.exception():
            suffix = 'ERROR'
            e = task.exception()

        self.save_event(getattr(TaskEventType, event_prefix+suffix), e)

    async def _transport_startup(self):

        done = []
        pending = []

        for name, done_callback in [('upstream', self._do_close_backend),
                                    ('downstream', self._do_close_frontend)]:
            task = asyncio.ensure_future(
                getattr(self, '_'+name)(), loop=self.loop)
            setattr(self, name+'_task', task)
            if self._debug:
                event_prefix = f'{name.upper()}_TASK_'
                task.add_done_callback(functools.partial(
                    self.save_task_status, event_prefix))

            task.add_done_callback(done_callback)
            pending.append(task)

        while pending:
            done, pending = await asyncio.wait(pending, loop=self.loop,
                                               return_when=asyncio.FIRST_COMPLETED)

    async def _transport_cleanup(self):
        for name in ('frontend', 'backend'):
            endpoint = getattr(self, name)
            if endpoint.closed:
                continue
            endpoint.close()
            if self._debug:
                self.save_event(
                    getattr(EventType, name.upper() + '_CLOSE'))

        await self.manager.middleware.close(self)
        self.save_event(EventType.CLEANUP_FINISHED)

    async def _upstream(self):
        self.save_event(TaskEventType.UPSTREAM_TASK_START)
        bypass = None
        while self._upstream_action is not None:
            if inspect.iscoroutinefunction(self._upstream_action):
                bypass = await self._upstream_action(bypass=bypass)
            else:
                bypass = self._upstream_action(bypass=bypass)

    async def _do_build_connection(self, bypass=None):
        middleware = self.manager.middleware
        self.save_event(EventType.FRONTEND_START_READING)
        while True:
            try:
                data = await self.frontend.read(self._read_max)
            except BaseException as e:
                self.save_event(FailEventType.FRONTEND_READ_ERROR, e)
                break
            if not data:
                self.save_event(EventType.FRONTEND_READ_FINISHED)
                break
            try:
                data = await middleware.upstream(self, data)
            except MiddlewareException as e:
                self.save_event(ErrorEventType.MIDDLEWARE_ERROR, e)
                break
            except BaseException as e:
                self.save_event(ErrorEventType.UNKONW, e)
                break
            if self.connected:
                self._upstream_action = self._do_upstream
                return data

        self._upstream_action = self._do_close_backend

    def _do_close_backend(self, bypass=None):
        if not self.backend.closed:
            self.save_event(EventType.BACKEND_CLOSE)
            self.backend.close()
        if not self.connected:
            self._connected_event.set()
        self._upstream_action = None

    async def _do_upstream(self, bypass=None):
        middleware = self.manager.middleware
        data = bypass
        while True:
            try:
                if data:
                    await self.backend.flush_write(data)
            except Exception as e:
                self.save_event(FailEventType.BACKEND_WRITE_ERROR, e)
                break
            try:
                data = await self.frontend.read(self._read_max)
            except BaseException as e:
                self.save_event(FailEventType.FRONTEND_READ_ERROR, e)
                break
            if not data:
                self.save_event(EventType.FRONTEND_READ_FINISHED)
                break
            try:
                data = await middleware.upstream(self, data)
            except MiddlewareException as e:
                self.save_event(ErrorEventType.MIDDLEWARE_ERROR, e)
                break
            except BaseException as e:
                self.save_event(ErrorEventType.UNKONW, e)
                break

        self._upstream_action = self._do_close_backend

    async def _downstream(self):
        self.save_event(TaskEventType.DOWNSTREAM_TASK_START)
        bypass = None
        while self._downstream_action is not None:
            if inspect.iscoroutinefunction(self._downstream_action):
                bypass = await self._downstream_action(bypass=bypass)
            else:
                bypass = self._downstream_action(bypass=bypass)

    async def _do_wait_connection(self, bypass=None):
        if not self.connected:
            await self._connected_event.wait()

        self._downstream_action = self._do_downstream

    def _do_close_frontend(self, bypass=None):
        if not self.frontend.closed:
            self.frontend.close()
            self.save_event(EventType.FRONTEND_CLOSE)

        self._downstream_action = None

    async def _do_downstream(self, bypass=None):
        if not self.backend.closed:
            self.save_event(EventType.BACKEND_START_READING)
            middleware = self.manager.middleware
            while True:
                try:
                    data = await self.backend.read(self._read_max)
                except BaseException as e:
                    self.save_event(FailEventType.BACKEND_READ_ERROR, e)
                    break
                if not data:
                    self.save_event(EventType.BACKEND_READ_FINISHED)
                    break
                try:
                    data = await middleware.downstream(self, data)
                except MiddlewareException as e:
                    self.save_event(ErrorEventType.MIDDLEWARE_ERROR, e)
                    break
                except BaseException as e:
                    self.save_event(ErrorEventType.UNKONW, e)
                    break
                try:
                    if data:
                        await self.frontend.flush_write(data)
                except Exception as e:
                    self.save_event(FailEventType.FRONTEND_WRITE_ERROR, e)
                    break
        self._downstream_action = self._do_close_frontend


class SerialStartupChannel(FullDuplexChannel):

    async def _transport_startup(self):
        self._upstream_task = asyncio.ensure_future(
            self._upstream(), loop=self.loop)
        if self._debug:
            self._upstream_task.add_done_callback(functools.partial(
                self.save_task_status, 'UPSTREAM_TASK_'))
        self._upstream_task.add_done_callback(self._do_close_backend)
        await self._upstream_task

        if self._downstream_task:
            await self._downstream_task

    def set_backend(self, endpoint):
        assert not self.closed and not self.backend
        self.save_event(EventType.BACKEND_CONNECTED)
        self.backend = endpoint
        self._downstream_task = asyncio.ensure_future(
            self._downstream(), loop=self.loop)
        if self._debug:
            self._downstream_task.add_done_callback(functools.partial(
                self.save_task_status, 'DOWNSTREAM_TASK_'))
        self._downstream_task.add_done_callback(self._do_close_frontend)
        self._connected_event.set()
