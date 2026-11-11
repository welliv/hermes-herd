# Security

Herd copies part of a Hermes profile between machines you pair. Read this
before you pair a second machine.

## Paired machines are trusted authors

A pull can write `skills/`, `memories/MEMORY.md`, `memories/USER.md` and
`SOUL.md`. Hermes loads those as the agent's instructions. A skill or a
paragraph of memory from the other machine is not data the agent quotes. It is
text the agent follows.

`config.yaml` syncs too, and it decides what Hermes runs and where it sends
requests. A paired machine can add an MCP server (a command Hermes starts on
this machine), or change the provider or `base_url` used with the keys this
machine keeps in `.env`. Herd pins the endpoint only beside a credential that
sits in `config.yaml` itself (see *Where a key is sent*); it cannot see which
`.env` key a provider will use. Treat a paired machine as able to run code
here.

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

API keys written into `config.yaml` stay on the machine too. Any key named
`api_key`, `token`, `secret`, `password` or `authorization` (case-insensitive,
`-` read as `_`, camelCase read as snake_case, so `apiKey`, `x-api-key` and
`accessToken` count), or ending in `_api_key`, `_token`, `_secret`,
`_password`, at any depth and inside lists, plus `mcp_servers.<name>.env` and
`mcp_servers.<name>.headers` (the section and the leaf are case-insensitive),
is dropped before the config is packed. The same filter runs on a config that
arrives from another machine, including when you settle a conflict with
`--take theirs`, so a peer cannot inject or overwrite one. Omitting the key,
setting it to null, or replacing its parent with null or a different shape
does not delete this machine's value. A list entry a peer removed is kept
here when it still holds a credential, so an empty `custom_providers` list
cannot drop a local `api_key`. `shared:` in `policy.yaml` cannot lift this
rule. `hermes sync policy` prints the full list (it also covers `passwd`,
`password_hash`, `private_key`, `secret_key`, `cookie`, and the suffixes
`_apikey`, `_passwd`, `_private_key`, `_secret_key`, `_authorization`). Names
such as `api_key_env`, which hold the *name* of an environment variable,
still sync. An `env` map that is not under `mcp_servers` is not local as a
whole: credential-named keys inside it stay here, and other keys still sync.

A store written by 1.2.0 or earlier may still hold `model.api_key` and similar
values inside its encrypted config objects. 1.2.1 ignores them on pull and
stops writing new ones, but it does not rewrite store history. If your
`config.yaml` held a key while 1.2.0 was syncing, rotate that key, or start a
new store.

`hermes sync secrets on` refuses. `--sync-secrets` is ignored. An older
`policy.yaml` with `sync_secrets: true` is ignored. An `env` item left in a
store by an earlier version is not decrypted and not applied.

### Where a key is sent

A credential that stays here is still used with settings that do sync. So in
any mapping that holds a credential on this machine (`model` with an
`api_key`, a `custom_providers` entry with one, an `mcp_servers.<name>` with
`env` or `headers`, a section whose `extra_headers` / `default_headers` carry
one), the keys that decide where the credential goes —
`base_url`, `url`, `endpoint`, `api_base`, `host`, `provider`, `command`,
`args` — are pinned. A peer that changes, adds or removes one of them does not
move this machine's: the value stays, the rest of the peer's change is taken,
and the held part is recorded as a conflict with reason `credential-endpoint`.
`hermes sync conflicts` shows it; keeping yours republishes it, and taking
theirs applies the peer's endpoint while this machine's key stays. A mapping
that holds no credential here syncs these keys normally, so a machine without
the key still follows a provider change.

### Other synced files are not scanned

The credential rule is applied to `config.yaml` by key name. Herd does not
look inside `skills/`, `memories/MEMORY.md`, `memories/USER.md` or `SOUL.md`
for secrets: whatever text is in them is encrypted and synced as written. Keep
keys out of those files.

The recovery code decrypts the store. The store holds config (without the
credentials above), skills, memory and `SOUL.md`, and anything written in
them. Keep the code in a password manager.

The short pairing code is a 15-minute wrapper around that recovery code,
written to `pairing.json` in the store folder. Herd does not commit that
file to a git remote: deleting it after use would not remove the ciphertext
from git history, and anyone who later had the short code could unwrap the
recovery code from an old commit. For a git-only second machine, use
`hermes sync join <git-url> --code HERD-…`.

## What a sync writes

Inside the Hermes home: `config.yaml` (per key, machine-bound keys left
alone), `skills/`, `memories/MEMORY.md`, `memories/USER.md`, `SOUL.md`, and
`cron/jobs.json` only on a machine that turned cron sync on itself: `--cron`
at `init` or `join`, at `pair --code` on the joining machine, or at `pair` on
the machine that makes the code (which turns it on there if that machine
already syncs; leaving `--cron` out never turns it off). A machine without it
declines a peer's cron jobs: it neither installs nor deletes them, and the
pull reports them as skipped, with a warning once per change to the peer's
jobs. Each pull copies
the previous file into `plugin-data/herd/backups/` first. `hermes sync undo`
restores the last backup.

Not written: `.env`, `auth.json`, `state.db`, sessions.

## Network

A folder store makes no network calls. A git store runs git against the remote
you configured. Git (and the ssh it starts) gets a minimal environment, not the
agent's: `PATH`, `HOME`, `TERM`, locale and temp-dir variables (`TMPDIR` on
macOS, `TEMP`/`TMP` on Windows), `GIT_EXEC_PATH`, the Windows variables git
needs to start (`SYSTEMROOT` and the rest of that set), `SSH_AUTH_SOCK`,
`GIT_SSH`/`GIT_SSH_COMMAND`/`GIT_SSH_VARIANT`/`GIT_ASKPASS`,
`GIT_CONFIG_GLOBAL`/`GIT_CONFIG_NOSYSTEM`, proxies and CA-bundle paths
(`SSL_CERT_*`, `CURL_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`). Names match
case-insensitively. ssh and any credential helper git starts inherit this
same environment. Provider keys and tokens (`OPENAI_API_KEY`, `GH_TOKEN`,
...) are not passed, and neither are `GIT_DIR`, `GIT_WORK_TREE`,
`GIT_CONFIG_COUNT` or `GIT_CONFIG_KEY_*`. Authenticate the remote with an ssh
key or a git credential helper:

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
`hermes -q` (`HERMES_SINGLE_QUERY_SESSION`, read from the process environment
or, when the gateway hosts the turn, from the session context; a one-shot
turn the gateway marks finite counts too), and when `HERD_UNATTENDED=1`,
the hook returns `{"action": "block"}` and the tool returns
`{"ok": false, "code": "unattended"}` without writing. Blocking, rather than
asking, is deliberate: a cron job can be configured to auto-approve, and a
prompt there would either hang or be granted with nobody present.
