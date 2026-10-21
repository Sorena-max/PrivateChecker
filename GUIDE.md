# 🛡 PrivateChecker: quick guide

[فارسی 🇮🇷](GUIDE.fa.md) | [Full README](README.md)

Your server talks to you on Telegram. This takes about 3 minutes.

## 🚀 Setup in 4 steps

**1️⃣ Make a bot 🤖**
Open [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name, and copy the **token**
(it looks like `123456789:ABC...`).

**2️⃣ Get your ID 🆔**
Send any message to [@userinfobot](https://t.me/userinfobot). Copy the number it shows. That is your **ID**.

**3️⃣ Press Start ▶️**
Open your new bot and press **Start**. (A bot cannot write to you until you do.)

**4️⃣ Install on the server 💻**
Log in to your server as root (or use `sudo`) and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/Sorena-max/PrivateChecker/main/install.sh | sudo bash
```

The screen will ask you for:
- 🌐 the bot language (Persian is the default)
- 🔑 your token: you will see a green ✔ when it is accepted, or a red ✖ if it is wrong
- 🆔 your ID: you will get a test message in Telegram, and a green ✔ here

When it says **installed and running**, open your bot and send `/start`. 🎉

## 🎛 The panel

`/start` shows buttons:

| Tap | You get |
|---|---|
| 📊 Full report now | everything, right now |
| 💻 🧠 💾 🌐 ... | just one part (system, memory, disk, network ...) |
| 🧩 Report sections | pick what goes in the scheduled report |
| ⏱ Report interval | every 5 min to 20 hours, or pause |
| 🔔 Alerts | warnings when CPU, RAM or disk get high |
| 🇮🇷 Iran check | can people in Iran reach your server? |
| ⚙️ Watched services | get warned if `nginx`, `x-ui` ... stop |
| 👥 Users | let a friend use the bot too (owner only) |
| 🧰 PrivateToolBox | secure and tune the server from here (owner only). Not installed yet? It offers to install it |
| 🌐 Language | Persian or English |

## ✅ Common tasks

- 🕒 **Reports more or less often:** ⏱ Report interval, then pick a time or ✏️ Custom and send a number from 5 to 1200 (minutes)
- 👀 **See only the disk:** tap 💾 on the main panel
- 🔕 **Pause scheduled reports:** ⏱ Report interval, then ⏸ Pause reports
- 🙋 **Add a person:** 👥 Users, ➕ Add, send their numeric ID. They must open the bot and press Start
- 🛑 **Know when a service dies:** ⚙️ Watched services, ➕ Add, send the name, for example `nginx`
- 🇮🇷 **Check another IP or a port:** 🇮🇷 Iran check, then set the target or the TCP ports

## 🖥 On the server

```bash
privatechecker status      # 🟢 is it running?
privatechecker logs -f     # 📜 live logs
privatechecker report      # 📊 report in the terminal
privatechecker doctor      # 🩺 find problems
privatechecker update      # 🔄 upgrade, keeps your settings
privatechecker uninstall   # 🗑 remove (add --purge to also delete settings)
```

## 🆘 Something is wrong?

| Problem | What to do |
|---|---|
| 🤐 The bot says nothing | Press **Start** in the bot, then run `privatechecker doctor` |
| ❌ "Could not message ID" during install | Open the bot, press **Start**, then try again |
| 🔑 Token rejected | Copy it again from @BotFather. It must look like `123456789:ABC...` |
| 🆔 Wrong ID | Use only digits, from @userinfobot |
| 🐳 Docker not shown | Run the installer again with `--with-docker` |
| 🇮🇷 "rate limited" in the Iran check | The free check-host.net service is busy. It retries on its own |

## 🔒 Good to know

- 🤫 The bot ignores everyone except you and the people you add.
- 🔑 If your token leaks: send `/revoke` to @BotFather, then uninstall and install again.
- 🆓 This project is free. Selling it or charging money for it is prohibited.

GitHub: [Sorena-max/PrivateChecker](https://github.com/Sorena-max/PrivateChecker)
