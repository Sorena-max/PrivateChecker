"""Settings and state, kept as small JSON files in PRIVATECHECKER_HOME
(default /var/lib/privatechecker)."""

import copy
import json
import os
import re
import threading
import time

MIN_INTERVAL = 5       # minutes
MAX_INTERVAL = 1200    # minutes
INTERVAL_PRESETS = (5, 10, 15, 30, 60, 120, 360, 720)

SECTIONS = (
    "system", "memory", "disk", "network", "processes", "services",
    "docker", "ports", "security", "updates", "iran",
)
LANGUAGES = ("fa", "en")

SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@:-]{1,64}$")
TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")

DEFAULTS = {
    "version": 1,
    "token": "",
    "api_base": "https://api.telegram.org",
    "owner_id": 0,
    "users": [],
    "language": "fa",
    "interval_min": 30,
    "reports_enabled": True,
    "sections": {
        "system": True, "memory": True, "disk": True, "network": True,
        "processes": True, "services": True, "docker": True, "ports": False,
        "security": True, "updates": True, "iran": True,
    },
    "services": [],
    "alerts": {
        "enabled": True, "cpu": 90, "mem": 90, "disk": 90,
        "services": True, "iran": True, "cooldown_min": 60,
    },
    "iran": {"target": "", "tcp_ports": []},
}


def home_dir():
    return os.environ.get("PRIVATECHECKER_HOME", "/var/lib/privatechecker")


def clamp_interval(value):
    return max(MIN_INTERVAL, min(MAX_INTERVAL, int(value)))


def valid_interval(value):
    """True for an int-like value inside the allowed range."""
    try:
        return MIN_INTERVAL <= int(value) <= MAX_INTERVAL
    except (TypeError, ValueError):
        return False


def _merge(base, extra):
    """Return base overlaid with extra, keeping only known keys."""
    out = copy.deepcopy(base)
    if not isinstance(extra, dict):
        return out
    for key, default in base.items():
        if key not in extra:
            continue
        value = extra[key]
        if isinstance(default, dict):
            out[key] = _merge(default, value)
        else:
            out[key] = value
    return out


def normalize(data):
    """Fill defaults and coerce every field into a safe, valid value."""
    cfg = _merge(DEFAULTS, data)
    cfg["token"] = str(cfg["token"]).strip()
    cfg["api_base"] = str(cfg["api_base"]).rstrip("/") or DEFAULTS["api_base"]
    try:
        cfg["owner_id"] = int(cfg["owner_id"])
    except (TypeError, ValueError):
        cfg["owner_id"] = 0
    users = []
    for item in cfg["users"] if isinstance(cfg["users"], list) else []:
        try:
            uid = int(item)
        except (TypeError, ValueError):
            continue
        if uid > 0 and uid != cfg["owner_id"] and uid not in users:
            users.append(uid)
    cfg["users"] = users
    if cfg["language"] not in LANGUAGES:
        cfg["language"] = DEFAULTS["language"]
    try:
        cfg["interval_min"] = clamp_interval(cfg["interval_min"])
    except (TypeError, ValueError):
        cfg["interval_min"] = DEFAULTS["interval_min"]
    cfg["reports_enabled"] = bool(cfg["reports_enabled"])
    cfg["sections"] = {s: bool(cfg["sections"].get(s)) for s in SECTIONS}
    services = []
    for name in cfg["services"] if isinstance(cfg["services"], list) else []:
        if isinstance(name, str) and SERVICE_RE.match(name) and name not in services:
            services.append(name)
    cfg["services"] = services
    alerts = cfg["alerts"]
    for key in ("cpu", "mem", "disk"):
        try:
            alerts[key] = max(50, min(99, int(alerts[key])))
        except (TypeError, ValueError):
            alerts[key] = DEFAULTS["alerts"][key]
    for key in ("enabled", "services", "iran"):
        alerts[key] = bool(alerts[key])
    try:
        alerts["cooldown_min"] = max(5, min(1440, int(alerts["cooldown_min"])))
    except (TypeError, ValueError):
        alerts["cooldown_min"] = DEFAULTS["alerts"]["cooldown_min"]
    iran = cfg["iran"]
    iran["target"] = str(iran["target"]).strip()[:253]
    ports = []
    for item in iran["tcp_ports"] if isinstance(iran["tcp_ports"], list) else []:
        try:
            port = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65535 and port not in ports:
            ports.append(port)
    iran["tcp_ports"] = ports[:3]
    return cfg


class JsonStore:
    """A JSON file guarded by a lock and written atomically with mode 0600."""

    def __init__(self, path, defaults, normalizer=None):
        self.path = path
        self._defaults = defaults
        self._normalizer = normalizer
        self._lock = threading.RLock()
        self.data = {}
        self.load()

    def load(self):
        with self._lock:
            raw = {}
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
            except (OSError, ValueError):
                raw = {}
            self.data = self._normalizer(raw) if self._normalizer else \
                _merge(self._defaults, raw)

    def save(self):
        with self._lock:
            if self._normalizer:
                self.data = self._normalizer(self.data)
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = "%s.tmp.%d" % (self.path, os.getpid())
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp, self.path)

    def update(self, fn):
        """Run fn(data) under the lock, then persist the result."""
        with self._lock:
            result = fn(self.data)
            self.save()
            return result

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self.data)


def open_config(path=None):
    return JsonStore(path or os.path.join(home_dir(), "config.json"),
                     DEFAULTS, normalize)


def open_state(path=None):
    return JsonStore(path or os.path.join(home_dir(), "state.json"),
                     {"last_report_ts": 0.0})


def is_authorized(cfg, user_id):
    """Only the owner and users the owner added may use the bot."""
    return bool(user_id) and (
        user_id == cfg["owner_id"] or user_id in cfg["users"])


def recipients(cfg):
    return [cfg["owner_id"]] + list(cfg["users"]) if cfg["owner_id"] else []


def now():
    return time.time()
