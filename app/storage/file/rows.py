"""行对象基类（替代 SQLAlchemy BaseModel/Base 的文件存储版本）。

- `Row` 为 @dataclass 基类：id/created_at/updated_at/deleted_at 公共字段 + 脏跟踪 + 序列化。
  子类 `@dataclass class Message(Row)` 自动继承公共字段（dataclass 继承）。
- 类名与模块路径保持不变 → serializers/编排/工具层 import 与属性访问零改动。
- `__setattr__` 钩子标脏（服务层直接字段赋值如 `doc.status = "chunking"` 可被捕获）。
- `to_dict/from_dict` 供 FileTable 序列化（datetime/uuid → ISO 字符串）。
"""

import uuid
from dataclasses import Field, dataclass, field
from datetime import UTC, datetime
from typing import Any, get_args, get_origin


def _jsonify(value: Any) -> Any:
    """datetime → isoformat；uuid → str；dict/list 递归；其余原样。"""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonify(v) for v in value]
    return value


def _dejsonify(value: Any, field_type: Any) -> Any:
    """JSON 值还原：uuid.UUID / datetime 类型字段还原（嵌套结构不还原——纯 JSON 载荷）。"""
    if value is None:
        return None
    if field_type is None:
        return value
    t = field_type
    if get_origin(t) is not None:
        t = get_args(t)[0]
    if t is uuid.UUID and isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return value
    if t is datetime and isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Row:
    """文件存储行：id 默认生成 + 时间戳 + 脏跟踪 + 序列化。"""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    deleted_at: datetime | None = None
    _dirty: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_dirty", False)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        object.__setattr__(self, name, value)
        # 业务字段赋值（非初始时间戳）→ 标脏 + 刷新 updated_at
        # （dataclass __init__ 的初始赋值也走这里，但 _dirty 随后由 __post_init__ 重置为 False）
        fields = getattr(self, "__dataclass_fields__", {})
        if name not in ("id", "created_at", "updated_at") and name in fields:
            object.__setattr__(self, "_dirty", True)
            object.__setattr__(self, "updated_at", _utcnow())

    def to_dict(self) -> dict[str, Any]:
        out = {}
        for f in getattr(self, "__dataclass_fields__", {}):
            if f == "_dirty":
                continue
            out[f] = _jsonify(getattr(self, f))
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Row":
        inst = cls.__new__(cls)
        fields = getattr(cls, "__dataclass_fields__", {})
        for k, v in data.items():
            if k == "_dirty":
                continue
            f = fields.get(k)
            ftype = f.type if isinstance(f, Field) else f  # Field 对象 → 类型
            object.__setattr__(inst, k, _dejsonify(v, ftype))
        object.__setattr__(inst, "_dirty", False)
        return inst

    def mark_clean(self) -> None:
        """落盘后清除脏标记（FileTable.register 调用）。"""
        object.__setattr__(self, "_dirty", False)
