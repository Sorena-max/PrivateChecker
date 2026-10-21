# Changelog

## 0.1.0

First release.

- One command installer: checks and installs prerequisites, verifies the bot token and your ID with
  Telegram, runs the bot as a sandboxed systemd service, adds a `privatechecker` command
- Private bot: the owner plus users the owner adds, nobody else gets a reply
- Scheduled reports every 5 to 1200 minutes (default 30), one tap quick views, pause and resume
- Choose report sections, watch systemd services, Persian and English
- Alerts for CPU, RAM, disk, services and Iran reachability, with recovery messages
- Ping and TCP checks from Iranian probes through check-host.net. Asking by hand always runs a fresh test,
  and a half-finished test is never shown again
- Report sections: system, memory, disks, network, top processes, services, Docker, listening ports,
  SSH security, pending updates, Iran reachability
- 🧰 PrivateToolBox button for the owner: scan, verify (with Iran), history, preview and apply a profile, keep or
  undo changes. Applying from the bot waits for a Keep tap and undoes itself if you do not tap it
- If PrivateToolBox is missing the button offers to install it, through an optional root helper that is off by
  default (`sudo privatechecker enable-install`). It can only download the pinned PrivateToolBox release over HTTPS,
  install it and connect it, and takes no arguments from the bot