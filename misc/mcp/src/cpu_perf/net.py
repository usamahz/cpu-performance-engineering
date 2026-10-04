"""A guarded HTTP client for reading linked sources.

* http and https only, default ports only, at most five redirects;
* every hop's host is resolved and refused unless every address is public
  (no loopback, private, link-local, metadata, reserved or mapped addresses),
  and the connection is pinned to the address that was checked;
* HTTPS_PROXY / NO_PROXY are honoured through CONNECT tunnels;
* bounded downloads and bounded gzip decoding;
* status classification mirrors misc/scripts/check_links.py;
* robots.txt and a per-host gap for the crawler.

Standard library only."""

from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import ssl
import threading
import time
import urllib.robotparser
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.request import getproxies_environment, proxy_bypass_environment

from . import REPO_URL, __version__

USER_AGENT = f"Mozilla/5.0 (compatible; cpu-perf/{__version__}; +{REPO_URL})"
ROBOTS_TOKEN = "cpu-perf"
BLOCKED = {401, 403, 429}
DEAD = {404, 410}
REDIRECTS = {301, 302, 303, 307, 308}
BLOCKED_HOSTS = ("localhost", "metadata.google.internal", "metadata")
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")
NAT64 = ipaddress.ip_network("64:ff9b::/96")
BOT_WALL_MARKERS = (
    "<title>just a moment",
    "attention required! | cloudflare",
    "cf-browser-verification",
    "making sure you&#39;re not a bot",
    "making sure you're not a bot",
    "<title>access denied</title>",
    "request unsuccessful. incapsula",
    "please enable js and disable any ad blocker",
    "verifying you are human",
)


