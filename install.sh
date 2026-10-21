#!/usr/bin/env bash
# PrivateChecker (Private Tool) - installer / updater / uninstaller.
#
#   curl -fsSL https://raw.githubusercontent.com/Sorena-max/PrivateChecker/main/PrivateChecker/install.sh | sudo bash
#
# GitHub: Sorena-max. Free software (MIT); selling it or charging for it is prohibited.
# Read this file before running it: it installs a systemd service on your server.
# Everything it does is listed in PrivateChecker/README.md.

set -Eeuo pipefail

SC_VERSION="0.3.0"
REPO_SLUG="Sorena-max/PrivateChecker"
APP_DIR="/opt/privatechecker"
STATE_DIR="/var/lib/privatechecker"
SVC_USER="privatechecker"
UNIT_FILE="/etc/systemd/system/privatechecker.service"
BIN_FILE="/usr/local/bin/privatechecker"
HELPER_UNIT_NAME="privatechecker-helper"
HELPER_UNIT_FILE="/etc/systemd/system/privatechecker-helper.service"
MIN_PY="3.8"

COMMAND="install"
REF="${SC_REF:-main}"
TOKEN="${SC_TOKEN:-}"
ADMIN="${SC_ADMIN:-}"
LANG_CODE="${SC_LANG:-}"
LOCAL_SOURCE=""
NON_INTERACTIVE=0
SKIP_VERIFY=0
WITH_DOCKER=0
WITH_HELPER=0
PURGE=0
NO_CLEAR=0
FAST=0
SLOW=0
PM=""
TMP_DIR=""
SRC=""
BOT_USERNAME=""


UI_COLOR=0
UI_UTF8=0
UI_256=0
COLS=64
C_RED=""; C_GRN=""; C_YLW=""; C_CYN=""; C_DIM=""; C_BLD=""; C_OFF=""
SYM_OK="[OK]"; SYM_BAD="[X]"; SYM_WARN="[!]"; SYM_DOT="-"; RULE_CH="-"

setup_ui() {
  if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != "dumb" ]; then
    UI_COLOR=1
    C_RED=$'\033[1;31m'; C_GRN=$'\033[1;32m'; C_YLW=$'\033[1;33m'
    C_CYN=$'\033[1;36m'; C_DIM=$'\033[2m'; C_BLD=$'\033[1m'; C_OFF=$'\033[0m'
    if [ "$(tput colors 2>/dev/null || echo 8)" -ge 256 ]; then UI_256=1; fi
    COLS="$(tput cols 2>/dev/null || echo 70)"
    if [ "$COLS" -gt 72 ]; then COLS=72; fi
    if [ "$COLS" -lt 40 ]; then COLS=40; fi
    # A person is watching: reveal the screen slowly instead of dumping it at once.
    if [ "$FAST" -eq 0 ] && [ "$NON_INTERACTIVE" -eq 0 ]; then SLOW=1; fi
  fi
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*)
      UI_UTF8=1; SYM_OK="✔"; SYM_BAD="✖"; SYM_WARN="!"; SYM_DOT="•"; RULE_CH="─" ;;
  esac
}

nap() {  # nap SECONDS - a pause that only happens when a person is watching
  if [ "$SLOW" -eq 1 ]; then sleep "$1"; fi
  return 0
}

rule() {
  local line="" i
  for ((i = 0; i < COLS; i++)); do line+="$RULE_CH"; done
  printf '%s%s%s\n' "$C_DIM" "$line" "$C_OFF"
}

info() { printf '  %s%s%s %s\n' "$C_DIM" "$SYM_DOT" "$C_OFF" "$*"; }
ok()   { printf '  %s%s%s %s\n' "$C_GRN" "$SYM_OK" "$C_OFF" "$*"; nap 0.35; }
bad()  { printf '  %s%s%s %s\n' "$C_RED" "$SYM_BAD" "$C_OFF" "$*"; nap 0.35; }
warn() { printf '  %s%s%s %s\n' "$C_YLW" "$SYM_WARN" "$C_OFF" "$*" >&2; }
die()  { printf '\n  %s%s %s%s\n\n' "$C_RED" "$SYM_BAD" "$*" "$C_OFF" >&2; exit 1; }

