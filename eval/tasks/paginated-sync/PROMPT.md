Bug report from operations:

> `python3 cli.py` only prints active accounts from the first API page. During
> last week's backend incident it also hung forever when the API repeated a
> cursor. Make the library and CLI consume every page in order, pass each
> `next_cursor` back exactly, and fail clearly on a cursor cycle without
> issuing the repeated request. Keep the existing one-page behavior working.

Fix the integration. Work exactly as you normally would.
