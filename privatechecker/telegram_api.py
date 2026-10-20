"""A tiny Telegram Bot API client built on the standard library."""

import http.client
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

MAX_MESSAGE = 3800  # Telegram allows 4096; leave room for markup
CONNECT_TIMEOUT = 8  # seconds to establish a connection to one address
POLL_SECONDS = 20    # long-poll length; also bounds how long a stalled poll can hide new messages


def open_socket(host, port, connect_timeout=CONNECT_TIMEOUT):
    """Connect to host, trying IPv4 first and failing fast per address.

    On a server with a broken IPv6 route the default behaviour waits out the
    whole request timeout on IPv6 before trying IPv4, which makes the bot look
    frozen for a minute at a time.
    """
    last = OSError("no address found for %s" % host)
    tried = set()
    for family in (socket.AF_INET, socket.AF_UNSPEC):
        try:
            infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
        except socket.gaierror as exc:
            last = exc
            continue
        for af, kind, proto, _canon, addr in infos:
            if addr in tried:
                continue
            tried.add(addr)
            sock = socket.socket(af, kind, proto)
            sock.settimeout(connect_timeout)
            try:
                sock.connect(addr)
                return sock
            except OSError as exc:
                sock.close()
                last = exc
    raise last


class _FastHTTPS(http.client.HTTPSConnection):
    def connect(self):
        sock = open_socket(self.host, self.port)
        sock.settimeout(self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(
            sock, server_hostname=self.host)


class _FastHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = open_socket(self.host, self.port)
        self.sock.settimeout(self.timeout)


class TelegramError(Exception):
    def __init__(self, code, description, retry_after=0):
        super().__init__("%s: %s" % (code, description))
        self.code = code
        self.description = description
        self.retry_after = retry_after


class Telegram:
    def __init__(self, token, api_base="https://api.telegram.org"):
        self._token = token
        self._base = api_base.rstrip("/")

    def redact(self, text):
        """Never let the bot token reach logs or exception messages."""
        text = str(text)
        return text.replace(self._token, "<token>") if self._token else text

    def _post(self, method, data, timeout):
        """Send one request and return the raw response body."""
        parts = urllib.parse.urlsplit(self._base)
        scheme = parts.scheme or "https"
        host = parts.hostname or "api.telegram.org"
        path = "%s/bot%s/%s" % (parts.path.rstrip("/"), self._token, method)
        headers = {"Content-Type": "application/json"}
        if urllib.request.getproxies().get(scheme) and \
                not urllib.request.proxy_bypass(host):
            # A proxy is configured (HTTPS_PROXY / HTTP_PROXY): let urllib handle it.
            req = urllib.request.Request(
                "%s://%s%s" % (scheme, parts.netloc, path), data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                return exc.read()  # Telegram explains the failure in the body
        conn_class = _FastHTTPS if scheme == "https" else _FastHTTP
        conn = conn_class(host, parts.port, timeout=timeout)
        try:
            conn.request("POST", path, body=data, headers=headers)
            return conn.getresponse().read()  # error statuses carry a JSON body too
        finally:
            conn.close()

    def call(self, method, params=None, timeout=25):
        data = json.dumps(params or {}).encode("utf-8")
        try:
            body = self._post(method, data, timeout)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            raise TelegramError(0, self.redact(exc))
        try:
            payload = json.loads(body.decode("utf-8"))
        except ValueError:
            raise TelegramError(0, "invalid response from Telegram")
        if not payload.get("ok"):
            retry = (payload.get("parameters") or {}).get("retry_after", 0)
            raise TelegramError(payload.get("error_code", 0),
                                self.redact(payload.get("description", "")),
                                retry)
        return payload.get("result")

    def get_me(self):
        return self.call("getMe", timeout=15)

    def delete_webhook(self):
        return self.call("deleteWebhook", {"drop_pending_updates": False},
                         timeout=15)

    def get_updates(self, offset, timeout=POLL_SECONDS):
        return self.call(
            "getUpdates",
            {"offset": offset, "timeout": timeout,
             "allowed_updates": ["message", "callback_query"]},
            timeout=timeout + 10)

    def send_message(self, chat_id, text, markup=None):
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}
        if markup:
            params["reply_markup"] = markup
        return self.call("sendMessage", params)

    def edit_message(self, chat_id, message_id, text, markup=None):
        params = {"chat_id": chat_id, "message_id": message_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True}
        if markup:
            params["reply_markup"] = markup
        return self.call("editMessageText", params)

    def answer_callback(self, callback_id, text=None):
        params = {"callback_query_id": callback_id}
        if text:
            params["text"] = text
        return self.call("answerCallbackQuery", params, timeout=15)


def pack(parts, limit=MAX_MESSAGE):
    """Join text parts into as few messages as fit under limit."""
    messages, current = [], ""
    for part in parts:
        if not part:
            continue
        if current and len(current) + len(part) + 2 > limit:
            messages.append(current)
            current = ""
        if len(part) > limit:  # a single oversized part: hard split by line
            for line in part.split("\n"):
                if current and len(current) + len(line) + 1 > limit:
                    messages.append(current)
                    current = ""
                current = (current + "\n" + line) if current else line[:limit]
            continue
        current = (current + "\n\n" + part) if current else part
    if current:
        messages.append(current)
    return messages