step() {  # step N TOTAL "Title"
  nap 0.5
  printf '\n'
  rule
  nap 0.2
  printf ' %sStep %s/%s%s  %s%s%s\n' "$C_CYN" "$1" "$2" "$C_OFF" "$C_BLD" "$3" "$C_OFF"
  nap 0.2
  rule
  nap 0.4
}

paint() {  # paint LINE ROW - banner gradient
  if [ "$UI_COLOR" -eq 0 ]; then printf '%s\n' "$1"; return; fi
  if [ "$UI_256" -eq 1 ]; then
    local shades=(51 45 39 33 27 21)
    printf '\033[38;5;%sm%s\033[0m\n' "${shades[$2]}" "$1"
  else
    printf '%s%s%s\n' "$C_CYN" "$1" "$C_OFF"
  fi
  nap 0.12
}

banner() {
  if [ "$UI_UTF8" -eq 1 ] && [ "$COLS" -ge 58 ]; then
    local -a art=(
      '██████╗ ██████╗ ██╗██╗   ██╗ █████╗ ████████╗███████╗'
      '██╔══██╗██╔══██╗██║██║   ██║██╔══██╗╚══██╔══╝██╔════╝'
      '██████╔╝██████╔╝██║██║   ██║███████║   ██║   █████╗  '
      '██╔═══╝ ██╔══██╗██║╚██╗ ██╔╝██╔══██║   ██║   ██╔══╝  '
      '██║     ██║  ██║██║ ╚████╔╝ ██║  ██║   ██║   ███████╗'
      '╚═╝     ╚═╝  ╚═╝╚═╝  ╚═══╝  ╚═╝  ╚═╝   ╚═╝   ╚══════╝'
      ' ██████╗██╗  ██╗███████╗ ██████╗██╗  ██╗███████╗██████╗ '
      '██╔════╝██║  ██║██╔════╝██╔════╝██║ ██╔╝██╔════╝██╔══██╗'
      '██║     ███████║█████╗  ██║     █████╔╝ █████╗  ██████╔╝'
      '██║     ██╔══██║██╔══╝  ██║     ██╔═██╗ ██╔══╝  ██╔══██╗'
      '╚██████╗██║  ██║███████╗╚██████╗██║  ██╗███████╗██║  ██║'
      ' ╚═════╝╚═╝  ╚═╝╚══════╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝'
    )
    local i
    for i in "${!art[@]}"; do paint "  ${art[$i]}" "$((i % 6))"; done
  else
    printf '\n  %s== PRIVATE CHECKER ==%s\n' "$C_CYN" "$C_OFF"
  fi
  nap 0.4
  printf '\n  %sPrivateChecker (Private Tool)%s  %s|  v%s%s\n' "$C_BLD" "$C_OFF" "$C_DIM" "$SC_VERSION" "$C_OFF"
  nap 0.35
  printf '  A private Telegram watchdog for your Linux server\n'
  nap 0.35
  printf '  %sGitHub:%s Sorena-max  %s|%s  github.com/%s\n' "$C_BLD" "$C_OFF" "$C_DIM" "$C_OFF" "$REPO_SLUG"
  nap 0.35
  printf '  %sThis project is completely free. Selling it or charging money for it is prohibited.%s\n' "$C_YLW" "$C_OFF"
}

show_header() {
  if [ "$UI_COLOR" -eq 1 ] && [ "$NO_CLEAR" -eq 0 ]; then printf '\033[2J\033[H'; fi
  printf '\n'
  nap 0.3
  banner
  nap 1
}

cleanup() { [ -n "$TMP_DIR" ] && rm -rf "$TMP_DIR"; return 0; }
trap cleanup EXIT

