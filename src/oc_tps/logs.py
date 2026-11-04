"""极简文件日志：单文件 + 超限滚动，不写系统日志、不发网络。"""

import os
import time
import traceback

from . import config

MAX_BYTES = 256 * 1024


def write(name, msg):
    path = config.log_path(name)
    try:
        if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
            os.replace(path, path + ".1")
    except Exception:
        pass
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def exception(name, exc, tb=None):
    write(name, "".join(traceback.format_exception(type(exc), exc, tb or exc.__traceback__)))
