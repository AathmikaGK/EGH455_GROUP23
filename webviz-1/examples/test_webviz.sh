#!/usr/bin/env bash
# end to end check of the web viz with curl. sends sample data for every
# subsystem, checks each reply, then reads it all back out.
#
#   bash examples/test_webviz.sh                         # web viz on this machine, port 8000
#   bash examples/test_webviz.sh http://<pi ip>          # through nginx on the pi
#   bash examples/test_webviz.sh http://127.0.0.1:8000 stream
#        ^ no checks, just sends live sample data for 2 minutes so you can watch the dashboard
#   bash examples/test_webviz.sh http://127.0.0.1:8000 live 300
#        ^ the checks first, then 300 s of live data
#
# run it from git bash, not powershell: there "bash" can start wsl, which cannot
# see 127.0.0.1 on windows.
# needs curl, awk and python with opencv (only to make the test jpeg once)

BASE="${1:-http://127.0.0.1:8000}"
MODE="${2:-}"
LIVE_SECONDS="${3:-120}"

HERE="$(cd "$(dirname "$0")" && pwd)"
IMG="$HERE/test_frame.jpg"
# git bash on windows: curl -F needs C:/... not /c/..., the pi does not need this
if command -v cygpath > /dev/null; then IMG="$(cygpath -m "$IMG")"; fi
OUT="$(mktemp)"
PASS=0
FAIL=0

green() { printf "\033[32m%s\033[0m\n" "$1"; }
red() { printf "\033[31m%s\033[0m\n" "$1"; }

# check NAME EXPECTED_CODE TEXT_IN_REPLY curl-args...
# TEXT_IN_REPLY may be "" to only check the status code
check() {
  local name="$1" want="$2" text="$3"
  shift 3
  local code
  code=$(curl -s -o "$OUT" -w "%{http_code}" --max-time 10 "$@")
  if [ "$code" = "$want" ] && { [ -z "$text" ] || grep -q -- "$text" "$OUT"; }; then
    green "PASS  $name"
    PASS=$((PASS + 1))
  else
    red "FAIL  $name  (got $code, wanted $want${text:+ and \"$text\"})"
    head -c 300 "$OUT"; echo
    FAIL=$((FAIL + 1))
  fi
}

post_json() {
  # post_json NAME EXPECTED_CODE TEXT PATH JSON
  check "$1" "$2" "$3" -X POST -H "Content-Type: application/json" -d "$5" "$BASE$4"
}

now() { date +%s; }

# a 640 x 480 test frame with a valve, a gauge and aruco marker 7 drawn in it
make_image() {
  [ -f "$IMG" ] && return
  python - "$IMG" <<'EOF'
import sys, cv2, numpy as np
img = np.full((480, 640, 3), (70, 75, 80), np.uint8)
cv2.rectangle(img, (0, 300), (640, 480), (55, 60, 62), -1)
cv2.rectangle(img, (220, 160), (320, 240), (200, 120, 40), -1)
cv2.circle(img, (470, 160), 60, (235, 235, 235), -1)
cv2.line(img, (470, 160), (430, 190), (20, 20, 20), 3)
m = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100), 7, 80)
img[320:400, 100:180] = cv2.cvtColor(m, cv2.COLOR_GRAY2BGR)
cv2.imwrite(sys.argv[1], img, [cv2.IMWRITE_JPEG_QUALITY, 70])
EOF
  [ -f "$IMG" ] || { red "could not make $IMG, put any 640x480 jpeg there"; exit 1; }
}

make_image

if [ "$MODE" != "stream" ]; then
echo "testing the web viz at $BASE"
echo

echo "== server"
check "health check" 200 '"ok":true' "$BASE/healthz"
check "status page" 200 '"writer"' "$BASE/api/status"
check "dashboard page" 200 "root" "$BASE/"

echo
echo "== air quality readings (AQ)"
post_json "one reading" 202 '"accepted":1' /api/ingest/reading \
  "{\"temperature\": 24.3, \"pressure\": 1012.6, \"humidity\": 41.2, \"light\": 356, \"oxidising_ppm\": 0.82, \"reducing_ppm\": 2.1, \"ammonia_ppm\": 0.64, \"captured_at\": $(now)}"
