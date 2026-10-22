"""URL canonicalization, deduplication and SSRF protection."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

from src.models import stable_id
from src.tools.base import SearchResult, UnsafeURLError

Resolver = Callable[[str, int], list[str]]

_TRACKING_PREFIXES = ("utm_", "mc_", "_hs")
_TRACKING_KEYS = {"fbclid", "gclid", "dclid", "msclkid", "mkt_tok", "igshid"}
_ALLOWED_PORTS = {80, 443}
_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
}


def canonicalize_url(url: str) -> str:
    """Return a stable, lower-noise representation of an absolute URL."""
    raw = url.strip()
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise UnsafeURLError(f"Only http and https URLs are supported, got {scheme!r}.")
    if parsed.username or parsed.password:
        raise UnsafeURLError("URLs with embedded credentials are not allowed.")

    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host.")
    host = host.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeURLError("URL has an invalid port.") from exc
    default_port = 443 if scheme == "https" else 80
    netloc = host if port in (None, default_port) else f"{host}:{port}"

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")

    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in _TRACKING_KEYS or lowered.startswith(_TRACKING_PREFIXES):
            continue
        query_items.append((key, value))
    query_items.sort()
    query = urlencode(query_items, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))


def source_id_for_url(url: str) -> str:
    """Build the deterministic source id used by notes and reports."""
    return stable_id("src", canonicalize_url(url))


def normalize_query(query: str) -> str:
    """Normalize whitespace for display and cache keys."""
    return " ".join(query.split()).strip()


def query_cache_key(query: str) -> str:
    return normalize_query(query).casefold()


def dedupe_results(results: Iterable[SearchResult]) -> list[SearchResult]:
    """Merge results that point to the same canonical URL."""
    merged: dict[str, SearchResult] = {}
    for result in results:
        try:
            canonical = canonicalize_url(result.url)
        except UnsafeURLError:
            continue
        source_id = source_id_for_url(canonical)
        normalized = result.model_copy(
            update={
                "url": canonical,
                "source_id": source_id,
                "title": result.title.strip(),
                "snippet": " ".join(result.snippet.split()),
            }
        )
        previous = merged.get(source_id)
        if previous is None:
            merged[source_id] = normalized
            continue
        winner = normalized if len(normalized.snippet) > len(previous.snippet) else previous
        metadata = {**previous.metadata, **normalized.metadata}
        merged[source_id] = winner.model_copy(update={"metadata": metadata})
    return list(merged.values())


def _default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def _is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def validate_public_url(url: str, *, resolver: Resolver | None = None) -> str:
    """Validate that a URL targets a public HTTP(S) endpoint.

    The hostname is resolved and every returned address is checked. Callers
    must re-run this function for each redirect target.
    """
    canonical = canonicalize_url(url)
    parsed = urlsplit(canonical)
    host = parsed.hostname or ""
    if host.lower() in _BLOCKED_HOSTS or host.lower().endswith(".local"):
        raise UnsafeURLError(f"Local hostnames are not allowed: {host!r}.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeURLError("URL has an invalid port.") from exc
    if port not in _ALLOWED_PORTS:
        raise UnsafeURLError(f"Port {port} is not allowed.")

    try:
        ipaddress.ip_address(host)
    except ValueError:
        resolve = resolver or _default_resolver
        try:
            addresses = resolve(host, port)
        except OSError as exc:
            raise UnsafeURLError(f"Could not resolve host {host!r}.") from exc
    else:
        addresses = [host]

    if not addresses:
        raise UnsafeURLError(f"Host {host!r} did not resolve to any address.")
    unsafe = [address for address in addresses if not _is_public_ip(address)]
    if unsafe:
        raise UnsafeURLError(f"Host {host!r} resolves to a non-public address.")
    return canonical


def resolve_redirect(base_url: str, location: str) -> str:
    """Resolve a Location header and return its canonical form."""
    return canonicalize_url(urljoin(base_url, location))


def quote_wikipedia_title(title: str) -> str:
    """Build the canonical Wikipedia path for a page title."""
    return quote(title.replace(" ", "_"), safe="()_-")
