from enum import Enum
from typing import List, Union

from pydantic import BaseSettings, Schema, validator

from os_aio_pod.utils import module_from_string
from os_aio_pod_channel.channel import Channel as BaseChannel, SerialStartupChannel
from os_aio_pod_channel.extension import Extension
from os_aio_pod_channel.middleware import Middleware

ENV_PREFIX = "OS_AIO_POD_CHANNEL_"


class ExtensionConfig(BaseSettings):
    name: str
    cls: Union[module_from_string(Extension), None] = None

    class Config:
        env_prefix = ENV_PREFIX
        extra = "allow"


class MiddlewareConfig(BaseSettings):
    cls: module_from_string(Middleware) = None
    id: Union[int, None] = Schema(50, ge=0, le=100)

    class Config:
        env_prefix = ENV_PREFIX
        extra = "allow"


class CloseChannelMode(str, Enum):
    SERIAL = "serial"
    PARALLEL = "parallel"


class EngineConfig(BaseSettings):

    MIDDLEWARES: List[MiddlewareConfig] = []
    EXTENSIONS: List[ExtensionConfig] = []
    read_max: int = 2 ** 16 * 5
    dumb_connect_timeout: Union[None, float] = 3.0
    close_wait: Union[None, float] = 60.0
    close_channel_mode = CloseChannelMode.SERIAL
    channel_class: module_from_string(BaseChannel) = Schema(
        SerialStartupChannel, validate_always=True
    )

    @validator("dumb_connect_timeout", "close_wait", pre=True, always=True)
    def check_timeout(cls, v):
        if v is not None:
            if v < 0.0:
                raise ValueError("value must greater than 0.0")
        return v

    class Config:
        env_prefix = ENV_PREFIX
        extra = "allow"
        validate_all = True


DEFAULT_CONFIG = EngineConfig()
