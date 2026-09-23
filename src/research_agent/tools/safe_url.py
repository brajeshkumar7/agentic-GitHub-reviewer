"""Public HTTPS destination validation with DNS-pinned outbound connections."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeDestination(ValueError):
    """Raised when a URL resolves to a non-public or unsupported destination."""


def public_destination_addresses(host: str, port: int = 443) -> list[str]:
    normalized_host = host.rstrip(".").lower()
    if (
        not normalized_host
        or normalized_host == "localhost"
        or normalized_host.endswith(".localhost")
        or normalized_host.endswith(".local")
        or normalized_host.endswith(".internal")
    ):
        raise UnsafeDestination("host is not a public destination")
    try:
        literal = ipaddress.ip_address(normalized_host)
    except ValueError:
        try:
            records = socket.getaddrinfo(
                normalized_host, port, type=socket.SOCK_STREAM
            )
        except OSError:
            raise UnsafeDestination("host did not resolve to public addresses") from None
        addresses = sorted({record[4][0] for record in records})
    else:
        addresses = [str(literal)]
    if not addresses:
        raise UnsafeDestination("host did not resolve to public addresses")
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            raise UnsafeDestination("DNS returned an invalid address") from None
        if not parsed.is_global:
            raise UnsafeDestination("host resolves to a non-public address")
    return addresses


def validate_public_https_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise UnsafeDestination("URL is malformed") from None
    if (
        parts.scheme.lower() != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or port not in (None, 443)
    ):
        raise UnsafeDestination("URL must be a public HTTPS URL on port 443")
    public_destination_addresses(parts.hostname, 443)
    return url
