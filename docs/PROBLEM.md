# The problem, and why it is worth solving

## One sentence

Hermes accumulates its value on the machine it runs on — memory, skills, config, keys — so a second device starts as a stranger, and the accumulated value never compounds across the surfaces Hermes already ships.

## Evidence, not anecdote

The request is already filed and still open: [`NousResearch/hermes-agent#20510`](https://github.com/NousResearch/hermes-agent/issues/20510) — *Cloud / Cross-Device Sync for Hermes Configuration*. It asks for config, profiles, skills, memory, sessions and credential pools to follow the user.

The comments are a better spec than the issue, because they are from people who tried:

> *"it read the .env file and posted the contents to slack"* — author of a published git-based sync tool, describing why they stopped trusting it.

> *"some skills work only on specific platforms, e.g. Apple Notes on MacOS; platform-specific skills shouldn't be synced between devices"* — the failure that makes naive folder sync actively harmful.

Four public attempts exist (`alovwang-sys`, `Black-Studio-ia`, `Liminal0426`, `tescalada`). All four move **files**. None models which keys belong to the machine. That is the gap this plugin fills, and the reason "sync Hermes" is not yet solved by having four repositories on the subject.

Measured on a real install (this one, 2026-11-07):

| | |
|---|---|
| Top-level config sections | 31 |
| Leaf keys | 155 |
| Keys that are machine-bound | **37 (24%), spread across 12 sections** |
| Skills | 75, 57 MB on disk → 71 syncable (4 are macOS-only) → 1.2 MB packed |

A quarter of a real config cannot be copied without breaking something. That is the structural reason a checkbox in a sync tool cannot work.

## Why it matters to Hermes specifically

**1. The moat is the accumulated context, and it is trapped.** Hermes is sold on its learning loop: it writes skills, keeps memory, builds a model of you. That is the differentiator against stateless coding agents. But it lives in `~/.hermes` on one host, so the moat has a blast radius of exactly one machine.

**2. Hermes already ships more surfaces than any one person can use.** CLI, TUI, desktop, browser webapp, and 21+ messaging platforms. Without portable state, each new surface competes with the first one instead of compounding on it: the desktop is a *different* agent, not the same one in a window. A user who tries the desktop and finds an empty memory goes back to the terminal, and the surface investment underperforms.

**3. Every other plugin's value is capped by the same limit.** Skills, cron automations, connectors, memory backends — all of it is per-host. Sync is infrastructure the catalog sits on: make state portable once, and every listed plugin becomes portable with it.

## Opportunity cost

- **Per user:** each additional machine costs a manual migration (`hermes profile export/import` is a full archive, not a continuous sync) or a from-scratch setup, and the agent's continuity is lost either way. The realistic user response is to stop using the second machine — one device per account, when the product ships five surfaces.
- **Per surface:** every surface without shared state ships to an empty agent, which suppresses trial-to-habit conversion on exactly the surfaces that were built to widen usage.
- **Per release:** the longer state stays host-local, the more users accumulate on a single machine, and the more expensive the eventual core migration becomes. A plugin proves the model now, against real installs, without core taking the risk.

## First principles

Strip the feature request down and there are two kinds of state, not one:

1. **State that belongs to the machine** — where commands run, which port a webapp binds, which bot token polls, which Docker socket exists.
2. **State that belongs to the person** — the model they prefer, the skills they wrote, what the agent remembers, the keys that pay for it.

File sync has one primitive: replace the file. That primitive cannot express the distinction, so every tool built on it either copies machine state (and breaks the second host) or refuses to sync secrets (and makes the second host useless). The whole design follows from adding the missing primitive: **a per-key model of ownership, with a merge that respects it.**

The end state is bigger than settings: if the person's state is addressed by a key rather than a path, the agent becomes portable by identity — the same Hermes on any host, and later on relays the user chooses rather than a vendor they rent from.

## What "solved" looks like

1. A second machine is useful in one command, with no manual migration.
2. No surface ever boots with an empty memory because it is a different host.
3. No secret ever lands in a store in plaintext.
4. A user can see, in one command, exactly which keys move and which do not.
5. Nothing is lost when two machines edit at once — a conflict is shown, not guessed.
