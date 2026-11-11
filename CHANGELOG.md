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
- `hermes sync policy` prints the credential rule.
- A one-shot Hermes turn (`hermes chat -q`, `-z`) hosted by the gateway is
  unattended even when `HERMES_SINGLE_QUERY_SESSION` lives only in the session
  context, or the gateway marks the turn finite. `sync_now` is blocked there
  instead of prompting a session with nobody to answer.