usage() {
  cat <<'EOF'
PrivateChecker (Private Tool) installer

Usage: install.sh [install|update|uninstall] [options]

Options:
  --token TOKEN        Telegram bot token (from @BotFather)
  --admin ID           numeric Telegram ID of the owner
  --lang fa|en         bot language (default: fa)
  --ref REF            git branch or tag to install (default: main)
  --with-docker        let the service read Docker (adds it to the docker group)
  --with-helper        let the owner install PrivateToolBox from the Telegram bot (adds a small root helper)
  --non-interactive    never prompt; fail if --token/--admin are missing
  --purge              with uninstall: also delete settings and the service user
  --no-clear           do not clear the screen at the start
  --fast               no animation or pauses (the default when not run by a person)
  --local-source DIR   install from a local checkout (development / CI)
  --skip-verify        do not contact Telegram during install (CI only)
  -h, --help           show this help

Environment: SC_TOKEN, SC_ADMIN, SC_LANG, SC_REF work like the flags.
Piped install with flags:  curl -fsSL <url> | sudo bash -s -- --token ... --admin ...
EOF
}

parse_args() {
  if [ $# -gt 0 ]; then
    case "$1" in install|update|uninstall|enable-install|disable-install) COMMAND="$1"; shift ;; esac
  fi
  while [ $# -gt 0 ]; do
    case "$1" in
      --token) TOKEN="${2:?--token needs a value}"; shift 2 ;;
      --admin) ADMIN="${2:?--admin needs a value}"; shift 2 ;;
      --lang) LANG_CODE="${2:?--lang needs a value}"; shift 2 ;;
      --ref) REF="${2:?--ref needs a value}"; shift 2 ;;
      --local-source) LOCAL_SOURCE="${2:?--local-source needs a value}"; shift 2 ;;
      --with-docker) WITH_DOCKER=1; shift ;;
      --with-helper) WITH_HELPER=1; shift ;;
      --non-interactive|--yes|-y) NON_INTERACTIVE=1; shift ;;
      --skip-verify) SKIP_VERIFY=1; shift ;;
      --purge) PURGE=1; shift ;;
      --no-clear) NO_CLEAR=1; shift ;;
      --fast) FAST=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown option: $1 (see --help)" ;;
    esac
  done
}


need_root() {
  [ "$(id -u)" -eq 0 ] || die "please run as root, e.g.: curl -fsSL <url> | sudo bash"
}

need_systemd() {
  [ -d /run/systemd/system ] || die "systemd is required (this server does not use it)"
}

os_name() {
  local name=""
  if [ -r /etc/os-release ]; then
    name="$(. /etc/os-release && printf '%s' "${PRETTY_NAME:-}")"
  fi
  printf '%s' "${name:-Linux}"
}

detect_pm() {
  local cand
  for cand in apt-get dnf yum zypper pacman; do
    if command -v "$cand" >/dev/null 2>&1; then PM="$cand"; return; fi
  done
  PM=""
}

pkg_name() {  # translate generic names for the package manager in use
  case "$PM:$1" in
    pacman:python3) echo python ;;
    *) echo "$1" ;;
  esac
}

pkg_install() {
  [ -n "$PM" ] || die "cannot install $* automatically: no supported package manager found"
  local pkgs=() p
  for p in "$@"; do pkgs+=("$(pkg_name "$p")"); done
  info "installing missing packages: ${pkgs[*]}"
  case "$PM" in
    apt-get) DEBIAN_FRONTEND=noninteractive apt-get update -qq </dev/null
             DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${pkgs[@]}" </dev/null ;;
    dnf)     dnf install -y -q "${pkgs[@]}" </dev/null ;;
    yum)     yum install -y -q "${pkgs[@]}" </dev/null ;;
    zypper)  zypper --non-interactive install -y "${pkgs[@]}" </dev/null ;;
    pacman)  pacman -Sy --noconfirm --needed "${pkgs[@]}" </dev/null ;;
  esac
}

