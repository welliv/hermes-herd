# Herd

**Every other tool copies `~/.hermes`. This one understands `config.yaml`.**

Herd keeps one Hermes across every machine you use. Settings, skills, memory and API keys follow you; each machine keeps what belongs to it. The store is encrypted before anything leaves the device, and every sync leaves a backup you can restore with one command.

```
hermes sync init            # on the machine you already use
hermes sync join <store>    # on the next one, with the recovery code
hermes sync                 # from then on
```

## Why this exists

Hermes gets better the longer you use it: memory accumulates, skills get sharper, your config becomes exactly yours. All of that lives in `~/.hermes` on one computer. Move to a laptop and the agent you spent months shaping is gone — so most people quietly stop using the second machine.

The obvious fix, syncing the folder, breaks the second machine in four ways:

| What breaks | Why |
|---|---|
| The config | `config.yaml` is 31 sections and roughly half are machine-bound: Docker paths, the webapp port, bot tokens, `auth.*`. Copy it and the laptop runs commands against the desktop's Docker socket. |
| The keys | Skip `.env` and you retype every API key. Sync it in git and you leak them — one published tool's author reported exactly that: *"it read the .env file and posted the contents to slack."* |
| The skills | A macOS-only skill arrives on Linux and loads as broken. |
| The edits | Two machines edit different keys; the last file write wins and one edit disappears. |

Herd models the thing file sync can't: **which parts of your Hermes belong to the machine, and which belong to you.**

## What moves, what stays

**Follows you:** model and provider, display, agent behaviour, skills (platform-checked), memory (`MEMORY.md`, `USER.md`), `SOUL.md`, and the API keys in `.env` that aren't machine-specific.

**Stays put:** `terminal.backend`, `terminal.cwd`, Docker and container settings, `database.*`, `webapp.*`, `browser.*`, `auth.*`, `updates.*`, per-platform bot config, and machine env vars (`PATH`, `DISPLAY`, `HERMES_DASHBOARD_*`). The full list is `hermes sync policy`, and every entry is one line in `~/.hermes/plugin-data/herd/policy.yaml`.

**Never:** `state.db` and sessions. SQLite with a write-ahead log is not a file to sync, and pretending otherwise corrupts history. Cron jobs are off by default, because a job that runs on three machines runs three times.

## Security model

- **Encrypted end to end.** One 32-byte key per store, stretched with scrypt, used for AES-256-GCM. The store holds ciphertext; a plain folder in Dropbox leaks nothing.
- **Names are keyed hashes.** Objects are addressed by `HMAC(key, plaintext)`, so the store can't even be probed by hashing guesses at a known setting.
- **One recovery code.** Printed once by `hermes sync init`, reprintable with `hermes sync code`. It decrypts everything, so keep it in a password manager. There is no reset.
- **Backups before writes.** Each pull snapshots what it is about to touch into `plugin-data/herd/backups/`; `hermes sync undo` restores the newest.
- **No network of ours.** The store is a folder you choose. Point it at git and Herd commits and pushes; nothing talks to a service we run.

## Commands

| Command | What it does |
|---|---|
| `hermes sync init [--store PATH] [--remote URL]` | Create a store, publish this machine, print the recovery code |
| `hermes sync join <store> --code <code>` | Attach this machine and take the store's state |
| `hermes sync` | Pull and push in the safe order |
| `hermes sync status` | What's in sync, what differs, which devices exist |
| `hermes sync diff` | What a sync would do, without doing it |
| `hermes sync push` / `pull` | One direction |
| `hermes sync conflicts` | Values kept over the store's, both sides shown |
| `hermes sync undo` | Restore files from the last pull's backup |
| `hermes sync policy` | Exactly what does and does not move |
| `hermes sync code` | Print the recovery code |
| `hermes sync leave` | Stop syncing; local files untouched |

The agent gets three tools with the same verbs: `sync_status`, `sync_diff`, `sync_now`.

## How it works

Each device writes exactly one manifest, `devices/<device>.json`, so two machines pushing at once can never clobber each other — git merges two different files. Items are content-addressed and encrypted; an item's version is a Lamport counter (higher wins, device id breaks ties).

`config.yaml` is merged **per key** with a stored base snapshot:

```
local == remote   keep it
local == base     take remote      (only they changed it)
remote == base    keep local       (only you changed it)
all three differ  keep local, record both values in `hermes sync conflicts`
```

Device-local paths are never even candidates: they resolve to the local value before the comparison, including when the remote payload doesn't contain them at all. A pull therefore can't delete the section your machine is running on.

Skills move as deterministic tarballs (gzip mtime pinned to zero) and carry their `platforms:` frontmatter; an item that doesn't list the target OS is skipped instead of installed broken.

## Install

```bash
git clone https://github.com/<you>/herd ~/.hermes/plugins/herd
hermes plugins enable herd
```

Requires Hermes 0.23+ and `git` only if you use a git-backed store.

## Limits, stated plainly

- **Sessions don't sync.** Deliberate, see above.
- **Losing the recovery code loses the store.** That is the cost of having no custodian.
- **A genuine conflict is shown, not guessed.** Herd keeps your value on this machine and tells you what the other side had.
- **Transport today is a folder or git.** Nostr is next: same store interface, keypair identity, no vendor.
