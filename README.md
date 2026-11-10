# Herd

**Two machines. One Hermes.**

Settings, skills and memory follow you between machines; each machine keeps the parts that only make sense on it. One command to start, one code to join, nothing to manage afterwards.

> Copying `~/.hermes` moves your Docker socket and your bot token with it. Herd moves the profile, not the machine.

[![Herd: two machines, one Hermes](docs/media/herd-demo.gif)](docs/media/herd-demo.mp4)

*92 seconds, real commands: pairing, the machine-bound split, a conflict settled with one key, keys arriving encrypted, undo.*

## The short version

| | |
|---|---|
| **What it is** | A plugin that keeps one Hermes across your machines — the same model, skills and memory everywhere, each machine keeping its own paths, ports and bot tokens |
| **What it fixes** | A second machine is a stranger with the same name; copying the folder to fix that moves the first machine's Docker socket and bot token with it |
| **How it works** | One encrypted store, one short pairing code, a per-key merge that knows what belongs to the machine, and a pull at session start / push at session end |
| **What it costs** | You keep the recovery code in a password manager (the pairing code is only for the other machine). Sessions and cron stay put. A real conflict is shown, then one key settles it |

New here? [`PROBLEM.md`](docs/PROBLEM.md) is the case for it, [`COMPARISON.md`](docs/COMPARISON.md) ranks it against every other way to do this, and [`DEMO.md`](docs/DEMO.md) is the 92-second film, shot by shot.

## In the wild

**Laptop and a VPS.** You work from the laptop; the VPS runs the always-on agent. Install on both, `hermes sync pair` on the VPS, paste the code on the laptop. The laptop answers with the same memory and the same skills, while the VPS keeps its daemon socket and the laptop keeps its own working directory. Edit a skill on the train; it is on the VPS at the next session start.

**Desktop plus a travel laptop.** The desktop has the big model and the local models; the travel laptop is a thin client. Settings follow, so it is the same agent — but the travel laptop does not inherit a Docker backend it cannot run, and its bot token does not start answering for the desktop.

**A replacement machine.** `pair` with the code and the profile comes back in one command: memory, skills, `SOUL.md`, config, and the keys if you turned them on. The values you set again are the ones that belong to the new machine anyway.

The common shape: **you stop choosing which machine to work on.** Every machine is the agent; only the plumbing differs.

And the first ninety seconds are one command that prints one short code, one paste, and a line that tells you it worked:

```
$ hermes sync pair
Ready to pair — desktop is the first machine.
  code   QK7M2-9XPRT-4HWBJ-2M8ZC   (once, 15 minutes)

$ hermes sync pair --code QK7M2-9XPRT-4HWBJ-2M8ZC
Paired with desktop. This machine is laptop.
  In sync · 2 machines · synced just now
```

## The problem, in numbers

- **24% of a real config is machine-bound** — 37 of 155 leaf keys across 12 sections. Copy them and the laptop runs commands in the desktop's Docker socket, binds its port, and answers its Telegram messages.
- **Secrets are all or nothing in a file sync.** Skip `.env` and you retype every key; include it and it lands in a cloud folder or a git history. A published sync tool did exactly that once: *"it read the .env file and posted the contents to slack."*
- **File sync keeps the last write.** Two machines editing the same setting is not an edge case, it is Tuesday. One edit disappears and nothing says so.

The measured detail, including the four prior attempts that all move files: [`PROBLEM.md`](docs/PROBLEM.md).

## What it solves

| Problem | Without Herd | With Herd |
|---|---|---|
| Second machine is empty | Retype keys, reinstall skills, re-teach memory | `join` with the code, once |
| Machine-bound settings | Copied and wrong, or excluded and missing | Resolved to each machine's own value |
| Secrets | Plaintext in a cloud folder, or never synced | Encrypted before they leave; off until you ask |
| Simultaneous edits | Last write wins, silently | A card in the terminal: `1` keep mine, `2` take theirs — the disagreement is recorded until you choose |
| A mistake | Restore from a backup you may not have | `hermes sync undo` |

## How it works

