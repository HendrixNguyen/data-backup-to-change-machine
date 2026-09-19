"""Minimal TOML *writer* for MCP server tables (tomllib is read-only). Handles str, bool, int, float, list[str], dict[str,str]."""
from __future__ import annotations

import json
import re


def _scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # TOML basic strings share JSON escaping for our cases
    if isinstance(v, list):
        return "[" + ", ".join(_scalar(x) for x in v) + "]"
    raise TypeError(f"unsupported TOML value: {type(v).__name__}")


def dumps_table(name: str, data: dict) -> str:
    """Emit [name] with scalar keys, then one [name.sub] per dict-valued key."""
    lines = [f"[{name}]"]
    subs = []
    for k, v in data.items():
        if isinstance(v, dict):
            subs.append((k, v))
        else:
            lines.append(f"{k} = {_scalar(v)}")
    out = "\n".join(lines) + "\n"
    for k, v in subs:
        out += "\n" + dumps_table(f"{name}.{k}", v)
    return out


def find_table_span(doc: str, name: str) -> tuple[int, int] | None:
    """(start, end) of the '[name]' table incl. its '[name.*]' subtables, up to the next unrelated header or EOF."""
    header = re.compile(r"^\[" + re.escape(name) + r"\]\s*$", re.M)
    m = header.search(doc)
    if not m:
        return None
    start = m.start()
    nxt = re.compile(r"^\[(?!" + re.escape(name) + r"(?:\.|\]))[^\]]*\]", re.M)
    n = nxt.search(doc, m.end())
    return start, (n.start() if n else len(doc))