post_json "batch of two readings" 202 '"accepted":2' /api/ingest/reading \
  '[{"temperature": 24.5, "humidity": 41.0}, {"temperature": 24.6, "humidity": 40.8}]'
post_json "reading out of range is refused" 400 "out of range" /api/ingest/reading \
  '{"temperature": 500}'
post_json "empty reading is refused" 400 "no values" /api/ingest/reading '{}'

echo
echo "== targets as json (TAQ, old route)"
post_json "valve open" 202 '"accepted":1' /api/ingest/detection \
  '{"type": "valve", "valve_state": "open", "confidence": 0.93}'
post_json "gauge 1.85 bar" 202 '"accepted":1' /api/ingest/detection \
  '{"type": "gauge", "gauge_value": 1.85, "gauge_units": "bar", "confidence": 0.88}'
post_json "aruco list from the taq" 202 '"accepted":1' /api/ingest/detection \
  '[{"id": 7, "x": 0.41, "y": -0.03, "z": 1.21, "uav": {"x": -0.38, "y": 0.12, "z": 1.17}}]'
post_json "empty frame (no markers)" 202 '"accepted":0' /api/ingest/detection 'null'
post_json "bad valve state is refused" 400 "valve_state" /api/ingest/detection \
  '{"type": "valve", "valve_state": "half"}'

echo
echo "== frames from the image processing (TAQ)"
make_image
check "live frame, no targets" 202 '"frame_id"' \
  -F "frame=@$IMG;type=image/jpeg" -F "captured_at=$(now)" -F "camera=OAK-D Lite RGB" \
  "$BASE/api/ingest/frame"
check "frame with valve, gauge and aruco" 202 '"accepted":3' \
  -F "frame=@$IMG;type=image/jpeg" -F "captured_at=$(now)" -F "camera=OAK-D Lite RGB" \
  -F 'targets=[{"type":"valve","valve_state":"closed","confidence":0.9,"box":[216,156,324,244]},{"type":"gauge","gauge_value":1.62,"gauge_units":"bar","confidence":0.85,"box":[406,96,534,224]},{"type":"aruco","id":7,"x":0.35,"y":0.18,"z":0.82,"uav":{"x":-0.33,"y":-0.2,"z":1.02},"corners":[[100,320],[180,320],[180,400],[100,400]]}]' \
  "$BASE/api/ingest/frame"
FRAME_ID=$(grep -o '"frame_id":[0-9]*' "$OUT" | cut -d: -f2)
check "frame with an empty target list" 202 '"accepted":0' \
  -F "frame=@$IMG;type=image/jpeg" -F "targets=[]" "$BASE/api/ingest/frame"
check "bad box is refused, frame still taken" 202 '"rejected":1' \
  -F "frame=@$IMG;type=image/jpeg" -F 'targets=[{"type":"valve","valve_state":"open","box":[50,50,10,10]}]' \
  "$BASE/api/ingest/frame"
check "raw jpeg body" 202 '"frame_id"' \
  -H "Content-Type: image/jpeg" --data-binary "@$IMG" "$BASE/api/ingest/frame"
check "not a jpeg is refused" 400 "jpeg" \
  -H "Content-Type: image/jpeg" --data-binary "hello" "$BASE/api/ingest/frame"
check "targets that are not json are refused" 400 "json list" \
  -F "frame=@$IMG;type=image/jpeg" -F "targets=oops" "$BASE/api/ingest/frame"

echo
echo "== logs and the drill"
post_json "taq log" 202 '"accepted":1' /api/ingest/log \
  '{"component": "TAIP", "message": "running, 9.8 fps"}'
post_json "warning log" 202 '"accepted":1' /api/ingest/log \
  '{"component": "AQ", "level": "warning", "message": "gas sensor warming up"}'
post_json "drill drilling" 202 '"accepted":1' /api/ingest/drill \
  '{"drill_state": "drilling", "hole_depth": 0.008, "trigger_pressure": 2.0}'
post_json "drill done" 202 '"accepted":1' /api/ingest/drill \
  '{"drill_state": "done", "hole_depth": 0.015, "trigger_pressure": 2.0, "message": "hole complete"}'
