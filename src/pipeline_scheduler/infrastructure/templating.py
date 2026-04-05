from jinja2 import Environment, StrictUndefined, Undefined
import yaml
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def render_pipeline(
    path: str, params: Dict[str, Any], strict: bool = True
) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # attempt to read metadata params without rendering
    meta_params = {}
    try:
        raw_obj = yaml.safe_load(content)
        if isinstance(raw_obj, dict):
            metadata = raw_obj.get("metadata") or {}
            meta_params = metadata.get("params") or {}
    except Exception:
        meta_params = {}

    merged = {}
    if isinstance(meta_params, dict):
        merged.update(meta_params)
    if isinstance(params, dict):
        merged.update(params)

    env = Environment(undefined=StrictUndefined if strict else Undefined)
    template = env.from_string(content)
    rendered = template.render(**merged)
    obj = yaml.safe_load(rendered)
    return obj
