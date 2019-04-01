import asyncio
import logging
from functools import partial
from itertools import chain

from os_aio_pod.utils import pydantic_dict

from os_aio_pod_channel.exceptions import MiddlewareException


class MiddlewareManager(object):

    def __init__(self, engine):
        self.engine = engine
        self.middlewares = []
        self.upstream_callbacks = []
        self.downstream_callbacks = []
        self.close_callbacks = []
        self.logger = logging.getLogger(self.__class__.__name__)
        self.load_middlewares()

    def load_middlewares(self):
        sorted_confs = []

        def insert(conf):
            for idx, sconf in enumerate(sorted_confs):
                if conf.id == sconf.id and conf.cls == sconf.cls:
                    sorted_confs[idx] = conf
                    return

                if sconf.id > conf.id:
                    sorted_confs.insert(idx, conf)
                    return
            sorted_confs.append(conf)

        def remove(conf):
            # TODO performance
            new = []
            for sconf in sorted_confs:
                if sconf.cls == conf.cls:
                    self.logger.warn(f'Remove middleware {sconf}')
                else:
                    new.append(sconf)
            sorted_confs = new

        for conf in self.engine.config.MIDDLEWARES:
            if conf.id is None:
                remove(conf)
            else:
                insert(conf)

        for conf in sorted_confs:
            try:
                middleware = conf.cls(
                    self.engine, **pydantic_dict(conf, exclude={'id', 'cls'}))
                self.middlewares.append(middleware)
                self.logger.debug(f'New middleware {conf}')
            except Exception as e:
                self.logger.error(f'Load middleware error {conf}, {e}')

    async def _action(self, channel, data, callbacks):
        for callback in callbacks:
            try:
                data = await callback(channel, data)
            except asyncio.CancelledError as e:
                raise e
            except Exception as e:
                raise MiddlewareException(
                    f'Action error {callback}', e)
            if data is None:
                return None
        return data

    async def upstream(self, channel, data):
        return await self._action(channel, data, self.upstream_callbacks)

    async def downstream(self, channel, data):
        return await self._action(channel, data, self.downstream_callbacks)

    async def close(self, channel):
        for callback in self.close_callbacks:
            await callback(channel)

    def _register_callbacks(self, middleware):
        for method, operate in [('upstream', 'append'),
                                ('downstream', 'insert'),
                                ('close', 'append')]:
            callbacks = getattr(self, method + '_callbacks')

            if not hasattr(middleware, method):
                continue

            call = getattr(middleware, method)
            if not call or (hasattr(call, '__func__')
                            and getattr(Middleware, method) == call.__func__):
                continue
            func = getattr(callbacks, operate)
            if operate == 'insert':
                func = partial(func, 0)
            func(call)

    async def _setup(self):
        for middleware in self.middlewares:
            self.logger.debug(f'Setup start {middleware}')
            try:
                await middleware.setup()
            except Exception as e:
                self.logger.error(f'Setup error {e}')
                continue
            self._register_callbacks(middleware)
            self.logger.debug(f'Setup finished {middleware}')

    async def setup(self):
        await self._setup()
        for callback in chain(self.upstream_callbacks,
                              self.downstream_callbacks,
                              self.close_callbacks):
            self.logger.debug(f'Registerd {callback}')

    async def cleanup(self):
        for middleware in reversed(self.middlewares):
            self.logger.debug(f'Cleanup start {middleware}')
            try:
                await middleware.cleanup()
            except Exception as e:
                self.logger.error(f'Cleanup error {e}')
                continue
            self.logger.debug(f'Cleanup finished {middleware}')


class Middleware(object):

    def __init__(self, engine, **kwargs):
        self.engine = engine

    async def upstream(self, channel, data):
        return data

    async def downstream(self, channel, data):
        return data

    async def close(self, channel):
        pass

    async def setup(self):
        pass

    async def cleanup(self):
        pass