post_json "unknown kind is refused" 404 "unknown" /api/ingest/nothing '{}'

echo
echo "== payload lcd selector"
check "read lcd mode" 200 '"modes"' "$BASE/api/lcd"
post_json "set lcd to temperature" 200 '"mode":"temperature"' /api/lcd '{"mode": "temperature"}'
check "lcd mode reads back" 200 '"mode":"temperature"' "$BASE/api/lcd"
post_json "bad lcd mode is refused" 400 "mode must be" /api/lcd '{"mode": "disco"}'
post_json "lcd back to ip" 200 '"mode":"ip"' /api/lcd '{"mode": "ip"}'

# the writer and the frame saver run in the background, give them a moment
sleep 2

echo
echo "== reading it back out"
check "readings history" 200 '"temperature"' "$BASE/api/history?type=readings"
check "readings carry the capture lag" 200 '"capture_lag"' "$BASE/api/history?type=readings"
check "detections history" 200 '"valve_state"' "$BASE/api/history?type=detections"
check "detections carry the uav position" 200 '"uav_z"' "$BASE/api/history?type=detections"
check "system log history" 200 '"drill_state"' "$BASE/api/history?type=system_log"
check "history with a time range" 200 '"count"' \
  "$BASE/api/history?type=readings&from=$(($(now) - 600))&to=$(now)"
check "bad history type is refused" 400 "type must be" "$BASE/api/history?type=nothing"
check "saved frames list" 200 '"targets"' "$BASE/api/frames"
check "saved frames, valve only" 200 '"valve"' "$BASE/api/frames?type=valve"
if [ -n "$FRAME_ID" ]; then
  check "saved frame image" 200 "" "$BASE/frames/$FRAME_ID.jpg"
else
  red "FAIL  saved frame image  (no frame id from the frame post)"
  FAIL=$((FAIL + 1))
fi
check "missing saved frame is 404" 404 "" "$BASE/frames/1.jpg"
check "live snapshot" 200 '"lcd_modes"' "$BASE/api/live"

echo
echo "== live streams"
curl -s -N --max-time 3 "$BASE/stream" > "$OUT"
if grep -q "event: snapshot" "$OUT"; then green "PASS  sse stream sends a snapshot"; PASS=$((PASS + 1));
else red "FAIL  sse stream sends a snapshot"; FAIL=$((FAIL + 1)); fi
TYPE=$(curl -s -o /dev/null --max-time 3 -w "%{content_type}" "$BASE/video_feed")
if echo "$TYPE" | grep -q "multipart/x-mixed-replace"; then green "PASS  mjpeg video feed"; PASS=$((PASS + 1));
else red "FAIL  mjpeg video feed  (content type \"$TYPE\")"; FAIL=$((FAIL + 1)); fi

echo
echo "$PASS passed, $FAIL failed"
fi
rm -f "$OUT"

# live sample data as if the payload were flying, up to two frames a second
# (about one on windows, git bash starts a new curl and awk each time).
# one cycle is 40 frames: the gauge falls from 2.8 to 0.85 bar (the drill
# starts below 2 bar and finishes), the valve flips every 30 frames, aruco
# marker 7's position drifts and it leaves the view for a few frames now and then
send_json() {
  curl -s -o /dev/null --max-time 2 -X POST -H "Content-Type: application/json" -d "$2" "$BASE$1"
}

