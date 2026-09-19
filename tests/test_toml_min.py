import tomllib

import pytest
from claude_backup import toml_min


def test_dumps_table_roundtrips_through_tomllib():
    text = toml_min.dumps_table("mcp_servers.figma", {"command": "npx", "args": ["-y", "x"], "env": {"A": "1", "B": 'q"uote'}})
    assert tomllib.loads(text) == {"mcp_servers": {"figma": {"command": "npx", "args": ["-y", "x"], "env": {"A": "1", "B": 'q"uote'}}}}
    assert text.startswith("[mcp_servers.figma]\n")
    assert "\n[mcp_servers.figma.env]\n" in text


def test_dumps_table_url_form():
    assert toml_min.dumps_table("mcp_servers.f", {"url": "https://x/mcp"}) == '[mcp_servers.f]\nurl = "https://x/mcp"\n'


def test_find_table_span_includes_subtables_and_stops_at_next_table():
    doc = 'model = "x"\n\n[mcp_servers.a]\ncommand = "a"\n\n[mcp_servers.a.env]\nK = "v"\n\n[mcp_servers.ab]\ncommand = "ab"\n\n[features]\nx = true\n'
    start, end = toml_min.find_table_span(doc, "mcp_servers.a")
    assert doc[start:end] == '[mcp_servers.a]\ncommand = "a"\n\n[mcp_servers.a.env]\nK = "v"\n\n'
    assert toml_min.find_table_span(doc, "mcp_servers.zzz") is None


def test_find_table_span_last_table_runs_to_eof():
    doc = '[mcp_servers.a]\ncommand = "a"\n'
    assert toml_min.find_table_span(doc, "mcp_servers.a") == (0, len(doc))


def test_find_table_span_header_with_trailing_comment():
    doc = '[mcp_servers.a] # note\ncommand = "a"\n\n[features] # x\nx = true\n'
    start, end = toml_min.find_table_span(doc, "mcp_servers.a")
    assert doc[start:end] == '[mcp_servers.a] # note\ncommand = "a"\n\n'


def test_dumps_table_omits_none_values():
    text = toml_min.dumps_table("t", {"a": "1", "b": None})
    assert tomllib.loads(text) == {"t": {"a": "1"}}
    assert "b" not in text


def test_dumps_table_escapes_del_character():
    text = toml_min.dumps_table("t", {"a": "x\x7fy"})
    assert "\\u007f" in text
    assert tomllib.loads(text) == {"t": {"a": "x\x7fy"}}


def test_dumps_table_unsupported_type_names_the_key():
    with pytest.raises(TypeError, match=r"unsupported TOML value at t\.a: object"):
        toml_min.dumps_table("t", {"a": object()})