ensure_prereqs() {
  local missing=()
  command -v python3 >/dev/null 2>&1 || missing+=(python3)
  command -v curl >/dev/null 2>&1 || missing+=(curl)
  command -v tar >/dev/null 2>&1 || missing+=(tar)
  [ -e /etc/ssl/certs ] || missing+=(ca-certificates)
  if [ ${#missing[@]} -gt 0 ]; then
    pkg_install "${missing[@]}"
  fi
  python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" \
    || die "Python $MIN_PY or newer is required (found $(python3 -V 2>&1))"
  ok "python3 ($(python3 -V 2>&1 | cut -d' ' -f2)), curl and tar are ready"
}


have_tty() { (exec </dev/tty) 2>/dev/null; }

prompt() {  # prompt VAR "text"; input stays visible so typos are easy to spot
  local __var="$1" __value=""
  read -rp "$2" __value </dev/tty
  printf -v "$__var" '%s' "$__value"
}

json_get() {  # json_get a.b.c  (reads JSON on stdin; prints nothing on error)
  python3 -c '
import sys, json
try:
    data = json.load(sys.stdin)
    for key in sys.argv[1].split("."):
        data = data[key]
    print(data)
except Exception:
    pass' "$1"
}

tg_api() {  # tg_api METHOD [curl args...]; the token never appears in argv
  local method="$1"; shift
  printf 'url = "https://api.telegram.org/bot%s/%s"\n' "$TOKEN" "$method" \
    | curl -sS -m 20 -K - "$@" || true
}

valid_token() { [[ "$1" =~ ^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$ ]]; }

working() {  # working "text" - a status line that the result replaces
  if [ "$UI_COLOR" -eq 1 ]; then printf '  %s...%s %s' "$C_DIM" "$C_OFF" "$1"; fi
}
done_working() { if [ "$UI_COLOR" -eq 1 ]; then printf '\r\033[K'; fi; }

verify_token() {
  local resp
  working "Checking the token with Telegram"
  resp="$(tg_api getMe)"
  done_working
  if [ "$(printf '%s' "$resp" | json_get ok)" = "True" ]; then
    BOT_USERNAME="$(printf '%s' "$resp" | json_get result.username)"
    ok "Token accepted ${C_DIM}-${C_OFF} bot ${C_BLD}@${BOT_USERNAME}${C_OFF}"
    return 0
  fi
  bad "Telegram rejected this token: $(printf '%s' "$resp" | json_get description)"
  return 1
}

verify_message() {  # the confirmation Telegram message, in the chosen language
  if [ "$LANG_CODE" = "fa" ]; then
    printf '✅ پرایوت چکر: اتصال تأیید شد.\nربات در حال نصب روی این سرور است.'
  else
    printf '✅ PrivateChecker: connection verified.\nThe bot is being installed on this server.'
  fi
}

verify_admin() {
  local resp answer
  while true; do
    working "Sending a test message to ID $ADMIN"
    resp="$(tg_api sendMessage --data-urlencode "chat_id=$ADMIN" \
      --data-urlencode "text=$(verify_message)")"
    done_working
    if [ "$(printf '%s' "$resp" | json_get ok)" = "True" ]; then
      ok "ID verified ${C_DIM}-${C_OFF} a confirmation message was sent to your Telegram"
      return 0
    fi
    bad "Could not message ID $ADMIN: $(printf '%s' "$resp" | json_get description)"
    [ "$NON_INTERACTIVE" -eq 0 ] && have_tty || return 1
    printf '\n  Open %shttps://t.me/%s%s with that account and press %sStart%s.\n' \
      "$C_BLD" "$BOT_USERNAME" "$C_OFF" "$C_BLD" "$C_OFF"
    prompt answer "  Press Enter to retry, or type 's' to skip this check: "
    [ "$answer" = "s" ] && { warn "skipped admin verification"; return 0; }
  done
}

choose_language() {
  if [ -z "$LANG_CODE" ]; then
    if [ "$NON_INTERACTIVE" -eq 1 ]; then
      LANG_CODE="fa"
    else
      printf '\n  %sBot language%s %s(the language of the messages your bot sends)%s\n' \
        "$C_BLD" "$C_OFF" "$C_DIM" "$C_OFF"
      nap 0.3
      printf '    1) Persian  %s(default)%s\n    2) English\n\n' "$C_DIM" "$C_OFF"
      local choice
      prompt choice "  Choose [1]: "
      case "$choice" in 2|en|EN|English) LANG_CODE="en" ;; *) LANG_CODE="fa" ;; esac
    fi
  fi
  case "$LANG_CODE" in
    fa|en) ;;
    *) warn "unknown language '$LANG_CODE', using fa"; LANG_CODE="fa" ;;
  esac
  ok "Bot language: $([ "$LANG_CODE" = "fa" ] && echo Persian || echo English)"
}

