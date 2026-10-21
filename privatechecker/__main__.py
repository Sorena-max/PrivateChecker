"""Command line entry point: python3 -m privatechecker <command>."""

import argparse
import logging
import os
import shutil
import signal
import socket
import sys

from . import __version__, collectors, config, render
from .bot import Bot
from .checkhost import CheckHostError, IranChecker, fetch_nodes
from .config import SECTIONS, TOKEN_RE
from .telegram_api import Telegram, TelegramError


def load_ready_config():
    cfg = config.open_config()
    data = cfg.snapshot()
    if not TOKEN_RE.match(data["token"]) or data["owner_id"] <= 0:
        sys.exit("privatechecker: not configured (missing bot token or owner id). "
                 "Run the installer again.")
    return cfg


def cmd_run(_args):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s",
                        stream=sys.stdout)
    cfg = load_ready_config()
    data = cfg.snapshot()
    bot = Bot(cfg, config.open_state(), Telegram(data["token"], data["api_base"]),
              collectors.Collector(IranChecker()))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    logging.getLogger("privatechecker").info("PrivateChecker %s starting", __version__)
    try:
        bot.run()
    except KeyboardInterrupt:
        pass


def cmd_helper(_args):
    """The root helper behind `privatechecker enable-install` (see helper.py)."""
    from . import helper
    helper.serve()


def cmd_init(_args):
    token = os.environ.get("SC_TOKEN", "").strip()
    owner = os.environ.get("SC_OWNER", "").strip()
    lang = os.environ.get("SC_LANG", "").strip() or None
    if not TOKEN_RE.match(token):
        sys.exit("privatechecker init: SC_TOKEN is not a valid bot token")
    if not owner.isdigit() or int(owner) <= 0:
        sys.exit("privatechecker init: SC_OWNER must be a numeric Telegram id")
    if lang and lang not in config.LANGUAGES:
        sys.exit("privatechecker init: SC_LANG must be one of %s" % ", ".join(config.LANGUAGES))
    cfg = config.open_config()

    def apply(d):
        d["token"], d["owner_id"] = token, int(owner)
        if lang:
            d["language"] = lang
        if int(owner) in d["users"]:
            d["users"].remove(int(owner))
    cfg.update(apply)
    print("configuration written to %s" % cfg.path)


def cmd_report(args):
    cfg = load_ready_config()
    data = cfg.snapshot()
    collector = collectors.Collector(IranChecker())
    if args.only and args.only not in SECTIONS:
        sys.exit("unknown section; choose from: %s" % ", ".join(SECTIONS))
    collected = collector.collect(data, only=args.only)
    if args.only:
        parts = [render.build_section(args.only, collected, data, data["language"])]
    else:
        parts = render.build_report(collected, data, data["language"],
                                    socket.gethostname())
    print(render.strip_html("\n\n".join(parts)))


def cmd_doctor(_args):
    ok_all = True

    def line(ok, text):
        nonlocal ok_all
        ok_all = ok_all and ok
        print(("[ ok ] " if ok else "[FAIL] ") + text)

    line(sys.version_info >= (3, 8), "Python %s (3.8+ required)" % sys.version.split()[0])
    cfg = config.open_config()
    data = cfg.snapshot()
    line(bool(TOKEN_RE.match(data["token"])), "bot token is configured")
    line(data["owner_id"] > 0, "owner id is configured (%s)" % data["owner_id"])
    if TOKEN_RE.match(data["token"]):
        tg = Telegram(data["token"], data["api_base"])
        try:
            me = tg.get_me()
            line(True, "Telegram API reachable, bot is @%s" % me.get("username"))
        except TelegramError as exc:
            line(False, "Telegram API: %s" % exc)
    try:
        nodes = fetch_nodes()
        line(bool(nodes), "check-host.net reachable, %d Iranian probes" % len(nodes))
    except CheckHostError as exc:
        line(False, "check-host.net: %s" % exc)
    line(bool(shutil.which("systemctl")), "systemctl available")
    line(collectors.read_file("/proc/meminfo") is not None, "/proc readable")
    sec = collectors.Collector().security()
    line(bool(sec.get("available")), "SSH logs readable (optional)")
    dock = collectors.Collector().docker()
    line(bool(dock.get("available")), "Docker accessible (optional)")
    sys.exit(0 if ok_all else 1)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="privatechecker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run the bot (used by systemd)")
    sub.add_parser("init", help="write token/owner from SC_TOKEN/SC_OWNER/SC_LANG")
    rep = sub.add_parser("report", help="print a report to the terminal")
    rep.add_argument("--only", help="a single section: %s" % ", ".join(SECTIONS))
    sub.add_parser("doctor", help="diagnose the installation")
    sub.add_parser("helper", help=argparse.SUPPRESS)
    sub.add_parser("version", help="print the version")
    args = parser.parse_args(argv)
    if args.command == "version":
        print(__version__)
        return
    {"run": cmd_run, "init": cmd_init, "report": cmd_report,
     "doctor": cmd_doctor, "helper": cmd_helper}[args.command](args)


if __name__ == "__main__":
    main()
