"""双击入口（无控制台）：把 src 加进路径后启动。"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from oc_tps.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