class Refused(Exception):
    """The URL or one of its redirects failed a safety check."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: str  # ok | not_modified | blocked | dead | unreachable | refused | too_large
    http_status: int | None = None
    content_type: str = ""
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    detail: str = ""
    redirects: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        elif addr in NAT64:
            addr = ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return addr.is_global and not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


class Fetcher:
    def __init__(
        self,
        user_agent: str = USER_AGENT,
        *,
        allow_private: bool = False,
        respect_robots: bool = True,
        per_host_interval: float = 1.0,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        resolver=socket.getaddrinfo,
        use_proxy: bool = True,
    ):
        self.user_agent = user_agent
        self.allow_private = allow_private
        self.respect_robots = respect_robots
        self.per_host_interval = per_host_interval
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.resolver = resolver
        self.use_proxy = use_proxy
        self._ctx = ssl.create_default_context()
        extra = os.environ.get("SSL_CERT_FILE")
        if extra and os.path.isfile(extra):
            try:
                self._ctx.load_verify_locations(cafile=extra)
            except (ssl.SSLError, OSError):
                pass
        self._host_locks: dict[str, threading.Lock] = {}
        self._host_last: dict[str, float] = {}
        self._guard = threading.Lock()
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # ----- safety ----------------------------------------------------------

    def check_url(self, url: str) -> tuple[str, str, int, list[str]]:
        """(scheme, host, port, addresses) for a URL that passes the checks."""
        parts = urlsplit(url)
        scheme = (parts.scheme or "").lower()
        if scheme not in ("http", "https"):
            raise Refused(f"scheme {scheme or '(none)'} not allowed")
        if parts.username or parts.password:
            raise Refused("credentials in URL not allowed")
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise Refused("no host")
        port = parts.port or (443 if scheme == "https" else 80)
        if self.allow_private:
            infos = self.resolver(host, port, type=socket.SOCK_STREAM)
            return scheme, host, port, [i[4][0] for i in infos]
        if port not in (80, 443):
            raise Refused(f"port {port} not allowed")
        if host in BLOCKED_HOSTS or host.endswith(BLOCKED_SUFFIXES):
            raise Refused(f"host {host} not allowed")
        try:
            ipaddress.ip_address(host)
            literal = True
        except ValueError:
            literal = False
        if literal:
            if not _ip_is_public(host):
                raise Refused(f"address {host} is not public")
            return scheme, host, port, [host]
        try:
            infos = self.resolver(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ConnectionError(f"DNS: {exc}") from exc
        addrs = []
        for info in infos:
            ip = info[4][0]
            if not _ip_is_public(ip):
                raise Refused(f"{host} resolves to non-public address {ip}")
            if ip not in addrs:
                addrs.append(ip)
        if not addrs:
            raise ConnectionError(f"DNS: no address for {host}")
        addrs.sort(key=lambda a: ":" in a)  # IPv4 first, as check_links does
        return scheme, host, port, addrs

    def _proxy_for(self, scheme: str, host: str) -> tuple[str, int, str | None] | None:
        if not self.use_proxy:
            return None
        proxies = getproxies_environment()
        proxy = proxies.get(scheme) or proxies.get("all")
        if not proxy:
            return None
        if proxy_bypass_environment(host, proxies):
            return None
        no_proxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
        try:
            hip = ipaddress.ip_address(host)
        except ValueError:
            hip = None
        for item in (x.strip() for x in no_proxy.split(",")):
            if not item:
                continue
            if hip is not None and "/" in item:
                try:
                    if hip in ipaddress.ip_network(item, strict=False):
                        return None
                except ValueError:
                    pass
            elif item.startswith("*.") and host.endswith(item[1:]):
                return None
        p = urlsplit(proxy if "://" in proxy else "http://" + proxy)
        auth = None
        if p.username:
            import base64

            auth = base64.b64encode(f"{p.username}:{p.password or ''}".encode()).decode()
        return p.hostname or "127.0.0.1", p.port or 8080, auth

    # ----- politeness --------------------------------------------------------

    def _host_lock(self, host: str) -> threading.Lock:
        with self._guard:
            lock = self._host_locks.get(host)
            if lock is None:
                lock = self._host_locks[host] = threading.Lock()
            return lock

    def _wait_turn(self, host: str) -> None:
        if self.per_host_interval <= 0:
            return
        last = self._host_last.get(host, 0.0)
        gap = self.per_host_interval - (time.monotonic() - last)
        if gap > 0:
            time.sleep(gap)

    def robots_allows(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: urllib.robotparser.RobotFileParser | None
            res = self.fetch(origin + "/robots.txt", max_bytes=512 * 1024, total_timeout=20, use_robots=False)
            if res.http_status and 200 <= res.http_status < 300:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(res.body.decode("utf-8", "replace").splitlines())
            elif res.http_status and 400 <= res.http_status < 500:
                parser = None  # RFC 9309: unavailable robots.txt allows everything
            elif res.status == "refused":
                parser = None
            else:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(ROBOTS_TOKEN, url)

    # ----- fetching ------------------------------------------------------------

    def fetch(
        self,
        url: str,
        *,
        max_bytes: int = 12 * 1024 * 1024,
        total_timeout: float = 60.0,
        headers: dict[str, str] | None = None,
        use_robots: bool = False,
        accept: str = "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.8",
    ) -> FetchResult:
        t0 = time.monotonic()
        deadline = t0 + total_timeout
        current = url
        redirects: list[str] = []
        try:
            if use_robots and not self.robots_allows(url):
                return FetchResult(url, url, "blocked", detail="disallowed by robots.txt", elapsed_ms=0)
            for _ in range(6):
                scheme, host, port, addrs = self.check_url(current)
                lock = self._host_lock(host)
                with lock:
                    self._wait_turn(host)
                    try:
                        resp_status, resp_headers, body, detail = self._request(
                            scheme, host, port, addrs, current, headers or {}, accept, max_bytes, deadline
                        )
                    finally:
                        self._host_last[host] = time.monotonic()
                if resp_status in REDIRECTS:
                    loc = resp_headers.get("location")
                    if not loc:
                        return self._result(url, current, "dead", resp_status, resp_headers, b"", "redirect without Location", redirects, t0)
                    current = urljoin(current, loc)
                    redirects.append(current)
                    continue
                if detail == "too_large":
                    return self._result(url, current, "too_large", resp_status, resp_headers, body, f"larger than {max_bytes} bytes", redirects, t0)
                if resp_status == 304:
                    return self._result(url, current, "not_modified", resp_status, resp_headers, b"", "", redirects, t0)
                if 200 <= resp_status < 300:
                    if self._is_bot_wall(resp_headers, body):
                        return self._result(url, current, "blocked", resp_status, resp_headers, b"", "bot check page served instead of the source", redirects, t0)
                    return self._result(url, current, "ok", resp_status, resp_headers, body, "", redirects, t0)
                if resp_status in BLOCKED:
                    return self._result(url, current, "blocked", resp_status, resp_headers, b"", f"HTTP {resp_status}", redirects, t0)
                if resp_status in DEAD or 400 <= resp_status < 500:
                    return self._result(url, current, "dead", resp_status, resp_headers, b"", f"HTTP {resp_status}", redirects, t0)
                return self._result(url, current, "unreachable", resp_status, resp_headers, b"", f"HTTP {resp_status}", redirects, t0)
            return self._result(url, current, "unreachable", None, {}, b"", "too many redirects", redirects, t0)
        except Refused as exc:
            return self._result(url, current, "refused", None, {}, b"", str(exc), redirects, t0)
        except ssl.SSLCertVerificationError as exc:
            return self._result(url, current, "blocked", None, {}, b"", f"TLS verification failed: {exc.verify_message}", redirects, t0)
        except (OSError, http.client.HTTPException, TimeoutError, ConnectionError) as exc:
            text = str(exc)
            if "Tunnel connection failed: 403" in text or "Tunnel connection failed: 407" in text:
                # the user's own network said no, not the publisher: retry later rather than park it
                return self._result(url, current, "unreachable", None, {}, b"", "the HTTPS proxy refused this host (local network policy)", redirects, t0)
            return self._result(url, current, "unreachable", None, {}, b"", f"{type(exc).__name__}: {text}", redirects, t0)

    def _result(self, url, final, status, code, headers, body, detail, redirects, t0) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=final,
            status=status,
            http_status=code,
            content_type=(headers or {}).get("content-type", ""),
            body=body,
            headers=headers or {},
            detail=detail,
            redirects=redirects,
            elapsed_ms=(time.monotonic() - t0) * 1000,
        )

    def _request(self, scheme, host, port, addrs, url, headers, accept, max_bytes, deadline):
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        proxy = self._proxy_for(scheme, host)
        timeout = min(self.read_timeout, max(1.0, deadline - time.monotonic()))
        if proxy:
            phost, pport, auth = proxy
            tunnel_headers = {"Proxy-Authorization": f"Basic {auth}"} if auth else None
            if scheme == "https":
                conn = http.client.HTTPSConnection(phost, pport, timeout=timeout, context=self._ctx)
            else:
                conn = http.client.HTTPConnection(phost, pport, timeout=timeout)
            conn.set_tunnel(host, port, headers=tunnel_headers)
        elif scheme == "https":
            conn = _PinnedHTTPS(host, port, addrs[0], self._ctx, timeout)
        else:
            conn = _PinnedHTTP(host, port, addrs[0], timeout)
        req_headers = {
            "User-Agent": self.user_agent,
            "Accept": accept,
            "Accept-Encoding": "gzip",
            "Accept-Language": "en",
            "Connection": "close",
        }
        req_headers.update(headers)
        try:
            conn.request("GET", path, headers=req_headers)
            resp = conn.getresponse()
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            if resp.status in REDIRECTS or resp.status == 304 or resp.status >= 400:
                resp.read(65536)
                return resp.status, resp_headers, b"", ""
            length = resp_headers.get("content-length")
            if length and length.isdigit() and int(length) > max_bytes:
                return resp.status, resp_headers, b"", "too_large"
            chunks: list[bytes] = []
            size = 0
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("download exceeded its time budget")
                chunk = resp.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    return resp.status, resp_headers, b"", "too_large"
                chunks.append(chunk)
            body = b"".join(chunks)
            if resp_headers.get("content-encoding", "").lower() == "gzip":
                d = zlib.decompressobj(16 + zlib.MAX_WBITS)
                out = d.decompress(body, max_bytes + 1)
                if len(out) > max_bytes or d.unconsumed_tail:
                    return resp.status, resp_headers, b"", "too_large"
                body = out
            return resp.status, resp_headers, body, ""
        finally:
            conn.close()

    @staticmethod
    def _is_bot_wall(headers: dict[str, str], body: bytes) -> bool:
        ctype = headers.get("content-type", "")
        if "html" not in ctype or len(body) > 200_000:
            return False
        head = body[:60_000].decode("utf-8", "replace").lower()
        return any(marker in head for marker in BOT_WALL_MARKERS)


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, context, timeout):
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
