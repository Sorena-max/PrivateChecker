"""Reads server health from /proc and a few standard tools. A missing file,
denied permission or slow command gives None instead of an error, so one
broken source never breaks a report."""

import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request

PUBLIC_IP_URLS = ("https://api.ipify.org", "https://ifconfig.me/ip",
                  "https://icanhazip.com")
IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
REAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "vfat",
           "ntfs", "fuseblk", "exfat", "reiserfs", "jfs"}
SKIP_MOUNT_PREFIXES = ("/var/lib/docker", "/snap", "/boot/efi", "/run")
IGNORED_IFACE = ("lo", "veth", "docker", "br-", "virbr", "cni", "flannel")
CACHE_HOURS = 3600


def proc_root():
    return os.environ.get("SC_PROC", "/proc")


def read_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def run(cmd, timeout=10):
    """Run a command and return (returncode, stdout); (None, '') on failure."""
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=timeout, universal_newlines=True)
        return proc.returncode, proc.stdout
    except (OSError, subprocess.SubprocessError):
        return None, ""


def parse_meminfo(text):
    info = {}
    for line in (text or "").splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            try:
                info[name] = int(parts[0]) * 1024
            except ValueError:
                pass
    if "MemTotal" not in info:
        return None
    total = info["MemTotal"]
    available = info.get("MemAvailable", info.get("MemFree", 0))
    swap_total = info.get("SwapTotal", 0)
    swap_used = swap_total - info.get("SwapFree", 0)
    return {
        "total": total, "available": available, "used": total - available,
        "pct": round((total - available) * 100.0 / total, 1) if total else 0.0,
        "swap_total": swap_total, "swap_used": swap_used,
        "swap_pct": round(swap_used * 100.0 / swap_total, 1) if swap_total else 0.0,
    }


def parse_cpu_times(text):
    """Return (idle, total) jiffies from the first line of /proc/stat."""
    for line in (text or "").splitlines():
        if line.startswith("cpu "):
            nums = [int(x) for x in line.split()[1:] if x.isdigit()]
            if len(nums) >= 4:
                idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
                return idle, sum(nums[:8])
    return None


def cpu_percent(before, after):
    if not before or not after:
        return None
    total = after[1] - before[1]
    if total <= 0:
        return None
    return round(max(0.0, min(100.0, (1 - (after[0] - before[0]) / total) * 100)), 1)


def parse_net_dev(text):
    """Return {iface: (rx_bytes, tx_bytes)} for real interfaces."""
    out = {}
    for line in (text or "").splitlines()[2:]:
        name, _, rest = line.partition(":")
        name = name.strip()
        fields = rest.split()
        if not name or len(fields) < 9 or name.startswith(IGNORED_IFACE):
            continue
        try:
            out[name] = (int(fields[0]), int(fields[8]))
        except ValueError:
            continue
    return out


def parse_tcp_table(text):
    """Return (listening, established) from /proc/net/tcp{,6} content.

    listening is a list of (port, scope) where scope is public
    (bound to every address) or local (loopback only) or other.
    """
    listening, established = [], 0
    for line in (text or "").splitlines()[1:]:
        fields = line.split()
        if len(fields) < 4:
            continue
        addr, _, port_hex = fields[1].rpartition(":")
        state = fields[3]
        if state == "01":
            established += 1
        elif state == "0A":
            try:
                port = int(port_hex, 16)
            except ValueError:
                continue
            if set(addr) == {"0"}:
                scope = "public"
            elif addr.upper() in ("0100007F", "00000000000000000000000001000000"):
                scope = "local"
            else:
                scope = "other"
            listening.append((port, scope))
    return listening, established


SSH_FAIL_RE = re.compile(r"(?:Failed \S+|Invalid user|authentication failure)")
SSH_IP_RE = re.compile(r"(?:from|rhost=)\s*([0-9]{1,3}(?:\.[0-9]{1,3}){3}|[0-9a-fA-F:]{3,39})")
SSH_OK_RE = re.compile(r"Accepted (\S+) for (\S+) from (\S+)")


