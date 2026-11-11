# Changelog

## 1.2.1

Fixes from the catalog review of 1.2.0 (NousResearch/hermes-agent#151037).

- **Credentials in `config.yaml` no longer sync.** Any key named `api_key`,
  `token`, `secret`, `password`, `authorization` (and `passwd`,
  `password_hash`, `private_key`, `secret_key`, `cookie`), or ending in
  `_api_key`, `_token`, `_secret`, `_password`, `_private_key`, `_secret_key`,
  `_authorization`, matched at any depth and inside lists. Names are
  case-insensitive, hyphens are underscores, and camelCase is snake_case, so
  `API_KEY`, `apiKey`, `x-api-key`, `accessToken` and `Authorization` match.
  `api_key_env` and `max_tokens` do not. `mcp_servers.*.env` and
  `mcp_servers.*.headers` are local-only whole (`MCP-Servers` / `Headers`
  too). The rule runs on outgoing config and on incoming config, including
  `sync conflicts --take theirs`. A peer cannot inject or overwrite one, and
  cannot delete one by omitting it, setting it to null, or replacing its
  parent with null or another shape. A list entry the peer removed is kept on
  this machine when it still holds a credential. `shared:` cannot lift the
  rule. 1.2.0 sent `model.api_key`. A store written by 1.2.0 may still hold
  such values in old objects: rotate any key that was in `config.yaml`, or
  start a new store.
- **Cron jobs land only where cron sync is on.** A pull now declines
  `file:cron` (no install, no delete, not recorded as agreed) unless this
  machine opted in. `hermes sync join` and `hermes sync pair --code` gain
  `--cron`. 1.2.0 wrote a peer's `cron/jobs.json` on any machine.
- **Git gets a minimal environment.** Every git call (`init`, `fetch`,
  `rebase`, `commit`, `push`, `clone`, `checkout`, and the rest) goes through
  one subprocess helper with an allowlist: `PATH`, `HOME`, `TERM`, locale,
  temp dir (`TMPDIR`/`TEMP`/`TMP`), `GIT_EXEC_PATH`, the Windows variables git
  needs to start (`SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`, `COMSPEC`,
  `PATHEXT`, `USERPROFILE`, `HOMEDRIVE`, `HOMEPATH`, `APPDATA`,
  `LOCALAPPDATA`, `PROGRAMDATA`), `SSH_AUTH_SOCK`, askpass and `DISPLAY`,
  `GIT_SSH` / `GIT_SSH_COMMAND` / `GIT_SSH_VARIANT` / `GIT_ASKPASS` /
  `GIT_TERMINAL_PROMPT`, `GIT_CONFIG_GLOBAL` / `GIT_CONFIG_NOSYSTEM`, proxies,
  and CA bundles (`GIT_SSL_CAINFO`, `GIT_SSL_CAPATH`, `SSL_CERT_FILE`,
  `SSL_CERT_DIR`, `CURL_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`). The allowlist is
  case-insensitive so Windows `Path` and `SystemRoot` still pass. ssh and
  credential helpers inherit that environment and nothing else. Not passed:
  `GIT_DIR`, `GIT_WORK_TREE`, `GIT_CONFIG_COUNT`, `GIT_CONFIG_KEY_*`,
  `GIT_CONFIG_PARAMETERS`, and provider keys or tokens (`OPENAI_API_KEY`,
  `GH_TOKEN`, `GITHUB_TOKEN`, ...). 1.2.0 passed the agent's whole
  environment. If your git remote relied on `GH_TOKEN`/`GITHUB_TOKEN` in the
  environment, use a credential helper or an ssh key.
- **A peer cannot point a local key somewhere else.** In a mapping that holds
  a credential on this machine (`model`, a `custom_providers` entry, an
  `mcp_servers.<name>` with `env` or `headers`, a section whose
  `extra_headers` / `default_headers` carry one), `base_url`, `url`,
  `endpoint`, `api_base`, `host`, `provider`, `command` and `args` are pinned:
  a peer's change to them is held, recorded as a `credential-endpoint`
  conflict, and applied only if you take theirs. The rest of the peer's change
  is taken, and a mapping with no local credential syncs these keys normally.
  Without this, a peer could change `model.base_url` and the next request
  would carry this machine's `model.api_key` to the peer's endpoint, or change
  an MCP server's `command` and receive its `env`.
- **`hermes sync pair --cron` works on the machine that makes the code.** It
  was accepted and ignored. On a new herd it creates the store with cron sync
  on; on a machine that already syncs it turns cron sync on and publishes the
  jobs. Leaving `--cron` out never turns it off.
- The pull warns about declined cron jobs once per change to the peer's jobs,
  not on every pull.
- Docs: a paired machine can add MCP servers and change the provider used
  with `.env` keys, so it is treated as able to run code here; secrets written into skills, `MEMORY.md`, `USER.md` or `SOUL.md` are
  not filtered and sync as written; `docs/AUDIT.md` maps the 1.2.1 claims to
  their tests.
- **Status is honest about a git store that has diverged.** After a fetch,
  `hermes sync status` (and `sync_status` / `sync_diff`) reports
  `transport: {ahead, behind, branch}` and lists device manifests that exist
  on `origin/<branch>` but not in this checkout. The summary does not say
  "In sync" when either count is non-zero; it says `git ahead N, behind M`.
- **`hermes sync conflicts --item config --take theirs` applies every
  recorded config path**, not only the first. Credentials are still
  preserved. The human conflict list prints `reason  credential-endpoint`
  (and any other reason on the row).
- **`pairing.json` is never committed to a git remote.** It seals the
  recovery code with the short pair code; a commit would leave that
  ciphertext in git history after the file is deleted. The file is
  gitignored, unstaged if an older commit added it, and deleted locally
  after a successful folder pair. A git-only second machine joins with
  the recovery code: `hermes sync join <git-url> --code HERD-…`.
- `hermes sync policy` prints the credential rule.
- `audit/matrix.py`: the same-device serialisation check read whichever
  device manifest the folder listed first, so it failed about half the time
  on a correct store. It now reads the pushing device's own manifest.
- A one-shot Hermes turn (`hermes chat -q`, `-z`) hosted by the gateway is
  unattended even when `HERMES_SINGLE_QUERY_SESSION` lives only in the session
  context, or the gateway marks the turn finite. `sync_now` is blocked there
  instead of prompting a session with nobody to answer.
