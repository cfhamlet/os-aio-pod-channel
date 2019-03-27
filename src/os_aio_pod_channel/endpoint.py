from collections import namedtuple


class Endpoint(namedtuple('Endpoint', 'reader writer')):

    def __init__(self, *args):
        super().__init__()
        self.closed = False

    def get_extra_info(self, name, default=None):
        return self.writer.get_extra_info(name, default)

    async def read(self, n=-1):
        return await self.reader.read(n)

    async def flush_write(self, data):
        self.write(data)
        return await self.drain()

    def write(self, data):
        return self.writer.write(data)

    async def drain(self):
        return await self.writer.drain()

    def close(self):
        if self.closed:
            return
        try:
            self.writer.close()
        finally:
            self.closed = True


class NullEndpoint(Endpoint):

    def __init__(self, *args):
        super().__init__(*args)
        self.closed = True

    def __bool__(self):
        return False

    def get_extra_info(self, name, default=None):
        return default

    def read(self, n=-1):
        return ''

    def write(self):
        pass

    async def drain(self):
        pass

    def close(self):
        pass

NULL_ENDPOINT = NullEndpoint(None, None)
