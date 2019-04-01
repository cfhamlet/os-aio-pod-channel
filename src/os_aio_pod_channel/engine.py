import asyncio
import logging

from os_aio_pod.contrib.tcp_server import Server
from os_aio_pod.utils import pydantic_dict

from os_aio_pod_channel.channel import ChannelManager
from os_aio_pod_channel.config import EngineConfig
from os_aio_pod_channel.endpoint import NULL_ENDPOINT, Endpoint
from os_aio_pod_channel.extension import ExtensionManager


class Engine(Server):

    async def on_stop(self):
        '''Handle on-stop action

        This method should be triggered only once before close.
        '''

        self.logger.debug(f'On stop, close wait {self.config.close_wait}')

        self.stopping = True
        await self.channel_manager.close(timeout=self.config.close_wait,
                                         now=self.context.loop.time())
        self.stopping = False
        self.stopped = True

        self.logger.warn('On stop finished')

    async def on_setup(self):
        self.logger.debug('On setup')
        await self.extension_manager.setup()
        await self.channel_manager.setup()
        self.logger.debug('On setup finished')

    async def on_cleanup(self):
        self.logger.debug('On cleanup')
        await self.channel_manager.cleanup()
        await self.extension_manager.cleanup()
        self.logger.debug('On cleanup finished')

    def __init__(self, context, config):
        config = EngineConfig(**pydantic_dict(config))
        super().__init__(context, config)
        self.extension_manager = ExtensionManager(self)
        self.channel_manager = ChannelManager(self)
        self.stopped = self.stopping = False
        self.logger = logging.getLogger(self.__class__.__name__)

    def force_close_endpoint(self, endpoint):
        info = endpoint.get_extra_info('peername')
        self.logger.warn(
            f'Not allowed new connection {info}')
        try:
            endpoint.close()
        except Exception as e:
            self.logger.error(
                f'Close endpoint error {info} {e}')

    async def on_connect(self, reader, writer):
        endpoint = Endpoint(reader, writer)
        if self.stopped or self.stopping:
            self.force_close_endpoint(endpoint)
        else:
            await self.channel_manager.transport(endpoint, NULL_ENDPOINT)
