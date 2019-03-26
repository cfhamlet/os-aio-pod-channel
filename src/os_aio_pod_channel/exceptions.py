class MiddlewareException(Exception):
    def __init__(self, reason='', real_exc=None):
        super(MiddlewareException, self).__init__(reason, real_exc)
        self.real_except = real_exc
