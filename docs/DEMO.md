# The 75-second demo

Narrated screen film. Every line on screen is real `hermes sync` output,
re-typeset; the captions carry the same argument, so the silent cut works on its
own for anyone watching muted.

**Narrated:** `docs/media/herd-demo.mp4` · 2.6 MB · −16.4 LUFS · 48 kHz stereo
**Silent:** `docs/media/herd-demo-silent.mp4` · 1.4 MB
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

## Narration

Eleven clips, each placed on its beat rather than one continuous take, so the
voice lands on the cut instead of drifting against it.

| In | Line |
|---|---|
| 0:00 | Everything this agent has learned about me lives in one folder. |
| 0:06 | Copy the folder, and you copy the machine with it. Its Docker path, its ports. Something breaks. |
| 0:16 | Herd. One command, and one recovery code. |
| 0:24 | Paste it on the laptop, and the same agent is there. Same model, same skills, same memory. |
| 0:31 | It takes what's mine. |
| 0:36 | And it leaves what belongs to the machine. |
| 0:39 | Its own Docker path, its own port, its own bot token. |
| 0:44 | Everything else follows you. |
| 0:47 | When both machines change the same setting, mine wins. And it tells me. |
| 0:55 | Every pull leaves a backup. |
| 1:01 | And it's encrypted before anything leaves the device. |
| 1:07 | Every tool copies the whole folder. Herd understands what's inside it. |

Spoken in the first person because the film shows one person's machine; the
closing line drops `config.yaml` for plain English — the card says it, and
"config dot yaml" is heard as "config that yaml" by half of listeners.

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
- **Voice over silence, deliberately.** The narration stays first person and
  never describes the frame ("as you can see"); it says the thing the frame
  means. Lines end before their caption does, so the viewer reads the last
  words rather than hearing them twice.

## Re-rendering

```bash
python render.py frames                      # 2 340 frames, ~55 s
ffmpeg -framerate 30 -i frames/f%05d.jpg -c:v libx264 -preset slow \
       -crf 18 -pix_fmt yuv420p -movflags +faststart out/herd-demo.mp4
```

Captions live in `CAPTIONS` in `render.py`; the SRT is generated from the same
list, so the two cannot drift.
