"""命令行入口。"""

import argparse
import sys
import time

from . import __version__, config, logs
from .engine import Engine
from .strings import Translator, detect_language


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="oc-tps-hud",
                                 description="OpenCode 输出速度浮层（只读本地数据库）")
    ap.add_argument("--db", default="", help="opencode.db 路径（默认自动探测）")
    ap.add_argument("--config", default="", help="配置文件路径")
    ap.add_argument("--lang", default="", choices=["", "zh", "en"], help="界面语言")
    ap.add_argument("--dump", action="store_true", help="不显示界面，把每秒状态打印到终端")
    ap.add_argument("--version", action="store_true", help="打印版本号后退出")
    return ap.parse_args(argv)


def fatal(tr, title, msg):
    """有控制台就打印，无控制台（pythonw）才弹窗，避免脚本/CI 里卡在模态框。"""
    logs.write("error.log", "%s: %s" % (title, msg))
    has_console = sys.stdout is not None
    if has_console:
        try:
            print("%s: %s" % (title, msg), file=sys.stderr)
        except Exception:
            pass
        return 1
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, msg)
        root.destroy()
    except Exception:
        pass
    return 1


def main(argv=None):
    args = parse_args(argv)
    if args.version:
        print("oc-tps-hud %s" % __version__)
        return 0

    cfg = config.load(args.config or None)
    if args.lang:
        cfg["language"] = args.lang
    tr = Translator(detect_language(cfg.get("language", "auto")))

    from .source import SchemaError, Source, find_db

    db = find_db(args.db or cfg.get("db_path", ""))
    if not db:
        return fatal(tr, tr("err.title"), tr("err.nodb"))

    try:
        src = Source(db)
    except SchemaError as e:
        detail = "json1" if str(e) == "json1" else str(e)
        msg = tr("err.json1") if detail == "json1" else tr("err.schema", detail=detail)
        return fatal(tr, tr("err.title"), msg)

    engine = Engine(src)

    if args.dump:
        for _ in range(10):
            d = engine.tick()
            print("state=%-8s rate=%6.1f tokens=%8.0f elapsed=%6.1f model=%s" % (
                d.get("state"), d.get("rate") or 0, d.get("tokens") or 0,
                d.get("elapsed") or 0, d.get("model", "-")))
            time.sleep(0.5)
        return 0

    if sys.platform != "win32":
        return fatal(tr, tr("err.title"), tr("err.platform"))

    try:
        import tkinter  # noqa: F401
    except Exception:
        return fatal(tr, tr("err.title"), tr("err.notk"))

    from .ui_win import UI

    UI(engine, cfg, tr).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
