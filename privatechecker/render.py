"""Turn collected data into Telegram-HTML report text."""

import html
import time

from .checkhost import summarize
from .i18n import t

WARN_DISK_CRIT = 95.0
ORDER = ("system", "memory", "disk", "network", "processes", "services",
         "docker", "ports", "security", "updates", "iran")


def esc(value):
    return html.escape(str(value), quote=False)


def human_bytes(n):
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024


def human_rate(n):
    return "?" if n is None else human_bytes(n) + "/s"


def human_duration(seconds, lang):
    if seconds is None:
        return "?"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    units = (("روز", "ساعت", "دقیقه") if lang == "fa" else ("d", "h", "m"))
    parts = []
    if days:
        parts.append("%d %s" % (days, units[0]))
    if hours:
        parts.append("%d %s" % (hours, units[1]))
    if minutes or not parts:
        parts.append("%d %s" % (minutes, units[2]))
    return " ".join(parts)


def minutes_label(minutes, lang):
    if minutes % 60 == 0 and minutes >= 60:
        hours = minutes // 60
        return "%d %s" % (hours, "ساعت" if lang == "fa" else "h")
    return "%d %s" % (minutes, "دقیقه" if lang == "fa" else "min")


def bar(pct, width=10):
    pct = max(0.0, min(100.0, float(pct or 0)))
    filled = int(round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def level(pct, warn, crit=None):
    crit = crit if crit is not None else min(100, warn + 5)
    if pct is None:
        return "⚪"
    return "🔴" if pct >= crit else "🟡" if pct >= warn else "🟢"


def _title(lang, key):
    return "<b>%s</b>" % esc(t(lang, key))


def _kv(lang, key, value):
    return "• %s: %s" % (esc(t(lang, key)), value)


def render_system(d, lang, cfg):
    warn = cfg["alerts"]["cpu"]
    lines = [_title(lang, "sec_system")]
    if d.get("os"):
        lines.append(_kv(lang, "os", esc(d["os"])))
    if d.get("kernel"):
        lines.append(_kv(lang, "kernel", esc(d["kernel"])))
    lines.append(_kv(lang, "uptime", esc(human_duration(d.get("uptime"), lang))))
    if d.get("load"):
        lines.append(_kv(lang, "load", "%.2f %.2f %.2f (%d %s)" % (
            d["load"][0], d["load"][1], d["load"][2], d["cores"], t(lang, "cores"))))
    if d.get("cpu_pct") is not None:
        lines.append(_kv(lang, "cpu", "%s %.0f%% <code>%s</code>" % (
            level(d["cpu_pct"], warn), d["cpu_pct"], bar(d["cpu_pct"]))))
    if d.get("reboot_required"):
        lines.append(esc(t(lang, "reboot_required")))
    return "\n".join(lines)


def render_memory(d, lang, cfg):
    lines = [_title(lang, "sec_memory")]
    if not d:
        return "\n".join(lines + [esc(t(lang, "no_data"))])
    warn = cfg["alerts"]["mem"]
    lines.append(_kv(lang, "ram", "%s %.0f%% <code>%s</code>\n   %s / %s" % (
        level(d["pct"], warn), d["pct"], bar(d["pct"]),
        human_bytes(d["used"]), human_bytes(d["total"]))))
    if d["swap_total"]:
        lines.append(_kv(lang, "swap", "%s %.0f%% (%s / %s)" % (
            level(d["swap_pct"], 60, 90), d["swap_pct"],
            human_bytes(d["swap_used"]), human_bytes(d["swap_total"]))))
    return "\n".join(lines)


def render_disk(d, lang, cfg):
    lines = [_title(lang, "sec_disk")]
    if not d:
        return "\n".join(lines + [esc(t(lang, "no_data"))])
    warn = cfg["alerts"]["disk"]
    for disk in d:
        text = "<code>%s</code> %s %.0f%% <code>%s</code>\n   %s / %s" % (
            esc(disk["mount"]), level(disk["pct"], warn, WARN_DISK_CRIT),
            disk["pct"], bar(disk["pct"]),
            human_bytes(disk["used"]), human_bytes(disk["total"]))
        if disk.get("inode_pct") is not None and disk["inode_pct"] >= 80:
            text += "\n   %s %s %.0f%%" % (esc(t(lang, "inodes")),
                                           level(disk["inode_pct"], 80, 95), disk["inode_pct"])
        lines.append("• " + text)
    return "\n".join(lines)


def render_network(d, lang, cfg):
    lines = [_title(lang, "sec_network")]
    if d.get("public_ip"):
        lines.append(_kv(lang, "public_ip", "<code>%s</code>" % esc(d["public_ip"])))
    lines.append(_kv(lang, "rx", human_bytes(d["rx_total"])))
    lines.append(_kv(lang, "tx", human_bytes(d["tx_total"])))
    if d.get("rate"):
        lines.append(_kv(lang, "rate_now", "⬇️ %s  ⬆️ %s" % (
            human_rate(d["rate"]["rx"]), human_rate(d["rate"]["tx"]))))
    lines.append(_kv(lang, "conn", str(d["established"])))
    return "\n".join(lines)


def render_processes(d, lang, cfg):
    lines = [_title(lang, "sec_processes")]
    lines.append("<i>%s</i>" % esc(t(lang, "by_cpu")))
    for row in d["by_cpu"][:5]:
        lines.append("• <code>%s</code> - %.1f%%" % (esc(row["name"]), row["cpu"]))
    lines.append("<i>%s</i>" % esc(t(lang, "by_mem")))
    for row in d["by_mem"][:5]:
        lines.append("• <code>%s</code> - %s" % (esc(row["name"]), human_bytes(row["rss"])))
    return "\n".join(lines)


def render_services(d, lang, cfg):
    lines = [_title(lang, "sec_services")]
    if not d.get("available"):
        return "\n".join(lines + [esc(t(lang, "unavailable"))])
    if d["failed"]:
        lines.append("🔴 %s: %s" % (esc(t(lang, "failed_units")),
                                    ", ".join("<code>%s</code>" % esc(u) for u in d["failed"])))
    else:
        lines.append("🟢 " + esc(t(lang, "all_services_ok")))
    for name, state in d["watched"].items():
        lines.append("• <code>%s</code>: %s %s" % (
            esc(name), "🟢" if state == "active" else "🔴", esc(state)))
    return "\n".join(lines)


def render_docker(d, lang, cfg):
    lines = [_title(lang, "sec_docker")]
    if not d.get("available"):
        key = "docker_no_access" if d.get("reason") == "no-access" else "docker_missing"
        return "\n".join(lines + [esc(t(lang, key))])
    total = len(d["containers"])
    lines.append(_kv(lang, "containers", "%d (%d %s)" % (total, d["running"], t(lang, "running"))))
    down = [c for c in d["containers"] if c["state"] != "running"]
    if down:
        lines.append("🔴 " + esc(t(lang, "not_running")))
        for c in down[:10]:
            lines.append("• <code>%s</code> - %s" % (esc(c["name"]), esc(c["status"])))
    return "\n".join(lines)


def render_ports(d, lang, cfg):
    lines = [_title(lang, "sec_ports")]
    if not d:
        return "\n".join(lines + [esc(t(lang, "none"))])
    for port, scope in d[:30]:
        icon = "🌍" if scope == "public" else "🏠" if scope == "local" else "📍"
        lines.append("• <code>%d</code> %s %s" % (port, icon, esc(t(lang, scope))))
    return "\n".join(lines)


def render_security(d, lang, cfg):
    lines = [_title(lang, "sec_security")]
    if d.get("available"):
        lines.append(_kv(lang, "ssh_failed", "%s %d" % (
            "🟡" if d["failed"] >= 50 else "🟢", d["failed"])))
        if d["top"]:
            lines.append("   %s: %s" % (esc(t(lang, "top_ips")), ", ".join(
                "<code>%s</code>x%d" % (esc(ip), n) for ip, n in d["top"])))
        lines.append(_kv(lang, "ssh_ok", str(d.get("accepted_count", 0))))
    else:
        lines.append(esc(t(lang, "log_unreadable")))
    if d.get("sessions"):
        lines.append(_kv(lang, "sessions", ", ".join(
            "<code>%s</code>%s" % (esc(s["user"]), " (%s)" % esc(s["from"]) if s["from"] else "")
            for s in d["sessions"][:6])))
    return "\n".join(lines)


def render_updates(d, lang, cfg):
    lines = [_title(lang, "sec_updates")]
    if not d.get("available"):
        return "\n".join(lines + [esc(t(lang, "updates_unknown"))])
    if d["count"] == 0:
        lines.append("🟢 " + esc(t(lang, "updates_none")))
    else:
        text = "%s %d" % ("🟡" if d.get("security") else "🟢", d["count"])
        if d.get("security"):
            text += " (%s: %d)" % (t(lang, "updates_security"), d["security"])
        lines.append(_kv(lang, "updates_count", text))
    return "\n".join(lines)


def render_iran(d, lang, cfg):
    lines = [_title(lang, "sec_iran")]
    if d.get("error"):
        if "limit" in d["error"]:
            return "\n".join(lines + ["⚠️ " + esc(t(lang, "iran_limited"))])
        return "\n".join(lines + ["⚠️ " + esc(t(lang, "iran_error", err=d["error"]))])
    lines.append(_kv(lang, "iran_target", "<code>%s</code>" % esc(d["target"])))
    for node in d["nodes"]:
        ping, label = node.get("ping"), node["node"].split(".")[0]
        city = node.get("city") or label
        if ping is None:
            lines.append("• %s: ⚪ %s" % (esc(city), esc(t(lang, "iran_noanswer"))))
            continue
        icon = "🟢" if ping["ok"] == ping["total"] else "🟡" if ping["ok"] else "🔴"
        text = "• %s (%s): %s ping %d/%d" % (esc(city), esc(label), icon, ping["ok"], ping["total"])
        if ping["avg_ms"] is not None:
            text += " | %.0f ms" % ping["avg_ms"]
        for port, res in node["tcp"].items():
            if res is None:
                text += " | TCP %d ⚪" % port
            elif res["ok"]:
                text += " | TCP %d ✅ %.0f ms" % (port, res["ms"])
            else:
                text += " | TCP %d ❌" % port
        lines.append(text)
    ok, total = summarize(d)
    lines.append("<i>%s</i>" % esc(t(lang, "iran_nodes", ok=ok, total=total)
                                   if total else t(lang, "iran_none")))
    lines.append("<i>%s</i>" % esc(t(lang, "iran_powered")))
    return "\n".join(lines)


RENDERERS = {
    "system": render_system, "memory": render_memory, "disk": render_disk,
    "network": render_network, "processes": render_processes,
    "services": render_services, "docker": render_docker, "ports": render_ports,
    "security": render_security, "updates": render_updates, "iran": render_iran,
}


def findings(data, cfg, lang):
    """Return [(severity, text), ...] describing what needs attention."""
    out = []
    alerts = cfg["alerts"]
    sysd = data.get("system")
    if sysd:
        if sysd.get("cpu_pct") is not None and sysd["cpu_pct"] >= alerts["cpu"]:
            out.append(("warn", t(lang, "f_cpu", v=round(sysd["cpu_pct"]))))
        if sysd.get("reboot_required"):
            out.append(("warn", t(lang, "f_reboot")))
    mem = data.get("memory")
    if mem and mem["pct"] >= alerts["mem"]:
        out.append(("warn", t(lang, "f_mem", v=round(mem["pct"]))))
    for disk in data.get("disk") or []:
        if disk["pct"] >= alerts["disk"]:
            sev = "crit" if disk["pct"] >= WARN_DISK_CRIT else "warn"
            out.append((sev, t(lang, "f_disk", m=disk["mount"], v=round(disk["pct"]))))
    svc = data.get("services")
    if svc and svc.get("available"):
        for name in svc["failed"]:
            out.append(("crit", t(lang, "f_failed", n=name)))
        for name, state in svc["watched"].items():
            if state != "active":
                out.append(("crit", t(lang, "f_inactive", n=name, s=state)))
    dock = data.get("docker")
    if dock and dock.get("available"):
        for c in dock["containers"]:
            if c["state"] in ("exited", "dead", "restarting"):
                out.append(("warn", t(lang, "f_docker", n=c["name"], s=c["state"])))
    upd = data.get("updates")
    if upd and upd.get("available") and upd.get("security"):
        out.append(("warn", t(lang, "f_sec_updates", n=upd["security"])))
    iran = data.get("iran")
    if iran and not iran.get("error"):
        ok, total = summarize(iran)
        if total and ok == 0:
            out.append(("crit", t(lang, "f_iran_down")))
        elif total and ok < total:
            out.append(("warn", t(lang, "f_iran_part", ok=ok, total=total)))
    return out


def build_report(data, cfg, lang, host, full=True):
    """Return a list of message parts (header first) for the collected data."""
    found = findings(data, cfg, lang)
    crit = [f for f in found if f[0] == "crit"]
    if crit:
        status = t(lang, "status_crit", n=len(crit))
    elif found:
        status = t(lang, "status_warn", n=len(found))
    else:
        status = t(lang, "status_ok")
    head = ["<b>%s - %s</b>" % (esc(t(lang, "report_title")), esc(host)),
            "🕒 " + esc(time.strftime("%Y-%m-%d %H:%M %Z").strip()),
            status]
    for sev, text in found:
        head.append("%s %s" % ("🔴" if sev == "crit" else "🟡", esc(text)))
    parts = ["\n".join(head)]
    for name in ORDER:
        if name not in data or data[name] is None:
            continue
        # Don't clutter every report on servers that simply have no Docker.
        if name == "docker" and data[name].get("reason") == "not-installed":
            continue
        parts.append(RENDERERS[name](data[name], lang, cfg))
    return parts


def build_section(name, data, cfg, lang):
    if name not in data or data[name] is None:
        return esc(t(lang, "no_data"))
    return RENDERERS[name](data[name], lang, cfg)


def strip_html(text):
    import re
    return html.unescape(re.sub(r"</?(?:b|i|code)>", "", text))
