"""Exclusive loopback port selection. The bound socket is the reservation."""

from __future__ import annotations

import socket

LOOPBACK = "127.0.0.1"
# Smartphone Clank documented 127.0.0.1:8200. It is outside this range and excluded.
EXCLUDED_PORTS = frozenset({8200})
CANDIDATE_PORTS = range(8210, 8300)


class PortOccupied(OSError):
    def __init__(self, port: int, reason: str) -> None:
        self.port = port
        super().__init__(f"127.0.0.1:{port} is not available ({reason})")


def bind_loopback(port: int) -> socket.socket:
    """Bind and listen on 127.0.0.1 only. The caller keeps this socket."""
    if port in EXCLUDED_PORTS:
        raise PortOccupied(port, "excluded reserved Clank port")
    if port < 1 or port > 65535:
        raise PortOccupied(port, "port is outside 1-65535")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((LOOPBACK, port))
        sock.listen(16)
    except OSError as exc:
        sock.close()
        reason = exc.strerror or exc.__class__.__name__
        raise PortOccupied(port, reason) from exc
    host = sock.getsockname()[0]
    if host != LOOPBACK:
        sock.close()
        raise PortOccupied(port, f"socket bound {host}, expected {LOOPBACK}")
    return sock


def select_bound_socket(port: int | None = None) -> socket.socket:
    """Return a listening socket. An explicit port never falls through to another."""
    if port is not None:
        return bind_loopback(port)
    failures: list[PortOccupied] = []
    for candidate in CANDIDATE_PORTS:
        if candidate in EXCLUDED_PORTS:
            continue
        try:
            return bind_loopback(candidate)
        except PortOccupied as exc:
            failures.append(exc)
    detail = failures[-1] if failures else "range empty"
    raise PortOccupied(0, f"no free port in {CANDIDATE_PORTS.start}-{CANDIDATE_PORTS.stop - 1}; last={detail}")
