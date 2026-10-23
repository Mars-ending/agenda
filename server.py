#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""议程后端 · 单文件 · 只用标准库。

跑起来：
    python server.py                 # 127.0.0.1:8080，本机用
    python server.py --host 0.0.0.0 --port 8080   # 服务器上，前面挂 Caddy

数据：本目录 agenda.db（SQLite 单文件，备份就是 copy 它）
令牌：本目录 token.txt（首次运行自动生成；每台设备一个，换行分隔）

接口（只有三个）：
    GET  /health                    → {ok, items, seq}
    GET  /sync?since=<seq>          → {seq, changes:[...]}
    POST /sync {since, changes:[]}  → {seq, changes:[...]}   一次往返同时推和拉

同步规则（单人双设备够用，且有明确的正确性边界）：
    · id 由客户端生成（UUID），服务端不自增
    · 每行有 seq，服务端分配；客户端只认 seq 做游标，不靠设备时钟判断先后
    · 删除写墓碑（deleted=1），不真删，否则另一台设备会把它复活
    · 冲突按 updated_at 后写覆盖先写（客户端时间；单人场景够用）
    · 客户端 since 大于服务端当前 seq（比如从备份恢复），自动退回全量
"""
import argparse
import json
import os
import secrets
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "agenda.db")
TOKEN_FILE = os.path.join(ROOT, "token.txt")
WEB_DIR = os.path.join(ROOT, "web")
WEB = os.path.join(WEB_DIR, "index.html")
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".css": "text/css; charset=utf-8",
}

LOCK = threading.Lock()
CONN = None


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db():
    global CONN
    if CONN is None:
        CONN = sqlite3.connect(DB, check_same_thread=False)
        CONN.execute("PRAGMA journal_mode=WAL")
        CONN.execute("""CREATE TABLE IF NOT EXISTS items(
            id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            seq INTEGER NOT NULL,
            deleted INTEGER NOT NULL DEFAULT 0)""")
        CONN.execute("CREATE INDEX IF NOT EXISTS idx_seq ON items(seq)")
        CONN.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL)")
        CONN.execute("INSERT OR IGNORE INTO meta(k,v) VALUES('seq','0')")
        CONN.commit()
    return CONN


def load_tokens():
    if not os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(24) + "\n")
        os.chmod(TOKEN_FILE, 0o600) if os.name != "nt" else None
    with open(TOKEN_FILE, encoding="utf-8") as f:
        return [t.strip() for t in f if t.strip()]


TOKENS = []


def next_seq(c):
    c.execute("UPDATE meta SET v = CAST(CAST(v AS INTEGER)+1 AS TEXT) WHERE k='seq'")
    return int(c.execute("SELECT v FROM meta WHERE k='seq'").fetchone()[0])


def current_seq(c):
    return int(c.execute("SELECT v FROM meta WHERE k='seq'").fetchone()[0])


def row_json(r):
    iid, payload, upd, seq, deleted = r
    return {"id": iid, "payload": json.loads(payload), "updated_at": upd,
            "seq": seq, "deleted": bool(deleted)}


def apply_changes(c, changes):
    """写入；返回实际接受了几条。"""
    accepted = 0
    for ch in changes:
        iid = (ch.get("id") or "").strip()
        if not iid:
            continue
        upd = ch.get("updated_at") or now_iso()
        deleted = 1 if ch.get("deleted") else 0
        payload = json.dumps(ch.get("payload") or {}, ensure_ascii=False)
        cur = c.execute("SELECT updated_at FROM items WHERE id=?", (iid,)).fetchone()
        if cur and str(upd) < str(cur[0]):
            continue  # 旧版本，丢弃
        seq = next_seq(c)
        if cur:
            c.execute("UPDATE items SET payload=?, updated_at=?, seq=?, deleted=? WHERE id=?",
                      (payload if not deleted else "{}", upd, seq, deleted, iid))
        else:
            c.execute("INSERT INTO items(id,payload,updated_at,seq,deleted) VALUES(?,?,?,?,?)",
                      (iid, payload if not deleted else "{}", upd, seq, deleted))
        accepted += 1
    return accepted


def changes_since(c, since):
    rows = c.execute("SELECT id,payload,updated_at,seq,deleted FROM items WHERE seq>? ORDER BY seq",
                     (since,)).fetchall()
    return [row_json(r) for r in rows]


class Handler(BaseHTTPRequestHandler):
    server_version = "Agenda/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if self.path.startswith("/health"):
            return
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    # ---------- 工具 ----------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self, qs):
        tok = ""
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            tok = auth[7:].strip()
        if not tok and qs.get("token"):
            tok = qs["token"][0]
        return tok in TOKENS

    # ---------- 路由 ----------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path in ("/", "/index.html") or u.path.startswith("/icon") or u.path in (
                "/manifest.json", "/sw.js", "/apple-touch-icon.png"):
            return self._static(u.path)
        if u.path == "/health":
            with LOCK:
                c = db()
                n = c.execute("SELECT COUNT(*) FROM items WHERE deleted=0").fetchone()[0]
                return self._json(200, {"ok": True, "items": n, "seq": current_seq(c),
                                        "time": now_iso()})
        if u.path == "/sync":
            if not self._auth_ok(qs):
                return self._json(401, {"error": "bad token"})
            since = int((qs.get("since") or ["0"])[0] or 0)
            with LOCK:
                c = db()
                cur = current_seq(c)
                if since > cur:
                    since = 0
                return self._json(200, {"seq": cur, "changes": changes_since(c, since)})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/sync":
            return self._json(404, {"error": "not found"})
        if not self._auth_ok(parse_qs(u.query)):
            return self._json(401, {"error": "bad token"})
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "bad json"})
        since = int(body.get("since") or 0)
        changes = body.get("changes") or []
        with LOCK:
            c = db()
            cur = current_seq(c)
            if since > cur:
                since = 0
            accepted = apply_changes(c, changes)
            c.commit()
            cur = current_seq(c)
            return self._json(200, {"seq": cur, "accepted": accepted,
                                    "changes": changes_since(c, since)})

    def _static(self, path="/"):
        rel = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not (full == WEB_DIR or full.startswith(WEB_DIR + os.sep)):
            return self._json(403, {"error": "forbidden"})
        if not os.path.isfile(full):
            return self._json(404, {"error": "not found"})
        ext = os.path.splitext(full)[1].lower()
        mime = MIME.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if ext == ".html" else "max-age=86400")
        self.end_headers()
        self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()

    global TOKENS
    TOKENS = load_tokens()
    db()

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    host = "127.0.0.1" if a.host in ("0.0.0.0", "") else a.host
    print("议程后端已启动：http://%s:%d" % (host, a.port))
    print("令牌文件：%s（共 %d 个）" % (TOKEN_FILE, len(TOKENS)))
    print("首次配对请打开：http://%s:%d/?token=%s" % (host, a.port, TOKENS[0]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