```
        desktop                          laptop
   ┌──────────────┐                ┌──────────────┐
   │ config.yaml  │                │ config.yaml  │
   │ skills/      │                │ skills/      │
   │ memories/    │                │ memories/    │
   │ .env         │                │ .env         │
   └──────┬───────┘                └──────┬───────┘
          │   merge per key, base = last agreed   │
          └────────────────┬──────────────────────┘
                           ▼
                 ┌───────────────────┐
                 │  encrypted store  │  folder, git, Dropbox, USB
                 │  ciphertext only  │  one recovery code opens it
                 └───────────────────┘
```

1. **`init`** creates the store, seals this machine's items, and prints one recovery code (`HERD-…`).
2. **`join`** on the next machine adopts the herd on its first pull.
3. From then on a session-start hook pulls and a session-end hook pushes: a background thread, at most once every two minutes, a couple of milliseconds of hook.

Each device writes exactly one manifest, so two machines pushing at once cannot clobber each other. Items are content-addressed and encrypted, and every change records the entry it was built on — that is how a fast-forward is told from a real disagreement.

`config.yaml` merges per key against the last **agreed** snapshot:

```
local == remote   keep it
local == base     take remote      only they changed it
remote == base    keep local       only you changed it
all three differ  keep local, record both, stop republishing
```

Machine-bound paths are resolved to the local value *before* that comparison — including when the remote payload omits them — so a pull cannot delete the section your machine is running on.

## How it improves Hermes

- **The surfaces stop competing.** CLI, TUI, desktop, webapp, 21+ messaging platforms: without shared state each one boots a different agent, and a new surface loses to the first one. With it, they are the same agent in different windows.
- **The catalog becomes portable.** Skills, automations and connectors are per-host today; make state portable once and every plugin that stores state inherits it.
- **The agent can answer for itself.** Three tools — `sync_status`, `sync_diff`, `sync_now` — so "am I in sync?" is a question Hermes answers, not a command you have to remember.
- **Nothing runs in the background.** No daemon, no port, no server. The store is a folder; if you can back up a folder you can run this.
- **It is reversible.** Every pull leaves a backup, and `hermes sync undo` puts the files back.

## How it compares

| Tool | Machine-bound keys | Secrets | Conflicts | Score |
|---|---|---|---|---|
| **Herd** | Modelled per key | Encrypted, opt-in | Kept, then one key to settle | **89** |
| Dotfiles + age/SOPS | Hand-written templates | Encrypted in git | Git conflict, by hand | 59 |
| Syncthing / Dropbox | Copied over each other | Provider-side, plaintext | Conflict copies, `.db` corruption | 51 |
| Shared home over SSH | One config for all hosts | Stays on the server | None to resolve | 51 |
| `hermes profile export/import` | Whole archive | Whole archive | None — one-way | 46 |
| Copy `~/.hermes` | Copied, breaks the host | Leaks or is skipped | Last write wins | 45 |

Full method, weights and per-tool verdicts — including when *not* to use Herd: [`COMPARISON.md`](docs/COMPARISON.md).

## Install

```bash
# both machines
hermes plugins install welliv/hermes-herd --enable

# first machine: creates the herd and prints one short code
hermes sync pair

# every other machine: type the code
hermes sync pair --code XXXX-XXXX-XXXX-XXXX
```

```
Ready to pair — desktop is the first machine.
  store  /root/herd-store

  code   QK7M2-9XPRT-4HWBJ-2M8ZC
         works once, for 15 minutes.

On the other machine, with this store folder reachable:
  hermes sync pair --code QK7M2-9XPRT-4HWBJ-2M8ZC
```

```
Paired with desktop. This machine is laptop.
  pulled  6 item(s): config, memory:agent, file:soul, skill:research, skill:writer, skill:deploy
  In sync · 2 machines · synced just now
```

The store is a folder: put it in Dropbox/iCloud/Syncthing so both machines see it, or pass `--remote <git-url>` on the first machine — then the second needs only the code and clones it. One code works once, for 15 minutes; the long recovery code still exists for a machine that has the folder but not the code (`hermes sync code`, `hermes sync join`).

Hermes 0.23+.

## What moves

