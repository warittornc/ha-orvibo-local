"""Root of the Orvibo LAN error tree.

Each package defines its own family beside the code that raises it:
``auth/``, ``cloud/``, ``gateway/``, ``protocol/``, and ``state/`` each have an
``exceptions.py`` whose base class derives from :class:`OrviboLanError`.
"""


class OrviboLanError(Exception):
    """Base exception for integration-owned failures."""
