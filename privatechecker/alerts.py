"""Alerts. A problem has to last a few checks in a row before we say
anything, and one message is sent when it clears."""

import os
import time

from . import collectors
from .checkhost import summarize

CHECK_EVERY = 60          # seconds between local checks
IRAN_EVERY = 15 * 60      # seconds between Iran checks
NEED = {"cpu": 3, "mem": 2, "disk": 1, "services": 2, "iran": 2}


class Alerts:
    def __init__(self, cfg, collector, notify):
        """notify(kind, key, params) is called with kind alert|recovered."""
        self.cfg = cfg
        self.col = collector
        self.notify = notify
        self._bad = {}
        self._active = {}
        self._cpu_prev = None
        self._next_iran = 0.0

    def _cpu(self):
        cur = collectors.parse_cpu_times(
            collectors.read_file(os.path.join(collectors.proc_root(), "stat")))
        prev, self._cpu_prev = self._cpu_prev, cur
        return collectors.cpu_percent(prev, cur)

    def evaluate(self, cfg, now):
        """Return {name: (is_bad, params)}; names without data are omitted."""
        limits = cfg["alerts"]
        out = {}
        cpu = self._cpu()
        if cpu is not None:
            out["cpu"] = (cpu >= limits["cpu"], {"v": round(cpu)})
        mem = self.col.memory()
        if mem:
            out["mem"] = (mem["pct"] >= limits["mem"], {"v": round(mem["pct"])})
        disks = self.col.disk()
        if disks:
            worst = max(disks, key=lambda d: d["pct"])
            out["disk"] = (worst["pct"] >= limits["disk"],
                           {"m": worst["mount"], "v": round(worst["pct"])})
        if limits["services"]:
            svc = self.col.services(cfg["services"])
            if svc.get("available"):
                broken = list(svc["failed"]) + [
                    "%s (%s)" % (n, s) for n, s in svc["watched"].items()
                    if s != "active"]
                out["services"] = (bool(broken), {"v": ", ".join(broken[:5])})
        if limits["iran"] and now >= self._next_iran:
            self._next_iran = now + IRAN_EVERY
            report = self.col.iran_check(cfg["iran"])
            ok, total = summarize(report)
            if not report.get("error") and total:
                out["iran"] = (ok * 2 < total, {"ok": ok, "total": total})
        return out

    def apply(self, name, bad, params, cooldown, now):
        if bad:
            self._bad[name] = self._bad.get(name, 0) + 1
            if self._bad[name] < NEED[name]:
                return
            last = self._active.get(name)
            if last is None or now - last >= cooldown * 60:
                self._active[name] = now
                self.notify("alert", "a_" + name, params)
        else:
            self._bad[name] = 0
            if name in self._active:
                del self._active[name]
                self.notify("recovered", "a_%s_ok" % name, params)

    def tick(self, now=None):
        now = time.time() if now is None else now
        cfg = self.cfg.snapshot()
        if not cfg["alerts"]["enabled"]:
            self._bad.clear()
            self._active.clear()
            self._cpu_prev = None
            return
        for name, (bad, params) in self.evaluate(cfg, now).items():
            self.apply(name, bad, params, cfg["alerts"]["cooldown_min"], now)
