"""A small root helper so the owner can install PrivateToolBox from the bot.

PrivateChecker itself runs as an unprivileged, sandboxed user. Installing
something needs root, so this separate service does exactly two things and
nothing else:

  install_toolbox  download the pinned PrivateToolBox release from GitHub over
                   HTTPS, install it, and enable its Telegram bridge
  enable_bridge    enable the bridge for a PrivateToolBox that is already installed

It takes no arguments from the bot, so a message can never choose what gets
downloaded or run. The socket can only be opened by root and the
`privatechecker` group. It is off unless you ran `sudo privatechecker enable-install`.
"""

import io
import json
import os
import subprocess
import tarfile
import tempfile
import threading
import urllib.request

TOOLBOX_REPO = "Sorena-max/PrivateToolBox"
TOOLBOX_REF = "v0.1.0"
TOOLBOX_BIN = "/usr/local/bin/privatetoolbox"
SOCKET = "/run/privatechecker/helper.sock"
GROUP = "privatechecker"
MAX_ARCHIVE = 20 * 1024 * 1024
MAX_OUTPUT = 20000
LOCK = threading.Lock()


class InstallError(Exception):
    pass


def tarball_url(repo=TOOLBOX_REPO, ref=TOOLBOX_REF):
    return "https://github.com/%s/archive/%s.tar.gz" % (repo, ref)


def download(url, limit=MAX_ARCHIVE):
    req = urllib.request.Request(url, headers={"User-Agent": "PrivateChecker-helper"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise InstallError("download is larger than expected")
    return data


def safe_extract(data, dest):
    """Unpack a release archive, refusing anything that could escape `dest`."""
    root = os.path.realpath(dest)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            target = os.path.realpath(os.path.join(root, member.name))
            if not (target == root or target.startswith(root + os.sep)):
                raise InstallError("unsafe path in archive: %s" % member.name)
            if not (member.isfile() or member.isdir()):
                raise InstallError("unexpected entry in archive: %s" % member.name)
        try:
            archive.extractall(root, members=members, filter="data")
        except TypeError:           # Python before 3.12 has no extraction filters
            archive.extractall(root, members=members)
    tops = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
    if len(tops) != 1:
        raise InstallError("unexpected archive layout")
    top = os.path.join(root, tops[0])
    for needed in ("install.sh", "privatetoolbox"):
        if not os.path.exists(os.path.join(top, needed)):
            raise InstallError("archive is missing %s" % needed)
    return top


def run_process(argv, timeout=600):
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout, universal_newlines=True,
                              env=dict(os.environ, NO_COLOR="1", TERM="dumb", LC_ALL="C.UTF-8"))
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except OSError as exc:
        return 127, str(exc)


def installed():
    return os.path.exists(TOOLBOX_BIN)


def install_toolbox(fetch=download, runner=run_process, workdir=None):
    """Install the pinned PrivateToolBox release and enable its bridge."""
    log = []
    tmp = workdir or tempfile.mkdtemp(prefix="privatechecker-toolbox-")
    try:
        data = fetch(tarball_url())
        top = safe_extract(data, tmp)
        code, out = runner(["bash", os.path.join(top, "install.sh"), "--non-interactive",
                            "--fast", "--no-clear", "--local-source", top], 600)
        log.append(out)
        if code != 0:
            return {"ok": False, "code": code, "output": clean("\n".join(log))}
        reply = enable_bridge(runner)
        log.append(reply["output"])
        return {"ok": reply["ok"], "code": reply.get("code", 0), "output": clean("\n".join(log))}
    except (InstallError, OSError, tarfile.TarError) as exc:
        return {"ok": False, "code": 1, "output": "%s" % exc}


def enable_bridge(runner=run_process):
    if not installed():
        return {"ok": False, "code": 1, "output": "PrivateToolBox is not installed"}
    code, out = runner([TOOLBOX_BIN, "integrate", "--yes"], 120)
    return {"ok": code == 0, "code": code, "output": clean(out)}


def clean(text):
    return (text or "").replace("\r", "")[-MAX_OUTPUT:]


def execute(request, fetch=download, runner=run_process):
    """Handle one request. Only the commands below exist; no arguments are read."""
    cmd = request.get("cmd") if isinstance(request, dict) else None
    if cmd == "ping":
        return {"ok": True}
    if cmd == "status":
        return {"ok": True, "installed": installed(), "ref": TOOLBOX_REF}
    if cmd not in ("install_toolbox", "enable_bridge"):
        return {"ok": False, "error": "unknown command"}
    if not LOCK.acquire(blocking=False):
        return {"ok": False, "error": "busy"}
    try:
        if cmd == "install_toolbox":
            return install_toolbox(fetch=fetch, runner=runner)
        return enable_bridge(runner)
    finally:
        LOCK.release()


def serve(path=None):
    import grp
    import socketserver

    path = path or os.environ.get("PRIVATECHECKER_HELPER_SOCKET", SOCKET)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                request = json.loads(self.rfile.readline(4096).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                request = None
            reply = execute(request)
            try:
                self.wfile.write((json.dumps(reply) + "\n").encode("utf-8"))
            except OSError:
                pass        # the bot restarts itself during the install; nobody is listening

    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    server = socketserver.ThreadingUnixStreamServer(path, Handler)
    try:
        os.chown(path, 0, grp.getgrnam(GROUP).gr_gid)
        os.chmod(path, 0o660)
    except KeyError:
        os.chmod(path, 0o600)
    try:
        server.serve_forever()
    finally:
        server.server_close()
