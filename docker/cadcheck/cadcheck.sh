#!/usr/bin/env bash
# Открыть каждый DXF из /w/in в LibreCAD под Xvfb и сложить в /w/out два снимка на файл:
#   <имя>.png         чертёж, вписанный в окно, и список слоёв
#   <имя>.layers.png  список слоёв с фильтром GREEN - слои результата отдельно от исходных
# Ожидание загрузки пропорционально размеру: LibreCAD читает файл на 76 МБ дольше двух минут.
# Экран фиксирован (1600x1000), поэтому координаты диалога и полей известны заранее.
set -u
IN=/w/in
OUT=/w/out
mkdir -p "$OUT"
log() { printf '%s\n' "$*" | tee -a "$OUT/cadcheck.log"; }
if command -v import >/dev/null; then SHOT="import"; else SHOT="magick import"; fi

log "== $(. /etc/os-release && echo "$PRETTY_NAME"), $(dpkg-query -W -f='${Package} ${Version}' librecad)"

for f in "$IN"/*.dxf; do
  [ -e "$f" ] || { log "в $IN нет DXF"; exit 1; }
  name=$(basename "$f" .dxf)
  size_mb=$(du -m "$f" | cut -f1)
  log "--- $name ($size_mb МБ)"

  Xvfb :99 -screen 0 1600x1000x24 >/dev/null 2>&1 &
  XPID=$!
  sleep 2
  DISPLAY=:99 librecad "$f" >>"$OUT/cadcheck.log" 2>&1 &
  LPID=$!

  # Диалог первого запуска (единицы и язык) закрывается кликом по «OK».
  for _ in $(seq 1 15); do
    sleep 2
    if DISPLAY=:99 xdotool search --name "Welcome" >/dev/null 2>&1; then
      DISPLAY=:99 xdotool mousemove 1078 632 click 1 >/dev/null 2>&1
      break
    fi
  done

  sleep $((30 + size_mb * 5))
  if DISPLAY=:99 xdotool search --name "$name" >/dev/null 2>&1; then
    log "документ открыт: $(DISPLAY=:99 xdotool search --name "$name" | head -1 | xargs -I{} sh -c 'DISPLAY=:99 xdotool getwindowname {}')"
  else
    log "документ НЕ открыт за $((30 + size_mb * 5)) с - смотри снимок"
  fi

  # Файл открывается на виде у начала координат, а участок лежит в километрах от нуля:
  # «za» (zoom auto) в строке команд вписывает чертёж в окно.
  DISPLAY=:99 xdotool mousemove 950 618 click 1 >/dev/null 2>&1
  sleep 1
  DISPLAY=:99 xdotool type --delay 120 "za" >/dev/null 2>&1
  DISPLAY=:99 xdotool key Return >/dev/null 2>&1
  sleep 8
  DISPLAY=:99 $SHOT -window root "$OUT/$name.png" >>"$OUT/cadcheck.log" 2>&1 && log "снимок чертежа: ok"

  DISPLAY=:99 xdotool mousemove 955 320 click 1 >/dev/null 2>&1
  sleep 1
  DISPLAY=:99 xdotool type --delay 120 "GREEN" >/dev/null 2>&1
  sleep 3
  DISPLAY=:99 $SHOT -window root "$OUT/$name.layers.png" >>"$OUT/cadcheck.log" 2>&1 && log "снимок слоёв GREEN: ok"

  kill $LPID $XPID >/dev/null 2>&1
  sleep 1
done
log "== готово: $OUT"
