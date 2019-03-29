# os-aio-pod-channel
[![Build Status](https://www.travis-ci.org/cfhamlet/os-aio-pod-channel.svg?branch=master)](https://www.travis-ci.org/cfhamlet/os-aio-pod-channel)
[![codecov](https://codecov.io/gh/cfhamlet/os-aio-pod-channel/branch/master/graph/badge.svg)](https://codecov.io/gh/cfhamlet/os-aio-pod-channel)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/os-aio-pod-channel.svg)](https://pypi.python.org/pypi/os-aio-pod-channel)
[![PyPI](https://img.shields.io/pypi/v/os-aio-pod-channel.svg)](https://pypi.python.org/pypi/os-aio-pod-channel)

A os-aio-pod component for transporting.

This lib is designed as a component of [os-aio-pod](https://github.com/cfhamlet/os-aio-pod) framework. It is mainly used for transporting data between TCP endpoints. The os-aio-pod built-in TCP server is used as background drive engine. With the middleware/extension mechanism, you can easily build aio programs like Proxy or MITM server.

## Install

```
pip install os-aio-pod-channel
```


## Conception

* **Engine**: Used to adapt with os-aio-pod framework, drive the whole event loop. It is also an access point for the components communicate with each other.
* **Endpoint**: Each incoming or outgoing connection is called endpoint. typically, just engine use it's APIs to read, write data or close connection.
* **Channel**: When incoming and outgoing endpoints all connected, a channel between them established. The engine is in charge of it's inner transporting status. 
* **Middleware**: Used to communicate with channel and handle data.
* **Extension**: Used for functional expansion. Can be accessed from engine instance. 



## Usage

This lib is used with [os-aio-pod](https://github.com/cfhamlet/os-aio-pod). Typically, you should define a configure file and run with os-aio-pod command line tool.

A minimal configure file (do nothing, just accept TCP connection, read and drop):

```
# config.py
BEANS  = [
    {
        'core'  : 'os_aio_pod.contrib.tcp_server.TCPServerAdapter',
        'server': 'os_aio_pod_channel.engine.Engine',
        'MIDDLEWARES': [],
        'EXTENSIONS': [],
    }
]
```

```
os-aio-pod -c config.py --debug
```



### Middleware

When data transporting or channel closed the corresponding method of middlewares will be invoked in specific order. You should inherit from ``os_aio_pod_channel.middleware.Middleware`` and configure class, id and other parameters of each middleware in ``MIDDLEWARES`` list.

### Extension

You shold inherit from ``os_aio_pod_channel.extension.Extension`` and config class, name and other parameters of each extension in ``EXTENSIONS`` list. You can get extension by ``engine.extension_manager.get_extension(extension_name)``


### Unit Tests

```
tox
```

### License

MIT licensed.
