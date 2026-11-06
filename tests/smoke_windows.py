"""Windows 端手工冒烟测试（不进 CI）。

需要：Windows + 本机正在运行的 OpenCode 桌面版 + 带 tkinter 的 Python。

用法：
    python tests/smoke_windows.py
    python tests/smoke_windows.py --no-ui    # 只测数据与配置

它不会写入 OpenCode 的任何文件；配置写入被临时屏蔽，不会改动你的 config.json。
"""

import os
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from oc_tps import config  # noqa: E402
from oc_tps.engine import Engine  # noqa: E402
from oc_tps.source import Source, find_db  # noqa: E402
from oc_tps.strings import Translator, detect_language  # noqa: E402

RESULTS = []
ERROR_LOG_BASE = None


def check(name, fn):
    try:
        detail = fn()
        RESULTS.append((True, name, detail or ""))
        print("  PASS  %-34s %s" % (name, detail or ""))
    except Exception as e:
        RESULTS.append((False, name, repr(e)))
        print("  FAIL  %-34s %r" % (name, e))
        traceback.print_exc()


class FakeClient:
    """可控的客户端窗口，用来测停靠逻辑。"""

    def __init__(self, rect=(100, 100, 1100, 800), state="ok"):
        self.rect = rect
        self.mode = state

    def find(self):
        return None

    def state(self):
        return (self.mode, self.rect if self.mode == "ok" else None)

    def virtual_screen(self):
        return (0, 0, 3840, 2160)


