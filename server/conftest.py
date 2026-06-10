"""Pytest 启动钩子：把 ``server/`` 加到 ``sys.path``。

这样 ``tests/`` 下可以直接 ``from adapters import ...`` / ``from main import ...``，
而不需要把 ``server`` 改成一个发布到 PyPI 的 package。
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
