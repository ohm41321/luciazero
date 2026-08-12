class CursorCycleError(RuntimeError): pass


class Client:
    def __init__(self, transport): self.transport = transport
    def fetch_page(self, cursor=None): return self.transport(cursor)
    def iter_items(self):
        cursor = None; seen = set()
        while True:
            if cursor in seen: raise CursorCycleError("cursor cycle")
            seen.add(cursor); page = self.fetch_page(cursor)
            yield from page["items"]
            cursor = page.get("next_cursor")
            if cursor is None: return