def parse_ssh_log(text):
    """Summarise failed and successful SSH logins from log text."""
    failed, ips, accepted = 0, {}, []
    for line in (text or "").splitlines():
        ok = SSH_OK_RE.search(line)
        if ok:
            accepted.append({"method": ok.group(1), "user": ok.group(2),
                             "ip": ok.group(3)})
            continue
        if "sshd" in line and SSH_FAIL_RE.search(line):
            failed += 1
            ip = SSH_IP_RE.search(line)
            if ip:
                ips[ip.group(1)] = ips.get(ip.group(1), 0) + 1
    top = sorted(ips.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return {"failed": failed, "top": top, "accepted": accepted[-3:],
            "accepted_count": len(accepted)}


def parse_stat_line(text):
    """Return (name, cpu_ticks) from a /proc/<pid>/stat line."""
    head, _, tail = text.rpartition(")")
    name = head.partition("(")[2]
    fields = tail.split()
    if len(fields) < 13:
        return None
    return name, int(fields[11]) + int(fields[12])


def uptime_seconds():
    text = read_file(os.path.join(proc_root(), "uptime"))
    try:
        return float(text.split()[0])
    except (AttributeError, IndexError, ValueError):
        return None


def os_pretty_name():
    text = read_file("/etc/os-release") or ""
    for line in text.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def snapshot_processes():
    """Map pid -> (name, cpu_ticks, rss_bytes) for readable processes."""
    page = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
    snap = {}
    root = proc_root()
    try:
        entries = os.listdir(root)
    except OSError:
        return snap
    for entry in entries:
        if not entry.isdigit():
            continue
        stat = read_file(os.path.join(root, entry, "stat"))
        if not stat:
            continue
        try:
            parsed = parse_stat_line(stat)
            statm = (read_file(os.path.join(root, entry, "statm")) or "").split()
            rss = int(statm[1]) * page if len(statm) > 1 else 0
        except (ValueError, IndexError):
            continue
        if parsed:
            snap[int(entry)] = (parsed[0], parsed[1], rss)
    return snap


class Collector:
    """Gathers every report section; keeps small caches between calls."""

    def __init__(self, iran_checker=None):
        self._lock = threading.Lock()
        self._net_prev = None
        self._ip = (None, 0.0)
        self._updates = (None, 0.0)
        self._security = (None, 0.0)
        self.iran = iran_checker

    def system(self, cpu):
        load = os.getloadavg() if hasattr(os, "getloadavg") else None
        return {
            "hostname": socket.gethostname(),
            "os": os_pretty_name(),
            "kernel": os.uname().release if hasattr(os, "uname") else None,
            "uptime": uptime_seconds(),
            "load": load,
            "cores": os.cpu_count() or 1,
            "cpu_pct": cpu,
            "reboot_required": os.path.exists("/run/reboot-required")
            or os.path.exists("/var/run/reboot-required"),
        }

    def memory(self):
        return parse_meminfo(read_file(os.path.join(proc_root(), "meminfo")))

    def disk(self):
        mounts = read_file(os.path.join(proc_root(), "mounts")) or ""
        seen, out = set(), []
        for line in mounts.splitlines():
            parts = line.split()
            if len(parts) < 3 or parts[2] not in REAL_FS:
                continue
            mount = parts[1].replace("\\040", " ")
            if mount.startswith(SKIP_MOUNT_PREFIXES) and mount != "/":
                continue
            try:
                dev = os.stat(mount).st_dev
                if dev in seen:
                    continue
                seen.add(dev)
                st = os.statvfs(mount)
            except OSError:
                continue
            total = st.f_blocks * st.f_frsize
            if not total:
                continue
            used = total - st.f_bfree * st.f_frsize
            avail = st.f_bavail * st.f_frsize
            pct = round(used * 100.0 / (used + avail), 1) if used + avail else 0.0
            inode_pct = None
            if st.f_files:
                inode_pct = round((st.f_files - st.f_ffree) * 100.0 / st.f_files, 1)
            out.append({"mount": mount, "fstype": parts[2], "total": total,
                        "used": used, "pct": pct, "inode_pct": inode_pct})
        return out

    def network(self):
        counters = parse_net_dev(read_file(os.path.join(proc_root(), "net/dev")))
        rx = sum(v[0] for v in counters.values())
        tx = sum(v[1] for v in counters.values())
        now = time.time()
        rate = None
        with self._lock:
            prev, self._net_prev = self._net_prev, (now, rx, tx)
        if prev and now > prev[0]:
            dt = now - prev[0]
            rate = {"rx": max(0, (rx - prev[1]) / dt),
                    "tx": max(0, (tx - prev[2]) / dt)}
        tcp4 = read_file(os.path.join(proc_root(), "net/tcp"))
        tcp6 = read_file(os.path.join(proc_root(), "net/tcp6"))
        l4, e4 = parse_tcp_table(tcp4)
        l6, e6 = parse_tcp_table(tcp6)
        return {"rx_total": rx, "tx_total": tx, "rate": rate,
                "established": e4 + e6, "interfaces": sorted(counters),
                "public_ip": self.public_ip(), "_listening": l4 + l6}

    def ports(self, listening):
        by_port = {}
        for port, scope in listening:
            rank = {"public": 0, "other": 1, "local": 2}[scope]
            if port not in by_port or rank < by_port[port][1]:
                by_port[port] = (scope, rank)
        return sorted((p, s[0]) for p, s in by_port.items())

    def public_ip(self):
        ip, ts = self._ip
        if ip and time.time() - ts < CACHE_HOURS:
            return ip
        for url in PUBLIC_IP_URLS:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "PrivateChecker"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    text = resp.read().decode("utf-8", "replace").strip()
                if IPV4_RE.match(text):
                    self._ip = (text, time.time())
                    return text
            except (OSError, ValueError):
                continue
        return ip

    def processes(self, before, after, interval):
        ticks = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        rows = []
        for pid, (name, t1, rss) in after.items():
            t0 = before.get(pid, (name, t1, rss))[1]
            cpu = max(0.0, (t1 - t0) / ticks / interval * 100) if interval else 0.0
            rows.append({"pid": pid, "name": name, "cpu": round(cpu, 1), "rss": rss})
        return {
            "by_cpu": sorted(rows, key=lambda r: r["cpu"], reverse=True)[:5],
            "by_mem": sorted(rows, key=lambda r: r["rss"], reverse=True)[:5],
        }

    def services(self, watched):
        if not shutil.which("systemctl"):
            return {"available": False, "failed": [], "watched": {}}
        _, failed_out = run(["systemctl", "--failed", "--no-legend", "--plain",
                             "--no-pager"])
        failed = [ln.split()[0] for ln in failed_out.splitlines() if ln.strip()]
        states = {}
        for name in watched:
            _, out = run(["systemctl", "is-active", name])
            states[name] = out.strip() or "unknown"
        return {"available": True, "failed": failed, "watched": states}

    def docker(self):
        if not shutil.which("docker"):
            return {"available": False, "reason": "not-installed"}
        code, out = run(["docker", "ps", "-a", "--format",
                         "{{.Names}}|{{.State}}|{{.Status}}"], timeout=10)
        if code != 0:
            return {"available": False, "reason": "no-access"}
        rows = []
        for line in out.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                rows.append({"name": parts[0], "state": parts[1], "status": parts[2]})
        return {"available": True, "containers": rows,
                "running": sum(1 for r in rows if r["state"] == "running")}

    def security(self):
        value, ts = self._security
        if value is not None and time.time() - ts < 300:
            return value
        text = None
        if shutil.which("journalctl"):
            code, out = run(["journalctl", "--since", "24 hours ago",
                             "--no-pager", "-q", "-o", "short", "-n", "50000",
                             "_COMM=sshd"], timeout=20)
            if code == 0 and out.strip():
                text = out
        if text is None:
            for path in ("/var/log/auth.log", "/var/log/secure"):
                data = read_file(path)
                if data:
                    text = data[-3_000_000:]
                    break
        if text is None:
            result = {"available": False}
        else:
            result = dict(parse_ssh_log(text), available=True)
        code, who = run(["who"], timeout=5)
        sessions = []
        for line in who.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                sessions.append({"user": parts[0], "tty": parts[1],
                                 "from": parts[-1].strip("()") if "(" in parts[-1] else ""})
        result["sessions"] = sessions
        self._security = (result, time.time())
        return result

    def updates(self):
        value, ts = self._updates
        if value is not None and time.time() - ts < CACHE_HOURS:
            return value
        result = {"available": False}
        if shutil.which("apt-get"):
            code, out = run(["apt-get", "-s", "-o", "Debug::NoLocking=1",
                             "upgrade"], timeout=40)
            if code == 0:
                lines = [ln for ln in out.splitlines() if ln.startswith("Inst ")]
                result = {"available": True, "count": len(lines),
                          "security": sum(1 for ln in lines if "-security" in ln)}
        elif shutil.which("dnf") or shutil.which("yum"):
            tool = "dnf" if shutil.which("dnf") else "yum"
            code, out = run([tool, "-q", "check-update"], timeout=60)
            if code in (0, 100):
                names = [ln for ln in out.splitlines()
                         if ln.strip() and not ln.startswith(("Obsoleting", " "))
                         and len(ln.split()) >= 3]
                result = {"available": True, "count": len(names), "security": None}
        self._updates = (result, time.time())
        return result

    def iran_target(self, cfg_iran, public_ip=None):
        return cfg_iran.get("target") or public_ip or self.public_ip()

    def iran_check(self, cfg_iran, public_ip=None, force=False):
        target = self.iran_target(cfg_iran, public_ip)
        if not self.iran:
            return {"target": target, "nodes": [], "error": "disabled"}
        if not target:
            return {"target": None, "nodes": [], "error": "no-target"}
        return self.iran.check(target, cfg_iran.get("tcp_ports", []), force=force)

    def collect(self, cfg, only=None):
        """Collect the sections enabled in cfg (or exactly only)."""
        wanted = [only] if only else [s for s, on in cfg["sections"].items() if on]
        # The Iran check can take a minute (rate-limit retries). Run it beside the
        # local sections, and never under a lock, so quick buttons stay instant.
        iran_job = {}
        iran_thread = None
        if "iran" in wanted:
            def run_iran():
                ip = None if cfg["iran"].get("target") else self.public_ip()
                iran_job["data"] = self.iran_check(cfg["iran"], ip)
            iran_thread = threading.Thread(target=run_iran, daemon=True)
            iran_thread.start()

        need_cpu = "system" in wanted or "processes" in wanted
        cpu_before = parse_cpu_times(read_file(os.path.join(proc_root(), "stat")))
        procs_before = snapshot_processes() if "processes" in wanted else {}
        t0 = time.time()
        if need_cpu:
            time.sleep(0.6)
        cpu_after = parse_cpu_times(read_file(os.path.join(proc_root(), "stat")))
        data = {}
        if "system" in wanted:
            data["system"] = self.system(cpu_percent(cpu_before, cpu_after))
        if "memory" in wanted:
            data["memory"] = self.memory()
        if "disk" in wanted:
            data["disk"] = self.disk()
        net = None
        if "network" in wanted or "ports" in wanted:
            net = self.network()
        if "network" in wanted:
            data["network"] = {k: v for k, v in net.items() if k != "_listening"}
        if "ports" in wanted:
            data["ports"] = self.ports(net["_listening"])
        if "processes" in wanted:
            data["processes"] = self.processes(
                procs_before, snapshot_processes(), max(0.1, time.time() - t0))
        if "services" in wanted:
            data["services"] = self.services(cfg["services"])
        if "docker" in wanted:
            data["docker"] = self.docker()
        if "security" in wanted:
            data["security"] = self.security()
        if "updates" in wanted:
            data["updates"] = self.updates()
        if iran_thread:
            iran_thread.join()
            data["iran"] = iran_job.get("data")
        return data
