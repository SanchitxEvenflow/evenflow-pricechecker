"""
instamart/socks5_provider.py

DEPRECATED — This module has moved to proxy/socks5_provider.py.

This shim re-exports the canonical module so any old imports still work.
Update your imports to:
    from proxy.socks5_provider import get_provider
    from proxy.socks5_provider import Socks5Provider
"""

# Re-export from canonical location
from proxy.socks5_provider import Socks5Provider, get_provider  # noqa: F401

__all__ = ["Socks5Provider", "get_provider"]
