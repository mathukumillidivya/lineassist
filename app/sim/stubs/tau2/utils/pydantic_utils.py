"""Minimal versions of two tau2 helpers, without the addict dependency."""
from typing import Any, Dict, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T", bound=BaseModel)


class BaseModelNoExtra(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _merge(base: dict, update: dict) -> dict:
    for k, v in update.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def update_pydantic_model_with_dict(model_instance: T, update_data: Dict[str, Any]) -> T:
    return type(model_instance).model_validate(_merge(model_instance.model_dump(), dict(update_data)))
