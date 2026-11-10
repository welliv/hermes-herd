# The 92-second demo

This is a **screen recording**, not a re-typeset render. `demo/record.sh` opens
a terminal on a headless display, runs `demo/demo.sh` against two throwaway
Hermes homes, and films the display with `ffmpeg`. Every line on screen was
printed by the real CLI, in the order you see it.

**Film:** `docs/media/herd-demo.mp4` — 1280×720, 92 s, 696 KB, no audio
**Loop:** `docs/media/herd-demo.gif` — 880 px, 759 KB
**Poster:** `docs/media/poster.png`

It has no audio track on purpose: it is watched muted, and a music bed under a
terminal is noise. If you publish it with narration, use the script below.

## Shot list

| Time | On screen | What it proves |
|---|---|---|
| 0:00 | **Two machines. One Hermes.** · `ls desk/skills` → `deploy research writer` · `ls laptop/skills` → *(nothing)* · laptop `cwd: /srv/laptop/work`, `port: 9131` | The second machine is a stranger with the same name |
| 0:07 | `hermes sync pair ~/hd/store --name desktop` → `Ready to pair`, one 20-character code, `works once, for 15 minutes` | One command starts the herd, and the code is short enough to type on a phone |
| 0:13 | `hermes sync pair --code XXXX-… --name laptop` → `Paired with desktop`, `pulled 6 item(s)`, `In sync · 2 machines · synced just now` | One paste, and the laptop is the same agent |
| 0:20 | `ls laptop/skills` → the same three skills | It really arrived |
| 0:27 | laptop `cwd: /srv/laptop/work`, `port: 9131` · desktop `cwd: /home/desk/work`, `port: 9120` | It did **not** copy the machine |
| 0:36 | both machines change `display.skin` → `hermes sync conflicts` shows `1 this machine "laptop"` / `2 the store "desk"` → `--take theirs` → `In sync` | A disagreement is a choice, not a merge conflict |
| 0:54 | `hermes sync secrets on` on both → write `DEMO_KEY` on the laptop → sync → `grep DEMO_KEY desk/.env` finds it | Credentials are opt-in and they travel |
| 1:07 | `grep -r herd-demo-123 ~/hd/store` → `(no plaintext in the store)` | Encrypted before it leaves |
| 1:19 | `hermes sync undo` → `grep DEMO_KEY desk/.env` → key gone | Every pull is reversible |
| 1:29 | **Same agent. Different machines.** — `hermes sync`: pull, merge, push | The whole product in one line |

## Narration (if you post it with sound)

> Your second machine is a stranger with the same name — no skills, no memory,
> a different model, and settings that belong to the other computer.
>
> Copying the folder is worse: the laptop inherits the desktop's Docker socket
> and its bot token.
>
> So: one command on the desktop creates an encrypted store and prints one
> short code. One paste on the laptop, and the skills, the memory, the model are
> there — while the Docker path and the port stay the laptop's own.
>
> When both machines change the same thing, it doesn't guess: it shows you both
> values and you press 1 or 2. Keys are a switch, off until you ask. And any
> pull can be undone.
>
> Same agent. Different machines.

## Why it is cut this way

- **The stranger first, the fix second.** The viewer has to recognise their own
  laptop in the empty skills list before the first command appears.
- **The code is the headset's one button.** A 20-character, single-use code is
  the shortest thing that can carry a real key without a service in the middle;
  the 52-character recovery code still exists, and the film never makes you
  look at it.
- **The split screen is the thesis.** Everything before it is setup; everything
  after it proves the merge is safe. If a viewer remembers one frame, it is the
  two `cwd` lines that differ.
- **The conflict beat is the trust beat.** Tools that hide collisions are the
  reason people stop trusting sync; one card and one key is the whole promise.
- **No claim without the command that shows it.** "Encrypted" is unverifiable as
  a word, so `grep` runs against the store on camera and finds nothing.
- **Undo stays in.** Sync tools that cannot undo are the reason people don't
  turn them on.

## Re-recording

Requires a running Bot Screen (`DISPLAY=:20`) with `xfce4-terminal` and `ffmpeg`.

```bash
bash demo/setup.sh /tmp/hd                 # two homes, plugin enabled in each
bash demo/record.sh /tmp/demo-raw.mp4      # films 115 s at 1440×900, trimmed to 92

# crop the terminal out of the desktop, then encode
ffmpeg -i /tmp/demo-raw.mp4 -t 92 \
  -vf "crop=1092:596:66:104,scale=1264:-2,pad=1280:720:8:(oh-ih)/2:black" \
  -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -movflags +faststart \
  docs/media/herd-demo.mp4

ffmpeg -i docs/media/herd-demo.mp4 \
  -vf "fps=10,scale=880:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=96[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4" \
  -loop 0 docs/media/herd-demo.gif

ffmpeg -y -ss 8 -i docs/media/herd-demo.mp4 -frames:v 1 docs/media/poster.png
```

Three things in the recording setup are not obvious:

- `demo/setup.sh` runs `hermes --version` in each home **before** enabling the
  plugin, because the first run bootstraps that data root's runtime and would
  otherwise clear the enablement.
- `demo/demo.sh` indents every line by one space, so the terminal's left border
  never clips a glyph.
- `HERMES_HOME=x cmd` must be written out, never as `$VAR cmd`: bash does not
  re-parse a variable expansion as an assignment prefix, and with stderr
  redirected the failure is silent.

## Publishing notes

- The pairing code in the film is for a throwaway store under `/tmp`; it is dead
  once the demo home is deleted, and it was already single-use.
- `DEMO_KEY=herd-demo-123` is not a credential. It exists to be grepped for.
- If you re-record, keep the item counts honest. Six items is the real number for
  two fresh homes; a home with months of use carries dozens.