collect_settings() {
  local existing=0
  [ -s "$STATE_DIR/config.json" ] && existing=1
  if [ "$existing" -eq 1 ] && [ -z "$TOKEN" ] && [ -z "$ADMIN" ]; then
    ok "Existing configuration found - keeping it ${C_DIM}(pass --token/--admin to replace)${C_OFF}"
    return
  fi
  if [ "$NON_INTERACTIVE" -eq 0 ] && ! have_tty; then
    die "no terminal available for prompts; pass --token and --admin (see --help)"
  fi

  choose_language

  printf '\n  %sBot token%s\n' "$C_BLD" "$C_OFF"
  printf '  %sOpen @BotFather in Telegram, send /newbot and copy the token it gives you.%s\n' "$C_DIM" "$C_OFF"
  while true; do
    if [ -z "$TOKEN" ]; then
      [ "$NON_INTERACTIVE" -eq 1 ] && die "--token is required in non-interactive mode"
      prompt TOKEN "  Paste the token here: "
    fi
    TOKEN="${TOKEN//[[:space:]]/}"
    if ! valid_token "$TOKEN"; then
      bad "That does not look like a bot token ${C_DIM}(expected 123456789:ABC...)${C_OFF}"
      [ "$NON_INTERACTIVE" -eq 1 ] && exit 1
      TOKEN=""; continue
    fi
    if [ "$SKIP_VERIFY" -eq 1 ] || verify_token; then break; fi
    [ "$NON_INTERACTIVE" -eq 1 ] && exit 1
    TOKEN=""
  done

  printf '\n  %sYour Telegram ID%s\n' "$C_BLD" "$C_OFF"
  printf '  %sSend any message to @userinfobot to see your numeric ID. Then open your bot and press Start.%s\n' "$C_DIM" "$C_OFF"
  while true; do
    if [ -z "$ADMIN" ]; then
      [ "$NON_INTERACTIVE" -eq 1 ] && die "--admin is required in non-interactive mode"
      prompt ADMIN "  Your numeric ID: "
    fi
    ADMIN="${ADMIN//[[:space:]]/}"
    if ! [[ "$ADMIN" =~ ^[0-9]{1,15}$ ]] || [ "$ADMIN" -le 0 ]; then
      bad "The ID must be a positive number ${C_DIM}(digits only)${C_OFF}"
      [ "$NON_INTERACTIVE" -eq 1 ] && exit 1
      ADMIN=""; continue
    fi
    if [ "$SKIP_VERIFY" -eq 1 ] || verify_admin; then break; fi
    [ "$NON_INTERACTIVE" -eq 1 ] && exit 1
    ADMIN=""
  done
}


fetch_source() {
  if [ -n "$LOCAL_SOURCE" ]; then
    SRC="$(cd "$LOCAL_SOURCE" && pwd)"
  else
    TMP_DIR="$(mktemp -d)"
    working "Downloading PrivateChecker ($REF) from GitHub"
    curl -fsSL --retry 3 --connect-timeout 15 \
      "https://github.com/$REPO_SLUG/archive/$REF.tar.gz" -o "$TMP_DIR/src.tar.gz" \
      || { done_working; die "download failed - check your connection and that '$REF' exists"; }
    tar -xzf "$TMP_DIR/src.tar.gz" -C "$TMP_DIR"
    SRC="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1 || true)"
    done_working
  fi
  [ -d "${SRC:-}/privatechecker" ] || die "PrivateChecker sources not found in the download"
  ok "Downloaded PrivateChecker ($REF)"
}

