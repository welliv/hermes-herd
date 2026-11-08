# The 75-second demo

Silent screen film. Captions carry the argument, so it reads with the sound off;
the same words work as a voiceover if you record one. Rendered from
`render.py` — every line on screen is real `hermes sync` output, re-typeset.

**File:** `docs/media/herd-demo.mp4` · 1920×1080 · 30 fps · 75 s · 1.4 MB
**Subtitles:** `docs/media/herd-demo.srt` · **Poster:** `docs/media/poster.png`

## Shot list

| Time | On screen | Caption |
|---|---|---|
| 0:00 | `ls ~/.hermes` on the desktop | Everything your agent has learned lives in this folder. |
| 0:06 | laptop: `rsync -a desktop:~/.hermes/`, then `grep` → `backend: docker`, then `docker ps` → **command not found** | Copy the folder and the laptop inherits the desktop's Docker path. |
| 0:16 | `hermes sync init` → 76 items, recovery code | Herd. One command, and one recovery code. |
| 0:23 | `hermes sync join … --code HERD-…` → 76 pulled | One paste, and the second machine is the same agent. |
| 0:31 | desktop vs laptop config, side by side | Same model. Same skills. Same memory. *(then)* Its own Docker path. Its own port. It keeps what belongs to the machine. |
| 0:47 | `hermes sync conflicts` → kept `deepseek-v4-pro`, ignored `gpt-5` | Both machines changed the model. Yours wins, and it says so. |
| 0:54 | `hermes sync undo` → 417 files restored | Every pull leaves a backup. One command puts it back. |
| 1:00 | `xxd` of a store object — ciphertext | Encrypted before it ever leaves the machine. |
| 1:07 | End card: *Every tool copies `~/.hermes`. Herd understands `config.yaml.`* | — |

## Voiceover (if you record one)

Speak at the caption, not before it. Roughly 100 words for 75 seconds — leave air.

> Everything your agent has learned lives in this folder. On one computer.
>
> Copy the folder to a second machine and you copy the machine with it — its Docker path, its ports, its bot token. Something breaks, quietly.
>
> Herd. One command gives you a recovery code. Paste it on the laptop and the same agent is there: same model, same skills, same memory.
>
> It takes what's yours. It leaves what's the machine's. When both machines change the same setting, yours wins and it tells you. Every pull leaves a backup.
>
> And it's encrypted before anything leaves the device.
>
> Every tool copies `~/.hermes`. Herd understands `config.yaml`.

## Why it is cut this way

- **The failure before the fix.** "Copy the folder" is what a viewer would try
  first, so the film kills that idea on screen before offering anything. Without
  that beat, the product looks like `rsync` with extra steps.
- **The split screen is the whole thesis.** Everything before it sets up the
  comparison; everything after it proves the comparison is safe to trust.
  Green follows you, amber stays. If a viewer remembers one frame, it's that one.
- **No claim without a command.** "Encrypted" is unverifiable as a word, so the
  hex dump sits under it. A judge who checks has nothing to catch us on.
- **The honest beat stays.** Showing a conflict is retail for a sync tool that
  other tools skip; it is also the moment a technical viewer decides whether to
  trust the thing.
- **Silence is deliberate.** Terminal footage plus a synthetic voice pulls the
  eye to the least real element. Captions first, a human voice if you add one.

## Re-rendering

```bash
python render.py frames                      # 2 340 frames, ~55 s
ffmpeg -framerate 30 -i frames/f%05d.jpg -c:v libx264 -preset slow \
       -crf 18 -pix_fmt yuv420p -movflags +faststart out/herd-demo.mp4
```

Captions live in `CAPTIONS` in `render.py`; the SRT is generated from the same
list, so the two cannot drift.
