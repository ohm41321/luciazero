class Client:
    def __init__(self, transport): self.transport = transport
    def fetch_page(self, cursor=None): return self.transport(cursor)
    def iter_items(self):
        first = self.fetch_page(None)
        yield from first["items"]
        if first.get("next_cursor") is not None:
            yield from self.fetch_page(first["next_cursor"])["items"]