ensure_user() {
  if ! id -u "$SVC_USER" >/dev/null 2>&1; then
    local nologin; nologin="$(command -v nologin || echo /usr/sbin/nologin)"
    useradd --system --no-create-home --shell "$nologin" "$SVC_USER" 2>/dev/null \
      || die "could not create the '$SVC_USER' service user"
    ok "Created the service user '$SVC_USER' ${C_DIM}(no login, no home)${C_OFF}"
  else
    ok "Service user '$SVC_USER' already exists"
  fi
  local grp
  for grp in systemd-journal adm; do   # read-only access to system logs
    if getent group "$grp" >/dev/null 2>&1; then usermod -aG "$grp" "$SVC_USER"; fi
  done
  if [ "$WITH_DOCKER" -eq 1 ]; then
    if getent group docker >/dev/null 2>&1; then
      usermod -aG docker "$SVC_USER"
      warn "the service can now talk to Docker (docker group = root-equivalent access)"
    else
      warn "--with-docker given but no 'docker' group exists; skipping"
    fi
  fi
}

deploy_code() {
  install -d -m 755 "$APP_DIR"
  rm -rf "$APP_DIR/privatechecker"
  cp -a "$SRC/privatechecker" "$APP_DIR/privatechecker"
  cp "$SRC/install.sh" "$APP_DIR/install.sh"
  chmod 755 "$APP_DIR/install.sh"
  find "$APP_DIR" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
  chown -R root:root "$APP_DIR"
  ok "Code installed in $APP_DIR ${C_DIM}(owned by root, read-only for the service)${C_OFF}"
}

write_config() {
  install -d -m 700 -o "$SVC_USER" -g "$SVC_USER" "$STATE_DIR"
  if [ -n "$TOKEN" ]; then
    SC_TOKEN="$TOKEN" SC_OWNER="$ADMIN" SC_LANG="$LANG_CODE" \
      PRIVATECHECKER_HOME="$STATE_DIR" PYTHONPATH="$APP_DIR" PYTHONDONTWRITEBYTECODE=1 \
      python3 -m privatechecker init >/dev/null
    ok "Settings saved ${C_DIM}(token file is readable only by the service)${C_OFF}"
  fi
  chown -R "$SVC_USER:$SVC_USER" "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  [ -f "$STATE_DIR/config.json" ] && chmod 600 "$STATE_DIR/config.json"
  return 0
}

write_unit() {
  local py; py="$(command -v python3)"
  cat >"$UNIT_FILE" <<EOF
[Unit]
Description=PrivateChecker - Telegram watchdog for this server
Documentation=https://github.com/$REPO_SLUG
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
Group=$SVC_USER
Environment=PYTHONPATH=$APP_DIR PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PRIVATECHECKER_HOME=$STATE_DIR
ExecStart=$py -m privatechecker run
Restart=always
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=$STATE_DIR
ProtectControlGroups=yes
ProtectKernelModules=yes
LockPersonality=yes
MemoryMax=200M

[Install]
WantedBy=multi-user.target
EOF
  chmod 644 "$UNIT_FILE"
}

