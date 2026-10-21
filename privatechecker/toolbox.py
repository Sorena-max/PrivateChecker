"""Client for the local PrivateToolBox agent.

The agent is installed by `sudo privatetoolbox integrate`. It listens on a Unix
socket that only its group can open, so the bot never needs root itself.
"""

import json
import os
import socket

DEFAULT_SOCKET = "/run/privatetoolbox/agent.sock"


def socket_path():
    return os.environ.get("PRIVATETOOLBOX_SOCKET", DEFAULT_SOCKET)


def available():
    """True when PrivateToolBox is installed with its Telegram bridge enabled."""
    return os.path.exists(socket_path())


def _exchange(path, payload, timeout):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(path)
        sock.sendall(payload)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
            if data.endswith(b"\n"):
                break
        return b"".join(chunks)
    finally:
        sock.close()


def call(request, timeout=900):
    """Send one request, return the reply dictionary (never raises)."""
    try:
        raw = _exchange(socket_path(), (json.dumps(request) + "\n").encode("utf-8"), timeout)
        reply = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, AttributeError) as exc:
        return {"ok": False, "error": str(exc)}
    return reply if isinstance(reply, dict) else {"ok": False, "error": "bad reply"}
