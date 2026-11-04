"""只读 OpenCode 本地数据库，取「最近一个会话的最新一步」。

对 schema 变化保持防御：先探测表结构，缺表或没有 JSON1 就抛 SchemaError，
由界面显示明确提示，而不是静默给出 0。
"""

import json
import os
import sqlite3
import sys

REQUIRED_TABLES = ("session", "message", "part")


class SchemaError(Exception):
    """数据库结构与预期不符。"""


def db_candidates(explicit=""):
    if explicit:
        yield explicit
        return
    env = os.environ.get("OPENCODE_DB")
    if env:
        yield env
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    yield os.path.join(data_home, "opencode", "opencode.db")
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            yield os.path.join(local, "opencode", "opencode.db")
    if sys.platform == "darwin":
        yield os.path.expanduser("~/Library/Application Support/opencode/opencode.db")


def find_db(explicit=""):
    for p in db_candidates(explicit):
        if p and os.path.exists(p):
            return p
    return None


class Source:
    def __init__(self, path):
        self.path = path
        self.con = None
        self.connect()

    def connect(self):
        uri = "file:%s?mode=ro" % self.path.replace("\\", "/")
        try:
            self.con = sqlite3.connect(uri, uri=True, timeout=2.0,
                                       check_same_thread=False, isolation_level=None)
        except sqlite3.Error:
            # 某些文件系统不支持 URI 形式，退化为普通只读连接
            self.con = sqlite3.connect(self.path, timeout=2.0,
                                       check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA query_only=1")
        self.con.execute("PRAGMA busy_timeout=2000")
        self.check_schema()

    def check_schema(self):
        try:
            ok = self.con.execute("select json_extract('{\"a\":1}', '$.a')").fetchone()
        except sqlite3.Error as e:
            raise SchemaError("json1") from e
        if ok is None:
            raise SchemaError("json1")
        tables = {r[0] for r in self.con.execute(
            "select name from sqlite_master where type='table'")}
        missing = [t for t in REQUIRED_TABLES if t not in tables]
        if missing:
            raise SchemaError("missing tables: " + ", ".join(missing))

    # ---------- 取数 ----------

    def _latest_session(self, cur):
        return cur.execute(
            "select id, model, time_updated from session order by time_updated desc limit 1"
        ).fetchone()

    def fetch(self):
        cur = self.con.cursor()
        s = self._latest_session(cur)
        if s is None:
            return None

        model = "?"
        try:
            mj = json.loads(s["model"] or "{}")
            model = mj.get("id") or mj.get("modelID") or "?"
        except Exception:
            pass

        m = cur.execute(
            "select id, time_created, data from message where session_id=? "
            "order by time_created desc limit 1",
            (s["id"],),
        ).fetchone()
        if m is None:
            return {"state": "idle", "model": model, "sid": s["id"]}

        try:
            md = json.loads(m["data"])
        except Exception:
            md = {}

        if md.get("role") != "assistant":
            return {"state": "queued", "model": model, "sid": s["id"], "mid": m["id"]}

        parts = cur.execute(
            "select json_extract(data,'$.type') t,"
            " json_extract(data,'$.text') tx,"
            " json_extract(data,'$.tokens.output') out_t,"
            " json_extract(data,'$.tokens.reasoning') rea_t,"
            " time_created tc"
            " from part where message_id=? order by time_created",
            (m["id"],),
        ).fetchall()

        start_t = finish_t = None
        out_t = rea_t = 0
        wchars = 0.0
        tools = 0
        for r in parts:
            t = r["t"]
            if t == "step-start" and start_t is None:
                start_t = r["tc"]
            elif t in ("text", "reasoning"):
                wchars += weighted_len(r["tx"] or "")
            elif t == "step-finish":
                finish_t = r["tc"]
                out_t += r["out_t"] or 0
                rea_t += r["rea_t"] or 0
            elif t == "tool":
                tools += 1

        if start_t is None:
            start_t = m["time_created"]

        return {
            "state": "run" if (md.get("time") or {}).get("completed") is None else "done",
            "sid": s["id"],
            "mid": m["id"],
            "model": model,
            "wchars": wchars,
            "start": start_t,
            "finish": finish_t,
            "tokens": (out_t + rea_t) if finish_t else 0,
            "tools": tools,
        }

    def recent_steps(self, limit=8):
        """回填最近若干已完成步骤，让中位数在启动时就有值。"""
        cur = self.con.cursor()
        s = self._latest_session(cur)
        if s is None:
            return []
        rows = cur.execute(
            "select id, time_created, data from message where session_id=? "
            "and json_extract(data,'$.role')='assistant' "
            "order by time_created desc limit 30",
            (s["id"],),
        ).fetchall()
        out = []
        for r in rows:
            try:
                md = json.loads(r["data"])
            except Exception:
                continue
            if not (md.get("time") or {}).get("completed"):
                continue
            parts = cur.execute(
                "select json_extract(data,'$.type') t,"
                " json_extract(data,'$.tokens.output') o,"
                " json_extract(data,'$.tokens.reasoning') rr,"
                " time_created tc from part where message_id=? order by time_created",
                (r["id"],),
            ).fetchall()
            start = next((x["tc"] for x in parts if x["t"] == "step-start"), r["time_created"])
            fin = next((x["tc"] for x in parts if x["t"] == "step-finish"), None)
            if not fin:
                continue
            tok = sum((x["o"] or 0) + (x["rr"] or 0) for x in parts if x["t"] == "step-finish")
            dur = (fin - start) / 1000.0
            if tok > 0 and dur > 0.3:
                out.append((tok, dur))
            if len(out) >= limit:
                break
        out.reverse()
        return out


def weighted_len(s):
    """CJK 记 1、其它记 0.25，再由校准系数吸收剩余偏差。"""
    if not s:
        return 0.0
    cjk = 0
    for ch in s:
        o = ord(ch)
        if 0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF:
            cjk += 1
    return cjk + (len(s) - cjk) * 0.25
