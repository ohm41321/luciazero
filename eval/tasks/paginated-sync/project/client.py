class Client:
    def __init__(self, transport):
        self.transport = transport

    def fetch_page(self, cursor=None):
        return self.transport(cursor)
