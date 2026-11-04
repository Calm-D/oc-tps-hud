"""配置：默认值 + 用户覆盖 + 跨平台目录。"""

import copy
import json
import os
import sys

APP_NAME = "oc-tps-hud"

DEFAULTS = {
    "follow": "br",              # br | bl | free
    "theme": "auto",             # auto | light | dark
    "alpha": 0.95,               # 0.5 ~ 1.0
    "language": "auto",          # auto | zh | en
    "db_path": "",               # 空 = 自动探测
    "poll_ms": 400,              # 数据刷新间隔
    "window": {
        "width": 268,
        "height": 128,
        "margin": 12,            # 距客户端窗口边缘的像素
    },
    "fonts": {
        "ui": "",                # 空 = 按平台选择
        "number": "",
    },
    "client_min_size": [480, 360],
    "debug": False,
}


def config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME)


def _ensure(d):
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass


def config_path():
    _ensure(config_dir())
    return os.path.join(config_dir(), "config.json")


def calibration_path():
    _ensure(config_dir())
    return os.path.join(config_dir(), "calibration.json")


def log_path(name):
    _ensure(config_dir())
    return os.path.join(config_dir(), name)


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path=None):
    path = path or config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
    except FileNotFoundError:
        user = {}
    except Exception:
        user = {}
    return _merge(DEFAULTS, user)


def save(cfg, path=None):
    path = path or config_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def font_family(which, cfg):
    """按平台给字体兜底，用户配置优先。"""
    user = (cfg.get("fonts") or {}).get(which) or ""
    if user:
        return user
    if sys.platform == "win32":
        return "Microsoft YaHei UI" if which == "ui" else "Segoe UI"
    if sys.platform == "darwin":
        return "PingFang SC" if which == "ui" else "Helvetica Neue"
    return "Noto Sans CJK SC" if which == "ui" else "DejaVu Sans"
