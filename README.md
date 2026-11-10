# Herd

**Two machines. One Hermes.**

Your settings, skills and memory are on every machine; each machine keeps the parts that only make sense on it. One command to start, one code to join, nothing to manage afterwards.

> Copying `~/.hermes` moves your Docker socket and your bot token with it. Herd moves the profile, not the machine.

## Watch it (79 s, real commands)

[![Herd: two machines, one Hermes](docs/media/herd-demo.gif)](docs/media/herd-demo.mp4)

Nothing in that recording is staged. `demo/demo.sh` runs the same commands against two throwaway Hermes homes, and `demo/record.sh` films the terminal.

## The problem, shown rather than described

A second machine is a stranger with the same name: no skills, no memory, a different model, and a `config.yaml` full of addresses that belong to the first machine. The usual fixes are worse than the problem:

- **Copy the folder** and the laptop runs commands in the desktop's Docker socket, binds the desktop's ports, and answers the same Telegram messages.
- **Copy `.env`** and your keys end up in a cloud folder or a git history. A published sync tool did exactly this once — its author's words: *"it read the .env file and posted the contents to slack."*
- **Sync the whole directory** and a genuine collision is resolved by whoever wrote last, silently.

Herd's answer: merge the profile per key, encrypt what leaves, keep machine-bound values where they belong, and say so when two machines really disagree.

## Try it in 60 seconds

```bash
# both machines
hermes plugins install welliv/hermes-herd --enable

# first machine
hermes sync init --store ~/herd-store        # prints one recovery code

# every other machine
hermes sync join ~/herd-store --code HERD-…
```

```
Herd is set up on desktop.
  pushed  6 item(s): config, memory:agent, file:soul, skill:research, skill:writer, skill:deploy
  Your recovery code — copy it to every machine you want in the herd:
    HERD-…

Joined the herd as laptop.
  pulled  6 item(s)
  adopted 1 value(s) from the store: model.default
```

Both machines now run the same agent — same model, same skills, same memory — and the laptop kept its own Docker path and port. From then on it pulls when a session starts and pushes when it ends: a couple of milliseconds of hook, the work in a background thread, at most once every two minutes.

Hermes 0.23+. Git only if you want a git-backed store.

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
- **A disagreement stops, it does not ping-pong.** When both machines changed the same item, each keeps its version, records the disagreement, and stops republishing it until one side agrees. `hermes sync conflicts` shows both.
- **A peer cannot widen your rules.** The skip list binds in both directions: a key this machine excludes is neither sent nor accepted, a key name has to be a plain environment name before it can become a line, and a key an administrator pinned is left to the administrator.

A store written by 1.0.2 or earlier holds unsealed objects. 1.0.3 skips them with a message rather than guessing; start a fresh store, or push once from each machine still running the old version.

## Commands

| | |
|---|---|
| `hermes sync init [--store PATH] [--remote URL]` | Create a store, publish this machine, print the code |
| `hermes sync join <store> --code …` | Attach a second machine |
| `hermes sync` | Pull, merge, push — the one you type |
| `hermes sync status` / `diff` | What's in sync; what a sync would do |
| `hermes sync secrets on` / `off` | Include API keys in sync, or stop (off until you ask) |
| `hermes sync gc [--dry-run]` | Delete store objects nothing references any more |
| `hermes sync conflicts` | Where the machines disagree, both values shown |
| `hermes sync undo` | Restore the files from the last pull |
| `hermes sync policy` / `code` / `leave` | The rules; the recovery code; stop syncing |

The agent gets three tools with the same verbs: `sync_status`, `sync_diff`, `sync_now`.

## How it works

Each device writes exactly one manifest, `devices/<device>.json`, so two machines pushing at once cannot clobber each other. Items are content-addressed and encrypted; every change records the entry it was built on, which is how a fast-forward is told from a genuine disagreement.

`config.yaml` is merged per key against the last **agreed** snapshot:

```
local == remote   keep it
local == base     take remote      only they changed it
remote == base    keep local       only you changed it
all three differ  keep local, record both, stop republishing
```

Machine-bound paths are resolved to the local value before that comparison — including when the remote payload doesn't contain them at all, which is why a pull can't delete the section your machine is running on.

## Limits

- Sessions don't sync. Deliberate, see the table above.
- Losing the recovery code loses the store. That is the cost of having no custodian.
- A genuine conflict is shown, not guessed — and resolved by an edit, not a button (yet).
- The store keeps every version it ever wrote; `hermes sync gc` prunes what nothing references, and old backups and conflict archives with it.
- Transport today is a folder or git. Nostr is the next backend: same interface, keypair identity, no vendor.

## What it is not

No account. No hosted service. No telemetry. It does not back up your sessions, and it will not guess which side of a real disagreement you meant.

## Docs

- [`docs/PROBLEM.md`](docs/PROBLEM.md) — the measured case for per-key sync
- [`docs/AUDIT.md`](docs/AUDIT.md) — every claim above, mapped to the test that proves it
- [`docs/DEMO.md`](docs/DEMO.md) — the 79-second demo: shot list, timings, and how to re-record it

MIT.
