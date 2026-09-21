import shutil, subprocess
import pytest
from claude_backup import common, secrets


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


def test_top_level_secret_key_redacted():
    out, found = secrets.placeholderize_server("personal", "svc", {"Authorization": "Bearer x"})
    assert out["Authorization"] == "${PERSONAL_MCP_SVC_AUTHORIZATION}"
    assert found == {"PERSONAL_MCP_SVC_AUTHORIZATION": "Bearer x"}


def test_nested_dict_is_walked():
    """A container named like a secret redacts every leaf, exactly as env/headers do: we would rather
    over-redact an operational value (recoverable from the key) than ship one credential in the clear."""
    out, found = secrets.placeholderize_server("personal", "svc", {"auth": {"apiKey": "z", "mode": "oauth"}})
    assert out["auth"]["apiKey"] == "${PERSONAL_MCP_SVC_APIKEY}"
    assert out["auth"]["mode"] == "${PERSONAL_MCP_SVC_MODE}"
    assert found == {"PERSONAL_MCP_SVC_APIKEY": "z", "PERSONAL_MCP_SVC_MODE": "oauth"}


def test_plain_nested_dict_only_redacts_secret_keys():
    out, found = secrets.placeholderize_server("personal", "svc", {"opts": {"apiKey": "z", "mode": "oauth"}})
    assert out["opts"]["apiKey"] == "${PERSONAL_MCP_SVC_APIKEY}"
    assert out["opts"]["mode"] == "oauth"
    assert found == {"PERSONAL_MCP_SVC_APIKEY": "z"}


def test_args_flag_then_value_redacted():
    out, found = secrets.placeholderize_server("personal", "svc", {"args": ["--token", "s", "--verbose"]})
    assert out["args"] == ["--token", "${PERSONAL_MCP_SVC_ARG_TOKEN}", "--verbose"]
    assert found == {"PERSONAL_MCP_SVC_ARG_TOKEN": "s"}


def test_args_inline_flag_value_redacted():
    out, found = secrets.placeholderize_server("personal", "svc", {"args": ["--api-key=abc"]})
    assert out["args"] == ["--api-key=${PERSONAL_MCP_SVC_ARG_API_KEY}"]
    assert found == {"PERSONAL_MCP_SVC_ARG_API_KEY": "abc"}


def test_url_with_userinfo_redacted():
    out, found = secrets.placeholderize_server("personal", "svc", {"url": "https://u:p@host/mcp"})
    assert out["url"] == "${PERSONAL_MCP_SVC_URL}"
    assert found == {"PERSONAL_MCP_SVC_URL": "https://u:p@host/mcp"}


def test_non_secret_fields_untouched():
    server = {"command": "npx", "type": "stdio", "args": ["-y", "pkg", "--port", "3000"]}
    out, found = secrets.placeholderize_server("personal", "svc", server)
    assert out == server and found == {}


def test_var_name_collision_disambiguates_and_warns(monkeypatch):
    warnings = []
    monkeypatch.setattr(secrets.common, "warn", warnings.append)
    out, found = secrets.placeholderize_server("personal", "svc", {"api-key": "AAA", "api_key": "BBB"})
    assert found == {"PERSONAL_MCP_SVC_API_KEY": "AAA", "PERSONAL_MCP_SVC_API_KEY_2": "BBB"}
    assert out["api-key"] == "${PERSONAL_MCP_SVC_API_KEY}"
    assert out["api_key"] == "${PERSONAL_MCP_SVC_API_KEY_2}"
    assert len(warnings) == 1 and "api-key" in warnings[0] and "api_key" in warnings[0]


def test_same_value_reuses_one_var(monkeypatch):
    warnings = []
    monkeypatch.setattr(secrets.common, "warn", warnings.append)
    out, found = secrets.placeholderize_server("personal", "svc", {"api-key": "SAME", "api_key": "SAME"})
    assert found == {"PERSONAL_MCP_SVC_API_KEY": "SAME"}
    assert out["api-key"] == out["api_key"] == "${PERSONAL_MCP_SVC_API_KEY}"
    assert warnings == []


def test_settings_var_name_collision_disambiguates(monkeypatch):
    monkeypatch.setattr(secrets.common, "warn", lambda m: None)
    out, found = secrets.placeholderize_settings("personal", {"env": {"MY-TOKEN": "a", "MY_TOKEN": "b"}})
    assert found == {"PERSONAL_SETTINGS_MY_TOKEN": "a", "PERSONAL_SETTINGS_MY_TOKEN_2": "b"}
    assert out["env"]["MY_TOKEN"] == "${PERSONAL_SETTINGS_MY_TOKEN_2}"


def test_env_file_roundtrip_escapes_newlines_and_backslashes(tmp_path):
    f = tmp_path / "secrets.env"
    values = {"A": "line1\nline2", "B": "c:\\path\\x", "C": "cr\rlf"}
    secrets.write_env(f, values)
    assert len(f.read_text().splitlines()) == 3  # one line per var despite the embedded newline
    assert secrets.read_env(f) == values


def test_write_env_rejects_key_with_equals(tmp_path):
    with pytest.raises(common.BackupError):
        secrets.write_env(tmp_path / "secrets.env", {"A=B": "1"})


def test_age_decrypt_missing_file_raises_backup_error(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "age_available", lambda: True)

    def boom(*a, **k):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(secrets.common, "run", boom)
    with pytest.raises(common.BackupError, match="not found"):
        secrets.age_decrypt(tmp_path / "secrets.env.age", tmp_path / "keys.txt")


def test_age_decrypt_wrong_key_raises_backup_error(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "age_available", lambda: True)

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, ["age"], output="", stderr="no identity matched")

    monkeypatch.setattr(secrets.common, "run", boom)
    with pytest.raises(common.BackupError, match="no identity matched"):
        secrets.age_decrypt(tmp_path / "secrets.env.age", tmp_path / "keys.txt")


def test_scan_for_leaks_finds_planted_token(tmp_path):
    (tmp_path / "personal").mkdir()
    f = tmp_path / "personal" / "s.json"
    f.write_text('{"a": "ghp_' + "A" * 24 + '"}\n')
    hits = secrets.scan_for_leaks(tmp_path)
    assert [(h[0], h[1]) for h in hits] == [(f, 1)]


def test_scan_for_leaks_ignores_placeholders(tmp_path):
    (tmp_path / "personal").mkdir()
    (tmp_path / "personal" / "s.json").write_text('{"a": "${PERSONAL_MCP_F_AUTHORIZATION}"}\n')
    assert secrets.scan_for_leaks(tmp_path) == []


def test_scan_for_leaks_finds_inline_password(tmp_path):
    (tmp_path / "personal").mkdir()
    f = tmp_path / "personal" / "s.sh"
    f.write_text('''curl -d \'{"email":"a@b.c","password":"hunter2x","returnSecureToken":true}\'\n''')
    assert [(h[0], h[2]) for h in secrets.scan_for_leaks(tmp_path)] == [(f, "inline-password")]


def test_scan_for_leaks_ignores_placeholdered_password(tmp_path):
    (tmp_path / "personal").mkdir()
    (tmp_path / "personal" / "s.json").write_text('{"password": "${PERSONAL_SETTINGS_PASSWORD}"}\n')
    assert secrets.scan_for_leaks(tmp_path) == []
