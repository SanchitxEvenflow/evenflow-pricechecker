"""
instamart/socks5_bridge.py

DEPRECATED — This module has moved to proxy/socks5_bridge.py.

This shim re-exports the canonical module so any old imports still work.
Update your imports to:
    from proxy.socks5_bridge import Socks5HttpBridge
"""

# Re-export from canonical location
from proxy.socks5_bridge import Socks5HttpBridge  # noqa: F401

__all__ = ["Socks5HttpBridge"]
