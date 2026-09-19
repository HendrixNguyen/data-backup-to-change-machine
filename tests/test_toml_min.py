import tomllib
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
