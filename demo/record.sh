#!/usr/bin/env bash
# Record demo/demo.sh in a terminal on the bot display.
set -uo pipefail
export DISPLAY=:20
export XAUTHORITY=/root/.hermes/bot-desktop/Xauthority

ROOT=/tmp/hd
OUT=${1:-/tmp/demo-raw.mp4}

pkill -x xfce4-terminal >/dev/null 2>&1 || true
sleep 1
bash /root/work/herd/demo/setup.sh "$ROOT" >/dev/null 2>&1 || { echo "setup failed"; exit 1; }

cat >/tmp/herd-run.sh <<RUN
#!/usr/bin/env bash
bash /root/work/herd/demo/demo.sh $ROOT
sleep 5
RUN
chmod +x /tmp/herd-run.sh

nohup xfce4-terminal --disable-server --geometry=120x26+60+60 \
  --font="DejaVu Sans Mono 14" --hide-menubar --hide-toolbar --hide-scrollbar \
  --title="herd" -e "bash /tmp/herd-run.sh" >/tmp/term.log 2>&1 &
sleep 3

ffmpeg -y -loglevel error -f x11grab -framerate 15 -video_size 1440x900 -i :20 \
  -t 80 -c:v libx264 -preset veryfast -crf 20 "$OUT"

ls -l "$OUT"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT"
