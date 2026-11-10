# Security

Herd copies part of a Hermes profile between machines you pair. Read this
before you pair a second machine.

## Paired machines are trusted authors

A pull can write `skills/`, `memories/MEMORY.md`, `memories/USER.md` and
`SOUL.md`. Hermes loads those as the agent's instructions. A skill or a
paragraph of memory from the other machine is not data the agent quotes. It is
text the agent follows.

Pair only machines you control. Do not pair a store you did not create, and do
not point `--remote` at a git URL you do not trust: whoever can push to that
remote can publish the next skill the other machine will load.

`sync_diff` lists instruction-bearing items that a pull would write under
`review_before_pull` (skills, memory, `SOUL.md`). `sync_status` keeps the last
instruction-bearing items a pull actually wrote in `incoming_instructions`.
`sync_now` asks Hermes for approval before it pulls or pushes. In a cron run,
a `hermes -q` session, or any other non-interactive session, the pull is not
attempted.

Session start still pulls on an interactive session, at most once every two
minutes, on a short background thread. That pull applies the same files. If
you do not want an unattended overwrite, set `auto_pull: false` in
`plugin-data/herd/policy.yaml`. Cron and non-interactive sessions skip the
thread either way.

## Credentials

Herd does not read or write `~/.hermes/.env`, `auth.json`, or any other
credential file. It does not call `agent.secret_scope.get_secret` to export
provider keys, and it does not call `load_env_file`. Hermes has no API that
lets a plugin move another product's API keys between machines without opening
that file, and catalog rule 11 forbids opening it.

`hermes sync secrets on` refuses. `--sync-secrets` is ignored. An older
`policy.yaml` with `sync_secrets: true` is ignored. An `env` item left in a
store by an earlier version is not decrypted and not applied.

The recovery code decrypts the store. The store holds config, skills, memory
and `SOUL.md`, not API keys. Keep the code in a password manager.

## What a sync writes

Inside the Hermes home: `config.yaml` (per key, machine-bound keys left
alone), `skills/`, `memories/MEMORY.md`, `memories/USER.md`, `SOUL.md`, and
`cron/jobs.json` only when cron sync was turned on at `init`. Each pull copies
the previous file into `plugin-data/herd/backups/` first. `hermes sync undo`
restores the last backup.

Not written: `.env`, `auth.json`, `state.db`, sessions.

## Network

A folder store makes no network calls. A git store runs git against the remote
you configured:

| Action | Git |
|---|---|
| `sync_status`, `sync_diff`, `hermes sync status`, `hermes sync diff` | `git fetch` only. No rebase, no commit, no push. |
| pull | `git fetch`, then `git rebase` onto the fetched branch. No push. |
| push | commit when the store changed, then `git push`. |

Nothing else is contacted. There is no telemetry and no phone-home.

## Approval

`sync_now` returns `{"action": "approve"}` from `pre_tool_call`, with a
`rule_key` of `herd:sync_now:<direction>`. Hermes shows its own approval
prompt. Herd does not approve the call itself, does not turn YOLO on, and
does not spawn a shell to get around the prompt.

In cron (`HERMES_CRON_SESSION`, or Hermes's cron execution identity), in
`hermes -q` (`HERMES_SINGLE_QUERY_SESSION`), and when `HERD_UNATTENDED=1`,
the hook returns `{"action": "block"}` and the tool returns
`{"ok": false, "code": "unattended"}` without writing. Blocking, rather than
asking, is deliberate: a cron job can be configured to auto-approve, and a
prompt there would either hang or be granted with nobody present.
