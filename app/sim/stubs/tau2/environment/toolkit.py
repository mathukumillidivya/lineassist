"""Minimal tool registry: marks methods as tools and looks them up by name."""
from enum import Enum

TOOL_ATTR = "__tool__"


class ToolType(str, Enum):
    READ = "read"
    WRITE = "write"
    THINK = "think"
    GENERIC = "generic"


def is_tool(tool_type=ToolType.READ, mutates_state=None):
    def decorator(func):
        setattr(func, TOOL_ATTR, True)
        return func
    return decorator


class ToolKitBase:
    def __init__(self, db=None):
        self.db = db

    def has_tool(self, name: str) -> bool:
        return getattr(getattr(type(self), name, None), TOOL_ATTR, False)

    def use_tool(self, tool_name: str, **kwargs):
        if not self.has_tool(tool_name):
            raise ValueError(f"Tool '{tool_name}' not found.")
        return getattr(self, tool_name)(**kwargs)
