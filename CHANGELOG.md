# Changelog

## 0.3.0

- The 🧰 PrivateToolBox button is always shown to the owner. If PrivateToolBox is not installed, it offers to
  install it; if it is installed but not connected, it offers to connect it
- Optional root helper for that (`sudo privatechecker enable-install`, off by default): it can only download the
  pinned PrivateToolBox release over HTTPS, install it and connect it, and takes no arguments from the bot.
  Turn it off with `sudo privatechecker disable-install`
- After the bot restarts during the install, the owner is told whether it worked

## 0.2.0

- New 🧰 PrivateToolBox button in the panel for the owner, when
  [PrivateToolBox](https://github.com/Sorena-max/PrivateToolBox) is installed and its bridge is enabled
  (`sudo privatetoolbox integrate`): scan, verify (with Iran), history, preview and apply a profile,
  keep or undo changes
- Applying from the bot always waits for a Keep tap and undoes itself if you do not
- Viewers added by the owner never see or use the button

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
