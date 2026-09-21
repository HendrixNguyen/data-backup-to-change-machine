# data-backup-to-change-machine

A Python 3.11+, stdlib-only CLI that exports this machine's Claude Code configuration
(your personal `~/.claude`, and optionally an `os-claude-harness` checkout's `.claude/`)
into a neutral, committable bundle, and restores it on another machine — into Claude
Code itself, or into Codex, Antigravity, OpenCode, or Kilo Code.

> **Secrets never land in the bundle in plaintext.** Export lifts anything that looks
> like a credential (tokens, keys, passwords, auth headers, URLs with embedded
> userinfo/query secrets, `env`/`headers` blocks) out into `${VAR}` placeholders. The
> real values are only ever stored **encrypted**, in `secrets.env.age`. The plaintext
> `secrets.env` is gitignored and does not survive a successful export — it's written,
> immediately encrypted, and shredded. As a last line of defence, export **refuses to
> finish** if a raw credential-shaped string (an Anthropic/OpenAI/GitHub/GitLab/Slack/AWS
> key, a private key block, a bearer token, …) is still sitting in the bundle.

## New machine — restore

### macOS

```bash
brew install git
git clone https://github.com/HendrixNguyen/data-backup-to-change-machine.git ~/Workspaces/common/data-backup-to-change-machine
cd ~/Workspaces/common/data-backup-to-change-machine
./doctor.sh                   # installs Python 3.11+ and age if needed, writes nothing else
# optional: put your age key at ~/.config/age/keys.txt to get secrets back
./restore.sh --dry-run        # read the plan
./restore.sh                  # apply (merge: your existing files win)
# run the printed `claude plugin install …` lines
./doctor.sh                   # verify
# harness, after cloning os-claude-harness:
./restore.sh --scope harness --harness-path ~/Workspaces/common/claude-harness/os-claude-harness
```

### Linux

```bash
sudo apt-get update && sudo apt-get install -y git   # or: sudo dnf install -y git
git clone https://github.com/HendrixNguyen/data-backup-to-change-machine.git ~/Workspaces/common/data-backup-to-change-machine
cd ~/Workspaces/common/data-backup-to-change-machine
./doctor.sh                   # installs Python 3.11+ and age if needed, writes nothing else
# optional: put your age key at ~/.config/age/keys.txt to get secrets back
./restore.sh --dry-run        # read the plan
./restore.sh                  # apply (merge: your existing files win)
# run the printed `claude plugin install …` lines
./doctor.sh                   # verify
# harness, after cloning os-claude-harness:
./restore.sh --scope harness --harness-path ~/Workspaces/common/claude-harness/os-claude-harness
```

### Windows (PowerShell)

```powershell
winget install --id Git.Git -e
git clone https://github.com/HendrixNguyen/data-backup-to-change-machine.git $HOME\Workspaces\common\data-backup-to-change-machine
cd $HOME\Workspaces\common\data-backup-to-change-machine
.\doctor.ps1                  # installs Python 3.11+ and age if needed, writes nothing else
# optional: put your age key at %USERPROFILE%\.config\age\keys.txt to get secrets back
.\restore.ps1 --dry-run       # read the plan
.\restore.ps1                 # apply (merge: your existing files win)
# run the printed `claude plugin install …` lines
.\doctor.ps1                  # verify
# harness, after cloning os-claude-harness:
.\restore.ps1 --scope harness --harness-path $HOME\Workspaces\common\claude-harness\os-claude-harness
```

`restore` never overwrites something that's already there and identical, and by default
never overwrites something that differs — it reports `skip (differs)` and leaves your
copy alone. Pass `--force` to let the bundle win on a specific unit (see Troubleshooting).

Plugins aren't installed automatically — restore only prints the `claude plugin install
<name>@<marketplace>` commands from the bundle's `personal/plugins.json`; run the ones
you want yourself.

`restore` ends by verifying what it wrote (skills have valid frontmatter, MCP servers
appear in the target's config, no unresolved `${VAR}` is left behind, `claude
--version`/`claude mcp list` if the `claude` CLI is present) and exits non-zero if any
check fails — read the PASS/FAIL list it prints; a failure there doesn't necessarily mean
the restore itself went wrong (see Troubleshooting).

## Other tools

Point `--target` at whichever editor you want the bundle restored into:

```bash
./restore.sh --target codex
./restore.sh --target antigravity
./restore.sh --target opencode
./restore.sh --target kilo
./restore.sh --target all       # every target above, one plan + verify per target
```

| target | skills dir | agents | commands | harness scope |
|---|---|---|---|---|
| `claude` | `~/.claude/skills` | yes — `~/.claude/agents` | yes | yes |
| `codex` | `~/.codex/skills` | no | no | no |
| `opencode` | `~/.config/opencode/skills` | yes — `agents/` (plural) | yes — `commands/` | no |
| `antigravity` | `~/.gemini/antigravity/skills` | no | yes — `global_workflows/` | no |
| `kilo` | `~/.kilocode/skills` | yes — as custom modes in `custom_modes.yaml` | no | no |

Honest limitations, not bugs:

- **Codex**, with `--force` on a server that already exists as an inline
  `mcp_servers.<name> = {…}` table, rewrites it as a standard `[mcp_servers.<name>]`
  table — the shape changes, the content doesn't.
- **OpenCode**'s `opencode.json` is parsed as JSONC but always **written back as plain
  JSON**, so hand-written comments are lost on that file; the pre-write `.bak` still has
  them.
- **Harness scope is Claude-only.** Every other target gets a notice
  (`harness scope is Claude-only — skipped for --target <name>`) and only restores the
  `personal` scope.
- A target with no agent or command concept (e.g. Codex has neither) skips those units
  with a notice instead of guessing at an equivalent.

## Existing machine — export

```bash
./export.sh
git add -A && git commit -m "backup: $(date +%F)"
git push   # do this yourself
```

Export reads your `~/.claude` (and, with `--scope harness`/`all`, an `os-claude-harness`
checkout) **read-only** — nothing there is modified. It refuses to run against a dirty
bundle checkout unless you pass `--yes`.

To get secrets back on restore, set up an age key once:

```bash
age-keygen -o ~/.config/age/keys.txt
```

Then put the **public** key it prints in `.age-recipient` at the repo root (gitignored,
so this stays local) or export it as `AGE_RECIPIENT`, and re-export:

```bash
echo "age1..." > .age-recipient
./export.sh
```

With a recipient configured, export encrypts the collected secrets into
`secrets.env.age` — gitignored by default, so it stays on this machine only. Pass
`--commit-secrets` if you want that encrypted file committed into the repo (it's still
useless without your private key, but decide that deliberately):

```bash
./export.sh --commit-secrets
```

## Flags

| flag | subcommands | meaning |
|---|---|---|
| `--scope personal\|harness\|all` | export, restore, doctor | what to read/write (default `all`) |
| `--harness-path DIR` | export, restore, doctor | the `os-claude-harness` checkout (default: `$CLAUDE_PROJECT_DIR`, then `~/optisigns`, then asked interactively) |
| `--bundle DIR` | export, restore, doctor | bundle directory (default: `$CLAUDE_BACKUP_DIR`, then this repo) |
| `--yes` | export, restore, doctor | skip confirmations (export: also allows a dirty bundle checkout) |
| `--target claude\|codex\|antigravity\|opencode\|kilo\|all` | restore, doctor | which tool to restore into / doctor (default `claude`) |
| `--only PATH` | restore | restrict to one bundle-relative unit or kind, e.g. `--only personal/skills/foo` (repeatable) |
| `--dry-run` | restore | print the plan, write nothing, install nothing |
| `--force` | restore | let the bundle overwrite a unit that already differs on this machine |
| `--remap OLD=NEW` | restore | rewrite a project path prefix for MCP project servers (repeatable) |
| `--commit-secrets` | export | commit the encrypted `secrets.env.age` instead of leaving it gitignored |

Environment variables:

| variable | meaning |
|---|---|
| `CLAUDE_BACKUP_DIR` | default bundle directory, if `--bundle` isn't passed |
| `AGE_RECIPIENT` | age public key for encryption, if `.age-recipient` isn't present |

## Troubleshooting

- **Home path differs between machines.** A restored MCP server's project path won't
  exist on the new machine. Remap it: `--remap /Users/old=/home/new`.
- **A unit exists both locally and in the bundle.** The plan shows `skip (differs)`, and
  restore leaves your copy alone. To take the bundle's version:
  `./restore.sh --force --only personal/skills/<name>`.
- **No age key.** Placeholders (`${VAR}`) are left in restored files instead of real
  values; `restore`'s final verify step lists them under "missing secrets (no key)" —
  that's expected, not a failure.
- **Bundle hash mismatch after a Windows clone.** Usually
  `git config core.autocrlf true` rewriting line endings on checkout. The repo already
  ships a `.gitattributes` with `* -text` to prevent this; if you still see it, run
  `git config core.autocrlf false` in your clone.
- **Hooks don't run on Windows.** Hook scripts from `harness/hooks` are restored
  byte-for-byte; POSIX shell scripts need Git Bash or WSL to actually execute there.
- **`restore --scope harness` on a fresh clone shows mostly `skip`.** That's expected —
  it means the harness checkout already has what the bundle has, not that the restore
  failed.
- **A target skips your agents or commands with a notice.** Expected when that tool has
  no equivalent concept (see the capability table above) — nothing was lost, there's just
  nowhere on that target to put it.
- **`restore` exits 1 even though the plan applied cleanly.** Its final verify step can
  fail for reasons that have nothing to do with the restore itself — most commonly a
  skill's `SKILL.md` that was already missing valid frontmatter before you ever exported
  it, or a literal `${SOME_VAR}`-shaped string that was already part of a skill's own
  documentation (a shell example, a plugin's own `${CLAUDE_PLUGIN_ROOT}` template
  variable) getting flagged by the "placeholders resolved" check, which can't tell that
  apart from a real unresolved secret. Read the PASS/FAIL list before assuming the
  restore failed.

## Development

```bash
python3 -m pip install pytest && python3 -m pytest -q
```

Use a Python 3.11+ interpreter — on this Mac that's `python3.11`, not the system
`python3`. 169 tests pass (4 skipped) as of this writing.

Layout:

- `bin/backup.py` — argument parsing / entry point.
- `bin/claude_backup/` — the library: `common.py` (paths/scopes), `content.py` (copying
  skills/agents/commands/hooks), `secrets.py` (placeholderizing + age), `mcp.py`
  (MCP server extraction/merge), `manifest.py` (`bundle.json`), `plan.py` (add/skip/replace
  planning), `merge.py` (atomic writes, backups), `preflight.py` (tool checks/installs),
  `verify.py` (post-restore checks), `export_cmd.py` / `restore_cmd.py` (the two
  subcommands), `targets/` (one adapter per tool: `claude.py`, `codex.py`, `opencode.py`,
  `antigravity.py`, `kilo.py`).
- `targets/` (adapters, above) decide where each tool's skills/agents/commands/MCP live
  and how to write them.
- `tests/` — pytest suite, one file roughly per module above.
- Generated, not committed by hand: `personal/` and `harness/` (the exported content
  itself), `bundle.json` (the manifest — per-file sha256, symlink origins, executable
  bits, what was exported and from where), `secrets.required` (the `${VAR}` names an
  export produced, so a restore without an age key knows what's missing).
