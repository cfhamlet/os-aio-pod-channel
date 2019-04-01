import logging
from collections import OrderedDict

from os_aio_pod.utils import pydantic_dict


class ExtensionManager(object):

    def __init__(self, engine):
        self.engine = engine
        self.extensions = OrderedDict()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.load_extensions()

    def _load_extension(self, conf):
        if conf.cls is None:
            if conf.name in self.extensions:
                self.extensions.pop(conf.name)
                self.logger.debug(f'Remove extension {conf}')
        else:
            try:
                extension = conf.cls(
                    self.engine,  **pydantic_dict(conf, exclude={'name', 'cls'}))
                if conf.name in self.extensions:
                    self.logger.warn(f'Duplicated extension {conf}')
                self.extensions[conf.name] = extension
                self.logger.debug(f'New extension {conf}')
            except Exception as e:
                self.logger.error(f'Load extension error {conf}, {e}')

    def load_extensions(self):
        for conf in self.engine.config.EXTENSIONS:
            self._load_extension(conf)

    def get_extension(self, name):
        return self.extensions[name]

    async def setup(self):
        for name in list(self.extensions.keys()):
            extension = self.extensions[name]
            self.logger.debug(f'Setup start {extension}')
            try:
                await extension.setup()
            except Exception as e:
                self.logger.error(f'Setup error {e}')
                self.extensions.pop(name, None)
                continue
            self.logger.debug(f'Setup finished {extension}')

    async def cleanup(self):
        for extension in reversed(self.extensions.values()):
            self.logger.debug(f'Cleanup start {extension}')
            try:
                await extension.cleanup()
            except Exception as e:
                self.logger.error(f'Cleanup error {e}')
                continue
            self.logger.debug(f'Cleanup finished {extension}')


class Extension(object):

    def __init__(self, engine, **kwargs):
        self.engine = engine

    async def setup(self):
        pass

    async def cleanup(self):
        pass
