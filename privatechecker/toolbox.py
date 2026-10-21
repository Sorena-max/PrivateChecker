"""Clients for the local PrivateToolBox agent and for the install helper.

The agent is installed by `sudo privatetoolbox integrate`. It listens on a Unix
socket that only its group can open, so the bot never needs root itself. The
optional helper (`sudo privatechecker enable-install`) can install PrivateToolBox.
"""

import json
import os
import socket

DEFAULT_SOCKET = "/run/privatetoolbox/agent.sock"
DEFAULT_HELPER_SOCKET = "/run/privatechecker/helper.sock"
PROGRAM = "/usr/local/bin/privatetoolbox"


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

def installed():
    """True when the privatetoolbox command exists on this server."""
    return os.path.exists(os.environ.get("PRIVATETOOLBOX_BIN", PROGRAM))


def helper_socket_path():
    return os.environ.get("PRIVATECHECKER_HELPER_SOCKET", DEFAULT_HELPER_SOCKET)


def helper_available():
    """True when the owner switched on installing PrivateToolBox from the bot."""
    return os.path.exists(helper_socket_path())


def helper_call(cmd, timeout=900):
    """Ask the root helper to do one of its fixed jobs. Never raises."""
    try:
        raw = _exchange(helper_socket_path(), (json.dumps({"cmd": cmd}) + "\n").encode("utf-8"), timeout)
        reply = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, AttributeError) as exc:
        return {"ok": False, "error": str(exc)}
    return reply if isinstance(reply, dict) else {"ok": False, "error": "bad reply"}
