#!/usr/bin/env bash
# The demo. Every command below runs for real.
set -uo pipefail
ROOT="${1:-/tmp/hd}"
: > "$ROOT/timing.log" 2>/dev/null || true
DESK="HERMES_HOME=$ROOT/desk"
LAPTOP="HERMES_HOME=$ROOT/laptop"
STORE="$ROOT/store"

B='\033[1m'; D='\033[2m'; C='\033[36m'; G='\033[32m'; R='\033[0m'

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
say "One command on the desktop starts the herd."
OUT=$(HERMES_HOME="$ROOT/desk" hermes sync pair "$STORE" --name desktop 2>&1)
printf '%s\n' "$OUT" | sed 's/^/  /'
CODE=$(printf '%s\n' "$OUT" | grep -oE '[A-Z2-7]{5}(-[A-Z2-7]{5}){3}' | head -1)
sleep 1.5
dim "One short code. It works once, for fifteen minutes."

printf "\033[2J\033[H"
say "Type it on the laptop."
printf "\n${C} \$ %s${R}\n" "HERMES_HOME=$ROOT/laptop hermes sync pair $STORE --code $CODE --name laptop"
sleep 0.8
HERMES_HOME="$ROOT/laptop" hermes sync pair "$STORE" --code "$CODE" --name laptop 2>&1 | sed 's/^/  /'
sleep 1.4
hold 2
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
say "When both machines change the same thing, you choose."
sed -i 's/skin: .*/skin: desk/' "$ROOT/desk/config.yaml"
HERMES_HOME="$ROOT/desk" hermes sync >/dev/null 2>&1
sed -i 's/skin: .*/skin: laptop/' "$ROOT/laptop/config.yaml"
HERMES_HOME="$ROOT/laptop" hermes sync >/dev/null 2>&1
cmd "$LAPTOP hermes sync conflicts </dev/null"
hold 1
cmd "$LAPTOP hermes sync conflicts --item config --take theirs"
cmd "$LAPTOP hermes sync status | head -2"

printf "\033[2J\033[H"
say "Credentials are a switch, not a default."
cmd "$DESK hermes sync secrets on"
cmd "$LAPTOP hermes sync secrets on"
printf 'DEMO_KEY=herd-demo-123\n' > "$ROOT/laptop/.env"
cmd "$LAPTOP hermes sync"
cmd "$DESK hermes sync"
cmd "grep DEMO_KEY $ROOT/desk/.env"
hold 1
dim "The store only ever holds ciphertext."
cmd "grep -r 'herd-demo-123' $STORE || echo '(no plaintext in the store)'"

printf "\033[2J\033[H"
say "And it can always be undone."
cmd "$DESK hermes sync undo"
hold 0.5
cmd "grep DEMO_KEY $ROOT/desk/.env || echo '(restored: the key is gone again)'"
hold 1

printf "\033[2J\033[H"
printf "\n${G} Same agent. Different machines.${R}\n"
dim "hermes sync — pull, merge, push. Nothing else to manage."
hold 1.5
