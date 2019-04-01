from typing import List, Union

from os_aio_pod.utils import module_from_string
from pydantic import BaseSettings, Schema

from os_aio_pod_channel.channel import SerialStartupChannel
from os_aio_pod_channel.extension import Extension
from os_aio_pod_channel.middleware import Middleware
from os_aio_pod_channel.channel import Channel as BaseChannel

ENV_PREFIX = 'OS_AIO_POD_CHANNEL_'


class ExtensionConfig(BaseSettings):
    name: str
    cls: Union[module_from_string(Extension), None] = None

    class Config:
        env_prefix = ENV_PREFIX
        allow_extra = True


class MiddlewareConfig(BaseSettings):
    cls: module_from_string(Middleware) = None
    id: Union[int, None] = Schema(50, ge=0, le=100)

    class Config:
        env_prefix = ENV_PREFIX
        allow_extra = True


class EngineConfig(BaseSettings):

    MIDDLEWARES: List[MiddlewareConfig] = []
    EXTENSIONS: List[ExtensionConfig] = []
    read_max = 2 ** 16 * 5
    close_wait = 60
    channel_class: module_from_string(BaseChannel) = Schema(
        SerialStartupChannel, validate_always=True)

    class Config:
        env_prefix = ENV_PREFIX
        allow_extra = True
        validate_all = True


DEFAULT_CONFIG = EngineConfig()