write_cli() {
  cat >"$BIN_FILE" <<'EOF'
#!/usr/bin/env bash
# privatechecker - control the PrivateChecker service
set -euo pipefail
APP=/opt/privatechecker
STATE=/var/lib/privatechecker
cmd="${1:-help}"; [ $# -gt 0 ] && shift

as_service_user() {
  if [ "$(id -u)" -eq 0 ]; then
    exec runuser -u privatechecker -- env PYTHONPATH="$APP" PRIVATECHECKER_HOME="$STATE" \
      PYTHONDONTWRITEBYTECODE=1 python3 -m privatechecker "$@"
  fi
  exec sudo -u privatechecker env PYTHONPATH="$APP" PRIVATECHECKER_HOME="$STATE" \
    PYTHONDONTWRITEBYTECODE=1 python3 -m privatechecker "$@"
}
root_only() { [ "$(id -u)" -eq 0 ] || exec sudo "$0" "$cmd" "$@"; }

case "$cmd" in
  status)   systemctl status privatechecker --no-pager ;;
  logs)     if [ "${1:-}" = "-f" ]; then exec journalctl -u privatechecker -f
            else exec journalctl -u privatechecker -n 100 --no-pager; fi ;;
  start|stop|restart) root_only "$@"; systemctl "$cmd" privatechecker && echo "privatechecker: $cmd done" ;;
  report)   as_service_user report "$@" ;;
  doctor)   as_service_user doctor ;;
  version)  PYTHONPATH="$APP" python3 -m privatechecker version ;;
  update)   root_only "$@"; exec bash "$APP/install.sh" update "$@" ;;
  uninstall) root_only "$@"; exec bash "$APP/install.sh" uninstall "$@" ;;
  enable-install|disable-install) root_only "$@"; exec bash "$APP/install.sh" "$cmd" "$@" ;;
  *) cat <<'USAGE'
Usage: privatechecker <command>

  status      service status
  logs [-f]   recent logs (-f to follow)
  start|stop|restart
  report [--only SECTION]   print a report here in the terminal
  doctor      diagnose the installation
  update      install the latest version (keeps your settings)
  enable-install   let the owner install PrivateToolBox from the bot (small root helper)
  disable-install  turn that off again
  uninstall   remove PrivateChecker (add --purge to delete settings too)
  version
USAGE
  ;;
esac
EOF
  chmod 755 "$BIN_FILE"
}

write_helper_unit() {
  local py; py="$(command -v python3)"
  cat >"$HELPER_UNIT_FILE" <<EOF
[Unit]
Description=PrivateChecker helper (installs PrivateToolBox when the owner asks in the bot)
Documentation=https://github.com/$REPO_SLUG

[Service]
Type=simple
Environment=PYTHONPATH=$APP_DIR PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ExecStart=$py -m privatechecker helper
Restart=always
RestartSec=5
RuntimeDirectory=privatechecker
RuntimeDirectoryMode=0755
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes

[Install]
WantedBy=multi-user.target
EOF
  chmod 644 "$HELPER_UNIT_FILE"
}

enable_helper() {
  write_helper_unit
  systemctl daemon-reload
  systemctl enable "$HELPER_UNIT_NAME" >/dev/null 2>&1
  systemctl restart "$HELPER_UNIT_NAME"
  for _ in 1 2 3 4 5; do
    if [ -S /run/privatechecker/helper.sock ]; then break; fi
    sleep 1
  done
  ok "The owner can now install PrivateToolBox from the bot ${C_DIM}(a small root helper, off switch: privatechecker disable-install)${C_OFF}"
}

disable_helper() {
  systemctl disable --now "$HELPER_UNIT_NAME" >/dev/null 2>&1 || true
  rm -f "$HELPER_UNIT_FILE"
  systemctl daemon-reload 2>/dev/null || true
}

offer_helper() {
  [ -f "$HELPER_UNIT_FILE" ] && return 0
  if [ "$WITH_HELPER" -eq 1 ]; then enable_helper; return 0; fi
  if [ "$NON_INTERACTIVE" -eq 1 ] || ! have_tty; then return 0; fi
  printf "\n  %sInstall PrivateToolBox from the bot?%s\n" "$C_BLD" "$C_OFF"
  info "PrivateToolBox hardens and tunes the server. With a small root helper, the bot owner can install it with one tap."
  info "The helper can only install one pinned release from github.com/Sorena-max/PrivateToolBox, nothing else."
  local answer
  prompt answer "  Turn it on? [y/N] "
  case "$answer" in
    y|Y|yes|YES) enable_helper ;;
    *) info "Skipped. Turn it on any time with: sudo privatechecker enable-install" ;;
  esac
}

