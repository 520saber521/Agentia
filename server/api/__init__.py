"""REST API 子包。当前仅一份 ``rest.py``，未来按 ``auth/upload/...`` 拆分。"""

from .rest import router

__all__ = ["router"]
