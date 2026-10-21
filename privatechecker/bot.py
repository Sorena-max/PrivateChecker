"""Telegram bot: control panel, scheduled reports and alerts.

Only the owner and the users the owner added get answers. Anyone else is
ignored without a reply, and groups are never handled.
"""

import logging
import re
import threading
import time

from . import collectors, config, helper, render, toolbox
from .alerts import Alerts
from .config import (INTERVAL_PRESETS, LANGUAGES, MAX_INTERVAL, MIN_INTERVAL,
                     SECTIONS, SERVICE_RE)
from .i18n import t
from .telegram_api import TelegramError, pack

log = logging.getLogger("privatechecker")
HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
START_COMMANDS = {"/start", "/panel", "/menu"}
TOOLBOX_PROFILES = ("recommended", "vpn", "web", "bot", "game")
TOOLBOX_KEEP_SECONDS = 180
TOOLBOX_TIMEOUT = {"scan": 150, "plan": 200, "apply": 900, "undo": 320, "confirm": 40,
                   "history": 40, "verify": 260}
TOOLBOX_CHUNK = 3000


def button(text, data):
    return {"text": text, "callback_data": data}


def keyboard(rows):
    return {"inline_keyboard": rows}


def chunk(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


class Bot:
    def __init__(self, cfg, state, tg, collector, sleep=time.sleep):
        self.cfg = cfg
        self.state = state
        self.tg = tg
        self.col = collector
        self._sleep = sleep
        self.pending = {}          # user id -> input kind awaiting a text reply
        self._busy = set()
        self._jobs = set()
        self._unauth_logged = {}
        self._stop = threading.Event()
        self.alerts = Alerts(cfg, collector, self._notify_alert)

    @property
    def lang(self):
        return self.cfg.snapshot()["language"]

    def snap(self):
        return self.cfg.snapshot()

    def host(self):
        import socket
        return socket.gethostname()

    def _send(self, chat_id, text, markup=None):
        try:
            return self.tg.send_message(chat_id, text, markup)
        except TelegramError as exc:
            log.warning("send to %s failed: %s", chat_id, exc)
            return None

    def _show(self, chat_id, message_id, text, markup):
        """Edit a panel in place; fall back to a fresh message."""
        try:
            self.tg.edit_message(chat_id, message_id, text, markup)
        except TelegramError as exc:
            if "not modified" in exc.description:
                return
            self._send(chat_id, text, markup)

    def _recipients(self):
        return config.recipients(self.snap())

    def broadcast(self, parts):
        for chat_id in self._recipients():
            for message in pack(parts):
                self._send(chat_id, message)

    def send_report(self, chat_ids=None, only=None, fresh=False):
        """fresh=True is for something a person just asked for: run a new Iran test now."""
        cfg = self.snap()
        lang = cfg["language"]
        data = self.col.collect(cfg, only=only, fresh=fresh)
        if only:
            parts = [render.build_section(only, data, cfg, lang)]
        else:
            parts = render.build_report(data, cfg, lang, self.host())
        for chat_id in chat_ids or self._recipients():
            for message in pack(parts):
                self._send(chat_id, message)

    def _notify_alert(self, kind, key, params):
        lang = self.lang
        title = t(lang, "alert_title" if kind == "alert" else "recovered_title")
        text = "<b>%s - %s</b>\n%s" % (title, render.esc(self.host()),
                                       render.esc(t(lang, key, **params)))
        self.broadcast([text])

    def panel_main(self, uid):
        cfg = self.snap()
        lang = cfg["language"]
        state = t(lang, "on") if cfg["reports_enabled"] else t(lang, "paused")
        alerts = t(lang, "on") if cfg["alerts"]["enabled"] else t(lang, "off")
        text = "%s\n%s\n\n%s\n\n%s" % (
            t(lang, "panel_title", host=render.esc(self.host())),
            t(lang, "panel_status", state=state, alerts=alerts,
              iv=render.minutes_label(cfg["interval_min"], lang)),
            t(lang, "quick_hint"), t(lang, "footer"))
        rows = [[button(t(lang, "btn_report"), "r:full")]]
        quick = [button(t(lang, "sec_" + s), "s:" + s) for s in SECTIONS]
        rows += chunk(quick, 2)
        rows.append([button(t(lang, "btn_sections"), "sec:menu"),
                     button(t(lang, "btn_interval"), "iv:menu")])
        rows.append([button(t(lang, "btn_alerts"), "al:menu"),
                     button(t(lang, "btn_iran"), "ir:menu")])
        row = [button(t(lang, "btn_services"), "sv:menu")]
        if uid == cfg["owner_id"]:
            row.append(button(t(lang, "btn_users"), "us:menu"))
        rows.append(row)
        if uid == cfg["owner_id"]:
            rows.append([button(t(lang, "btn_toolbox"), "tb:menu")])
        rows.append([button(t(lang, "btn_lang"), "lg:menu")])
        return text, keyboard(rows)

    def panel_toolbox(self):
        lang = self.lang
        rows = [[button(t(lang, "tb_scan"), "tb:scan"), button(t(lang, "tb_verify"), "tb:verify")],
                [button(t(lang, "tb_iran"), "tb:iran"), button(t(lang, "tb_history"), "tb:hist")],
                [button(t(lang, "tb_apply"), "tb:profiles")],
                [button(t(lang, "tb_keep"), "tb:keep"), button(t(lang, "tb_undo"), "tb:undo")],
                [button(t(lang, "btn_back"), "m:main")]]
        return t(lang, "tb_title"), keyboard(rows)

    def panel_tb_profiles(self):
        lang = self.lang
        rows = chunk([button(name, "tb:plan:" + name) for name in TOOLBOX_PROFILES], 3)
        rows.append([button(t(lang, "btn_back"), "tb:menu")])
        return t(lang, "tb_profiles_title"), keyboard(rows)

    def panel_sections(self):
        cfg = self.snap()
        lang = cfg["language"]
        toggles = [button(("✅ " if cfg["sections"][s] else "❌ ") + t(lang, "sec_" + s),
                          "sec:t:" + s) for s in SECTIONS]
        rows = chunk(toggles, 2) + [[button(t(lang, "btn_back"), "m:main")]]
        return t(lang, "sections_title"), keyboard(rows)

    def panel_interval(self):
        cfg = self.snap()
        lang = cfg["language"]
        current = cfg["interval_min"]
        presets = [button(("✅ " if m == current else "") + render.minutes_label(m, lang),
                          "iv:set:%d" % m) for m in INTERVAL_PRESETS]
        rows = chunk(presets, 4)
        rows.append([button(t(lang, "btn_custom"), "iv:custom")])
        rows.append([button(t(lang, "btn_resume") if not cfg["reports_enabled"]
                            else t(lang, "btn_pause"), "iv:toggle")])
        rows.append([button(t(lang, "btn_back"), "m:main")])
        text = t(lang, "interval_title", iv=render.minutes_label(current, lang),
                 min=MIN_INTERVAL, max=MAX_INTERVAL)
        if not cfg["reports_enabled"]:
            text += "\n⏸ " + t(lang, "reports_paused")
        return text, keyboard(rows)

    def panel_alerts(self):
        cfg = self.snap()
        lang = cfg["language"]
        al = cfg["alerts"]
        text = t(lang, "alerts_title",
                 state=t(lang, "on") if al["enabled"] else t(lang, "off"),
                 cpu=al["cpu"], mem=al["mem"], disk=al["disk"])
        mark = lambda on: "✅ " if on else "❌ "
        rows = [[button(mark(al["enabled"]) + t(lang, "btn_alerts"), "al:toggle")]]
        for key, label in (("cpu", t(lang, "cpu")), ("mem", t(lang, "ram")),
                           ("disk", t(lang, "sec_disk"))):
            rows.append([button("-5", "al:%s:-5" % key),
                         button("%s %d%%" % (label, al[key]), "al:noop"),
                         button("+5", "al:%s:5" % key)])
        rows.append([button(mark(al["services"]) + t(lang, "alert_services"), "al:services"),
                     button(mark(al["iran"]) + t(lang, "alert_iran"), "al:iran")])
        rows.append([button(t(lang, "btn_back"), "m:main")])
        return text, keyboard(rows)

    def panel_users(self):
        cfg = self.snap()
        lang = cfg["language"]
        text = t(lang, "users_title", owner=cfg["owner_id"])
        rows = []
        if cfg["users"]:
            text += "\n" + "\n".join("• <code>%d</code>" % u for u in cfg["users"])
            rows += chunk([button("🗑 %d" % u, "us:del:%d" % u) for u in cfg["users"]], 2)
        else:
            text += "\n" + t(lang, "users_none")
        rows.append([button(t(lang, "btn_add"), "us:add")])
        rows.append([button(t(lang, "btn_back"), "m:main")])
        return text, keyboard(rows)

    def panel_services(self):
        cfg = self.snap()
        lang = cfg["language"]
        text = t(lang, "svc_title")
        rows = []
        if cfg["services"]:
            text += "\n" + "\n".join("• <code>%s</code>" % render.esc(s) for s in cfg["services"])
            rows += chunk([button("🗑 " + s, "sv:del:%d" % i)
                           for i, s in enumerate(cfg["services"])], 2)
        rows.append([button(t(lang, "btn_add"), "sv:add")])
        rows.append([button(t(lang, "btn_back"), "m:main")])
        return text, keyboard(rows)

    def panel_iran(self):
        cfg = self.snap()
        lang = cfg["language"]
        iran = cfg["iran"]
        target = iran["target"] or t(lang, "iran_target_auto")
        ports = ", ".join(str(p) for p in iran["tcp_ports"]) or t(lang, "none")
        text = t(lang, "iran_title", target=render.esc(target), ports=ports)
        rows = [[button(t(lang, "btn_iran_now"), "ir:now")],
                [button(t(lang, "btn_iran_target"), "ir:target"),
                 button(t(lang, "btn_iran_ports"), "ir:ports")],
                [button(t(lang, "btn_iran_auto"), "ir:auto")],
                [button(t(lang, "btn_back"), "m:main")]]
        return text, keyboard(rows)

    def panel_lang(self):
        lang = self.lang
        rows = [[button("🇮🇷 فارسی", "lg:set:fa"), button("🇬🇧 English", "lg:set:en")],
                [button(t(lang, "btn_back"), "m:main")]]
        return t(lang, "lang_title"), keyboard(rows)

    def _panel(self, name, uid):
        if name == "main":
            return self.panel_main(uid)
        return {"sections": self.panel_sections, "interval": self.panel_interval,
                "alerts": self.panel_alerts, "users": self.panel_users,
                "services": self.panel_services, "iran": self.panel_iran,
                "lang": self.panel_lang, "toolbox": self.panel_toolbox,
                "tbprofiles": self.panel_tb_profiles}[name]()

    def set_interval(self, minutes):
        def apply(d):
            d["interval_min"] = int(minutes)
            d["reports_enabled"] = True
        self.cfg.update(apply)
        self.state.update(lambda d: d.__setitem__("last_report_ts", time.time()))

    def _unit_exists(self, name):
        code, out = collectors.run(["systemctl", "show", "-p", "LoadState",
                                    "--value", name], timeout=5)
        return code is None or out.strip() not in ("not-found", "")

    def handle_input(self, uid, chat_id, kind, text):
        """Process the free-text answer to a prompt. Returns the panel to show."""
        lang = self.lang
        text = text.strip()
        if kind == "interval":
            if not text.isdigit() or not config.valid_interval(text):
                self._send(chat_id, t(lang, "interval_bad", min=MIN_INTERVAL, max=MAX_INTERVAL))
                self.pending[uid] = kind
                return None
            self.set_interval(int(text))
            self._send(chat_id, t(lang, "interval_set",
                                  iv=render.minutes_label(int(text), lang)))
            return "interval"
        if kind == "add_user":
            if uid != self.snap()["owner_id"]:
                self._send(chat_id, t(lang, "owner_only"))
                return None
            if not text.isdigit() or int(text) <= 0:
                self._send(chat_id, t(lang, "users_bad"))
                self.pending[uid] = kind
                return None
            new = int(text)
            self.cfg.update(lambda d: d["users"].append(new)
                            if new != d["owner_id"] and new not in d["users"] else None)
            self._send(chat_id, t(lang, "users_added", uid=new))
            return "users"
        if kind == "add_service":
            if not SERVICE_RE.match(text) or not self._unit_exists(text):
                self._send(chat_id, t(lang, "svc_bad"))
                self.pending[uid] = kind
                return None
            self.cfg.update(lambda d: d["services"].append(text)
                            if text not in d["services"] else None)
            self._send(chat_id, t(lang, "svc_added", name=render.esc(text)))
            return "services"
        if kind == "iran_target":
            if not HOST_RE.match(text):
                self._send(chat_id, t(lang, "iran_bad"))
                self.pending[uid] = kind
                return None
            self.cfg.update(lambda d: d["iran"].__setitem__("target", text))
            self._send(chat_id, t(lang, "iran_saved"))
            return "iran"
        if kind == "iran_ports":
            ports = []
            if text != "-":
                for item in text.replace("،", ",").split(","):
                    item = item.strip()
                    if not item.isdigit() or not 1 <= int(item) <= 65535:
                        self._send(chat_id, t(lang, "iran_bad"))
                        self.pending[uid] = kind
                        return None
                    ports.append(int(item))
            self.cfg.update(lambda d: d["iran"].__setitem__("tcp_ports", ports[:3]))
            self._send(chat_id, t(lang, "iran_saved"))
            return "iran"
        return None

    def authorized(self, uid):
        return config.is_authorized(self.snap(), uid)

    def _note_unauthorized(self, uid):
        last = self._unauth_logged.get(uid, 0)
        if time.time() - last > 3600:
            self._unauth_logged[uid] = time.time()
            log.info("ignored message from unauthorised user %s", uid)

    def on_message(self, msg):
        chat, sender = msg.get("chat") or {}, msg.get("from") or {}
        uid = sender.get("id")
        if chat.get("type") != "private" or chat.get("id") != uid:
            return
        if not self.authorized(uid):
            self._note_unauthorized(uid)
            return
        text = (msg.get("text") or "").strip()
        lang = self.lang
        word = text.split()[0].split("@")[0].lower() if text else ""
        if word in START_COMMANDS:
            self.pending.pop(uid, None)
            body, markup = self.panel_main(uid)
            self._send(uid, body, markup)
        elif word == "/report":
            self.pending.pop(uid, None)
            self._async(uid, lambda: self.send_report([uid], fresh=True))
        elif word == "/help":
            self._send(uid, t(lang, "help"))
        elif word == "/cancel":
            self.pending.pop(uid, None)
            self._send(uid, t(lang, "cancelled"))
        elif uid in self.pending and text and not text.startswith("/"):
            panel = self.handle_input(uid, uid, self.pending.pop(uid), text)
            if panel:
                body, markup = self._panel(panel, uid)
                self._send(uid, body, markup)

    def _spawn(self, fn):
        """Start fn on a background thread (tests replace this to run inline)."""
        threading.Thread(target=fn, daemon=True).start()

    def _async(self, uid, fn):
        """Run slow work (data collection) off the polling thread, once per user."""
        if uid in self._busy:
            return False
        self._busy.add(uid)

        def runner():
            try:
                fn()
            except Exception:
                log.exception("background job failed")
            finally:
                self._busy.discard(uid)
        self._spawn(runner)
        return True

    def _run_once(self, name, fn):
        """Run a scheduled job in the background unless the last run is still going."""
        if name in self._jobs:
            return
        self._jobs.add(name)

        def runner():
            try:
                fn()
            except Exception:
                log.exception("%s job failed", name)
            finally:
                self._jobs.discard(name)
        self._spawn(runner)

    def _answer(self, cq_id, text=None):
        try:
            self.tg.answer_callback(cq_id, text)
        except TelegramError:
            pass

    def on_callback(self, cq):
        sender = cq.get("from") or {}
        uid = sender.get("id")
        msg = cq.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        message_id = msg.get("message_id")
        if not self.authorized(uid) or chat_id != uid:
            self._answer(cq.get("id"))
            return
        lang = self.lang
        data = cq.get("data") or ""
        owner = uid == self.snap()["owner_id"]
        self.pending.pop(uid, None)

        def show(name):
            body, markup = self._panel(name, uid)
            self._show(chat_id, message_id, body, markup)

        if data == "m:main":
            self._answer(cq["id"])
            show("main")
        elif data == "r:full" or data == "ir:now" or (
                data.startswith("s:") and data[2:] in SECTIONS):
            only = None
            if data.startswith("s:"):
                only = data[2:]
            elif data == "ir:now":
                only = "iran"
            if self._async(uid, lambda: self.send_report([uid], only=only, fresh=True)):
                self._answer(cq["id"], t(lang, "collecting"))
            else:
                self._answer(cq["id"], t(lang, "rate_limited"))
        elif data == "sec:menu":
            self._answer(cq["id"])
            show("sections")
        elif data.startswith("sec:t:") and data[6:] in SECTIONS:
            name = data[6:]
            self.cfg.update(lambda d: d["sections"].__setitem__(name, not d["sections"][name]))
            self._answer(cq["id"])
            show("sections")
        elif data == "iv:menu":
            self._answer(cq["id"])
            show("interval")
        elif data.startswith("iv:set:"):
            minutes = data[7:]
            if minutes.isdigit() and config.valid_interval(minutes):
                self.set_interval(int(minutes))
            self._answer(cq["id"], t(lang, "done"))
            show("interval")
        elif data == "iv:custom":
            self.pending[uid] = "interval"
            self._answer(cq["id"])
            self._send(uid, t(lang, "interval_ask", min=MIN_INTERVAL, max=MAX_INTERVAL))
        elif data == "iv:toggle":
            self.cfg.update(lambda d: d.__setitem__("reports_enabled", not d["reports_enabled"]))
            self.state.update(lambda d: d.__setitem__("last_report_ts", time.time()))
            self._answer(cq["id"])
            show("interval")
        elif data == "al:menu":
            self._answer(cq["id"])
            show("alerts")
        elif data.startswith("al:"):
            self._on_alert_button(cq, data[3:], show)
        elif data == "us:menu":
            self._answer(cq["id"], None if owner else t(lang, "owner_only"))
            if owner:
                show("users")
        elif data == "us:add" and owner:
            self.pending[uid] = "add_user"
            self._answer(cq["id"])
            self._send(uid, t(lang, "users_ask"))
        elif data.startswith("us:del:") and owner and data[7:].isdigit():
            target = int(data[7:])
            self.cfg.update(lambda d: d["users"].remove(target) if target in d["users"] else None)
            self._answer(cq["id"], t(lang, "users_removed", uid=target))
            show("users")
        elif data == "sv:menu":
            self._answer(cq["id"])
            show("services")
        elif data == "sv:add":
            self.pending[uid] = "add_service"
            self._answer(cq["id"])
            self._send(uid, t(lang, "svc_ask"))
        elif data.startswith("sv:del:") and data[7:].isdigit():
            index = int(data[7:])
            self.cfg.update(lambda d: d["services"].pop(index) if index < len(d["services"]) else None)
            self._answer(cq["id"], t(lang, "done"))
            show("services")
        elif data == "ir:menu":
            self._answer(cq["id"])
            show("iran")
        elif data == "ir:target":
            self.pending[uid] = "iran_target"
            self._answer(cq["id"])
            self._send(uid, t(lang, "iran_target_ask"))
        elif data == "ir:ports":
            self.pending[uid] = "iran_ports"
            self._answer(cq["id"])
            self._send(uid, t(lang, "iran_ports_ask"))
        elif data == "ir:auto":
            self.cfg.update(lambda d: d["iran"].__setitem__("target", ""))
            self._answer(cq["id"], t(lang, "iran_saved"))
            show("iran")
        elif data == "lg:menu":
            self._answer(cq["id"])
            show("lang")
        elif data.startswith("lg:set:") and data[7:] in LANGUAGES:
            code = data[7:]
            self.cfg.update(lambda d: d.__setitem__("language", code))
            self._answer(cq["id"], t(code, "lang_set"))
            show("main")
        elif data.startswith("tb:"):
            self._on_toolbox(cq, data, uid, owner, show)
        else:
            self._answer(cq["id"])

    def _on_toolbox(self, cq, data, uid, owner, show):
        """The PrivateToolBox button. Owner only. Without PrivateToolBox it offers to set it up."""
        lang = self.lang
        if not owner:
            self._answer(cq["id"], t(lang, "owner_only"))
            return
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        arg = parts[2] if len(parts) > 2 else ""
        if not toolbox.available():
            if action in ("menu", "install", "enable"):
                self._toolbox_setup(cq, uid, action, arg)
            else:
                self._answer(cq["id"], t(lang, "tb_unavailable"))
            return
        simple = {"scan": {"cmd": "scan"}, "verify": {"cmd": "verify"},
                  "iran": {"cmd": "verify", "iran": True}, "hist": {"cmd": "history"},
                  "keep": {"cmd": "confirm"}}
        if action == "menu":
            self._answer(cq["id"])
            show("toolbox")
        elif action == "profiles":
            self._answer(cq["id"])
            show("tbprofiles")
        elif action in simple:
            self._toolbox_start(cq, uid, dict(simple[action]))
        elif action == "plan" and arg in TOOLBOX_PROFILES:
            self._toolbox_start(cq, uid, {"cmd": "plan", "profile": arg})
        elif action == "do" and arg in TOOLBOX_PROFILES:
            self._toolbox_start(cq, uid, {"cmd": "apply", "profile": arg,
                                          "rollback": TOOLBOX_KEEP_SECONDS})
        elif action == "undo" and arg == "yes":
            self._toolbox_start(cq, uid, {"cmd": "undo"})
        elif action == "undo":
            self._answer(cq["id"])
            self._send(uid, t(lang, "tb_undo_ask"), keyboard([[
                button(t(lang, "tb_undo_yes"), "tb:undo:yes"),
                button(t(lang, "tb_cancel"), "tb:menu")]]))
        else:
            self._answer(cq["id"])

    def _toolbox_setup(self, cq, uid, action, arg):
        """PrivateToolBox is missing or not connected: explain, and offer to fix it if allowed."""
        lang = self.lang
        can_install = toolbox.helper_available()
        have_program = toolbox.installed()
        self._answer(cq["id"])
        if action == "menu":
            if have_program:
                text, button_data, label = (t(lang, "tb_installed_no_bridge"), "tb:enable", "tb_enable_btn")
                manual = t(lang, "tb_manual_enable")
            else:
                text, button_data, label = (t(lang, "tb_not_installed"), "tb:install", "tb_install_btn")
                manual = t(lang, "tb_manual_install")
            if can_install:
                self._send(uid, text, keyboard([[button(t(lang, label), button_data),
                                                 button(t(lang, "tb_cancel"), "m:main")]]))
            else:
                self._send(uid, text + "\n\n" + manual)
        elif not can_install:
            self._send(uid, t(lang, "tb_manual_install" if not have_program else "tb_manual_enable"))
        elif action == "install" and arg != "yes":
            self._send(uid, t(lang, "tb_install_ask", ref=helper.TOOLBOX_REF), keyboard([[
                button(t(lang, "tb_install_yes"), "tb:install:yes"),
                button(t(lang, "tb_cancel"), "m:main")]]))
        elif action in ("install", "enable"):
            cmd = "install_toolbox" if action == "install" else "enable_bridge"
            self._async(uid, lambda: self._toolbox_setup_job(uid, cmd))

    def _toolbox_setup_job(self, uid, cmd):
        """Run the root helper. The bot restarts itself near the end, so the result
        may only be reported after the restart (see _toolbox_followup)."""
        lang = self.lang
        self.state.update(lambda d: d.__setitem__("toolbox_pending", time.time()))
        self._send(uid, t(lang, "tb_installing"))
        reply = toolbox.helper_call(cmd, timeout=900)
        self.state.update(lambda d: d.__setitem__("toolbox_pending", 0.0))
        if reply.get("error") == "busy":
            self._send(uid, t(lang, "tb_busy"))
            return
        output = (reply.get("output") or reply.get("error") or "").strip()
        for part in self._toolbox_chunks(output):
            self._send(uid, "<pre>%s</pre>" % render.esc(part))
        self._send(uid, t(lang, "tb_ready" if reply.get("ok") else "tb_not_ready"))

    def _toolbox_followup(self, owner):
        """After a restart caused by installing PrivateToolBox, tell the owner how it went."""
        if not self.state.snapshot().get("toolbox_pending"):
            return
        self.state.update(lambda d: d.__setitem__("toolbox_pending", 0.0))
        key = "tb_ready" if toolbox.available() else "tb_not_ready"
        self._send(owner, t(self.lang, key))

    def _toolbox_start(self, cq, uid, request):
        lang = self.lang
        request["lang"] = lang
        if self._async(uid, lambda: self._toolbox_job(uid, request)):
            self._answer(cq["id"], t(lang, "tb_working"))
        else:
            self._answer(cq["id"], t(lang, "rate_limited"))

    @staticmethod
    def _toolbox_chunks(text, size=TOOLBOX_CHUNK):
        chunks, current = [], ""
        for line in text.splitlines():
            while len(line) > size:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(line[:size])
                line = line[size:]
            if current and len(current) + len(line) + 1 > size:
                chunks.append(current)
                current = ""
            current = (current + "\n" + line) if current else line
        if current:
            chunks.append(current)
        return chunks

    def _toolbox_job(self, uid, request):
        """Run one request on the agent and show the result (runs off the polling thread)."""
        lang = request["lang"]
        cmd = request["cmd"]
        reply = toolbox.call(request, timeout=TOOLBOX_TIMEOUT.get(cmd, 300))
        if reply.get("error") == "busy":
            self._send(uid, t(lang, "tb_busy"))
            return
        output = (reply.get("output") or reply.get("error") or "").strip()
        for part in self._toolbox_chunks(output) or [t(lang, "tb_empty")]:
            self._send(uid, "<pre>%s</pre>" % render.esc(part))
        if not reply.get("ok"):
            self._send(uid, t(lang, "tb_failed", code=reply.get("code", "?")))
            return
        if cmd == "plan":
            self._send(uid, t(lang, "tb_apply_ask", profile=render.esc(request["profile"]),
                              seconds=TOOLBOX_KEEP_SECONDS), keyboard([[
                button(t(lang, "tb_apply_btn"), "tb:do:" + request["profile"]),
                button(t(lang, "tb_cancel"), "tb:menu")]]))
        elif cmd == "apply" and reply.get("pending"):
            self._send(uid, t(lang, "tb_pending", seconds=TOOLBOX_KEEP_SECONDS), keyboard([[
                button(t(lang, "tb_keep_btn"), "tb:keep"),
                button(t(lang, "tb_undo_btn"), "tb:undo:yes")]]))

    def _on_alert_button(self, cq, action, show):
        lang = self.lang
        if action == "toggle":
            self.cfg.update(lambda d: d["alerts"].__setitem__("enabled", not d["alerts"]["enabled"]))
        elif action in ("services", "iran"):
            self.cfg.update(lambda d: d["alerts"].__setitem__(action, not d["alerts"][action]))
        elif action != "noop":
            key, _, step = action.partition(":")
            if key in ("cpu", "mem", "disk") and step.lstrip("-").isdigit():
                self.cfg.update(lambda d: d["alerts"].__setitem__(
                    key, max(50, min(99, d["alerts"][key] + int(step)))))
        self._answer(cq["id"])
        show("alerts")

    def handle_update(self, update):
        if "message" in update:
            self.on_message(update["message"])
        elif "callback_query" in update:
            self.on_callback(update["callback_query"])

    def scheduler_tick(self, now=None):
        now = time.time() if now is None else now
        cfg = self.snap()
        if cfg["reports_enabled"]:
            last = self.state.snapshot().get("last_report_ts", 0.0)
            if not last:
                self.state.update(lambda d: d.__setitem__("last_report_ts", now))
            elif now >= last + cfg["interval_min"] * 60:
                self.state.update(lambda d: d.__setitem__("last_report_ts", now))
                self._run_once("report", self.send_report)

    def scheduler_loop(self):
        next_alert = 0.0
        while not self._stop.is_set():
            try:
                now = time.time()
                self.scheduler_tick(now)
                if now >= next_alert:
                    next_alert = now + 60
                    self._run_once("alerts", lambda: self.alerts.tick(now))
            except Exception:
                log.exception("scheduler error")
            self._stop.wait(5)

    def startup(self):
        """Wait until Telegram accepts the token, then announce ourselves."""
        delay = 5
        while True:
            try:
                me = self.tg.get_me()
                log.info("connected as @%s", me.get("username"))
                break
            except TelegramError as exc:
                log.error("cannot reach Telegram (%s); retrying in %ds", exc, delay)
                self._sleep(delay)
                delay = min(60, delay * 2)
        try:
            self.tg.delete_webhook()
        except TelegramError:
            pass
        lang = self.lang
        commands = [{"command": "start", "description": t(lang, "cmd_start")},
                    {"command": "report", "description": t(lang, "cmd_report")},
                    {"command": "help", "description": t(lang, "cmd_help")}]
        try:
            self.tg.call("setMyCommands", {"commands": commands})
        except TelegramError:
            pass
        owner = self.snap()["owner_id"]
        self._send(owner, t(lang, "started", host=render.esc(self.host()),
                            footer=t(lang, "footer")))
        self._toolbox_followup(owner)

    def run(self):
        self.startup()
        threading.Thread(target=self.scheduler_loop, daemon=True).start()
        offset, delay = 0, 2
        while not self._stop.is_set():
            try:
                updates = self.tg.get_updates(offset)
                delay = 2
            except TelegramError as exc:
                if exc.code == 429:
                    self._sleep(exc.retry_after or 5)
                else:
                    log.error("polling failed (%s); retrying in %ds", exc, delay)
                    self._sleep(delay)
                    delay = min(60, delay * 2)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    self.handle_update(update)
                except Exception:
                    log.exception("error while handling an update")

    def stop(self):
        self._stop.set()
