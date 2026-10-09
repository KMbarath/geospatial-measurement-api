"""Make attribute values JSON-safe."""
import base64
import datetime as dt
import decimal
import math
from typing import Any


def sanitize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, decimal.Decimal):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize(v) for v in value]
    return str(value)
