#!/usr/bin/env bash
# Prepare two throwaway Hermes homes for the demo. Not filmed; run once.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${1:-/tmp/hd}"

rm -rf "$ROOT"; mkdir -p "$ROOT/desk/plugins/herd" "$ROOT/laptop/plugins/herd"

for home in desk laptop; do
  mkdir -p "$ROOT/$home/skills" "$ROOT/$home/memories" "$ROOT/$home/plugins/herd"
  cp -r "$REPO/herd" "$REPO/__init__.py" "$REPO/plugin.yaml" "$REPO/pyproject.toml" "$ROOT/$home/plugins/herd/"
  printf 'memories from the %s\n' "$home" > "$ROOT/$home/memories/MEMORY.md"
done

# the desktop: a home with a few skills and its own machine-bound settings
for s in research writer deploy; do
  mkdir -p "$ROOT/desk/skills/$s"
  printf -- '---\nname: %s\ndescription: %s skill\n---\nbody\n' "$s" "$s" > "$ROOT/desk/skills/$s/SKILL.md"
done
cat > "$ROOT/desk/config.yaml" <<'YAML'
model:
  default: deepseek-v4-flash
  provider: deepseek
display:
  skin: default
terminal:
  backend: local
  cwd: /home/desk/work
webapp:
  port: 9120
YAML

# the laptop: same agent, different machine
cat > "$ROOT/laptop/config.yaml" <<'YAML'
model:
  default: something-else
  provider: deepseek
display:
  skin: default
terminal:
  backend: docker
  cwd: /srv/laptop/work
webapp:
  port: 9131
YAML

# enable last: `hermes plugins enable` rewrites config.yaml, so the machine
# settings above must already be in place.
for home in desk laptop; do
  # first run bootstraps this data root's runtime; enabling before that is lost
  HERMES_HOME="$ROOT/$home" hermes --version >/dev/null 2>&1 || true
  HERMES_HOME="$ROOT/$home" hermes plugins enable herd >/dev/null
done

echo "ready: $ROOT"
