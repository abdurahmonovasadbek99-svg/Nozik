"""
webapp/server.py
Telegram Mini App uchun yengil HTTP server (Render health-check bilan BIR portda).

  GET /, /health      -> "OK"                      (UptimeRobot / self-ping)
  GET /app            -> Mini App sahifasi (webapp/page.html)
  GET /api/signal     -> signal darajalari va holati (DB)       ?s=SYMBOL&t=sent_ts
  GET /api/klines     -> Bybit shamlari (server orqali — region bloki yo'q) ?symbol=&interval=&limit=

Xavfsizlik: /api/* faqat Telegram `initData` (HMAC, bot tokeni bilan) to'g'ri va foydalanuvchi
ADMIN_CHAT_IDS ichida bo'lsa ishlaydi. Sinash uchun: env WEBAPP_OPEN=1 (tekshiruvsiz — faqat vaqtincha!).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, parse_qsl, urlparse

import config as C
from engine import db

logger = logging.getLogger("nozik.webapp")

_PAGE_PATH = os.path.join(os.path.dirname(__file__), "page.html")
_SYM_RE = re.compile(r"^[A-Z0-9]{3,24}USDT$")
_INTERVALS = {"1", "3", "5", "15", "30", "60", "240", "D"}
_CACHE: dict = {}            # (symbol, interval, limit) -> (ts, data)
_CACHE_LOCK = threading.Lock()
CACHE_TTL = 2.0


# ----------------------------------------------------------------- auth
def verify_init_data(init_data: str, token: str, admin_ids, max_age: int = 3 * 86400,
                     now: float | None = None) -> tuple[bool, str]:
    """Telegram WebApp initData ni tekshiradi. (ok, sabab)"""
    if not init_data:
        return False, "initData yo'q — Mini App'ni botdagi tugma orqali oching"
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        got = pairs.pop("hash", "")
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got):
            return False, "imzo noto'g'ri"
        if (now or time.time()) - int(pairs.get("auth_date", "0")) > max_age:
            return False, "sessiya eskirgan — Mini App'ni qayta oching"
        uid = int(json.loads(pairs.get("user", "{}")).get("id", 0))
        if uid not in set(admin_ids):
            return False, "ruxsat yo'q"
        return True, ""
    except Exception as e:                      # noto'g'ri format
        return False, f"initData xato: {e}"


# ------------------------------------------------------------------ data
def get_klines(symbol: str, interval: str, limit: int):
    key = (symbol, interval, limit)
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
    from signals.amd_volume import bybit_klines      # kech import: tsikl bo'lmasin
    data = bybit_klines(symbol, interval, limit)
    if data:
        out = [[c[0], c[1], c[2], c[3], c[4], c[5]] for c in data]
        with _CACHE_LOCK:
            _CACHE[key] = (now, out)
            if len(_CACHE) > 200:
                for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:100]:
                    _CACHE.pop(k, None)
        return out
    return None


_TF_INTERVAL = {"pump": "1", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}


def get_signal(symbol: str, sent_ts: int):
    cols = "symbol, tf, side, entry, sl, tp1, tp2, rr1, rr2, status, tp1_hit, gross_r, result_r, sent_ts, closed_ts"
    with db.tx() as conn:
        try:
            row = conn.execute(f"SELECT {cols}, tp3 FROM signals WHERE symbol=? AND sent_ts=? "
                               "ORDER BY id DESC LIMIT 1", (symbol, sent_ts)).fetchone()
        except Exception:                      # tp3 ustuni yo'q (eski baza)
            row = None
    if row is None:
        with db.tx() as conn:
            r2 = conn.execute(f"SELECT {cols} FROM signals WHERE symbol=? AND sent_ts=? "
                              "ORDER BY id DESC LIMIT 1", (symbol, sent_ts)).fetchone()
        row = tuple(r2) + (None,) if r2 else None
    if row is None:
        return None
    keys = ["symbol", "tf", "side", "entry", "sl", "tp1", "tp2", "rr1", "rr2", "status", "stage",
            "gross_r", "result_r", "sent_ts", "closed_ts", "tp3"]
    d = dict(zip(keys, row))
    d["interval"] = _TF_INTERVAL.get(d["tf"], "15")
    d["stage"] = int(d["stage"] or 0)
    return d


# --------------------------------------------------------------- handler
class WebHandler(BaseHTTPRequestHandler):
    server_version = "Nozik"

    def _send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        if os.environ.get("WEBAPP_OPEN", "0") == "1":
            return True
        ok, why = verify_init_data(self.headers.get("X-Init-Data", ""), C.TELEGRAM_BOT_TOKEN,
                                   C.ADMIN_CHAT_IDS)
        if not ok:
            self._json(401, {"error": why})
        return ok

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path in ("/", "/health"):
                return self._send(200, b"OK")
            if u.path == "/app":
                with open(_PAGE_PATH, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if u.path == "/api/klines":
                if not self._authorized():
                    return
                sym, iv = q.get("symbol", "").upper(), q.get("interval", "1")
                limit = max(10, min(int(q.get("limit", "200")), 400))
                if not _SYM_RE.match(sym) or iv not in _INTERVALS:
                    return self._json(400, {"error": "noto'g'ri symbol/interval"})
                data = get_klines(sym, iv, limit)
                if data is None:
                    return self._json(502, {"error": "Bybit shamlari olinmadi"})
                return self._json(200, {"symbol": sym, "interval": iv, "candles": data})
            if u.path == "/api/signal":
                if not self._authorized():
                    return
                sym = q.get("s", "").upper()
                if not _SYM_RE.match(sym):
                    return self._json(400, {"error": "noto'g'ri symbol"})
                sig = get_signal(sym, int(q.get("t", "0")))
                if not sig:
                    return self._json(404, {"error": "signal topilmadi"})
                return self._json(200, sig)
            self._send(404, b"not found")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            logger.warning(f"webapp xatosi: {e}")
            try:
                self._json(500, {"error": "server xatosi"})
            except Exception:
                pass

    def log_message(self, format, *args):
        pass


def run_server(port: int):
    srv = ThreadingHTTPServer(("0.0.0.0", port), WebHandler)
    srv.daemon_threads = True
    srv.serve_forever()
