"""Bridge only declared host loopback ports into a Linux network namespace."""

from __future__ import annotations
from contextlib import contextmanager
import json
from pathlib import Path
import select
import socket
import socketserver
import threading
import tempfile


def relay(left, right):
    try:
        while True:
            ready, _, _ = select.select([left, right], [], [], 1)
            for source in ready:
                data = source.recv(65536)
                if not data:
                    return
                (right if source is left else left).sendall(data)
    except (OSError, ValueError):
        pass
    finally:
        left.close()
        right.close()


class UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


class TCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


@contextmanager
def host_gateway(ports):
    temporary = tempfile.TemporaryDirectory(prefix="rsi-gw-", dir="/tmp")
    root = Path(temporary.name)
    servers = []
    threads = []
    try:
        for port in sorted(set(ports)):
            if not 1 <= int(port) <= 65535:
                raise ValueError("Invalid gateway port")
            path = root / f"{port}.sock"
            if path.exists():
                raise ValueError("Gateway socket already exists")

            def handler_for(target):
                class Handler(socketserver.BaseRequestHandler):
                    def handle(self):
                        with socket.create_connection(
                            ("127.0.0.1", target), timeout=30
                        ) as remote:
                            remote.settimeout(None)
                            relay(self.request, remote)

                return Handler

            server = UnixServer(str(path), handler_for(port))
            path.chmod(0o600)
            servers.append(server)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            threads.append(thread)
        yield root
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
        temporary.cleanup()


def namespace_main():
    import subprocess, sys

    root = Path(sys.argv[1])
    ports = json.loads(sys.argv[2])
    servers = []
    try:
        for port in ports:

            def handler_for(path):
                class Handler(socketserver.BaseRequestHandler):
                    def handle(self):
                        remote = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        remote.connect(str(path))
                        relay(self.request, remote)

                return Handler

            server = TCPServer(("127.0.0.1", port), handler_for(root / f"{port}.sock"))
            servers.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
        raise SystemExit(subprocess.call(sys.argv[3:]))
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    namespace_main()
