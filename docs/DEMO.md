# The 75-second demo

Screen film, captions first: it has to work muted, because judges watch in
tabs. A music bed sits under it at −22 LUFS and leans back when the Docker
error lands, so the failure is heard rather than covered.

Every line on screen was printed by the real CLI and re-typeset — no mock-ups,
no invented output.

**Film:** `docs/media/herd-demo.mp4` · 3.2 MB · 75 s · 48 kHz stereo
**Silent cut:** `docs/media/herd-demo-silent.mp4` · 1.4 MB
**Subtitles:** `docs/media/herd-demo.srt` · **Poster:** `docs/media/poster.png`
**Music:** Kevin MacLeod — "Perspectives" (incompetech.com), CC BY — the credit
is required, keep it wherever the film is published.

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

## Sound

A bed, not a voice. A synthetic voice reading a product name wrong is a defect
the viewer hears; a quiet bed that is merely a little generic is not. The one
musical decision: the bed drops to a third of its level at 0:11.9 when the
Docker error appears, and comes back at 0:17.2 with the first `sync init`.

Mixed at −22.4 LUFS integrated, peak −8.8 dB, 2.6 s fade in, 5 s fade out.
It never sits over a claim that needs reading.

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
- **Music, not narration.** The film has to be legible muted; a bed adds
  presence without adding claims. The duck at the failure is the only time the
  sound comments on the picture.

## Re-rendering

```bash
python render.py frames                      # 2 250 frames, ~55 s
ffmpeg -framerate 30 -i frames/f%05d.jpg -c:v libx264 -preset slow \
       -crf 18 -pix_fmt yuv420p -movflags +faststart out/herd-demo.mp4
```

Captions live in `CAPTIONS` in `render.py`; the SRT is generated from the same
list, so the two cannot drift.
