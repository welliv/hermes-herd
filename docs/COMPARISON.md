# How Herd compares

The question is narrow: **which tool keeps one Hermes across several machines without breaking any of them?** Everything below is judged against that, not against "syncing files" in general.

## The one axis that decides it

A Hermes home holds two kinds of state:

1. **Machine state** — Docker backend, working directory, webapp port, bot token, `PATH`, `DISPLAY`.
2. **Person state** — model, skills, memory, `SOUL.md`, API keys.

A tool that cannot tell them apart has only two moves: copy everything (and break the second machine) or copy nothing portable (and make the second machine useless). Measured on a real install: **37 of 155 config keys (24%) are machine-bound, across 12 sections** — see [`PROBLEM.md`](PROBLEM.md).

A quarter of the config is the whole argument. Rank accordingly.

## Scored

Six candidates, six criteria, weights summing to 100. Each cell is 1–5 (5 = best); the total is weighted and scaled to 100. Scores are judgements, the method is not — [reproduce them](#reproducing-the-numbers) in ten lines.

| # | Tool | Machine-bound handled | Secrets | Conflicts | Setup | Running cost | Maturity | **Score** |
|---|---|---|---|---|---|---|---|---|
| 1 | **Herd** (this plugin) | 5 | 5 | 5 | 5 | 4 | 2 | **89** |
| 2 | Dotfiles manager + age/SOPS (chezmoi, yadm) | 2 | 4 | 2 | 2 | 3 | 5 | **59** |
| 3 | Syncthing / Dropbox / iCloud folder | 1 | 2 | 2 | 3 | 4 | 5 | **51** |
| 4 | Shared home over SSH (NFS / sshfs) | 1 | 3 | 4 | 2 | 2 | 4 | **51** |
| 5 | `hermes profile export/import` | 2 | 2 | 1 | 3 | 2 | 4 | **46** |
| 6 | Copy `~/.hermes` (rsync, scp, git) | 1 | 1 | 1 | 4 | 3 | 5 | **45** |

| Criterion | Weight | What it measures |
|---|---|---|
| Machine-bound handled | 25 | Does the second machine keep its own Docker path, port, bot token? |
| Secrets | 20 | Do keys travel, encrypted, without a plaintext copy in a cloud folder or git history? |
| Conflicts | 15 | Two machines edited the same thing — is it kept, shown, or silently overwritten? |
| Setup | 15 | Commands and decisions before the second machine is useful |
| Running cost | 10 | What runs forever after setup: daemon, network mount, manual reruns |
| Maturity | 15 | Field time and evidence, not features |

## What each one is actually for

**Herd — 89. Built for this job, new.**
Per-key merge with a stored base, machine-bound paths resolved locally, encrypted store, opt-in secrets, a conflict that is a one-key choice in the terminal, `undo` on every pull. Setup is one command and a 20-character code that works once. Cost: it is a young plugin — zero public users at the time of writing, one audit cycle. The remaining gap is interface polish (no GUI), not behaviour.
*Pick it when* you want Hermes to behave like one agent and you accept 1.x software.

**Dotfiles manager + age/SOPS — 59. The mature incumbent, for a different job.**
`chezmoi`/`yadm` plus `age` or `sops` is how careful people already sync config, and it is genuinely good at that: templates per host, encrypted secrets in git, years of production use. What it does not have is a model of *Hermes*: you hand-write a template for every machine-bound key, every new Hermes section needs a template edit, and a genuine two-sided edit is a git conflict you resolve by hand.
*Pick it when* you want one tool for every dotfile on the box, not just Hermes, and you are willing to maintain the templates.

**Syncthing / Dropbox / iCloud — 51. The obvious answer, and the one that corrupts state.**
It syncs the folder, so it works until it doesn't: `state.db` (SQLite + WAL) is copied mid-write across devices, machine-bound keys overwrite each other, and `.env` sits in plaintext in a provider's cloud. Provider-side encryption is not end-to-end encryption.
*Pick it when* you are syncing documents, not a live application home.

**Shared home over SSH — 51. Elegant, and wrong for a laptop.**
One home on one server: no merge, no conflict, one source of truth — but every device now shares one `config.yaml`, so the machine-bound quarter is wrong on all but one host, and Hermes becomes unusable offline or over a bad connection.
*Pick it when* every machine is the same machine (a fleet of identical workers), not a laptop and a VPS.

**`hermes profile export/import` — 46. Built in, one-way, not sync.**
A full archive is the right tool for a migration, and the wrong one for a working pair of machines: it is manual, it replaces rather than merges, and it carries no notion of what should stay behind.
*Pick it when* you are moving a profile once and never coming back.

**Copy `~/.hermes` — 45. The thing everyone tries first.**
One command, works instantly — and the laptop inherits the desktop's Docker socket and bot token, and either leaks `.env` or leaves you retyping keys. This is the option every other row exists to beat, and the one in the video's opening shot.

## Verdict

- **For Hermes specifically, Herd is first** on the axis that decides the job: it is the only candidate that models ownership per key, so the machine keeps its machine and the person keeps their agent.
- **It is first with a caveat**: 1.x maturity. If you need years of field time today, dotfiles + age is the honest choice, and it will cost you a template per machine-bound key.
- **It is first with a caveat**: 1.x maturity. Pairing, the conflict choice and the status line are in; a GUI is not.

## What would change the ranking

| Change | Effect |
|---|---|
| Field time (users, months, incidents) | Herd's only weak criterion rises; nothing else moves |
| A GUI surface (Hermes Desktop pane) | Setup and conflicts stop being terminal-shaped |
| A hosted relay instead of a folder | Ops 4 → 5, and pairing needs no shared folder at all |
| A team story (shared store, per-device identity) | Opens a category none of these six cover |

## Reproducing the numbers

```python
crit  = {"machine": .25, "secrets": .20, "conflict": .15, "setup": .15, "ops": .10, "maturity": .15}
herd  = dict(machine=5, secrets=5, conflict=5, setup=5, ops=4, maturity=2)
score = sum(herd[k] * w for k, w in crit.items()) / 5 * 100      # 89.0
```

Change a weight and the ordering changes with it — the point of publishing the method is that you can disagree with the arithmetic instead of the vibe.
