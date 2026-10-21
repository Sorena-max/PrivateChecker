"""Checks whether Iran can reach this server, using the check-host.net API
(it has probe nodes inside Iran)."""

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

API = "https://check-host.net"
FALLBACK_NODES = ("ir1.node.check-host.net", "ir3.node.check-host.net")
MAX_NODES = 5
MAX_PORTS = 3
RESULT_TTL = 120        # seconds a complete check is reused (scheduled reports and alerts)
WAIT = 40               # seconds to wait for the Iranian probes to answer
NODES_TTL = 6 * 3600
BACKOFF = 600           # seconds to stay quiet after the API says "limit exceeded"
START_TRIES = 3         # starting a check is rate limited per IP: retry politely
START_RETRY_WAIT = 20   # seconds between tries
IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


class CheckHostError(Exception):
    pass


def _get(path, timeout=15):
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/json",
        "User-Agent": "PrivateChecker/%s" % __version__,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise CheckHostError("HTTP %s from check-host.net" % exc.code)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CheckHostError(str(exc))
    # The API reports problems (e.g. "limit_exceeded") as {"error": "..."} with HTTP 200.
    if isinstance(data, dict) and data.get("error") and "request_id" not in data:
        raise CheckHostError(str(data["error"]))
    return data


def parse_nodes(payload):
    """Return [(node, city), ...] for the Iranian probes in a nodes reply."""
    found = []
    nodes = (payload or {}).get("nodes") or {}
    for name, info in sorted(nodes.items()):
        loc = (info or {}).get("location") or []
        if loc and str(loc[0]).lower() == "ir":
            city = loc[2] if len(loc) > 2 else (loc[1] if len(loc) > 1 else "")
            found.append((name, city))
    return found


def fetch_nodes():
    """Ask check-host.net for its Iranian probes (raises CheckHostError)."""
    return parse_nodes(_get("/nodes/hosts"))


def parse_ping(value):
    """Summarise one node's ping answer; None while it is still pending."""
    if not value or value == [None]:
        return None
    rows = value[0] if isinstance(value, list) else None
    if rows is None:
        return None
    if isinstance(rows, dict):  # {"error": "..."}
        return {"ok": 0, "total": 4, "avg_ms": None}
    times = [r[1] for r in rows
             if isinstance(r, list) and len(r) > 1 and r[0] == "OK"]
    avg = round(sum(times) / len(times) * 1000, 1) if times else None
    return {"ok": len(times), "total": len(rows), "avg_ms": avg}


def parse_tcp(value):
    """Summarise one node's TCP-connect answer; None while pending."""
    if not value or value == [None]:
        return None
    item = value[0] if isinstance(value, list) else value
    if not isinstance(item, dict):
        return None
    if "time" in item:
        return {"ok": True, "ms": round(float(item["time"]) * 1000, 1),
                "error": None}
    return {"ok": False, "ms": None, "error": str(item.get("error", ""))[:60]}


class IranChecker:
    """Runs ping/TCP checks from Iranian nodes, with caching and rate limits."""

    def __init__(self, sleep=time.sleep):
        self._lock = threading.Lock()
        self._sleep = sleep
        self._nodes = None
        self._nodes_ts = 0.0
        self._last = None
        self._last_key = None
        self._last_ts = 0.0
        self._blocked_until = 0.0

    def nodes(self):
        if self._nodes and time.time() - self._nodes_ts < NODES_TTL:
            return self._nodes
        try:
            found = fetch_nodes()
        except CheckHostError:
            found = []
        if not found:
            found = [(n, "") for n in FALLBACK_NODES]
        self._nodes, self._nodes_ts = found, time.time()
        return found

    def _start(self, path):
        """Start a check; starting is rate limited, reading results is not."""
        for attempt in range(START_TRIES):
            try:
                return _get(path)
            except CheckHostError as exc:
                if "limit" not in str(exc) or attempt == START_TRIES - 1:
                    raise
                self._sleep(START_RETRY_WAIT)

    def _run(self, kind, host, node_names, wait):
        query = urllib.parse.urlencode(
            [("host", host)] + [("node", n) for n in node_names])
        started = self._start("/check-%s?%s" % (kind, query))
        request_id = started.get("request_id")
        if not request_id:
            raise CheckHostError("no request id from check-host.net")
        parser = parse_ping if kind == "ping" else parse_tcp
        deadline = time.time() + wait
        results = {}
        while True:
            self._sleep(3)
            raw = _get("/check-result/%s" % request_id)
            results = {n: parser(raw.get(n)) for n in node_names}
            if all(v is not None for v in results.values()) or \
                    time.time() >= deadline:
                return results

    def check(self, host, ports=(), wait=WAIT, force=False):
        """Return a dict describing reachability of host from Iran.

        force=True is for a person who just asked: it always runs a fresh test (and
        tries even during the quiet period after a rate limit). Only complete results
        are cached, so a half-finished test is never shown again.
        """
        ports = [p for p in list(ports)[:MAX_PORTS]]
        key = (host, tuple(ports))
        with self._lock:
            if (not force and self._last is not None and key == self._last_key
                    and time.time() - self._last_ts < RESULT_TTL):
                return self._last
            report = {"target": host, "nodes": [], "error": None, "ts": time.time()}
            if not force and time.time() < self._blocked_until:
                report["error"] = "limit_exceeded"
                return report
            try:
                chosen = self.nodes()[:MAX_NODES]
                names = [n for n, _ in chosen]
                ping = self._run("ping", host, names, wait)
                tcp = {p: self._run("tcp", "%s:%d" % (host, p), names, wait)
                       for p in ports}
                for name, city in chosen:
                    report["nodes"].append({
                        "node": name, "city": city, "ping": ping.get(name),
                        "tcp": {p: tcp[p].get(name) for p in ports}})
            except CheckHostError as exc:
                report["error"] = str(exc)
                if "limit" in report["error"]:
                    self._blocked_until = time.time() + BACKOFF
            complete = not report["error"] and all(n["ping"] is not None for n in report["nodes"])
            if complete:
                self._last, self._last_key, self._last_ts = report, key, time.time()
            else:
                self._last = None
            return report


def summarize(report):
    """Reduce a report to (reachable, total) node counts by ping."""
    total = reachable = 0
    for node in report.get("nodes", []):
        ping = node.get("ping")
        if ping is None:
            continue
        total += 1
        if ping["ok"] > 0:
            reachable += 1
    return reachable, total