def main():
    only_data = "--no-ui" in sys.argv
    global ERROR_LOG_BASE
    _e = config.log_path("error.log")
    ERROR_LOG_BASE = os.path.getsize(_e) if os.path.exists(_e) else 0
    db = find_db()
    print("数据库:", db or "未找到")
    if not db:
        print("跳过：没有可用的 opencode.db")
        return 2

    print("\n[1] 配置")
    check("默认值可加载", lambda: config.load(os.path.join(tempfile.mkdtemp(), "none.json"))["poll_ms"] == 400)

    def cfg_roundtrip():
        tmp = os.path.join(tempfile.mkdtemp(), "config.json")
        cfg = config.load(tmp)
        cfg["follow"] = "bl"
        cfg["window"]["width"] = 300
        assert config.save(cfg, tmp)
        again = config.load(tmp)
        assert again["follow"] == "bl", again["follow"]
        assert again["window"]["width"] == 300
        assert again["window"]["height"] == 128, "深层合并丢了默认值"
        return "写入/读回/深合并 OK"

    check("配置读写与深合并", cfg_roundtrip)
    check("字体按平台兜底", lambda: config.font_family("ui", {"fonts": {}}) != "")

    print("\n[2] 数据源")
    check("打开数据库并探测 schema", lambda: Source(db).check_schema() is None)

    def read_state():
        d = Engine(Source(db)).tick()
        assert d.get("state"), d
        return "state=%s model=%s" % (d.get("state"), d.get("model"))

    check("取到当前状态", read_state)

    def bad_db():
        tmp = os.path.join(tempfile.mkdtemp(), "fake.db")
        import sqlite3
        sqlite3.connect(tmp).execute("create table t(x)").connection.commit()
        try:
            Source(tmp)
        except Exception as e:
            return type(e).__name__ + ": " + str(e)[:40]
        raise AssertionError("没有抛错")

    check("结构不符时抛错", bad_db)

    print("\n[3] 文案")
    check("中文文案", lambda: Translator("zh")("state.run") == "生成")
    check("英文文案", lambda: Translator("en")("state.run") == "Generating")
    check("未知键回退", lambda: Translator("en")("no.such.key") == "no.such.key")
    check("自动识别语言", lambda: detect_language("auto") in ("zh", "en"))

    if only_data:
        return summary()

    print("\n[4] 界面")
    import ctypes
    from ctypes import wintypes

    from oc_tps.ui_win import UI

    saved_save = config.save
    config.save = lambda *a, **k: True          # 不污染用户配置
    try:
        cfg = config.load()
        tr = Translator("zh")
        app = UI(Engine(Source(db)), cfg, tr)

        def window_ready():
            for _ in range(20):
                app.root.update()
                time.sleep(0.1)
            h = ctypes.windll.user32.FindWindowW(None, "oc-tps-hud")
            assert h, "窗口不存在"
            r = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(h, ctypes.byref(r))
            visible = bool(ctypes.windll.user32.IsWindowVisible(h))
            if app.client.state()[0] == "ok":
                assert visible, "客户端可见，但浮层没有显示"
            else:
                assert not visible, "客户端不可见，浮层却还显示着（应自动隐藏）"
            if app.layout == "bar":
                exp_w = min(app.base_w, 1000 - 2 * app.margin)
                exp_h = cfg["window"]["bar_height"]
            else:
                exp_w, exp_h = cfg["window"]["width"], cfg["window"]["height"]
            assert (r.right - r.left, r.bottom - r.top) == (exp_w, exp_h), \
                (r.right - r.left, r.bottom - r.top)
            return "%dx%d 可见" % (r.right - r.left, r.bottom - r.top)

        check("窗口创建且可见", window_ready)

        def dock_br():
            app.client = FakeClient((100, 100, 1100, 800))
            app.follow.set("br")
            app._pos = None
            app.dock()
            app.root.update()
            x, y = app._pos
            if app.layout == "bar":
                assert x == 100 + (1000 - app.W) // 2, x
            else:
                assert x == 1100 - app.W - app.margin, (x, app.W, app.margin)
            assert y == 800 - app.H - (app.margin + app.bottom_offset), y
            return "落点 (%d,%d)" % (x, y)

        check("右下角停靠", dock_br)

        def switch_bl():
            app.follow.set("bl")
            app._pos = None
            app.dock()
            app.root.update()
            x, y = app._pos
            if app.layout == "bar":
                assert x == 100 + (1000 - app.W) // 2, x
            else:
                assert x == 100 + app.margin, x
            return "落点 (%d,%d)" % (x, y)

        check("切左下角", switch_bl)

        def follow_move():
            app.follow.set("br")
            app.client = FakeClient((300, 200, 1300, 900))
            app._pos = None
            app.dock()
            app.root.update()
            if app.layout == "bar":
                assert app._pos[0] == 300 + (1000 - app.W) // 2, app._pos
            else:
                assert app._pos[0] == 1300 - app.W - app.margin
            return "跟随移动 OK"

        check("客户端移动后跟随", follow_move)

        def hide_on_min():
            app.client = FakeClient(state="min")
            app.dock()
            app.root.update()
            assert app.root.state() == "withdrawn", app.root.state()
            app.client = FakeClient((100, 100, 1100, 800))
            app.dock()
            app.root.update()
            assert app.root.state() == "normal", app.root.state()
            return "最小化隐藏 / 还原恢复"

        check("最小化联动", hide_on_min)

        def refresh_states():
            seen = set()
            for st in ("run", "ttft", "wait", "done", "queue", "idle", "error", "noschema", "nodata"):
                app.engine.tick = lambda s=st: {"state": s, "model": "m", "rate": 120.0,
                                                "tokens": 2000, "elapsed": 30, "recent": 150.0}
                app.refresh()
                app.root.update()
                seen.add(st)
            return "9 种状态渲染无异常"

        check("状态渲染", refresh_states)

        def english():
            app.tr = Translator("en")
            app.refresh()
            app.root.update()
            return "英文文案渲染 OK"

        check("英文界面", english)

        def fit_rules():
            f = app.f_status
            full = "Generating · deepseek-v4.1-flash"
            tail = "deepseek-v4.1-flash"
            assert app.fit(full, f.measure(full) + 1) == full, "够宽时应原样返回"
            assert app.fit(full, f.measure(tail) + 2) == tail, "放不下时应只留模型名"
            tiny = app.fit(full, f.measure(tail) // 2)
            assert "…" in tiny, tiny
            return "整串 / 保模型名 / 左截断 三档 OK"

        check("文案截断策略", fit_rules)

        check("本次运行无新增异常", no_new_errors)

        app.root.destroy()
    finally:
        config.save = saved_save

    return summary()


def no_new_errors():
    p = config.log_path("error.log")
    size = os.path.getsize(p) if os.path.exists(p) else 0
    if size > (ERROR_LOG_BASE or 0):
        raise AssertionError("error.log 新增了内容")
    return "error.log 未增长"


def summary():
    ok = sum(1 for r in RESULTS if r[0])
    bad = len(RESULTS) - ok
    print("\n结果：%d 通过，%d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
