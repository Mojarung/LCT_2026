#!/usr/bin/env bash
# Открыть каждый DXF из /w/in в LibreCAD под Xvfb и сложить в /w/out снимки на файл:
#   <имя>.png           вид, вписанный по слоям GREEN_* (план, ведомость, легенда), при этом
#                       включены все слои - исходные и результата; справа список слоёв
#   <имя>.green.png     тот же вид, включены только слои GREEN_*
#   <имя>.layers.png    список слоёв с фильтром GREEN - слои результата отдельно от исходных
#   <имя>.schedule.png  ведомость элементов озеленения крупно (слой GREEN_SCHEDULE)
# Чертёж без слоёв GREEN_* (например, исходник) вписывается целиком, ведомости нет.
#
# Почему не просто «za» (zoom auto): он вписывает весь габарит, а подоснова бывает в разы шире
# плана (у фрагмента Берзарина граница заказа - 2,9 км при плане 0,4 км), и план сжимается в
# полоску. LibreCAD вписывает только видимые слои, а окно зума не принимает координат из строки
# команд, поэтому скрипт скрывает все слои, показывает слои GREEN_*, делает «za» и снова
# включает все слои: вид остаётся на результате.
#
# LibreCAD каждый раз стартует с чистыми настройками (окно первого запуска закрывается кликом),
# окно разворачивается на весь экран 1600x1000, панель Pen Wizard закрывается - поэтому
# координаты строки команд и списка слоёв известны заранее. Загрузка ждётся по заголовку окна,
# а не фиксированной паузой: LibreCAD читает DXF на 33 МБ несколько минут.
set -u
IN=/w/in
OUT=/w/out
mkdir -p "$OUT"
export DISPLAY=:99
log() { printf '%s\n' "$*" | tee -a "$OUT/cadcheck.log"; }
if command -v import >/dev/null; then SHOT="import"; else SHOT="magick import"; fi
shot() { $SHOT -window root "$OUT/$1" >>"$OUT/cadcheck.log" 2>&1; }

# Координаты на экране 1600x1000 после разворота окна и закрытия Pen Wizard.
CMD_X=1445 CMD_Y=884            # строка команд
FILTER_X=1440 FILTER_Y=123      # фильтр списка слоёв
FILTER_CLEAR_X=1583             # крестик очистки фильтра
SHOW_ALL_X=1338 HIDE_ALL_X=1378 # «показать все» и «скрыть все»: действуют на слои под фильтром
LAYER_BUTTONS_Y=155

click() { xdotool mousemove "$1" "$2" click 1 >/dev/null 2>&1; sleep 1; }
command_line() {
  click $CMD_X $CMD_Y
  xdotool type --delay 120 "$1" >/dev/null 2>&1
  xdotool key Return >/dev/null 2>&1
}
filter_layers() {
  click $FILTER_CLEAR_X $FILTER_Y
  if [ -n "$1" ]; then
    click $FILTER_X $FILTER_Y
    xdotool type --delay 120 "$1" >/dev/null 2>&1
  fi
  sleep 2
}
# Вписать вид по слоям, в имени которых есть $1, и снова включить все слои. Если задан $2 -
# снимок с этим именем, пока включены только слои $1.
zoom_to_layers() {
  filter_layers ""
  click $HIDE_ALL_X $LAYER_BUTTONS_Y
  sleep 3
  filter_layers "$1"
  click $SHOW_ALL_X $LAYER_BUTTONS_Y
  sleep 3
  command_line za
  sleep 5
  if [ -n "${2:-}" ]; then
    shot "$2" && log "снимок только слоёв $1: ok"
  fi
  filter_layers ""
  click $SHOW_ALL_X $LAYER_BUTTONS_Y
  sleep "$REDRAW"
}

log "== $(. /etc/os-release && echo "$PRETTY_NAME"), $(dpkg-query -W -f='${Package} ${Version}' librecad)"

for f in "$IN"/*.dxf; do
  [ -e "$f" ] || { log "в $IN нет DXF"; exit 1; }
  name=$(basename "$f" .dxf)
  size_mb=$(du -m "$f" | cut -f1)
  LOAD_LIMIT=$((120 + size_mb * 20))
  REDRAW=$((8 + size_mb / 2))
  log "--- $name ($size_mb МБ)"

  rm -rf "$HOME/.config/LibreCAD"
  Xvfb :99 -screen 0 1600x1000x24 >/dev/null 2>&1 &
  XPID=$!
  sleep 2
  start=$(date +%s)
  librecad "$f" >"$OUT/$name.librecad.log" 2>&1 &
  LPID=$!

  # Окно первого запуска (единицы и язык) закрывается кликом по «OK».
  for _ in $(seq 1 15); do
    sleep 2
    if xdotool search --name "Welcome" >/dev/null 2>&1; then
      xdotool mousemove 1078 632 click 1 >/dev/null 2>&1
      break
    fi
  done

  win=""
  while [ $(($(date +%s) - start)) -lt "$LOAD_LIMIT" ]; do
    win=$(xdotool search --onlyvisible --name "$name" 2>/dev/null | head -1)
    [ -n "$win" ] && break
    sleep 5
  done
  if [ -z "$win" ]; then
    log "документ НЕ открыт за $LOAD_LIMIT с - смотри снимок"
    shot "$name.png"
    kill $LPID $XPID >/dev/null 2>&1
    sleep 1
    continue
  fi
  log "документ открыт за $(($(date +%s) - start)) с: $(xdotool getwindowname "$win")"

  xdotool windowmove "$win" 0 0 >/dev/null 2>&1
  xdotool windowsize "$win" 1600 1000 >/dev/null 2>&1
  sleep 3
  click 1592 100 # закрыть Pen Wizard: список слоёв вытягивается на всю высоту
  sleep 2

  if grep -aq -m1 'GREEN_' "$f"; then
    zoom_to_layers GREEN "$name.green.png"
    log "вид вписан по слоям GREEN_*, включены все слои"
  else
    command_line za
    sleep "$REDRAW"
    log "слоёв GREEN_* нет: вписан весь чертёж"
  fi
  shot "$name.png" && log "снимок чертежа: ok"

  filter_layers GREEN
  shot "$name.layers.png" && log "снимок слоёв GREEN: ok"

  if grep -aq -m1 'GREEN_SCHEDULE' "$f"; then
    zoom_to_layers GREEN_SCHEDULE
    shot "$name.schedule.png" && log "снимок ведомости: ok"
  fi

  kill $LPID $XPID >/dev/null 2>&1
  sleep 1
done
log "== готово: $OUT"
