"""Shared fixtures for the PrivateChecker tests."""

import os
import tempfile

from privatechecker import config

OWNER = 1001
FRIEND = 2002
STRANGER = 9999
TOKEN = "123456789:" + "A" * 35


def make_config(**overrides):
    tmp = tempfile.mkdtemp()
    cfg = config.open_config(os.path.join(tmp, "config.json"))

    def apply(d):
        d["token"], d["owner_id"] = TOKEN, OWNER
        d.update(overrides)
    cfg.update(apply)
    state = config.open_state(os.path.join(tmp, "state.json"))
    return cfg, state


def sample_data():
    return {
        "system": {"hostname": "box", "os": "Ubuntu 22.04", "kernel": "5.15",
                   "uptime": 90061, "load": (0.5, 0.4, 0.3), "cores": 2,
                   "cpu_pct": 12.0, "reboot_required": False},
        "memory": {"total": 2 * 1024 ** 3, "available": 1024 ** 3, "used": 1024 ** 3,
                   "pct": 50.0, "swap_total": 0, "swap_used": 0, "swap_pct": 0.0},
        "disk": [{"mount": "/", "fstype": "ext4", "total": 20 * 1024 ** 3,
                  "used": 10 * 1024 ** 3, "pct": 50.0, "inode_pct": 5.0}],
        "network": {"rx_total": 1024 ** 3, "tx_total": 2 * 1024 ** 3,
                    "rate": {"rx": 1000.0, "tx": 2000.0}, "established": 7,
                    "interfaces": ["eth0"], "public_ip": "203.0.113.5"},
        "processes": {"by_cpu": [{"pid": 1, "name": "python3", "cpu": 3.0, "rss": 1000}],
                      "by_mem": [{"pid": 1, "name": "python3", "cpu": 3.0, "rss": 1000}]},
        "services": {"available": True, "failed": [], "watched": {"nginx": "active"}},
        "docker": {"available": True, "containers": [
            {"name": "web", "state": "running", "status": "Up 2 days"}], "running": 1},
        "ports": [(22, "public"), (5432, "local")],
        "security": {"available": True, "failed": 3, "top": [("198.51.100.7", 3)],
                     "accepted": [], "accepted_count": 1, "sessions": []},
        "updates": {"available": True, "count": 4, "security": 1},
        "iran": {"target": "203.0.113.5", "error": None, "nodes": [
            {"node": "ir1.node.check-host.net", "city": "Tehran",
             "ping": {"ok": 4, "total": 4, "avg_ms": 61.5},
             "tcp": {443: {"ok": True, "ms": 70.0, "error": None}}}]},
    }


class FakeTelegram:
    """Records what the bot would send to Telegram."""

    def __init__(self):
        self.sent = []       # (chat_id, text, markup)
        self.edited = []     # (chat_id, message_id, text, markup)
        self.answers = []    # (callback_id, text)

    def send_message(self, chat_id, text, markup=None):
        self.sent.append((chat_id, text, markup))
        return {"message_id": len(self.sent)}

    def edit_message(self, chat_id, message_id, text, markup=None):
        self.edited.append((chat_id, message_id, text, markup))

    def answer_callback(self, callback_id, text=None):
        self.answers.append((callback_id, text))

    def call(self, method, params=None, timeout=30):
        return {}

    def get_me(self):
        return {"username": "test_bot"}

    def delete_webhook(self):
        return True


class FakeCollector:
    def __init__(self, data=None):
        self.data = data or sample_data()
        self.collect_calls = []
        self.fresh_calls = []

    def collect(self, cfg, only=None, fresh=False):
        self.collect_calls.append(only)
        self.fresh_calls.append(fresh)
        return {only: self.data[only]} if only else dict(self.data)

    def memory(self):
        return self.data["memory"]

    def disk(self):
        return self.data["disk"]

    def services(self, watched):
        return self.data["services"]

    def iran_check(self, cfg_iran, public_ip=None, force=False):
        return self.data["iran"]
