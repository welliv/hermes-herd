# The 85-second explainer

**Film:** `docs/media/herd-explainer.mp4` — 1920×1080, 30 fps, 85 s, ~5.9 MB, narrated, captions burned in
**Loop:** `docs/media/herd-explainer.gif` — 880 px, the key-by-key merge scene, silent
**Poster:** `docs/media/poster.png`

The film explains one idea: **herd splits Hermes in two — the agent travels, the machine stays put.**
Teal is the agent (model, skills, memory, `SOUL.md`); amber is the machine (working folder, ports, bot tokens, API keys).

## How it was made

- **Motion graphics** are drawn in code (Skia, 1920×1080 @ 30 fps), one scene per idea.
- **Terminal shots are real runs of herd 1.2.0** (`edb87bf`) on Hermes 0.23.1, against two throwaway homes
  (`server`, `laptop`) and a folder store. Each command was executed, its output captured, and the capture drawn
  as a clean terminal at 1080p. The text on screen is exactly what the CLI printed; only the scratch home path is
  shown as `~`. Typing is sped up.
- **Voice:** Microsoft Edge TTS, `en-US-AndrewMultilingualNeural`, rate −2%.

## Scenes

| Time | Scene | Narration | What it shows |
|---|---|---|---|
| 0:00 | Drift | "Your Hermes on the server learned a new skill last night. The one on your laptop has no idea. Same name. Two agents, drifting apart." | A skill appears on the server only; the laptop gets a "?" |
| 0:09 | Copying breaks | "Copy the Hermes folder across? … On one real setup, 37 of 155 settings. A working folder, a port, a bot token. Copy those, and two machines answer one bot." | Copied config with `terminal.cwd`, `webapp.port` and the bot token in red; one bot, two replies. 37/155 is from [`PROBLEM.md`](PROBLEM.md) |
| 0:26 | Two layers | "Herd splits Hermes in two. The agent travels. The machine stays put." | The mental model |
| 0:32 | Key by key | "Config merges key by key. Model, skills and memory flow across. Folders, ports and tokens stay pinned." | Shared keys flow server → laptop; machine keys get pinned |
| 0:41 | Join (real) | "Joining takes one command, and a one-time code." | `hermes sync pair` on the server, `--code` on the laptop |
| 0:46 | Proof (real) | "The new skill and the memory note are on the laptop. Same model. Its own folder and port." | `hermes sync`, `ls skills`, `tail MEMORY.md`, `grep` of the laptop's config |
| 0:55 | Your store | "It all moves through a store you own: a folder, or a git repo. Contents are encrypted. No server, no account." | AES-256-GCM sealed contents (item names and device names are not secret) |
| 1:04 | Sessions | "It syncs as sessions start and end. Your API keys never leave the machine." | Pull at start, push at end; unattended runs skip; `.env` is never read |
| 1:09 | Undo (real) | "Pulled a change you didn't want? One command puts it back." | A `SOUL.md` line arrives, `hermes sync undo` restores the file |
| 1:15 | Payoff | "Teach it once. By the next session, every machine knows." | |
| 1:19 | Install | "Herd, for Hermes Agent. Open source, one line to install." | `hermes plugins install welliv/hermes-herd --enable` |

## Publishing notes

- The pairing code on screen belongs to a throwaway store under `/tmp`; it was single-use and is dead.
- No credentials appear anywhere in the film.

## Terminal-only recording

`demo/setup.sh` + `demo/record.sh` still film `demo/demo.sh` on a headless display, for a silent screen
recording of the CLI. Requires a running Bot Screen (`DISPLAY=:20`) with `xfce4-terminal` and `ffmpeg`:

```bash
bash demo/setup.sh /tmp/hd
bash demo/record.sh /tmp/demo-raw.mp4
```

- `demo/setup.sh` runs `hermes --version` in each home **before** enabling the plugin, because the first run
  bootstraps that data root's runtime and would otherwise clear the enablement.
- `HERMES_HOME=x cmd` must be written out, never as `$VAR cmd`: bash does not re-parse a variable expansion as
  an assignment prefix, and with stderr redirected the failure is silent.
