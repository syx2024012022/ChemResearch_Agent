from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx


class SafeHttpRemoteFileFetcher:
    """Bounded HTTPS downloader for platform-provided file URLs."""

    def __init__(self, *, timeout_seconds: float = 20, max_redirects: int = 3) -> None:
        self._timeout = timeout_seconds
        self._max_redirects = max_redirects

    def fetch(self, url: str, max_bytes: int) -> bytes:
        current = url
        with httpx.Client(
            follow_redirects=False,
            timeout=self._timeout,
            trust_env=False,
            headers={"User-Agent": "ChemResearch-Agent/0.1"},
        ) as client:
            for redirect_count in range(self._max_redirects + 1):
                _validate_public_https_url(current)
                with client.stream("GET", current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location or redirect_count >= self._max_redirects:
                            raise ValueError("remote file exceeded the redirect limit")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    declared = response.headers.get("content-length")
                    if declared and int(declared) > max_bytes:
                        raise ValueError("remote file exceeds the 50 MB limit")
                    payload = bytearray()
                    for chunk in response.iter_bytes():
                        payload.extend(chunk)
                        if len(payload) > max_bytes:
                            raise ValueError("remote file exceeds the 50 MB limit")
                    return bytes(payload)
        raise ValueError("remote file could not be downloaded")


def _validate_public_https_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("file.url must be an absolute HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("file.url must not contain credentials")
    try:
        resolved = socket.getaddrinfo(
            parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
        )
        addresses = {item[4][0] for item in resolved}
    except socket.gaierror as exc:
        raise ValueError("file.url hostname could not be resolved") from exc
    if not addresses:
        raise ValueError("file.url hostname has no usable address")
    for raw_address in addresses:
        address = ipaddress.ip_address(raw_address)
        if not address.is_global:
            raise ValueError("file.url must resolve only to public Internet addresses")
