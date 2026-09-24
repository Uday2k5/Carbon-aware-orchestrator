"""Transfer mechanisms for the migration profiler.

    loopback  TCP over 127.0.0.1 (exercises the kernel network stack, no NIC)
    copy      shutil.copyfile (pure disk path)
    netem     same as loopback but you shape 'lo' first, e.g.
              sudo tc qdisc add dev lo root netem delay 60ms rate 500mbit
"""
from __future__ import annotations

import shutil
import socket
import threading

CHUNK = 4 * 1024 * 1024


def copy_transfer(src: str, dst: str) -> int:
    shutil.copyfile(src, dst)
    import os
    return os.path.getsize(dst)


def loopback_transfer(src: str, dst: str, chunk: int = CHUNK) -> int:
    """Send src over a loopback TCP socket into dst. Returns bytes received."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    received = {"n": 0}

    def serve() -> None:
        conn, _ = srv.accept()
        with conn, open(dst, "wb") as out:
            while True:
                data = conn.recv(chunk)
                if not data:
                    break
                out.write(data)
                received["n"] += len(data)

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    cli = socket.create_connection(("127.0.0.1", port))
    with cli, open(src, "rb") as fh:
        while True:
            data = fh.read(chunk)
            if not data:
                break
            cli.sendall(data)
        cli.shutdown(socket.SHUT_WR)
    th.join()
    srv.close()
    return received["n"]


TRANSPORTS = {"loopback": loopback_transfer, "copy": copy_transfer, "netem": loopback_transfer}
