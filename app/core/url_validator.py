"""Provider URL validation with SSRF risk reduction.

``validate_provider_url`` enforces scheme, credential, and host restrictions
before a provider base_url is persisted or used for outbound probing.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


# Private / reserved CIDR blocks to reject when allow_private=False
_PRIVATE_CIDRS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),       # link-local / cloud metadata
    ipaddress.ip_network("::1/128"),               # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),               # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),              # IPv6 link-local
]

_UNSAFE_HOSTNAMES = {"metadata.google.internal"}


def _is_private_ip(host: str) -> bool:
    """Check if *host* resolves to a private/reserved IP address."""
    # Try parsing as a literal IP first.
    try:
        addr = ipaddress.ip_address(host.strip("[]"))
        return any(addr in cidr for cidr in _PRIVATE_CIDRS)
    except ValueError:
        pass

    # Hostname — attempt DNS resolution (best-effort).
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _family, _type, _proto, _canonname, sockaddr in infos:
            addr = ipaddress.ip_address(sockaddr[0])
            if any(addr in cidr for cidr in _PRIVATE_CIDRS):
                return True
    except (socket.gaierror, OSError):
        # Cannot resolve — treat as non-private (the probe will fail later with
        # a clear network error rather than a misleading SSRF rejection).
        pass

    return False


def validate_provider_url(url: str, *, allow_private: bool = True) -> str:
    """Validate and normalize a provider ``base_url``.

    Returns the normalized URL on success.

    Raises ``ValueError`` with a human-readable message on failure.
    """
    if not url or not url.strip():
        raise ValueError("Provider URL must not be empty")

    parsed = urlparse(url.strip())

    # ── Scheme ──────────────────────────────────────────────────────────────
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Provider URL scheme must be http or https, got '{parsed.scheme}'")

    # ── Embedded credentials ────────────────────────────────────────────────
    if parsed.username or parsed.password:
        raise ValueError("Provider URL must not contain embedded credentials (user:pass@host)")

    # ── Host ────────────────────────────────────────────────────────────────
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Provider URL must include a hostname")

    # Reject known-unsafe hostnames.
    if hostname.lower() in _UNSAFE_HOSTNAMES:
        raise ValueError(f"Provider URL hostname '{hostname}' is not allowed")

    # Private-net check.
    if not allow_private:
        if hostname.lower() in ("localhost",):
            raise ValueError("Provider URL must not target localhost in production mode")
        if _is_private_ip(hostname):
            raise ValueError("Provider URL must not target private/reserved IP addresses in production mode")

    # ── Normalize ───────────────────────────────────────────────────────────
    normalized = url.strip().rstrip("/")
    return normalized