if [ "$MODE" = "live" ] || [ "$MODE" = "stream" ]; then
  echo
  echo "sending live data for $LIVE_SECONDS s to $BASE"
  echo "open $BASE in a browser and watch, ctrl+c to stop"
  start=$(now)
  end=$((start + LIVE_SECONDS))
  i=0
  sent=0
  failed=0
  while [ "$(now)" -lt "$end" ]; do
    step=$((i % 40))

    # every changing number for this tick, in one awk call
    read -r temp hum pres light ox red nh3 gauge ax az ux uz <<< "$(awk -v i="$i" 'BEGIN {
      t = i * 0.5
      printf "%.2f %.1f %.1f %.0f %.2f %.2f %.2f %.2f %.3f %.3f %.3f %.3f",
        24 + 1.5 * sin(t / 15), 42 + 4 * sin(t / 20), 1012 + 0.8 * sin(t / 30),
        360 + 40 * sin(t / 10), 0.8 + 0.15 * sin(t / 8), 2.1 + 0.3 * sin(t / 12),
        0.6 + 0.1 * sin(t / 9), 2.8 - 0.05 * (i % 40),
        -0.3 + (i * 6 % 320) / 640, 1.2 - 0.2 * sin(t / 6), 0.3 - (i * 6 % 320) / 640, 1.2 - 0.2 * sin(t / 6)
    }')"

    targets=""
    # the gauge is always in view
    targets="{\"type\":\"gauge\",\"gauge_value\":$gauge,\"gauge_units\":\"bar\",\"confidence\":0.86,\"box\":[406,96,534,224]}"
    # the valve is in view 3 seconds out of 4, open for 15 s then closed for 15 s
    if [ $((i % 8)) -lt 6 ]; then
      state=$([ $(( (i / 30) % 2 )) -eq 0 ] && echo open || echo closed)
      targets="$targets,{\"type\":\"valve\",\"valve_state\":\"$state\",\"confidence\":0.91,\"box\":[216,156,324,244]}"
    fi
    # the marker leaves the view one tick in five. the outline stays on the
    # marker printed in the test image, only the position numbers change
    if [ $((i % 25)) -lt 20 ]; then
      targets="$targets,{\"type\":\"aruco\",\"id\":7,\"x\":$ax,\"y\":0.18,\"z\":$az,\"uav\":{\"x\":$ux,\"y\":-0.18,\"z\":$uz},\"corners\":[[100,320],[180,320],[180,400],[100,400]]}"
    fi

    if curl -s -f -o /dev/null --max-time 2 -F "frame=@$IMG;type=image/jpeg" -F "captured_at=$(now)" \
        -F "camera=OAK-D Lite RGB" -F "model=test data" -F "inference_ms=35" \
        -F "targets=[$targets]" "$BASE/api/ingest/frame"; then
      sent=$((sent + 1))
    else
      failed=$((failed + 1))
    fi

    # air quality every 2 s
    if [ $((i % 4)) -eq 0 ]; then
      send_json /api/ingest/reading "{\"temperature\": $temp, \"pressure\": $pres, \"humidity\": $hum, \"light\": $light, \"oxidising_ppm\": $ox, \"reducing_ppm\": $red, \"ammonia_ppm\": $nh3, \"captured_at\": $(now)}"
    fi

    # the drill follows the gauge: starts once it drops below 2 bar, done 6 s later
    [ "$step" -eq 0 ] && send_json /api/ingest/drill '{"drill_state": "idle", "trigger_pressure": 2.0}'
    [ "$step" -eq 17 ] && send_json /api/ingest/drill '{"drill_state": "drilling", "hole_depth": 0.004, "trigger_pressure": 2.0}'
    [ "$step" -eq 23 ] && send_json /api/ingest/drill '{"drill_state": "drilling", "hole_depth": 0.010, "trigger_pressure": 2.0}'
    [ "$step" -eq 29 ] && send_json /api/ingest/drill '{"drill_state": "done", "hole_depth": 0.015, "trigger_pressure": 2.0, "message": "hole complete, retracted"}'

    # heartbeats from the payload every 10 s, and a warning now and then
    if [ $((i % 20)) -eq 0 ]; then
      send_json /api/ingest/log '{"component": "TAIP", "message": "running, 2.0 fps (test data)"}'
      send_json /api/ingest/log "{\"component\": \"AQ\", \"message\": \"enviro+ ok, $temp C\"}"
    fi
    [ $((i % 70)) -eq 35 ] && send_json /api/ingest/log '{"component": "TAIP", "level": "warning", "message": "gauge needle not found in 3 frames (test data)"}'

    i=$((i + 1))
    if [ $((i % 20)) -eq 0 ]; then
      echo "  $(( $(now) - start )) s: $sent frames sent, $failed failed"
    fi
    sleep 0.5
  done
  echo "done, $sent frames sent, $failed failed"
  [ "$sent" -gt 0 ] || { red "no frame got through, is the web viz running at $BASE?"; exit 1; }
fi

[ "$FAIL" -eq 0 ]
