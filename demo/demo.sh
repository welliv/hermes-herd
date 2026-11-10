#!/usr/bin/env bash
# The 75-second demo. Every command below runs for real.
set -uo pipefail
ROOT="${1:-/tmp/hd}"
: > "$ROOT/timing.log" 2>/dev/null || true
DESK="HERMES_HOME=$ROOT/desk"
LAPTOP="HERMES_HOME=$ROOT/laptop"
STORE="$ROOT/store"

B='\033[1m'; D='\033[2m'; C='\033[36m'; G='\033[32m'; Y='\033[33m'; R='\033[0m'

say()  { printf "\n${B} %s${R}\n" "$*"; printf "%s\t%s\n" "$SECONDS" "$*" >> "$ROOT/timing.log"; sleep 1.1; }
dim()  { printf "${D} %s${R}\n" "$*"; sleep 0.9; }
cmd()  { printf "\n${C} \$ %s${R}\n" "$*"; sleep 0.8; eval "$@" 2>&1 | sed 's/^/  /'; sleep 1.3; }
hold() { sleep "${1:-2}"; }

printf "\033[2J\033[H"
say "Two machines. One Hermes."
dim "This is the desktop: three skills, its own settings."
cmd "ls $ROOT/desk/skills"
hold 1
dim "This is the laptop today: a different agent with the same name."
cmd "ls $ROOT/laptop/skills || echo '(nothing)'"
cmd "grep -E 'cwd|port' $ROOT/laptop/config.yaml"

printf "\033[2J\033[H"
say "One command on the desktop creates the herd."
cmd "$DESK hermes sync init --store $STORE --name desktop"
hold 3
CODE=$(python3 - <<'PY'
import json, glob, os
p = sorted(glob.glob("/tmp/hd/desk/plugin-data/herd/identity.json"))
print(json.load(open(p[0]))["code"] if p else "")
PY
)
dim "The code it printed is the only thing the laptop needs."

printf "\033[2J\033[H"
say "On the laptop, one command joins."
printf "\n${C} \$ %s${R}\n" "HERMES_HOME=$ROOT/laptop hermes sync join $STORE --code ${CODE:0:11}… --name laptop"
sleep 0.7
HERMES_HOME="$ROOT/laptop" hermes sync join "$STORE" --code "$CODE" --name laptop 2>&1 | sed 's/^/  /'
sleep 0.9
hold 3
dim "It pulled the desktop's settings, skills and memory."
cmd "ls $ROOT/laptop/skills"
cmd "grep -E 'default:' $ROOT/laptop/config.yaml"

printf "\033[2J\033[H"
say "It did not copy the machine."
dim "Each machine keeps what belongs to it."
cmd "grep -E 'cwd|port' $ROOT/laptop/config.yaml"
cmd "grep -E 'cwd|port' $ROOT/desk/config.yaml"
dim "Same model, same skills — different machine."
hold 2

printf "\033[2J\033[H"
say "Credentials are a switch, not a default."
cmd "$DESK hermes sync secrets on"
cmd "$LAPTOP hermes sync secrets on"
printf 'DEMO_KEY=herd-demo-123\n' > "$ROOT/laptop/.env"
cmd "$LAPTOP hermes sync"
cmd "$DESK hermes sync"
cmd "grep DEMO_KEY $ROOT/desk/.env"
hold 2
dim "The store only ever holds ciphertext."
cmd "grep -r 'herd-demo-123' $STORE || echo '(no plaintext in the store)'"
hold 2

printf "\033[2J\033[H"
say "And it can always be undone."
cmd "$DESK hermes sync undo"
hold 1
cmd "grep DEMO_KEY $ROOT/desk/.env || echo '(restored: the key is gone again)'"
hold 2

printf "\033[2J\033[H"
printf "\n${G} Same agent. Different machines.${R}\n"
dim "hermes sync — pull, merge, push. Nothing else to manage."
hold 3
