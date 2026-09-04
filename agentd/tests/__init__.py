"""The daemon's test suite.

Nothing here may put a window on the developer's screen: the claim dialog is
always injected, and this arms the daemon's own kill switch so an
accidentally default-configured server falls back to the console code
instead of raising a real modal.
"""

import os

from luciazero_agentd.approval import NO_DIALOG_ENV

os.environ.setdefault(NO_DIALOG_ENV, "1")
