# Changelog

## 0.1.0

First release.

- One command installer: checks and installs prerequisites, verifies the bot token and your ID with
  Telegram, runs the bot as a sandboxed systemd service, adds a `privatechecker` command
- Private bot: the owner plus users the owner adds, nobody else gets a reply
- Scheduled reports every 5 to 1200 minutes (default 30), one tap quick views, pause and resume
- Choose report sections, watch systemd services, Persian and English
- Alerts for CPU, RAM, disk, services and Iran reachability, with recovery messages
- Ping and TCP checks from Iranian probes through check-host.net
- Report sections: system, memory, disks, network, top processes, services, Docker, listening ports,
  SSH security, pending updates, Iran reachability
