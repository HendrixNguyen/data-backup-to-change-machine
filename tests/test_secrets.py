import shutil, subprocess
import pytest
from claude_backup import secrets


def test_var_name_normalisation():
    assert secrets.var_name("personal", "mcp", "figma-remote", "Authorization") == "PERSONAL_MCP_FIGMA_REMOTE_AUTHORIZATION"
    assert secrets.var_name("harness", "settings", None, "MY TOKEN!") == "HARNESS_SETTINGS_MY_TOKEN_"


def test_placeholderize_mcp_server():
    server = {"type": "http", "url": "https://x.com/mcp?key=abc", "headers": {"Authorization": "Bearer t"},
              "env": {"API_KEY": "k", "PLAIN": "v"}, "command": "npx", "args": ["-y", "pkg"], "apiToken": "tt"}
    out, found = secrets.placeholderize_server("personal", "figma", server)
    assert out["url"] == "${PERSONAL_MCP_FIGMA_URL}"
    assert out["headers"]["Authorization"] == "${PERSONAL_MCP_FIGMA_AUTHORIZATION}"
    assert out["env"] == {"API_KEY": "${PERSONAL_MCP_FIGMA_API_KEY}", "PLAIN": "${PERSONAL_MCP_FIGMA_PLAIN}"}
    assert out["apiToken"] == "${PERSONAL_MCP_FIGMA_APITOKEN}"
    assert out["command"] == "npx" and out["args"] == ["-y", "pkg"]
    assert found == {"PERSONAL_MCP_FIGMA_URL": "https://x.com/mcp?key=abc", "PERSONAL_MCP_FIGMA_AUTHORIZATION": "Bearer t",
                     "PERSONAL_MCP_FIGMA_API_KEY": "k", "PERSONAL_MCP_FIGMA_PLAIN": "v", "PERSONAL_MCP_FIGMA_APITOKEN": "tt"}


def test_placeholderize_url_without_query_is_kept():
    out, found = secrets.placeholderize_server("personal", "s", {"url": "https://mcp.figma.com/mcp"})
    assert out["url"] == "https://mcp.figma.com/mcp" and found == {}


def test_placeholderize_settings_env_only():
    settings = {"env": {"MY_TOKEN": "tok", "PLAIN": "1"}, "permissions": {"allow": ["x"]}}
    out, found = secrets.placeholderize_settings("personal", settings)
    assert out["env"] == {"MY_TOKEN": "${PERSONAL_SETTINGS_MY_TOKEN}", "PLAIN": "${PERSONAL_SETTINGS_PLAIN}"}
    assert out["permissions"] == settings["permissions"]
    assert found == {"PERSONAL_SETTINGS_MY_TOKEN": "tok", "PERSONAL_SETTINGS_PLAIN": "1"}


def test_env_file_roundtrip(tmp_path):
    f = tmp_path / "secrets.env"
    secrets.write_env(f, {"B": "2", "A": "x=y z"})
    assert f.read_text() == "A=x=y z\nB=2\n"
    assert secrets.read_env(f) == {"A": "x=y z", "B": "2"}


def test_substitute_reports_unresolved():
    text = 'url "${A}" and "${B}"'
    out, missing = secrets.substitute(text, {"A": "1"})
    assert out == 'url "1" and "${B}"' and missing == ["B"]


def test_write_required(tmp_path):
    secrets.write_required(tmp_path / "secrets.required", {"Z": "1", "A": "2"})
    assert (tmp_path / "secrets.required").read_text() == "A\nZ\n"


@pytest.mark.skipif(not shutil.which("age") or not shutil.which("age-keygen"), reason="age not installed")
def test_age_roundtrip(tmp_path):
    key = tmp_path / "keys.txt"
    subprocess.run(["age-keygen", "-o", str(key)], check=True, capture_output=True)
    recipient = [l for l in key.read_text().splitlines() if l.startswith("# public key:")][0].split(":")[1].strip()
    plain = tmp_path / "secrets.env"; plain.write_text("A=1\n")
    enc = tmp_path / "secrets.env.age"
    secrets.age_encrypt(plain, enc, recipient)
    assert not plain.exists() and enc.exists()
    assert secrets.age_decrypt(enc, key) == {"A": "1"}
