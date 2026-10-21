# PrivateChecker

A private Telegram watchdog for your Linux server. One command installs a bot that sends you
the server's health on a schedule you choose, warns you when something breaks, and tells you
whether the server can be reached from inside Iran.

[فارسی](README.fa.md) | [Quick guide](GUIDE.md) | [راهنمای سریع](GUIDE.fa.md)

- Full reports every 5 to 1200 minutes (default 30), or on demand with one tap
- Alerts for high CPU, RAM and disk, failed services and Iran outages, with a message when things recover
- Ping and TCP checks from Iranian probes, through [check-host.net](https://check-host.net)
- You choose which sections the report contains, from buttons inside the bot
- The bot only answers you (and people you add). Everyone else gets no reply at all
- No dependencies: Python standard library and one systemd service

One install means one server, one bot and one owner. There is no central service. Data only goes to
Telegram (your own bot) and, for the Iran check, to check-host.net.

## Install

You need a Linux server with systemd (Debian, Ubuntu, Fedora, CentOS, Rocky, Alma, openSUSE or Arch) and root access.

1. In Telegram open [@BotFather](https://t.me/BotFather), send `/newbot` and copy the token.
2. Get your numeric ID from [@userinfobot](https://t.me/userinfobot).
3. Open your new bot and press Start. A bot cannot message you before you do.
4. Run this on the server:

```bash
curl -fsSL https://raw.githubusercontent.com/Sorena-max/PrivateChecker/main/install.sh | sudo bash
```

The installer asks for the token and your ID and checks both with Telegram. It installs missing
prerequisites (`python3`, `curl`, `tar`) and starts the service. Then send `/start` to your bot.

Without questions, for scripts:

```bash
curl -fsSL https://raw.githubusercontent.com/Sorena-max/PrivateChecker/main/install.sh \
  | sudo bash -s -- --token 123456789:ABC... --admin 123456789 --lang en --non-interactive
```

Want to read it first? Download `install.sh`, read it, then run `sudo bash install.sh`.
To install a fixed release instead of `main`, add `--ref v0.1.0`.

## Using the bot

`/start` opens the panel.

| Button | What it does |
|---|---|
| Full report now | Everything that is enabled, immediately |
| System, Memory, Disk, Network ... | Just that section, right now |
| Report sections | Choose what the scheduled report contains |
| Report interval | Presets from 5 minutes to 12 hours, a custom value (5 to 1200), or pause |
| Alerts | On/off and the CPU, RAM and disk thresholds |
| Iran check | Target (default: the server's public IP), extra TCP ports, check now |
| Watched services | systemd units that are reported and alerted on, such as `nginx` or `x-ui` |
| Users (owner only) | Add or remove people who may use this bot |
| Language | Persian or English |
| 🧰 PrivateToolBox (owner only) | Harden and tune the server from the bot, if [PrivateToolBox](https://github.com/Sorena-max/PrivateToolBox) is installed. Enable it with `sudo privatetoolbox integrate` |

Commands: `/start`, `/report`, `/help`, `/cancel`.

A report covers system (OS, uptime, load, CPU), memory and swap, disks and inodes, network (traffic, speed,
public IP, connections), top processes, failed and watched services, Docker containers, listening ports,
SSH security (failed and successful logins, top attacking IPs, open sessions), pending updates and the
Iran check. The first lines tell you at a glance whether all is well, with warnings or problems.

Alerts are checked every minute. A problem must last a few checks before you hear about it (CPU 3 minutes,
RAM and services 2, disk at once), you are reminded at most once an hour, and you get a message when it clears.
The Iran check runs every 15 minutes.

## From the server

```bash
privatechecker status      # service status
privatechecker logs -f     # follow the logs
privatechecker report      # print a full report in the terminal
privatechecker doctor      # diagnose the installation
privatechecker update      # upgrade, keeping your settings
privatechecker uninstall   # remove it (--purge also deletes settings)
```

## Security

- Only the owner ID and the users the owner adds can use the bot. Messages from anyone else are ignored.
  Only private chats are handled, never groups.
- The token lives in `/var/lib/privatechecker/config.json` (mode 0600, owned by the service user). It is never
  logged and is stripped from error messages.
- The service runs as its own `privatechecker` user (no login, no home) with systemd sandboxing:
  `ProtectSystem=strict`, `ProtectHome`, `NoNewPrivileges`, `PrivateTmp` and a memory cap. The code in
  `/opt/privatechecker` belongs to root, so the service cannot change it.
- It only reads the state of the server and never runs commands that come from chat messages.
- For the SSH section the service user can read the journal and auth log (groups `systemd-journal` and `adm`).
  Docker access is off unless you install with `--with-docker`. The docker group is effectively root,
  so enable it only if you accept that.
- If a token leaks, send `/revoke` to @BotFather, run `sudo privatechecker uninstall` and install again with the new token.

## About the Iran check

Results come from the Iranian probes of [check-host.net](https://check-host.net) (Tehran, Isfahan, Shiraz and others).
Only the server's public IP (or the target you set) and the port list are sent to them.
check-host.net limits how often a check can be started from one IP. PrivateChecker retries politely and waits
10 minutes when asked to, so a report can sometimes say the check was rate limited. This is not an official
integration, and check-host.net may change or restrict its API.

## Troubleshooting

| Problem | Fix |
|---|---|
| The bot does not answer | Run `privatechecker doctor`, then `privatechecker logs`. Is your ID the owner ID? Did you press Start? |
| Installer says it could not message the ID | Open the bot, press Start, and try again |
| "SSH logs are not readable" | Your distribution logs elsewhere. Run `privatechecker doctor` and open an issue with the output |
| Docker shows "not accessible" | Update with `--with-docker` |
| Telegram is blocked on the server | Set `HTTPS_PROXY` (`systemctl edit privatechecker`) or `api_base` in `config.json` |

## Development

```bash
python3 -m unittest discover -s tests -t .
PRIVATECHECKER_HOME=/tmp/pc python3 -m privatechecker doctor
```

CI runs the tests on Python 3.8 to 3.13 and installs the real service on Ubuntu.

## License

[MIT](LICENSE). This project is free. Selling it or charging money for it is prohibited.
GitHub: [Sorena-max](https://github.com/Sorena-max)
