# Herd

Keep one Hermes across every machine.

Settings, skills, memory and API keys follow you between devices. Each machine keeps what belongs to it — its Docker path, its ports, its bot tokens. The store is encrypted before anything leaves the device, and every pull leaves a backup you can undo.

> File sync copies `~/.hermes`. Herd understands `config.yaml`.

## Watch it (75 s)

[![Herd: settings, skills, memory and keys follow you between machines](docs/media/herd-demo.gif)](docs/media/herd-demo.mp4)

Click for sound. No mock-ups — every line of output in it was printed by the
real CLI.

## Install

```bash
hermes plugins install welliv/hermes-herd --enable
```

Hermes 0.23+. Git only if you want a git-backed store.

## Twenty seconds

```
$ hermes sync init
Herd is set up on desktop.
  pushed  76 item(s): config, env, memory:agent, memory:user, file:soul,
          and 71 skills
  Your recovery code — copy it to every machine you want in the herd:
    HERD-…

$ hermes sync join ~/herd-store --code HERD-…
Joined the herd as laptop.  pulled 76 item(s).
```

That is the whole setup. From then on it pulls when a session starts and pushes when it ends: the hook returns in about 10 ms and the work finishes in the background, at most once every two minutes.

## What moves

| | |
|---|---|
| **Follows you** | model and provider, display, agent behaviour, skills, memory (`MEMORY.md`, `USER.md`), `SOUL.md`, and the API keys that aren't machine-specific |
| **Stays put** | `terminal.backend`, `terminal.cwd`, Docker and container settings, `database.*`, `webapp.*`, `browser.*`, `auth.*`, `updates.*`, bot config, and machine env vars (`PATH`, `DISPLAY`, `HERMES_DASHBOARD_*`, `TELEGRAM_BOT_TOKEN`) |
| **Never** | `state.db` and sessions — SQLite with a write-ahead log is not a file to sync. Cron is opt-in, because a job on three machines runs three times |

The rules are data, not code: `hermes sync policy` prints them, and each is one line in `plugin-data/herd/policy.yaml`.

## Why copying the folder fails

- **A quarter of your config isn't portable.** 37 of 155 keys are machine-bound across 12 sections. Copy them and the laptop runs commands in the desktop's Docker socket.
- **Secrets are all or nothing.** Skip `.env` and you retype every key. Put it in git and you leak them — a published sync tool's author reported exactly that: *"it read the .env file and posted the contents to slack."*
- **Skills are platform-specific.** Of the 75 skills on this machine, 4 are macOS-only. They are skipped, not installed broken.
- **Two edits collide.** File sync keeps the last write. Herd keeps both values and tells you.

The longer argument, with the measured numbers: [`docs/PROBLEM.md`](docs/PROBLEM.md).

## Security

- **Encrypted end to end.** One 32-byte key, stretched with scrypt, used for AES-256-GCM. The store holds ciphertext — a folder in Dropbox leaks nothing.
- **Names are keyed hashes.** Objects are addressed by `HMAC(key, plaintext)`, so the store can't be probed by hashing guesses at a known setting.
- **One recovery code.** Printed by `init`, reprintable with `hermes sync code`. It decrypts everything and cannot be reset — keep it in a password manager.

## Commands

| | |
|---|---|
| `hermes sync init [--store PATH] [--remote URL]` | Create a store, publish this machine, print the code |
| `hermes sync join <store> --code …` | Attach a second machine |
| `hermes sync` | Pull and push in the safe order |
| `hermes sync status` / `diff` | What's in sync; what a sync would do |
| `hermes sync conflicts` | Values kept over the store's, both sides shown |
| `hermes sync undo` | Restore the files from the last pull |
| `hermes sync policy` / `code` / `leave` | The rules; the recovery code; stop syncing |

The agent gets three tools with the same verbs: `sync_status`, `sync_diff`, `sync_now`.

## How it works

Each device writes exactly one manifest, `devices/<device>.json`, so two machines pushing at once cannot clobber each other. Items are content-addressed and encrypted; versions are Lamport counters, with the device id breaking ties.

`config.yaml` is merged per key against a stored base:

```
local == remote   keep it
local == base     take remote      only they changed it
remote == base    keep local       only you changed it
all three differ  keep local, record both in `hermes sync conflicts`
```

Machine-bound paths are resolved to the local value before that comparison — including when the remote payload doesn't contain them at all, which is why a pull can't delete the section your machine is running on.

## Limits

- Sessions don't sync. Deliberate, see the table above.
- Losing the recovery code loses the store. That is the cost of having no custodian.
- A genuine conflict is shown, not guessed.
- Transport today is a folder or git. Nostr is the next backend: same interface, keypair identity, no vendor.

## Docs

- [`docs/PROBLEM.md`](docs/PROBLEM.md) — what this solves and why it matters for Hermes
- [`docs/AUDIT.md`](docs/AUDIT.md) — every claim above, mapped to the test that proves it
- [`docs/DEMO.md`](docs/DEMO.md) — the 75-second demo: shot list and narration

Demo music: Kevin MacLeod — "Perspectives" (incompetech.com), Creative Commons Attribution.

MIT.
