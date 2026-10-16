# 011 — Installer checks that Claude can run inside the hooks

**Status:** implemented (uncommitted) on `009-aioutput-skills` (user decision) · **Date:** 2026-10-02 ·
**Builds on:** 001, 009, 010

## Problem

Skills run Claude with `--restricted`, which ignores `~/.claude/settings.json`. Many
setups keep their provider configuration in that file's `env` block, for example
Bedrock's `CLAUDE_CODE_USE_BEDROCK`. In those setups every skill fails with
`Not logged in`, but `claude auth status` reports logged in, because it does read the
file. The failure is silent: it shows up as a warning in `logs/hooks.log` only. This
was found live on 2026-10-02 (Bedrock, Windows).

## Decisions (from the user)

| # | Decision |
|---|----------|
| D1 | If Claude cannot run the way the hooks run it, **the install aborts** (exit 1) and asks for the variables to be set. |
| D2 | **Both checks**: a static check (which settings names are missing from the environment) and a live confined call. `--skip-claude-check` skips the live call for offline or CI installs. |
| D3 | The installer requires **claude CLI ≥ 2.1.287** (009's confinement minimum), not just presence. |
| D4 | TUTORIAL installation section: explain which environment variables are needed, **only the necessary ones**, per provider. |

## Facts this relies on (Claude Code docs, verified 2026-10-02)

- `--restricted` ignores user and project settings files. It still reads managed
  (policy) settings and `--settings`, and keeps `/login` OAuth credentials.
  (cli-reference)
- Bedrock: `CLAUDE_CODE_USE_BEDROCK=1`. The region comes from `AWS_REGION`, then
  `AWS_DEFAULT_REGION`, then the AWS profile, then `us-east-1`. Credentials come from
  the AWS chain: `AWS_PROFILE`, access keys, or `AWS_BEARER_TOKEN_BEDROCK`.
- Vertex: `CLAUDE_CODE_USE_VERTEX=1`, `CLOUD_ML_REGION` and `ANTHROPIC_VERTEX_PROJECT_ID`.
  Credentials come from gcloud ADC or `GOOGLE_APPLICATION_CREDENTIALS`.
- Foundry: `CLAUDE_CODE_USE_FOUNDRY=1` and `ANTHROPIC_FOUNDRY_RESOURCE` (or `_BASE_URL`).
  Credentials are `ANTHROPIC_FOUNDRY_API_KEY`, `_AUTH_TOKEN` or Entra ID. Model pins
  `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL` are required.
- API key: `ANTHROPIC_API_KEY`. Gateway: `ANTHROPIC_BASE_URL` plus `ANTHROPIC_AUTH_TOKEN`.
- Network: `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `NODE_EXTRA_CA_CERTS`,
  `CLAUDE_CODE_CERT_STORE`, `CLAUDE_CODE_CLIENT_CERT`/`_KEY`/`_KEY_PASSPHRASE`.
- `CLAUDECODE=1` is set in processes started from inside a Claude Code session.
- `--restricted` also confines file tools to the working directory. This corrects
  010's risk 2, which assumed the boundary was an instruction only.

## Design (`install.py`)

Pure functions, with side effects injected (same pattern as `check_hook_python`).

- `RELEVANT_ENV`: the allowlist of names above (provider, credentials, model pins,
  gateway, network). Only these are reported. Unrelated settings `env` entries, such
  as telemetry toggles, are ignored.
- `IGNORED_AUTH_SETTINGS = ("apiKeyHelper", "awsAuthRefresh", "awsCredentialExport")`.
  These are settings keys, not variables. The hooks never use them; replace them with
  environment-based credentials.
- `read_user_settings(path)` returns a dict. A missing or malformed file, or a non-dict
  value, gives `{}`. The path is `$CLAUDE_CONFIG_DIR/settings.json` or
  `~/.claude/settings.json`.
- `missing_env(settings, environ)` returns the sorted names in `settings["env"]` that are
  in `RELEVANT_ENV` and absent from `environ`. **Names only: values are never printed
  or copied.**
- `ignored_settings(settings)` returns the `IGNORED_AUTH_SETTINGS` keys present.
- `probe_claude(command, run)` makes one call: `claude -p --output-format json
  --max-turns 1 <CONFINEMENT_ARGS from src/claude_bridge.py>`, with the prompt "Reply
  with the single word OK." on stdin and a 90 s timeout. This is exactly the hook's
  confinement, so a pass here means a pass in the hooks. It returns `(ok, error)`, and
  the error text comes from the bridge's payload parser.
- `check_claude_auth(settings, environ, probe, skip)` returns a `ClaudeAuthResult` with
  `status` (`ok`, `failed` or `skipped`), `missing`, `ignored`, `error` and `notes`:
  - live call passes: `ok`. If names are still missing, it adds a note: "not applied to
    the hooks: …". These are typically model pins, and the call works without them.
  - live call fails: `failed`. The result carries the missing names (if any), the
    ignored settings keys, and the CLI's error.
  - skipped: the status is `skipped` and the static findings become notes.
  - `CLAUDECODE` set: a note that the check may pass only because it runs inside a
    Claude Code session, so re-run from a normal terminal.
- The CLI prerequisite gets `min_version=(2, 1, 287)` and `version_parse=_parse_semver`,
  taken from `claude_bridge.MIN_CLI_VERSION`.
- `main()` gets `--skip-claude-check`. The auth check runs after the prerequisites pass
  and before any change. On `failed`, it prints `[ERROR]` lines, the variable names to
  set, a pointer to TUTORIAL §1 and the `--skip-claude-check` hint, then exits 1.

## Tests (`tests/test_install.py`)

- `missing_env`: Bedrock names missing are reported, an unrelated name is ignored, all
  present gives `[]`, and an `env` that is not a dict gives `[]`.
- `read_user_settings`: missing file, malformed JSON and a non-object all give `{}`.
- `ignored_settings`: `apiKeyHelper` is detected.
- `check_claude_auth`:
  - ok;
  - fail with missing names;
  - fail with no missing names (the error is kept);
  - pass but names missing (a note, not a failure);
  - skip;
  - `CLAUDECODE` note.
- `probe_claude` with a fake runner:
  - argv carries every `CONFINEMENT_ARGS` flag and `--max-turns 1`;
  - an `is_error` payload or a non-zero exit gives the error;
  - a timeout gives the error;
  - a missing CLI gives the error.
- The CLI version prerequisite: `2.1.286` is outdated and `2.1.287` is ok.

## Docs

- TUTORIAL §1:
  - the Prerequisites table: Claude ≥ 2.1.287, logged in, required;
  - a new "Claude authentication for the hooks" subsection with the per-provider table
    of necessary variables and how to set them (Windows and POSIX);
  - `--skip-claude-check`.
- TUTORIAL §4 and 010's plan: correct the "boundary is an instruction" claim, per the
  facts above.
- TUTORIAL §6 001 entry and `CLAUDE.md`.

## Tasks

- [x] T1 Failing tests.
- [x] T2 Implement in `install.py`.
- [x] T3 Pytest + ruff: no new findings over 37.
- [x] T4 Docs.
- [x] T5 Live checks on this machine:
  - `python install.py` from Claude's shell passes, with the `CLAUDECODE` note;
  - with `CLAUDE_CODE_USE_BEDROCK` removed from the environment, the install aborts
    and names it.
- [x] T6 Check off the tasks. Commit only when the user asks.

## Outcome (2026-10-02)

- Tests: 249 passed, 4 skipped. Ruff: 37 findings, no new findings.
- Live, from Claude's shell:
  - `python install.py` passes (`claude answers under the hooks' read-only confinement`),
    warns about `CLAUDECODE` and the ignored `awsAuthRefresh`, and changes nothing on
    re-run;
  - with `CLAUDE_CODE_USE_BEDROCK` removed, it aborts with exit 1, names the variable,
    and points to TUTORIAL §1.
- Fixed during the live check: the new messages used `—`, which the Windows console
  rendered as `�`. They are ASCII now.
- Not verified: a run from a plain terminal, outside Claude Code, where `CLAUDECODE`
  is not set.
