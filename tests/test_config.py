import pytest

from os_aio_pod.utils import load_module_from_pyfile, vars_from_module
from os_aio_pod_channel.config import CloseChannelMode, EngineConfig


@pytest.fixture
def config():
    def _config(config_file):
        module = load_module_from_pyfile(config_file)
        return EngineConfig.parse_obj(vars_from_module(module))

    return _config


def test_empty_config(config):
    conf = config("tests/configs/empty.py")
    default = EngineConfig()
    for k, v in default:
        assert getattr(conf, k) == v


def test_close_channle_mode(config):
    conf = config("tests/configs/close_channel_mode.py")
    assert conf.close_channel_mode == CloseChannelMode.PARALLEL
