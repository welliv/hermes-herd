# The 79-second demo

This one is a **screen recording**, not a re-typeset render. `demo/record.sh`
opens a terminal on a headless display, runs `demo/demo.sh` against two
throwaway Hermes homes, and films the display with `ffmpeg`. Every line on
screen was printed by the real CLI, in the order you see it.

**Film:** `docs/media/herd-demo.mp4` — 1280×720, 79 s, 628 KB, no audio
**Loop:** `docs/media/herd-demo.gif` — 880 px, 616 KB
**Poster:** `docs/media/poster.png`

It has no audio track on purpose: it is watched muted, and a music bed under a
terminal is noise. If you publish it with narration, use the script below.

## Shot list

| Time | On screen | What it proves |
|---|---|---|
| 0:00 | **Two machines. One Hermes.** · `ls desk/skills` → `deploy research writer` · `ls laptop/skills` → *(nothing)* · laptop `cwd: /srv/laptop/work`, `port: 9131` | The second machine is a stranger with the same name |
| 0:07 | `hermes sync init --store ~/hd/store --name desktop` → `pushed 6 item(s)` + recovery code | One command creates the herd |
| 0:16 | `hermes sync join … --code HERD-…` → `pulled 6 item(s)`, `adopted 1 value: model.default` | One paste and the laptop has the same skills, memory and model |
| 0:19 | `ls laptop/skills` → the same three skills | It really arrived |
| 0:29 | laptop `cwd: /srv/laptop/work`, `port: 9131` · desktop `cwd: /home/desk/work`, `port: 9120` | It did **not** copy the machine |
| 0:38 | `hermes sync secrets on` on both → write `DEMO_KEY` on the laptop → sync → `grep DEMO_KEY desk/.env` finds it | Credentials are opt-in and they travel |
| 0:57 | `grep DEMO_KEY desk/.env` finds `DEMO_KEY=herd-demo-123`, then `grep -r herd-demo-123 /tmp/hd/store` → `(no plaintext in the store)` | Encrypted before it leaves |
| 1:04 | `hermes sync undo` → `grep DEMO_KEY desk/.env` → key gone | Every pull is reversible |
| 1:14 | **Same agent. Different machines.** — `hermes sync`: pull, merge, push | The whole product in one line |

## Narration (if you post it with sound)

> Your second machine is a stranger with the same name — no skills, no memory,
> a different model, and settings that belong to the other computer.
>
> Copying the folder is worse: the laptop inherits the desktop's Docker socket
> and its bot token.
>
> So: one command on the desktop creates an encrypted store and prints one
> recovery code. One command on the laptop joins. The skills, the memory, the
> model — they're there. The Docker path and the port — still the laptop's own.
>
> Keys are a switch, off until you ask; when you turn it on they're encrypted
> before they leave. And any pull can be undone.
>
> Same agent. Different machines.

## Why it is cut this way

- **The stranger first, the fix second.** The viewer has to recognise their own
  laptop in the empty skills list before the first command appears.
- **The split screen is the thesis.** Everything before it is setup; everything
  after it proves the merge is safe. If a viewer remembers one frame, it is the
  two `cwd` lines that differ.
- **No claim without the command that shows it.** "Encrypted" is unverifiable as
  a word, so `grep` runs against the store on camera and finds nothing.
- **Secrets are shown as a switch, on both sides.** Off by default is a claim
  the viewer can check by reading the command, not the README.
- **Undo stays in.** Sync tools that cannot undo are the reason people don't
  turn them on.

## Re-recording

Requires a running Bot Screen (`DISPLAY=:20`) with `xfce4-terminal` and `ffmpeg`.

```bash
bash demo/setup.sh /tmp/hd          # two homes, plugin enabled in each
bash demo/record.sh /tmp/demo-raw.mp4      # films 80 s at 1440×900, trimmed to 79

# crop the terminal out of the desktop, then encode
ffmpeg -i /tmp/demo-raw.mp4 \
  -vf "crop=1092:596:66:104,scale=1264:-2,pad=1280:720:8:(oh-ih)/2:black" \
  -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -movflags +faststart \
  docs/media/herd-demo.mp4

ffmpeg -i docs/media/herd-demo.mp4 \
  -vf "fps=10,scale=880:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=96[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4" \
  -loop 0 docs/media/herd-demo.gif

ffmpeg -y -ss 4 -i docs/media/herd-demo.mp4 -frames:v 1 docs/media/poster.png
```

`demo/setup.sh` has one non-obvious step: it runs `hermes --version` in each
home **before** enabling the plugin, because the first run bootstraps that data
root's runtime and would otherwise clear the enablement. `demo/demo.sh` indents
every line by one space, so the terminal's left border never clips a glyph.

## Publishing notes

- The recovery code in the film belongs to a throwaway store under `/tmp`; it is
  dead once the demo home is deleted.
- `DEMO_KEY=herd-demo-123` is not a credential. It exists to be grepped for.
- If you re-record, keep the item counts honest. Six items is the real number for
  two fresh homes; a home with months of use carries dozens.
