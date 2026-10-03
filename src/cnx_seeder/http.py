"""Bounded HTTP fetch: robots, retries, body cap, per-host interval."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from cnx_seeder.bounds import (
    MAX_BODY_BYTES,
    MAX_RETRIES,
    PER_HOST_INTERVAL_SECONDS,
    RETRY_STATUSES,
    TIMEOUT_SECONDS,
    USER_AGENT,
)
from cnx_seeder.normalize import strip_host

_RETRY_ERRORS = frozenset({"timeout"})
MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_SIXTO4_ANYCAST = ipaddress.ip_network("192.88.99.0/24")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_V4COMPAT = ipaddress.ip_network("::/96")
_METADATA = ipaddress.ip_address("169.254.169.254")


class DestinationRejected(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Destination:
    url: str
    scheme: str
    hostname: str
    port: int
    pin_ip: str
    allowed_ips: frozenset[str]
    target: str


def _same_ip(left: str, right: str) -> bool:
    try:
        return ipaddress.ip_address(left) == ipaddress.ip_address(right)
    except ValueError:
        return False


def _embedded_addresses(ip: ipaddress.IPv4Address | ipaddress.IPv6Address):
    found: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = [ip]
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            found.append(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            found.append(ip.sixtofour)
        if ip.teredo is not None:
            found.append(ip.teredo[1])
        if ip in _NAT64 or ip in _V4COMPAT:
            found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return found


def _one_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return True
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return True
    if ip.version == 4 and (ip in _CGNAT or ip in _SIXTO4_ANYCAST or ip == _METADATA):
        return True
    return False


def ip_blocked(text: str) -> bool:
    try:
        parsed = ipaddress.ip_address(text)
    except ValueError:
        return False
    return any(_one_blocked(item) for item in _embedded_addresses(parsed))


def _resolve_host(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise OSError("name or service not known") from exc
    found: list[str] = []
    for info in infos:
        addr = str(info[4][0])
        if addr not in found:
            found.append(addr)
    return found


def validate_destination(url: str, resolve) -> Destination:
    """Reject a non-public or non-standard destination before any connection."""
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise DestinationRejected("bad_scheme") from exc
    if parts.scheme not in {"http", "https"}:
        raise DestinationRejected("bad_scheme")
    hostname = parts.hostname
    if not hostname or "%" in hostname:
        raise DestinationRejected("bad_host")
    port = 443 if parts.scheme == "https" else 80
    if parts.port is not None:
        port = parts.port
    if port not in {80, 443}:
        raise DestinationRejected("bad_port")
    literal = None
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [str(literal)]
    else:
        try:
            addresses = list(resolve(hostname))
        except OSError as exc:
            raise DestinationRejected("dns") from exc
    if not addresses:
        raise DestinationRejected("dns")
    if any(ip_blocked(addr) for addr in addresses):
        raise DestinationRejected("private_address")
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    return Destination(
        url,
        parts.scheme,
        hostname,
        port,
        addresses[0],
        frozenset(addresses),
        target,
    )


@dataclass
class HttpResponse:
    status: int | None
    body: bytes
    final_url: str
    content_type: str = ""
    error: str | None = None
    location: str | None = None


class Transport:
    def reject_reason(self, url: str) -> str | None:
        return None

    def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        raise NotImplementedError


@dataclass
class VirtualClock:
    now: datetime

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.now += timedelta(seconds=seconds)


@dataclass
class LiveClock:
    def __post_init__(self) -> None:
        return None

    @property
    def now(self) -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0)

    def sleep(self, seconds: float) -> None:
        import time

        if seconds > 0:
            time.sleep(seconds)


def stamp(moment: datetime) -> str:
    value = moment.astimezone(timezone.utc).replace(microsecond=0)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stamp(text: str) -> datetime:
    raw = text.replace("Z", "+00:00")
    return datetime.fromisoformat(raw)


@dataclass
class FetchRecord:
    url: str
    attempt: int
    fetched_at: str
    http_status: int | None
    body: bytes
    content_sha256: str | None
    byte_length: int
    elapsed_ms: int
    robots_decision: str
    outcome: str
    error: str | None = None
    content_type: str = ""
    final_url: str = ""
    location: str | None = None


@dataclass
class Fetcher:
    transport: Transport
    clock: VirtualClock | LiveClock
    calls: list[tuple[str, str]] = field(default_factory=list)
    history: list[FetchRecord] = field(default_factory=list)
    _last: dict[str, datetime] = field(default_factory=dict)
    _robots: dict[str, tuple[str, RobotFileParser | None]] = field(default_factory=dict)
    blocked_hosts: set[str] = field(default_factory=set)

    def _host(self, url: str) -> str:
        return strip_host(urlsplit(url).hostname or "")

    def _wait(self, host: str) -> datetime:
        last = self._last.get(host)
        now = self.clock.now
        if last is not None:
            earliest = last + timedelta(seconds=PER_HOST_INTERVAL_SECONDS)
            if now < earliest:
                self.clock.sleep((earliest - now).total_seconds())
                now = self.clock.now
        self._last[host] = now
        return now

    def _robots_url(self, url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}/robots.txt"

    def prepare_host(self, url: str) -> str:
        host = self._host(url)
        if host in self._robots:
            return self._robots[host][0]
        robots_url = self._robots_url(url)
        record = self._once(robots_url, robots_decision="allow", skip_robots=True)
        if record.http_status != 200 or record.error:
            record.robots_decision = "robots_unavailable"
            self._robots[host] = ("robots_unavailable", None)
            self.blocked_hosts.add(host)
            return "robots_unavailable"
        parser = RobotFileParser()
        parser.parse(record.body.decode("utf-8", "replace").splitlines())
        parser.last_checked = 1
        self._robots[host] = ("allow", parser)
        return "allow"

    def can_fetch(self, url: str) -> str:
        host = self._host(url)
        decision = self.prepare_host(url)
        if decision == "robots_unavailable" or host in self.blocked_hosts:
            return "robots_unavailable"
        parser = self._robots[host][1]
        if parser is not None and not parser.can_fetch(USER_AGENT, url):
            return "disallow"
        return "allow"

    def _once(self, url: str, *, robots_decision: str, skip_robots: bool) -> FetchRecord:
        host = self._host(url)
        moment = self._wait(host)
        self.calls.append((url, USER_AGENT))
        started = self.clock.now
        try:
            response = self.transport.get(url, {"User-Agent": USER_AGENT})
        except TimeoutError:
            response = HttpResponse(None, b"", url, error="timeout")
        except OSError as exc:
            message = str(exc).casefold()
            kind = "dns" if "name or service" in message or "nodename" in message else "tls"
            response = HttpResponse(None, b"", url, error=kind)
        elapsed = 0
        body = response.body or b""
        overflow = len(body) > MAX_BODY_BYTES
        if overflow:
            body = body[:MAX_BODY_BYTES]
        retained = body
        digest = hashlib.sha256(retained).hexdigest() if response.error is None else None
        outcome = "ok"
        error = response.error
        if response.error:
            outcome = "timeout" if response.error == "timeout" else "fetch_failed"
        elif overflow:
            outcome = "fetch_failed"
            error = "body_cap"
        elif response.status is None:
            outcome = "fetch_failed"
        elif response.status in {401, 403, 407, 429}:
            outcome = "blocked"
            error = "http_blocked"
        elif response.status >= 400:
            outcome = "fetch_failed"
            error = error or f"http_{response.status}"
        record = FetchRecord(
            url=url,
            attempt=1,
            fetched_at=stamp(moment),
            http_status=response.status,
            body=retained,
            content_sha256=digest,
            byte_length=len(retained),
            elapsed_ms=elapsed,
            robots_decision=robots_decision,
            outcome=outcome,
            error=error,
            content_type=response.content_type,
            final_url=response.final_url or url,
            location=response.location,
        )
        self.history.append(record)
        return record

    def _refused(self, url: str, error: str) -> FetchRecord:
        moment = self.clock.now
        record = FetchRecord(
            url=url,
            attempt=1,
            fetched_at=stamp(moment),
            http_status=None,
            body=b"",
            content_sha256=None,
            byte_length=0,
            elapsed_ms=0,
            robots_decision="deny",
            outcome="fetch_failed",
            error=error,
            final_url=url,
        )
        self.history.append(record)
        return record

    def _fetch_allowed(self, url: str) -> list[FetchRecord]:
        decision = self.can_fetch(url)
        if decision == "disallow":
            moment = self.clock.now
            record = FetchRecord(
                url=url,
                attempt=1,
                fetched_at=stamp(moment),
                http_status=None,
                body=b"",
                content_sha256=None,
                byte_length=0,
                elapsed_ms=0,
                robots_decision="disallow",
                outcome="blocked",
                error="robots_disallow",
            )
            self.history.append(record)
            return [record]
        if decision == "robots_unavailable":
            moment = self.clock.now
            record = FetchRecord(
                url=url,
                attempt=1,
                fetched_at=stamp(moment),
                http_status=None,
                body=b"",
                content_sha256=None,
                byte_length=0,
                elapsed_ms=0,
                robots_decision="robots_unavailable",
                outcome="blocked",
                error="robots_unavailable",
                final_url=url,
            )
            self.history.append(record)
            return [record]
        records: list[FetchRecord] = []
        for attempt in range(1, MAX_RETRIES + 2):
            record = self._once(url, robots_decision="allow", skip_robots=False)
            record.attempt = attempt
            records.append(record)
            retryable = record.http_status in RETRY_STATUSES or record.error in _RETRY_ERRORS
            if record.outcome == "ok" or not retryable or attempt > MAX_RETRIES:
                break
        return records

    def fetch(self, url: str) -> list[FetchRecord]:
        return self._follow(url, left=MAX_REDIRECTS, seen=set())

    def _follow(self, url: str, *, left: int, seen: set[str]) -> list[FetchRecord]:
        if url in seen:
            return [self._refused(url, "redirect_loop")]
        if left < 0:
            return [self._refused(url, "redirect_cap")]
        seen.add(url)
        reason = self.transport.reject_reason(url)
        if reason:
            return [self._refused(url, reason)]
        records = self._fetch_allowed(url)
        if not records:
            return records
        last = records[-1]
        if last.http_status in _REDIRECT_STATUSES and last.location and last.error is None:
            nxt = urljoin(url, last.location)
            if urlsplit(url).scheme == "https" and urlsplit(nxt).scheme == "http":
                return records + [self._refused(nxt, "https_downgrade")]
            return records + self._follow(nxt, left=left - 1, seen=seen)
        return records


class FixtureTransport(Transport):
    """File-backed transport. It never opens a socket."""

    def __init__(self, root: Path) -> None:
        self.root = root
        payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.routes: dict[str, dict] = payload.get("routes") or {}
        self._cursors: dict[str, int] = {}

    def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        log = self.root / "calls.jsonl"
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"url": url, "ua": headers.get("User-Agent", "")}) + "\n")
        spec = self.routes.get(url)
        if spec is None:
            return HttpResponse(404, b"missing fixture", url, content_type="text/plain")
        error = spec.get("error")
        if error == "timeout":
            raise TimeoutError("timeout")
        if error == "dns":
            raise OSError("name or service not known")
        if error == "tls":
            raise OSError("tls handshake failed")
        statuses = spec.get("statuses")
        if isinstance(statuses, list) and statuses:
            index = self._cursors.get(url, 0)
            status = int(statuses[min(index, len(statuses) - 1)])
            self._cursors[url] = index + 1
        else:
            status = int(spec.get("status", 200))
        if "body_file" in spec:
            body = (self.root / spec["body_file"]).read_bytes()
        elif "body_b64" in spec:
            import base64

            body = base64.b64decode(spec["body_b64"])
        else:
            body = str(spec.get("body", "")).encode("utf-8")
        return HttpResponse(
            status,
            body,
            str(spec.get("final_url") or url),
            content_type=str(spec.get("content_type") or "text/html"),
        )


class _DeadlineFile:
    """File object that re-arms the remaining wall-clock budget on every read."""

    def __init__(self, raw, sock: "_DeadlineSocket") -> None:
        self._raw = raw
        self._sock = sock

    def read(self, *args, **kwargs):
        self._sock._arm()
        return self._raw.read(*args, **kwargs)

    def readline(self, *args, **kwargs):
        self._sock._arm()
        return self._raw.readline(*args, **kwargs)

    def readinto(self, *args, **kwargs):
        self._sock._arm()
        return self._raw.readinto(*args, **kwargs)

    def close(self) -> None:
        return self._raw.close()

    def flush(self) -> None:
        return self._raw.flush()

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    @property
    def closed(self):
        return self._raw.closed


class _DeadlineSocket:
    """Socket wrapper whose timeout is the remaining request deadline."""

    def __init__(self, sock, deadline: float) -> None:
        self._sock = sock
        self._deadline = deadline

    def _remain(self) -> float:
        left = self._deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("timeout")
        return left

    def _arm(self) -> None:
        self._sock.settimeout(self._remain())

    def __getattr__(self, name: str):
        return getattr(self._sock, name)

    def recv(self, *args, **kwargs):
        self._arm()
        return self._sock.recv(*args, **kwargs)

    def recv_into(self, *args, **kwargs):
        self._arm()
        return self._sock.recv_into(*args, **kwargs)

    def send(self, *args, **kwargs):
        self._arm()
        return self._sock.send(*args, **kwargs)

    def sendall(self, *args, **kwargs):
        self._arm()
        return self._sock.sendall(*args, **kwargs)

    def makefile(self, *args, **kwargs):
        self._arm()
        return _DeadlineFile(self._sock.makefile(*args, **kwargs), self)

    def close(self) -> None:
        return self._sock.close()

    def getpeername(self):
        return self._sock.getpeername()

    def settimeout(self, value) -> None:
        return self._sock.settimeout(value)


def _pinned_get(dest: Destination, headers: dict[str, str], connect) -> HttpResponse:
    """Connect to the validated address. http.client does not follow redirects."""
    import http.client
    import ssl

    deadline = time.monotonic() + TIMEOUT_SECONDS
    remain = deadline - time.monotonic()
    if remain <= 0:
        raise TimeoutError("timeout")
    sock = connect((dest.pin_ip, dest.port), remain)
    conn: http.client.HTTPConnection | None = None
    try:
        peer = sock.getpeername()[0]
        if ip_blocked(peer) or not _same_ip(peer, dest.pin_ip):
            raise DestinationRejected("private_address")
        remain = deadline - time.monotonic()
        if remain <= 0:
            raise TimeoutError("timeout")
        sock.settimeout(remain)
        if dest.scheme == "https":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=dest.hostname)
        sock = _DeadlineSocket(sock, deadline)
        if dest.scheme == "https":
            conn = http.client.HTTPSConnection(dest.hostname, dest.port, timeout=remain)
        else:
            conn = http.client.HTTPConnection(dest.hostname, dest.port, timeout=remain)
        conn.sock = sock
        conn.request("GET", dest.target, headers=headers)
        response = conn.getresponse()
        body = response.read(MAX_BODY_BYTES + 1)
        return HttpResponse(
            response.status,
            body,
            dest.url,
            content_type=response.getheader("Content-Type") or "",
            location=response.getheader("Location"),
        )
    finally:
        if conn is not None:
            conn.close()
        else:
            sock.close()


class LiveTransport(Transport):
    """Live HTTP that never follows redirects and never dials an unvalidated address."""

    def __init__(self, resolve=None, exchange=None, connect=None) -> None:
        self._resolve = resolve or _resolve_host
        self._exchange = exchange
        self._connect = connect or socket.create_connection

    def _checkout(self, url: str) -> Destination:
        return validate_destination(url, self._resolve)

    def reject_reason(self, url: str) -> str | None:
        try:
            self._checkout(url)
        except DestinationRejected as exc:
            return exc.code
        return None

    def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        try:
            dest = self._checkout(url)
        except DestinationRejected as exc:
            return HttpResponse(None, b"", url, error=exc.code)
        if self._exchange is not None:
            return self._exchange(url, headers, dest)
        try:
            return _pinned_get(dest, headers, self._connect)
        except DestinationRejected as exc:
            return HttpResponse(None, b"", url, error=exc.code)
        except TimeoutError:
            raise
        except OSError as exc:
            message = str(exc).casefold()
            if "timed out" in message or "timeout" in message:
                raise TimeoutError(message)
            if "name or service" in message or "nodename" in message or "gaierror" in message:
                raise OSError("name or service not known")
            raise OSError("tls handshake failed")
