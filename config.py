# config.py
BEANS  = [
    {
        'core'  : 'os_aio_pod.contrib.tcp_server.TCPServerAdapter',
        'server': 'os_aio_pod_channel.engine.Engine',
        'MIDDLEWARES': [],
        'EXTENSIONS': [],
        'dumb_connect_timeout': None,
        'close_wait': 10
    }
]
