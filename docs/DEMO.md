# The 90-second demo

Two terminals, side by side. One store folder. No slides.

## 0:00 — the gap

Terminal A (desktop):

```
$ hermes sync init --store ~/herd-store
Herd is set up on desktop.
  pushed  76 item(s)
  Your recovery code — copy it to every machine you want in the herd:
    HERD-…
```

*"This is my Hermes. Seventy-six items: config, seventy-five skills, memory, keys."*

## 0:10 — the naive fix breaks

Terminal B (laptop), same script everyone reaches for:

```
$ rsync -a desktop:~/.hermes/ ~/.hermes/
$ hermes chat -q "run the tests"
… error: cannot connect to the Docker daemon at unix:///var/run/docker.sock
```

*"Because the config moved too. My laptop now runs commands in my desktop's Docker socket."*

## 0:25 — the one command

```
$ hermes sync join ~/herd-store --code HERD-…
Joined the herd as laptop.
  pulled  76 item(s)
  adopted 2 value(s) from the store: model.default, display.skin
```

*"Same store. Same code."*

## 0:35 — show, don't tell

Terminal B:

```
$ hermes sync status
  config        in-sync
  skill:demo    in-sync
  env           in-sync
```

Then one file, on screen:

```yaml
terminal:
  backend: docker        # ← laptop kept its own
  cwd: /srv/laptop
webapp:
  port: 9999
model:
  default: deepseek-v4-flash   # ← followed me from the desktop
```

*"It took what belongs to me. It left what belongs to the machine."*

## 0:50 — the change that proves the loop

On the laptop: add a skill, switch the skin, add an API key. `hermes sync`.
On the desktop: `hermes sync`. All three arrive. The desktop's port and bot token are untouched.

## 1:05 — the honest part

Edit the same key on both, sync the laptop, then the desktop:

```
$ hermes sync conflicts
config · display.skin
  kept    "neon"   (this machine)
  ignored "mono"   (store)
```

*"It doesn't guess which one I meant. It keeps mine and tells me what the other machine had."*

## 1:15 — the safety net

```
$ hermes sync undo
Restored 4 file(s)
```

*"Every pull keeps a copy of what it changed."*

## 1:20 — the close

*"Hermes gets better the longer you use it. That value shouldn't be trapped on one computer. One store, encrypted before anything leaves the device, and the same agent on every machine you own."*

> **Every tool copies `~/.hermes`. This one understands `config.yaml`.**

## Before recording

- Reset both demo homes to known state; run the whole flow once, in order, on camera-less.
- Have the recovery code pasted in a text file, not typed live.
- The Docker error is the one moment worth faking: pre-capture it, in case the daemon is not running on demo day.