start_service() {
  systemctl daemon-reload
  systemctl enable privatechecker >/dev/null 2>&1
  working "Starting the service"
  systemctl restart privatechecker
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if systemctl is-active --quiet privatechecker; then
      done_working
      ok "Service is running ${C_DIM}(starts automatically on boot)${C_OFF}"
      return 0
    fi
    sleep 1
  done
  done_working
  journalctl -u privatechecker -n 30 --no-pager || true
  die "the service did not start - see the log above"
}

finish_screen() {
  printf '\n'
  rule
  printf ' %s%s PrivateChecker is installed and running%s\n' "$C_GRN" "$SYM_OK" "$C_OFF"
  rule
  if [ -n "$BOT_USERNAME" ]; then
    printf '\n  %s1.%s Open  %shttps://t.me/%s%s  and send  %s/start%s\n' \
      "$C_BLD" "$C_OFF" "$C_CYN" "$BOT_USERNAME" "$C_OFF" "$C_BLD" "$C_OFF"
  else
    printf '\n  %s1.%s Open your bot in Telegram and send  %s/start%s\n' "$C_BLD" "$C_OFF" "$C_BLD" "$C_OFF"
  fi
  printf '  %s2.%s Manage it from this server:\n' "$C_BLD" "$C_OFF"
  printf '       privatechecker status | logs -f | report | doctor | update\n'
  printf '\n  %sGitHub: Sorena-max  |  https://github.com/%s%s\n' "$C_DIM" "$REPO_SLUG" "$C_OFF"
  printf '  %sFree software - selling it or charging for it is prohibited.%s\n\n' "$C_DIM" "$C_OFF"
}

do_install() {
  need_root; need_systemd
  detect_pm

  step 1 5 "Checking this server"
  ok "$(os_name) ${C_DIM}|${C_OFF} systemd ${C_DIM}|${C_OFF} running as root"
  ensure_prereqs

  step 2 5 "Bot settings"
  collect_settings

  step 3 5 "Downloading"
  fetch_source

  step 4 5 "Installing"
  ensure_user
  deploy_code
  write_config
  write_unit
  write_cli

  step 5 5 "Starting"
  start_service
  finish_screen
  if [ "$COMMAND" = "install" ]; then offer_helper; fi
  if [ -f "$HELPER_UNIT_FILE" ]; then write_helper_unit; systemctl daemon-reload; systemctl restart "$HELPER_UNIT_NAME" || true; fi
}

do_enable_install() {
  need_root; need_systemd
  [ -d "$APP_DIR/privatechecker" ] || die "PrivateChecker is not installed here"
  step 1 1 "Install PrivateToolBox from the bot"
  enable_helper
  printf "\n  Open your bot, tap PrivateToolBox, and choose Install.\n\n"
}

do_disable_install() {
  need_root
  step 1 1 "Turning off installing from the bot"
  disable_helper
  ok "Done. The bot can no longer install anything"
  printf "\n"
}

do_uninstall() {
  need_root
  step 1 1 "Removing PrivateChecker"
  disable_helper
  systemctl disable --now privatechecker >/dev/null 2>&1 || true
  rm -f "$UNIT_FILE" "$BIN_FILE"
  systemctl daemon-reload 2>/dev/null || true
  rm -rf "$APP_DIR"
  if [ "$PURGE" -eq 1 ]; then
    rm -rf "$STATE_DIR"
    id -u "$SVC_USER" >/dev/null 2>&1 && userdel "$SVC_USER" 2>/dev/null || true
    ok "Removed everything, including settings and the service user"
  else
    ok "Removed the service and code ${C_DIM}(settings kept in $STATE_DIR; use --purge to delete)${C_OFF}"
  fi
  printf '\n'
}

main() {
  parse_args "$@"
  setup_ui
  show_header
  case "$COMMAND" in
    install|update) do_install ;;
    enable-install) do_enable_install ;;
    disable-install) do_disable_install ;;
    uninstall) do_uninstall ;;
  esac
}

main "$@"