| | |
|---|---|
| **Follows you** | model and provider, display, agent behaviour, skills, memory (`MEMORY.md`, `USER.md`), `SOUL.md` — and, only with `hermes sync secrets on`, the API keys that aren't machine-specific |
| **Stays put** | `terminal.backend`, `terminal.cwd`, Docker and container settings, `database.*`, `webapp.*`, `browser.*`, `auth.*`, `updates.*`, bot config, and machine env vars (`PATH`, `DISPLAY`, `HERMES_DASHBOARD_*`, `TELEGRAM_BOT_TOKEN`) |
| **Never** | `state.db` and sessions — SQLite with a write-ahead log is not a file to sync. Cron is opt-in, because a job on three machines runs three times |

The rules are data, not code: `hermes sync policy` prints them, and each is one line in `plugin-data/herd/policy.yaml`.

## Security

- **Encrypted before it leaves.** One 32-byte key, stretched with scrypt, used for AES-256-GCM. The store holds ciphertext.
- **Names are keyed hashes.** Objects are addressed by `HMAC(key, plaintext)`, so the store can't be probed by hashing guesses at a known setting.
- **One recovery code.** Printed by `init`, reprintable with `hermes sync code`. It decrypts everything and cannot be reset — keep it in a password manager.
- **Every payload names itself.** An object carries the item id and kind it was sealed for, so a manifest cannot point the config item at the secrets blob, and a repeated object cannot be replayed as another item.
- **Credentials are opt-in.** Until you run `hermes sync secrets on`, nothing reads `.env` on either side: the file is not opened, and a peer's keys are left in the store untouched.
- **A disagreement stops, it does not ping-pong.** Each side keeps its version, records the disagreement, and stops republishing the item until one side agrees.
- **A peer cannot widen your rules.** The skip list binds in both directions; a key name must be a plain environment name before it can become a line; every `.env` write goes through Hermes's own check and then re-reads the file.

A store written by 1.0.2 or earlier holds unsealed objects. 1.0.3 skips them with a message rather than guessing; start a fresh store, or push once from each machine still running the old version.

## Commands

| | |
|---|---|
| `hermes sync pair [--store PATH] [--remote URL]` | Create the herd and print one short, single-use code |
| `hermes sync pair --code …` | Join with that code (clones `--remote` if the store is git) |
| `hermes sync init` / `join` | The explicit path: choose a store, use the long recovery code |
| `hermes sync` | Pull, merge, push — the one you type |
| `hermes sync status` / `diff` | What's in sync; what a sync would do |
| `hermes sync secrets on` / `off` | Include API keys in sync, or stop (off until you ask) |
| `hermes sync gc [--dry-run]` | Delete store objects nothing references any more |
| `hermes sync conflicts` | Review disagreements; `--item config --take mine\|theirs` settles one |
| `hermes sync undo` | Restore the files from the last pull |
| `hermes sync policy` / `code` / `leave` | The rules; the recovery code; stop syncing |

The agent gets three tools with the same verbs: `sync_status`, `sync_diff`, `sync_now`.

## Limits

- Sessions don't sync, and cron is off by default. Deliberate, see the table above.
- Losing the recovery code loses the store. That is the cost of having no custodian.
- A genuine conflict is shown, not guessed — and settled with one key in the terminal. There is no GUI yet.
- The store keeps every version it ever wrote; `hermes sync gc` prunes what nothing references, and old backups and conflict archives with it.
- Transport today is a folder or git. Nostr is the next backend: same interface, keypair identity, no vendor.

## What it is not

No account. No hosted service. No telemetry. It does not back up your sessions, and it will not guess which side of a real disagreement you meant.

## Docs

| | |
|---|---|
| [`docs/PROBLEM.md`](docs/PROBLEM.md) | The measured case for per-key sync, and why Hermes needs it |
| [`docs/COMPARISON.md`](docs/COMPARISON.md) | Six ways to do this, weighted and ranked, with when to choose each |
| [`docs/DEMO.md`](docs/DEMO.md) | The 92-second demo: shot list, timings, how to re-record it |
| [`docs/AUDIT.md`](docs/AUDIT.md) | Every claim above, mapped to the test that proves it |

MIT.
