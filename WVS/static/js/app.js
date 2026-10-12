// dashboard front end. plain react, no jsx, so there is no build step

var h = React.createElement;
var useState = React.useState;
var useEffect = React.useEffect;
var useRef = React.useRef;

var POINTS = 90;        // how many samples the charts keep on screen
var POSE_POINTS = 150;  // the taq sends a pose every frame, so keep more of them
var MARKER_STALE = 3;   // seconds without a pose before a marker counts as lost
var STRIP_KEEP = 30;    // detection images in the image stream
var IN_VIEW_MS = 5000;  // a target seen this recently counts as in view for the average readings
var SPEAK_GAP = 10000;  // ms a target must be out of sight before it is announced again
var TABLE_SHOW = 2000;  // rows drawn in a logged data table, the csv gets them all
var TEN_MIN = 10 * 60 * 1000;

// same blue and black as style.css
var BLUE = "#1450c8";
var SKY = "#6b9be8";
var BLACK = "#0b1220";
var GRID = "#e3eaf4";

// same font list as style.css, chart.js draws its own text so it needs telling
var FONT = '"WVS Sans", Calibri, Carlito, Arial, sans-serif';
Chart.defaults.font.family = FONT;

// the sections of the navigation menu (HLO-M-3 item 1), the id is the #hash
var PAGES = [
  { id: "dashboard", name: "Dashboard", short: "Home" },
  { id: "video", name: "Live video feed", short: "Video" },
  { id: "targets", name: "Identified targets", short: "Targets" },
  { id: "air", name: "Air quality charts", short: "Air" },
  { id: "logged", name: "Logged data", short: "Data" },
  { id: "images", name: "Image history", short: "Images" },
  { id: "logs", name: "System log", short: "Log" }
];

// line icons for the phone's bottom menu, 24 x 24 stroke paths
var PAGE_ICONS = {
  dashboard: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  video: "M3 7h12v10H3zM15 10.5l6-3.5v10l-6-3.5",
  targets: "M12 3v4M12 17v4M3 12h4M17 12h4M12 6a6 6 0 1 0 0 12a6 6 0 1 0 0-12",
  air: "M3 8h10a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h7",
  logged: "M4 5h16v14H4zM4 10h16M4 15h16M10 5v14",
  images: "M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15 8.5h.01",
  logs: "M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"
};

function PageIcon(props) {
  return h("svg", {
    viewBox: "0 0 24 24", width: 22, height: 22, fill: "none", stroke: "currentColor",
    strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true"
  }, h("path", { d: PAGE_ICONS[props.id] }));
}

var LCD_NAMES = { ip: "IP address", detection: "Live detection", temperature: "Temperature" };

// little helpers
function clockOf(iso) {
  // the server sends 2026-09-15T10:22:03.417, the panels only want the time
  if (!iso) { return "--:--:--"; }
  var bits = iso.split("T");
  return bits.length > 1 ? bits[1].slice(0, 8) : iso;
}

function dateTimeOf(iso) {
  // the logged data tables want the date too
  if (!iso) { return "--"; }
  return iso.replace("T", " ");
}

function countUp(ms) {
  var total = Math.floor(ms / 1000);
  var hrs = Math.floor(total / 3600);
  var mins = Math.floor((total % 3600) / 60);
  var secs = total % 60;
  return pad(hrs) + ":" + pad(mins) + ":" + pad(secs);
}

function pad(n) {
  return (n < 10 ? "0" : "") + n;
}

function has(value) {
  return value !== null && value !== undefined && !isNaN(value);
}

function num(value, places) {
  if (!has(value)) { return "--"; }
  return Number(value).toFixed(places);
}

function grouped(value) {
  // 2188 comes out as 2,188
  if (!has(value)) { return "--"; }
  return Number(value).toLocaleString("en-AU");
}

function localInput(ms) {
  // the value a datetime-local box wants, local time to the second
  var d = new Date(ms);
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
    "T" + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
}

function pageFromHash() {
  var id = (window.location.hash || "").replace("#", "");
  for (var i = 0; i < PAGES.length; i++) {
    if (PAGES[i].id === id) { return id; }
  }
  return "dashboard";
}

function capital(text) {
  // "open" comes out as "Open", missing stays empty
  if (!text) { return ""; }
  return String(text).charAt(0).toUpperCase() + String(text).slice(1);
}

var TYPE_NAMES = { valve: "Valve", gauge: "Gauge", aruco: "ArUco" };

function typesText(types) {
  // "aruco,gauge,valve" comes out as "ArUco, Gauge, Valve"
  if (!types) { return "No targets"; }
  return types.split(",").map(function (t) { return TYPE_NAMES[t] || capital(t); }).join(", ");
}

function targetFacts(row, limit) {
  // a detection as labelled facts, [label, value] pairs, every number with its unit
  var facts = [];
  if (row.type === "valve") {
    facts.push(["State", capital(row.valve_state)]);
  } else if (row.type === "gauge") {
    facts.push(["Reading", num(row.gauge_value, 2) + " " + (row.gauge_units || "bar")]);
    if (has(limit)) {
      facts.push(["Drill", row.gauge_value < limit
        ? "Below the " + num(limit, 1) + " bar threshold" : "Above the " + num(limit, 1) + " bar threshold"]);
    }
  } else {
    facts.push(["Marker ID", String(row.aruco_id)]);
    if (has(row.uav_z)) {
      facts.push(["UAV position", "x " + num(row.uav_x, 2) + " m,  y " + num(row.uav_y, 2) + " m,  z " + num(row.uav_z, 2) + " m"]);
    }
    if (has(row.z)) {
      facts.push(["Camera position", "x " + num(row.x, 2) + " m,  y " + num(row.y, 2) + " m,  z " + num(row.z, 2) + " m"]);
    }
  }
  if (has(row.confidence)) { facts.push(["Confidence", num(row.confidence * 100, 0) + "%"]); }
  facts.push(["Detected at", clockOf(row.ts)]);
  return facts;
}

function FoundBox(props) {
  // the last target found, as a labelled box (REQ-F-05)
  var t = props.target;
  if (!t) {
    return h("div", { className: "found-box none" }, "No targets detected yet");
  }
  var title = t.type === "aruco" ? "ArUco marker " + t.aruco_id
    : t.type === "gauge" ? "Pressure gauge" : "Valve";
  return h("div", { className: "found-box" },
    h("div", { className: "found-head" },
      h("span", { className: "found-tag" }, "Target found"),
      h("span", { className: "found-title" }, title),
      h("span", { className: "found-lag" }, h(AgeBadge, { lag: t.capture_lag, limit: props.ageLimit }))),
    h("dl", { className: "found-facts" }, targetFacts(t, props.limit).map(function (f) {
      return [h("dt", { key: f[0] + "-k" }, f[0]), h("dd", { key: f[0] + "-v" }, f[1])];
    })));
}

function targetText(row) {
  // one line naming a detection, every number with its unit
  if (!row) { return ""; }
  if (row.type === "valve") { return "Valve: " + capital(row.valve_state); }
  if (row.type === "gauge") {
    return "Pressure gauge: " + num(row.gauge_value, 2) + " " + (row.gauge_units || "bar");
  }
  return "ArUco marker " + row.aruco_id;
}

function poseText(row) {
  // the aruco positions as one line, empty for other targets
  if (!row || row.type !== "aruco") { return ""; }
  var bits = [];
  if (has(row.z)) {
    bits.push("Camera: x " + num(row.x, 2) + ", y " + num(row.y, 2) + ", z " + num(row.z, 2) + " m");
  }
  if (has(row.uav_z)) {
    bits.push("UAV: x " + num(row.uav_x, 2) + ", y " + num(row.uav_y, 2) + ", z " + num(row.uav_z, 2) + " m");
  }
  return bits.join("  ·  ");
}

// speaking the targets out loud at the gcs (HLO-M-2). browsers only allow
// speech after the user has clicked or pressed a key on the page, so the
// first click anywhere unlocks it. it is on by default after that
var speech = { unlocked: false, muted: false, seen: {} };

function canSpeak() {
  return typeof window.speechSynthesis !== "undefined";
}

function say(text) {
  if (!canSpeak() || !speech.unlocked || speech.muted) { return; }
  var synth = window.speechSynthesis;
  // chrome can leave the queue paused after a while, nudge it first
  synth.resume();
  var words = new SpeechSynthesisUtterance(text);
  words.rate = 1.05;
  synth.speak(words);
}

function spokenText(row) {
  if (row.type === "valve") { return "Valve detected, " + row.valve_state; }
  if (row.type === "gauge") {
    return "Pressure gauge detected, " + num(row.gauge_value, 1) + " " + (row.gauge_units || "bar");
  }
  return "ArUco marker " + row.aruco_id + " detected";
}

function announce(row) {
  // the taq sends every frame, so only speak a target that was out of sight
  // for SPEAK_GAP. a valve that changes state is a new target.
  // nothing is remembered while speech is off, so a target already in view
  // is still announced the moment voice alerts come on
  if (!speech.unlocked || speech.muted) { return; }
  var key = row.type === "valve" ? "valve:" + row.valve_state
    : row.type === "gauge" ? "gauge" : "aruco:" + row.aruco_id;
  var now = Date.now();
  var last = speech.seen[key];
  speech.seen[key] = now;
  if (last && now - last < SPEAK_GAP) { return; }
  say(spokenText(row));
}

// header
function HudItem(props) {
  return h("div", { className: "hud-item" },
    h("span", { className: "k" }, props.label),
    h("span", { className: "v" }, props.value));
}

function streamState(props) {
  // data arriving is LIVE, connected but silent is STANDBY
  if (!props.live) { return { text: "OFFLINE", on: false }; }
  if (props.quiet === null) { return { text: "STANDBY", on: false }; }
  if (props.quiet > (props.info.cadence || 4) * 3) {
    return { text: "STANDBY", on: false };
  }
  return { text: "LIVE", on: true };
}

function LcdSelect(props) {
  // what the payload lcd shows, the payload reads the choice from GET /api/lcd (HLO-M-5)
  var modes = props.modes || ["ip", "detection", "temperature"];
  return h("select", {
    value: props.mode || modes[0],
    disabled: props.busy,
    onChange: function (ev) { props.pick(ev.target.value); }
  }, modes.map(function (m) {
    return h("option", { key: m, value: m }, LCD_NAMES[m] || m);
  }));
}

function SoundControls(props) {
  if (!canSpeak()) {
    return h("span", { className: "hud-note" }, "No speech in this browser");
  }
  if (!props.sound.unlocked) {
    // any click on the page unlocks speech, this button is just the obvious place.
    // it unlocks on its own click: unlocked on the press, the same click would
    // land on the mute button that replaces it and turn voice straight off
    return h("button", { className: "btn small attention voice-allow", onClick: props.unlock },
      "Click to allow voice");
  }
  return h("button", { className: "btn small", onClick: props.toggleMute },
    props.sound.muted ? "Voice off (unmute)" : "Voice on (mute)");
}

// a phone either way up: the mobile.css phone width, or a phone on its side.
// the header says it is the smartphone ground control station there
var HANDHELD = window.matchMedia
  ? window.matchMedia("(max-width: 759px), (orientation: landscape) and (max-height: 500px)")
  : { matches: false };

function Header(props) {
  var stream = streamState(props);
  // one app, two presentations: the header says which one this is.
  // it redraws every second, so a turned phone updates this too
  var mobile = HANDHELD.matches;

  return h("div", { className: "topbar" },
    h("div", { className: "brand" },
      h("span", { className: "name" }, "UAV PAYLOAD",
        h("span", { className: "mode-tag" }, mobile ? "Mobile" : "Web")),
      h("span", { className: "sub" }, mobile ? "Mobile Interface · GCS" : "Web Interface")),
    h("div", { className: "spacer" }),
    h("div", { className: "hud" },
      h("div", { className: "hud-item" },
        h("span", { className: "k" }, "Stream"),
        h("span", { className: "lamp" + (stream.on ? "" : " off") },
          h("span", { className: "bulb" }),
          h("span", null, stream.text))),
      h(HudItem, { label: "Log timer", value: props.timer }),
      h(HudItem, {
        label: "Payload LCD",
        value: h(LcdSelect, {
          mode: props.lcd ? props.lcd.mode : null,
          modes: props.info.lcd_modes,
          busy: props.lcdBusy,
          pick: props.pickLcd
        })
      }),
      h(HudItem, {
        label: "Voice alerts",
        value: h(SoundControls, { sound: props.sound, toggleMute: props.toggleMute, unlock: props.unlock })
      })));
}

function NavBar(props) {
  var nav = useRef(null);

  // on a phone the menu scrolls sideways, so bring the open page's link into
  // view. only the menu scrolls, never the page, and a desktop menu that
  // fits is left alone
  useEffect(function () {
    var box = nav.current;
    var on = box && box.querySelector("a.on");
    if (!on || box.scrollWidth <= box.clientWidth) { return; }
    box.scrollLeft = on.offsetLeft - (box.clientWidth - on.offsetWidth) / 2;
  }, [props.page]);

  // a phone gets the menu as a bottom bar (mobile.css): icon over a short name
  var phone = PHONE.matches;
  return h("nav", { className: "nav", ref: nav }, PAGES.map(function (p) {
    return h("a", {
      key: p.id, href: "#" + p.id, className: p.id === props.page ? "on" : "",
      "aria-label": phone ? p.name : undefined
    }, phone ? [h(PageIcon, { key: "i", id: p.id }), h("span", { key: "t" }, p.short)] : p.name);
  }));
}

// the phone's operator status strip under the header: link state, how fresh
// the data is, the last target found and the gauge against the drill
// threshold. all from state the page already has, nothing is worked out here
function OperatorHero(props) {
  var stream = streamState(props);
  var quiet = props.quiet;
  var fresh = quiet === null ? "No data yet"
    : quiet < 1 ? "Data just now"
    : quiet < 120 ? "Data " + num(quiet, 0) + " s ago"
    : "Data " + Math.floor(quiet / 60) + " min ago";

  var t = props.target;
  var flag = null;
  if (t && t.type === "aruco") { flag = props.inView(t.aruco_id) ? "In view" : "Lost"; }

  var g = props.gauge;
  var reading = g && has(g.gauge_value);
  var below = reading && g.gauge_value < props.limit;

  return h("div", { className: "ops" },
    h("div", { className: "ops-row" },
      h("span", { className: "ops-lamp" + (stream.on ? "" : " off") }, h("span", { className: "bulb" }), stream.text),
      h("span", { className: "ops-meta" }, fresh),
      h("span", { className: "ops-meta" }, "Log " + props.timer)),
    h("div", { className: "ops-line" },
      h("span", { className: "ops-k" }, "Target"),
      h("span", { className: "ops-v" }, t ? targetText(t) : "No targets detected yet",
        t ? h("span", { className: "ops-time" }, "  " + clockOf(t.ts)) : null),
      flag ? h("span", { className: "ops-flag" + (flag === "Lost" ? " lost" : "") }, flag) : null),
    h("div", { className: "ops-line" + (below ? " alert" : "") },
      h("span", { className: "ops-k" }, "Gauge"),
      h("span", { className: "ops-v" }, reading
        ? num(g.gauge_value, 2) + " " + (g.gauge_units || "bar")
        : "No reading yet"),
      reading ? h("span", { className: "ops-flag" + (below ? " lost" : "") },
        (below ? "Below " : "Above ") + num(props.limit, 1) + " bar") : null));
}

function AgeBadge(props) {
  // seconds from capture on the payload to arrival here (REQ-M-19)
  var limit = has(props.limit) ? props.limit : 4;
  if (!has(props.lag)) {
    return h("span", { className: "age none" }, "Capture lag n/a");
  }
  var late = props.lag > limit;
  return h("span", { className: "age" + (late ? " late" : "") },
    "Capture lag " + num(props.lag, 2) + " s" + (late ? " (over " + num(limit, 0) + " s)" : ""));
}

// live detector feed
function feedLine(frame) {
  // the numbers come from the meta sent with each frame, nothing is guessed
  if (!frame || !frame.live) {
    return "No frames received  ·  waiting for the image processing (TAIP) to send frames";
  }

  var parts = [];
  parts.push(has(frame.detections) ? "Detections: " + frame.detections : "Detections: n/a");
  if (has(frame.inference_ms)) { parts.push("Inference " + num(frame.inference_ms, 0) + " ms"); }
  if (frame.model) { parts.push("Model: " + frame.model); }
  if (has(frame.conf)) { parts.push("Confidence " + num(frame.conf, 2)); }
  if (has(frame.fps) && frame.fps > 0) { parts.push(num(frame.fps, 1) + " fps"); }
  return parts.join("  ·  ");
}

function LiveScreen(props) {
  // the mjpeg feed with the boxes already drawn on it by the server
  var frame = props.frame || {};
  var running = frame.live;

  // the mjpeg stream does not say when it dies (server restart, wifi change,
  // phone asleep), the picture just freezes. a new src replaces the old
  // connection, the ?t= stops the browser reusing it. only one LiveScreen is
  // on screen at a time (dashboard or video page), so this is one stream
  var [src, setSrc] = useState("/video_feed");
  var retry = useRef(null);
  var hiddenAt = useRef(null);
  var wasLive = useRef(props.live);
  var dropped = useRef(false);
  var img = useRef(null);
  var gone = useRef(false);

  function reconnect(delay) {
    if (gone.current) { return; }
    // only ever one retry waiting, so failures cannot stack up into a loop
    clearTimeout(retry.current);
    retry.current = setTimeout(function () {
      retry.current = null;
      setSrc("/video_feed?t=" + Date.now());
    }, delay);
  }

  // the push stream dropped and came back, the video went down with it
  useEffect(function () {
    if (props.live && dropped.current) {
      dropped.current = false;
      reconnect(0);
    }
    if (!props.live && wasLive.current) { dropped.current = true; }
    wasLive.current = props.live;
  }, [props.live]);

  // a phone that slept for more than a few seconds has usually lost the connection
  useEffect(function () {
    function onVisibility() {
      if (document.visibilityState === "hidden") {
        hiddenAt.current = Date.now();
        return;
      }
      if (hiddenAt.current && Date.now() - hiddenAt.current > 5000) { reconnect(0); }
      hiddenAt.current = null;
    }
    document.addEventListener("visibilitychange", onVisibility);
    // kept here because react has already cleared the ref when this cleans up
    var node = img.current;
    return function () {
      document.removeEventListener("visibilitychange", onVisibility);
      gone.current = true;
      clearTimeout(retry.current);
      // the browser keeps a multipart image streaming after the img is taken
      // off the page, so leaving the video page still pulled the video.
      // dropping the src is what closes the connection
      if (node) { node.removeAttribute("src"); }
    };
  }, []);

  return h("div", { className: "screen" },
    // a failed connect waits a few seconds before the next try
    h("img", { ref: img, src: src, alt: "detector feed", onError: function () { reconnect(3000); } }),
    h("div", { className: "cam" }, frame.camera || "CAM 0"),
    h("div", { className: "rec" + (running ? "" : " off") },
      running ? "REC " + props.rec : "NO SIGNAL"));
}

function FeedNote(props) {
  var frame = props.frame || {};
  return h("div", { className: "feed-note" }, feedLine(frame),
    frame.live ? h("span", null, "  ·  ", h(AgeBadge, { lag: frame.capture_lag, limit: props.ageLimit })) : null);
}

function FeedPanel(props) {
  return h("div", { className: "section" },
    h("h2", null, "Live Detector Feed"),
    h(LiveScreen, { frame: props.frame, rec: props.rec, live: props.live }),
    h(FeedNote, { frame: props.frame, ageLimit: props.ageLimit }));
}

function TargetFound(props) {
  // the latest target of any type, so the operator sees what was just found (REQ-F-05)
  return h("div", { className: "section" }, h("h2", null, "Target Found"),
    h(FoundBox, { target: props.target, ageLimit: props.ageLimit, limit: props.limit }));
}

function CaptureStrip(props) {
  // the saved frames that had targets in them, newest first (REQ-F-07)
  var items = props.captures || [];
  var strip;
  if (items.length === 0) {
    strip = h("div", { className: "empty" }, "No detection images saved yet");
  } else {
    strip = h("div", { className: "thumbs" }, items.map(function (c) {
      return h("a", { key: c.id, href: c.url, target: "_blank", rel: "noopener" },
        h("img", { src: c.url, alt: "detection " + c.types, loading: "lazy" }),
        h("span", null, clockOf(c.ts) + "  ·  " + typesText(c.types)));
    }));
  }
  return h("div", { className: "section" },
    h("h2", null, "Detection Images", h("a", { className: "h2-link", href: "#images" }, "Image history")),
    strip);
}

// target acquisition
function ValveCard(props) {
  var valve = props.valve;
  var state = valve ? valve.valve_state : null;

  // the card only lights up once a real detection has come in
  var css = "card dark";
  if (state === "open") { css = "card lit-blue"; }
  if (state === "closed") { css = "card lit-black"; }

  var note = "Awaiting TAIP";
  if (valve) {
    note = has(valve.confidence) ? "Detected, " + num(valve.confidence * 100, 0) + "% confidence" : "Detected";
  }

  return h("div", { className: css },
    h("div", { className: "k" }, "Ball valve"),
    h("div", { className: "big" }, state ? state.toUpperCase() : "NO DATA"),
    h("div", { className: "note" }, note));
}

function GaugeCard(props) {
  var gauge = props.gauge;
  var value = gauge ? gauge.gauge_value : null;
  var limit = props.limit;
  var top = props.max;
  // the drill fires once the pressure drops below the threshold (REQ-F-09)
  var below = has(value) && value < limit;
  var pct = has(value) ? Math.max(0, Math.min(100, (value / top) * 100)) : 0;

  var note = "Awaiting TAIP";
  if (has(value)) { note = below ? "Below drill threshold" : "Above drill threshold"; }

  return h("div", { className: "card " + (gauge ? "lit-black" : "dark") },
    h("div", { className: "k" }, "Pressure gauge"),
    h("div", { className: "big" }, num(value, 2),
      h("span", { className: "unit" }, gauge ? gauge.gauge_units : "bar")),
    h("div", { className: "note" + (below ? " alert" : "") }, note),
    h("div", { className: "meter" },
      h("div", { className: "fill" + (below ? " over" : ""), style: { width: pct + "%" } }),
      // the drill fires at this mark, it comes from the config not the ui
      h("div", { className: "mark", style: { left: Math.min(100, (limit / top) * 100) + "%" } })),
    h("div", { className: "meter-note" },
      h("span", null, "0 bar"),
      h("span", null, "Drill below " + num(limit, 1) + " bar"),
      h("span", null, num(top, 0) + " bar")));
}

function range(m) {
  // straight line distance from the lens to the marker
  if (!has(m.x) || !has(m.y) || !has(m.z)) { return null; }
  return Math.sqrt(m.x * m.x + m.y * m.y + m.z * m.z);
}

function ArucoCard(props) {
  var markers = props.markers || [];
  var seen = markers.filter(function (m) { return props.inView(m.aruco_id); });
  // the uav columns only show once the taq sends a uav position
  var withUav = markers.some(function (m) { return has(m.uav_z); });

  var head = h("div", { className: "k" }, "ArUco markers, position (m)",
    h("span", { className: "count" + (seen.length ? " on" : "") },
      seen.length + " in view"));

  if (markers.length === 0) {
    return h("div", { className: "card wide" }, head,
      h("div", { className: "empty" }, "No markers detected yet"));
  }

  // a phone lists each marker as a card, the same numbers without a wide table
  if (PHONE.matches) {
    return h("div", { className: "card wide" }, head,
      h("div", { className: "marker-cards" }, markers.map(function (m) {
        var on = props.inView(m.aruco_id);
        return h("div", { key: m.aruco_id, className: "marker-card" + (on ? " on" : " lost") },
          h("div", { className: "marker-head" },
            h("span", { className: "marker-id" }, "Marker " + m.aruco_id),
            h("span", { className: "marker-state" }, on ? "In view" : "Lost, last seen " + clockOf(m.ts))),
          has(m.uav_z) ? h("div", { className: "marker-pos" }, h("span", null, "UAV"),
            "x " + num(m.uav_x, 3) + "  y " + num(m.uav_y, 3) + "  z " + num(m.uav_z, 3) + " m") : null,
          h("div", { className: "marker-pos" }, h("span", null, "Camera"),
            "x " + num(m.x, 3) + "  y " + num(m.y, 3) + "  z " + num(m.z, 3) + " m"),
          h("div", { className: "marker-pos" }, h("span", null, "Range"), num(range(m), 3) + " m"));
      })),
      h("div", { className: "subnote" },
        "Camera = the marker's position seen from the camera. UAV = the UAV's position relative to the marker."));
  }

  var names = ["ID", "Camera x (m)", "Camera y (m)", "Camera z (m)"];
  if (withUav) { names = names.concat(["UAV x (m)", "UAV y (m)", "UAV z (m)"]); }
  names = names.concat(["Range (m)", "Seen"]);

  // markers that left the view stay listed, dimmed, with when they were last seen
  var rows = markers.map(function (m) {
    var on = props.inView(m.aruco_id);
    var cells = [m.aruco_id, num(m.x, 3), num(m.y, 3), num(m.z, 3)];
    if (withUav) { cells = cells.concat([num(m.uav_x, 3), num(m.uav_y, 3), num(m.uav_z, 3)]); }
    cells = cells.concat([num(range(m), 3), on ? "In view" : clockOf(m.ts)]);
    return h("tr", { key: m.aruco_id, className: on ? "" : "lost" },
      cells.map(function (c, i) { return h("td", { key: i }, c); }));
  });

  return h("div", { className: "card wide" }, head,
    h("div", { className: "table-scroll" },
      h("table", { style: { marginTop: "8px" } },
        h("thead", null, h("tr", null, names.map(function (n) { return h("th", { key: n }, n); }))),
        h("tbody", null, rows))),
    h("div", { className: "subnote" },
      "Camera = the marker's position seen from the camera. UAV = the UAV's position relative to the marker."));
}

function PosePanel(props) {
  // the marker the taq saw last. the uav position w.r.t. the marker when the
  // taq sends it (HLO-M-3 item 3b), otherwise the marker seen from the camera
  var rows = props.rows.filter(function (row) { return row.aruco_id === props.id; });
  var uav = rows.some(function (row) { return has(row.uav_z); });
  var p = uav ? "uav_" : "";

  var pose = [
    { name: "x", unit: "m", places: 3, colour: BLUE, data: points(rows, p + "x") },
    { name: "y", unit: "m", places: 3, colour: SKY, data: points(rows, p + "y") },
    { name: "z (right axis)", unit: "m", places: 3, colour: BLACK, data: points(rows, p + "z"), axis: "y2" }
  ];

  var name = "Marker position (m)";
  if (has(props.id)) {
    name = uav ? "UAV position w.r.t. marker " + props.id + " (m)" : "Marker " + props.id + " seen from the camera (m)";
  }
  return h("div", { className: props.tall ? "fill" : null },
    h(ChartHead, { name: name, series: pose }),
    h(LineChart, { key: uav ? "uav" : "cam", series: pose, twoAxis: true, tall: props.tall,
      yTitle: "x and y position (m)", y2Title: "z position (m)" }));
}

function TargetPanel(props) {
  return h("div", { className: "section" },
    h("h2", null, "Target Acquisition"),
    h("div", { className: "cards" },
      h(ValveCard, { valve: props.valve }),
      h(GaugeCard, { gauge: props.gauge, limit: props.limit, max: props.gaugeMax }),
      h(ArucoCard, { markers: props.markers, inView: props.inView })),
    h(PosePanel, { rows: props.poseRows, id: props.poseId }));
}

// charts. the x axis is real time: the last CHART_SPAN, a tick every
// CHART_STEP, moving every second, so a new reading shows within the 4 s limit
// (REQ-M-19) and nothing older squashes the axis
var CHART_SPAN = 30000;
var CHART_STEP = 3000;

// server time minus browser time, so a viewer with a wrong clock still sees
// the newest readings at the right edge
var clockSkew = 0;

function chartNow() {
  return Date.now() + clockSkew;
}

function msOf(iso) {
  // the server sends local time without a zone, the browser reads it the same way
  return Date.parse(iso);
}

function hms(ms) {
  var d = new Date(ms);
  return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
}

// AQ sends the MiCS-6814 gas readings as sensor resistance in ohms (*_ohms).
// The dashboard shows them in kilo-ohms, so each reading row gets *_kohm
// copies as it arrives. Lower resistance means more of that gas.
var GAS_KEYS = ["oxidising", "reducing", "ammonia"];

function withKohm(row) {
  if (!row) { return row; }
  var out = Object.assign({}, row);
  GAS_KEYS.forEach(function (g) {
    var ohms = row[g + "_ohms"];
    out[g + "_kohm"] = has(ohms) ? ohms / 1000 : null;
  });
  return out;
}

function points(rows, name) {
  return rows.map(function (row) {
    return { x: msOf(row.ts), y: has(row[name]) ? row[name] : null };
  });
}

function axisTitle(text) {
  // every axis says what it measures and in which unit
  return { display: !!text, text: text || "", color: BLACK, font: { family: FONT, size: 13, weight: "600" } };
}

// phones get a lighter time axis: a label every 10 s, never tilted, and no
// axis titles (the name above each chart already says what and which unit).
// same breakpoint as mobile.css. no matchMedia means the desktop axis
var PHONE = window.matchMedia ? window.matchMedia("(max-width: 759px)") : { matches: false };
var PHONE_STEP = 10000;

function makeScales(props) {
  var phone = PHONE.matches;
  var axis = {
    title: axisTitle(phone ? "" : props.yTitle),
    grid: { color: GRID, drawTicks: false },
    border: { color: GRID },
    ticks: { color: BLACK, font: { size: 12 }, maxTicksLimit: 5, padding: 4 }
  };

  var now = chartNow();
  var scales = {
    x: {
      type: "linear",
      min: now - CHART_SPAN,
      max: now,
      title: axisTitle(phone ? "" : "Time (hh:mm:ss)"),
      grid: { color: GRID, drawTicks: false },
      border: { color: GRID },
      ticks: {
        // a label every step, tilted when the chart is too narrow to fit them flat
        color: BLACK, font: { size: 11 }, minRotation: 0, maxRotation: phone ? 0 : 50, autoSkip: phone,
        stepSize: phone ? PHONE_STEP : CHART_STEP, includeBounds: false,
        callback: function (value) { return hms(value); }
      }
    },
    y: axis
  };

  // the temperature chart needs a second axis on the right for humidity
  if (props.twoAxis) {
    scales.y2 = {
      position: "right",
      title: axisTitle(phone ? "" : props.y2Title),
      grid: { drawOnChartArea: false },
      border: { color: GRID },
      ticks: { color: BLACK, font: { size: 12 }, maxTicksLimit: 5 }
    };
  }
  return scales;
}

function LineChart(props) {
  var canvas = useRef(null);
  var chart = useRef(null);

  // the chart object is built once, after that only the numbers get swapped
  useEffect(function () {
    var sets = props.series.map(function (s) {
      return {
        label: s.name,
        data: [],
        borderColor: s.colour,
        backgroundColor: s.colour,
        borderWidth: 1.6,
        pointRadius: 2,
        pointHoverRadius: 4,
        tension: 0.3,
        // smooth without overshooting, so readings close together do not loop back
        cubicInterpolationMode: "monotone",
        spanGaps: true,
        yAxisID: s.axis || "y",
        unit: s.unit || "",
        places: has(s.places) ? s.places : 2
      };
    });

    chart.current = new Chart(canvas.current.getContext("2d"), {
      type: "line",
      data: { datasets: sets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "nearest", axis: "x", intersect: false },
        scales: makeScales(props),
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#ffffff",
            borderColor: "#c9d6e8",
            borderWidth: 1,
            titleColor: BLACK,
            bodyColor: BLACK,
            titleFont: { family: FONT, size: 14 },
            bodyFont: { family: FONT, size: 14 },
            callbacks: {
              title: function (items) {
                return items.length ? hms(items[0].parsed.x) : "";
              },
              // every value with its unit, e.g. "Temperature: 24.31 °C"
              label: function (item) {
                var ds = item.dataset;
                return ds.label + ": " + num(item.parsed.y, ds.places) + (ds.unit ? " " + ds.unit : "");
              }
            }
          }
        }
      }
    });

    // a phone turned or a window resized across the phone breakpoint
    function resized() {
      chart.current.options.scales = makeScales(props);
      chart.current.update("none");
    }
    // safari before 14 only has addListener
    if (PHONE.addEventListener) { PHONE.addEventListener("change", resized); }
    else if (PHONE.addListener) { PHONE.addListener(resized); }

    return function () {
      if (PHONE.removeEventListener) { PHONE.removeEventListener("change", resized); }
      else if (PHONE.removeListener) { PHONE.removeListener(resized); }
      chart.current.destroy();
    };
  }, []);

  // runs on every render, and the page renders every second, so the time
  // axis keeps sliding even when no new reading has come in
  useEffect(function () {
    if (!chart.current) { return; }
    props.series.forEach(function (s, i) {
      chart.current.data.datasets[i].data = s.data;
    });
    var now = chartNow();
    chart.current.options.scales.x.min = now - CHART_SPAN;
    chart.current.options.scales.x.max = now;
    chart.current.update("none");
  });

  return h("div", { className: "chart-box" + (props.tall ? " tall" : "") }, h("canvas", { ref: canvas }));
}

function ChartHead(props) {
  var keys = props.series.map(function (s) {
    return h("span", { key: s.name },
      h("i", { style: { background: s.colour } }), s.name);
  });

  return h("div", { className: "chart-head" },
    h("span", { className: "name" }, props.name),
    h("div", { className: "legend" }, keys));
}

// air quality
function Tile(props) {
  return h("div", { className: "tile" + (props.accent ? " accent" : "") },
    h("div", { className: "k" }, props.name),
    h("div", { className: "v" + (props.value === "--" ? " none" : "") }, props.value,
      h("span", { className: "unit" }, props.unit)));
}

function ReadingTiles(props) {
  var r = props.reading || {};

  return h("div", { className: "tiles" },
    h(Tile, { name: "Temperature", value: num(r.temperature, 1), unit: "°C" }),
    h(Tile, { name: "Pressure", value: num(r.pressure, 1), unit: "hPa" }),
    h(Tile, { name: "Humidity", value: num(r.humidity, 0), unit: "%RH" }),
    h(Tile, { name: "Light", value: num(r.light, 0), unit: "lux" }),
    h(Tile, { name: "Oxidising", value: num(r.oxidising_kohm, 1), unit: "kΩ" }),
    h(Tile, { name: "Reducing", value: num(r.reducing_kohm, 1), unit: "kΩ" }),
    h(Tile, { name: "Ammonia (NH3)", value: num(r.ammonia_kohm, 1), unit: "kΩ" }),
    h(Tile, { name: "Samples", value: grouped(props.samples), unit: "rows", accent: true }));
}

function ReadingsSection(props) {
  return h("div", { className: "section" },
    h("h2", null, "Current Readings",
      h("span", { className: "h2-side" },
        h(AgeBadge, { lag: props.reading ? props.reading.capture_lag : null, limit: props.ageLimit }))),
    h(ReadingTiles, { reading: props.reading, samples: props.samples }));
}

function AirPanel(props) {
  var rows = props.rows;

  var gas = [
    { name: "Oxidising", unit: "kΩ", places: 1, colour: BLUE, data: points(rows, "oxidising_kohm") },
    { name: "Reducing", unit: "kΩ", places: 1, colour: SKY, data: points(rows, "reducing_kohm") },
    { name: "Ammonia", unit: "kΩ", places: 1, colour: BLACK, data: points(rows, "ammonia_kohm") }
  ];

  var climate = [
    { name: "Temperature", unit: "°C", colour: BLACK, data: points(rows, "temperature") },
    { name: "Humidity (right axis)", unit: "%RH", places: 1, colour: BLUE, data: points(rows, "humidity"), axis: "y2" }
  ];

  return h("div", { className: "section" },
    h("h2", null, "Air Quality Trends"),
    h(ChartHead, { name: "Gas sensor resistance (kΩ), lower means more gas", series: gas }),
    h(LineChart, { series: gas, yTitle: "Resistance (kΩ)" }),
    h(ChartHead, { name: "Temperature (°C) & Humidity (%RH)", series: climate }),
    h(LineChart, { series: climate, twoAxis: true, yTitle: "Temperature (°C)", y2Title: "Humidity (%RH)" }));
}

// the dashboard, laid out like the customer's example interface (Appendix F):
// image stream | current image | chart tabs, then targets and the sensor gauges

var CHART_TABS = [
  { id: "position", name: "Position" },
  { id: "gas", name: "Gas" },
  { id: "temperature", name: "Temperature" },
  { id: "humidity", name: "Humidity" },
  { id: "pressure", name: "Pressure" },
  { id: "light", name: "Light" }
];

// the bar gauges. lo / hi only scale the bar, the number above it is the reading
var SENSOR_BARS = [
  { key: "temperature", long: "Temperature", name: "Temp.", unit: "°C", lo: 0, hi: 50, places: 1 },
  { key: "humidity", long: "Humidity", name: "Humid.", unit: "%RH", lo: 0, hi: 100, places: 0 },
  { key: "pressure", long: "Pressure", name: "Pressure", unit: "hPa", lo: 950, hi: 1050, places: 1 },
  { key: "light", long: "Light", name: "Light", unit: "lux", lo: 0, hi: 1000, places: 0 },
  { key: "oxidising_kohm", long: "Oxidising", name: "Oxidising", unit: "kΩ", lo: 0, hi: 100, places: 1 },
  { key: "reducing_kohm", long: "Reducing", name: "Reducing", unit: "kΩ", lo: 0, hi: 1000, places: 0 },
  { key: "ammonia_kohm", long: "Ammonia (NH3)", name: "NH3", unit: "kΩ", lo: 0, hi: 500, places: 0 }
];

var TARGET_ROWS = [
  { type: "valve", name: "Valve" },
  { type: "gauge", name: "Pressure gauge" },
  { type: "aruco", name: "ArUco marker" }
];

// the readings averaged while each target was in view
var AVG_COLS = [
  { key: "oxidising_kohm", name: "Oxidising (kΩ)", places: 1 },
  { key: "reducing_kohm", name: "Reducing (kΩ)", places: 1 },
  { key: "ammonia_kohm", name: "NH3 (kΩ)", places: 1 },
  { key: "temperature", name: "Temperature (°C)", places: 1 },
  { key: "humidity", name: "Humidity (%RH)", places: 0 }
];

function ImageStream(props) {
  // newest detection image on top, a click shows it as the current image
  var items = props.captures || [];
  var list;
  if (items.length === 0) {
    list = h("div", { className: "empty pad" }, "Detection images appear here");
  } else {
    list = items.map(function (c) {
      var on = props.selected && props.selected.id === c.id;
      return h("a", {
        key: c.id, href: c.url, className: on ? "on" : "",
        onClick: function (ev) { ev.preventDefault(); props.pick(on ? null : c); }
      },
        h("img", { src: c.url, alt: "detection " + c.types, loading: "lazy" }),
        h("span", null, clockOf(c.ts) + "  ·  " + typesText(c.types)));
    });
  }
  return h("div", { className: "panel stream" },
    h("div", { className: "panel-title" }, "Image Stream"),
    h("div", { className: "stream-list" }, list));
}

function CurrentImage(props) {
  var sel = props.selected;
  var t = props.target;
  var screen;
  var notes;
  if (sel) {
    screen = h("div", { className: "screen" }, h("img", { src: sel.url, alt: "saved frame " + sel.id }),
      h("div", { className: "rec off" }, "SAVED " + clockOf(sel.ts)));
    notes = h("div", { className: "feed-note" },
      "Saved detection image  ·  " + typesText(sel.types) + "  ",
      h("button", { className: "btn small", onClick: function () { props.pick(null); } }, "Back to live"));
  } else {
    screen = h(LiveScreen, { frame: props.frame, rec: props.rec, live: props.live });
    notes = h(FeedNote, { frame: props.frame, ageLimit: props.ageLimit });
  }

  // the last target found, so the operator sees what was just detected (REQ-F-05)
  var found = h(FoundBox, { target: t, ageLimit: props.ageLimit, limit: props.limit });

  return h("div", { className: "panel current" },
    h("div", { className: "panel-title" }, sel ? "Current Image (saved)" : "Current Image (live)"),
    h("div", { className: "panel-body" }, screen, notes, found));
}

function ChartTabs(props) {
  var [tab, setTab] = useState(props.start || "position");
  var rows = props.rows;

  var chart;
  if (tab === "position") {
    chart = h(PosePanel, { rows: props.poseRows, id: props.poseId, tall: true });
  } else {
    var sets = {
      gas: { name: "Gas sensor resistance (kΩ), lower means more gas", axis: "Resistance (kΩ)", series: [
        { name: "Oxidising", unit: "kΩ", places: 1, colour: BLUE, data: points(rows, "oxidising_kohm") },
        { name: "Reducing", unit: "kΩ", places: 1, colour: SKY, data: points(rows, "reducing_kohm") },
        { name: "Ammonia", unit: "kΩ", places: 1, colour: BLACK, data: points(rows, "ammonia_kohm") }] },
      temperature: { name: "Temperature (°C)", axis: "Temperature (°C)", series: [
        { name: "Temperature", unit: "°C", colour: BLACK, data: points(rows, "temperature") }] },
      humidity: { name: "Humidity (%RH)", axis: "Humidity (%RH)", series: [
        { name: "Humidity", unit: "%RH", places: 1, colour: BLUE, data: points(rows, "humidity") }] },
      pressure: { name: "Atmospheric pressure (hPa)", axis: "Pressure (hPa)", series: [
        { name: "Pressure", unit: "hPa", places: 1, colour: BLACK, data: points(rows, "pressure") }] },
      light: { name: "Light (lux)", axis: "Light (lux)", series: [
        { name: "Light", unit: "lux", places: 0, colour: SKY, data: points(rows, "light") }] }
    };
    var pick = sets[tab];
    chart = h("div", { className: "fill" },
      h(ChartHead, { name: pick.name, series: pick.series }),
      h(LineChart, { key: tab, series: pick.series, tall: true, yTitle: pick.axis }));
  }

  return h("div", { className: "panel charts" },
    h("div", { className: "tabs" }, (props.tabs || CHART_TABS).map(function (t) {
      return h("button", {
        key: t.id, className: "tab" + (t.id === tab ? " on" : ""),
        onClick: function () { setTab(t.id); }
      }, t.name);
    })),
    h("div", { className: "panel-body" }, chart));
}

function TargetsTable(props) {
  // one row per target: what it read, where it is, when, then the air while it was in view
  var dash = h("span", { className: "nil" }, "—");
  var rows = TARGET_ROWS.map(function (r) {
    var t = props.latest[r.type];
    var reading = dash;
    var position = dash;
    if (t && r.type === "valve") {
      reading = h("span", null, h("b", null, capital(t.valve_state)),
        has(t.confidence) ? h("span", { className: "sub" }, num(t.confidence * 100, 0) + "% confidence") : null);
    } else if (t && r.type === "gauge") {
      var below = t.gauge_value < props.limit;
      reading = h("span", null, h("b", null, num(t.gauge_value, 2) + " " + (t.gauge_units || "bar")),
        h("span", { className: "sub" + (below ? " alert" : "") },
          (below ? "Below" : "Above") + " drill threshold (" + num(props.limit, 1) + " bar)"));
    } else if (t) {
      var uav = has(t.uav_z);
      reading = h("span", null, h("b", null, "Marker " + t.aruco_id));
      position = h("span", null,
        h("span", { className: "sub top" }, uav ? "UAV w.r.t. marker" : "Seen from camera"),
        uav ? "x " + num(t.uav_x, 2) + ",  y " + num(t.uav_y, 2) + ",  z " + num(t.uav_z, 2) + " m"
          : "x " + num(t.x, 2) + ",  y " + num(t.y, 2) + ",  z " + num(t.z, 2) + " m");
    }

    var s = props.stats[r.type];
    var avgs = AVG_COLS.map(function (c) {
      var n = s ? s.count[c.key] || 0 : 0;
      return h("td", { key: c.key, className: "num" }, n ? num(s.sum[c.key] / n, c.places) : dash);
    });

    return h("tr", { key: r.type },
      h("th", { scope: "row", className: "left" }, r.name),
      h("td", { className: "left" }, reading),
      h("td", { className: "left nowrap" }, position),
      h("td", { className: "num" }, t ? clockOf(t.ts) : dash),
      avgs);
  });

  return h("div", { className: "table-scroll" },
    h("table", { className: "targets-table" },
      h("thead", null,
        h("tr", null,
          h("th", { className: "group", colSpan: 4 }, "Detection"),
          h("th", { className: "group avg", colSpan: AVG_COLS.length }, "Average readings while in view")),
        h("tr", null,
          h("th", { className: "left" }, "Target"),
          h("th", { className: "left" }, "Reading"),
          h("th", { className: "left" }, "Position"),
          h("th", { className: "num" }, "Last seen"),
          AVG_COLS.map(function (c) { return h("th", { key: c.key, className: "num avg" }, c.name); }))),
      h("tbody", null, rows)));
}

function SensorBars(props) {
  var r = props.reading || {};
  return h("div", { className: "bars" }, SENSOR_BARS.map(function (b) {
    var v = r[b.key];
    var pct = has(v) ? Math.max(0, Math.min(100, (v - b.lo) / (b.hi - b.lo) * 100)) : 0;
    return h("div", { key: b.key, className: "bar" },
      h("div", { className: "bar-value" + (has(v) ? "" : " none") }, num(v, b.places),
        h("span", { className: "bar-unit" }, b.unit)),
      h("div", { className: "bar-tube" }, h("div", { className: "bar-fill", style: { height: pct + "%" } })),
      h("div", { className: "bar-name" }, b.name, h("br"), "(" + b.unit + ")"));
  }));
}

// the same readings as the bars, as cards on a phone: name, value and unit
function SensorCards(props) {
  var r = props.reading || {};
  return h("div", { className: "sensor-cards" },
    h("div", { className: "panel-title" }, "Live sensors"),
    h("div", { className: "sensor-grid" }, SENSOR_BARS.map(function (b) {
      var v = r[b.key];
      return h("div", { key: b.key, className: "sensor-card" },
        h("div", { className: "k" }, b.long),
        h("div", { className: "v" + (has(v) ? "" : " none") }, num(v, b.places),
          h("span", { className: "unit" }, b.unit)));
    })));
}

function ActivateDrill() {
  // asks the web viz to call activate_drill() in drill_controller.py (POST /api/drill/activate)
  var [busy, setBusy] = useState(false);
  var [result, setResult] = useState(null);

  function press() {
    setBusy(true);
    setResult(null);
    fetch("/api/drill/activate", { method: "POST" })
      .then(function (res) { return res.json(); })
      .then(function (body) {
        setBusy(false);
        setResult(body.ok ? { text: "Drill activated " + hms(Date.now()), error: false }
          : { text: body.error || "Activate drill failed", error: true });
      })
      .catch(function () {
        setBusy(false);
        setResult({ text: "Could not reach the web viz", error: true });
      });
  }

  return h("span", { className: "drill-activate" },
    h("button", { className: "btn primary small", disabled: busy, onClick: press },
      busy ? "Activating..." : "Activate drill"),
    result ? h("span", { className: "drill-result" + (result.error ? " error" : "") }, result.text) : null);
}

function DrillLine(props) {
  var drill = props.drill;
  var state = drill && drill.drill_state ? drill.drill_state : null;
  return h("div", { className: "drill-line" },
    h("span", { className: "drill-label" }, "Drill (EDM)"),
    h("span", { className: "pill " + (state || "") }, state ? capital(state) : "No data"),
    h("span", null, "Hole depth ", h("b", null, drill && has(drill.hole_depth) ? num(drill.hole_depth * 1000, 1) + " mm" : "--")),
    h("span", null, "Fires below ", h("b", null, num(drill && has(drill.trigger_pressure) ? drill.trigger_pressure : props.limit, 1) + " bar")),
    h("span", null, "Last event ", h("b", null, drill ? clockOf(drill.ts) : "--")),
    h(ActivateDrill),
    h("a", { className: "h2-link inline", href: "#logs" }, "System log"));
}

function Dashboard(props) {
  return h("div", { className: "mock" },
    h(ImageStream, { captures: props.captures, selected: props.selected, pick: props.pick }),
    h(CurrentImage, {
      frame: props.frame, rec: props.rec, live: props.live, ageLimit: props.ageLimit,
      selected: props.selected, pick: props.pick, target: props.target, limit: props.limit
    }),
    h(ChartTabs, { rows: props.rows, poseRows: props.poseRows, poseId: props.poseId }),
    h("div", { className: "panel bottom" },
      h("div", { className: "bottom-left" },
        h(TargetsTable, { latest: props.latest, stats: props.stats, limit: props.limit }),
        h("div", { className: "subnote" }, "Averages cover this browser session, using the readings taken while each target was in view (seen in the last " + IN_VIEW_MS / 1000 + " s)."),
        h(DrillLine, { drill: props.drill, limit: props.limit })),
      h("div", { className: "bottom-right" },
        PHONE.matches ? h(SensorCards, { reading: props.reading }) : h(SensorBars, { reading: props.reading }),
        h("div", { className: "bars-note" },
          h(AgeBadge, { lag: props.reading ? props.reading.capture_lag : null, limit: props.ageLimit })))));
}

// drill controller
function DrillPanel(props) {
  var drill = props.drill;
  var state = drill && drill.drill_state ? drill.drill_state : "idle";

  var lines = (props.logs || []).slice().reverse().map(function (row, i) {
    return h("div", { key: i, className: row.level },
      clockOf(row.ts) + "  " + row.component + "  " + row.message);
  });

  if (lines.length === 0) {
    lines = [h("div", { key: "none", className: "none" }, "No log messages received")];
  }

  return h("div", { className: "section" },
    h("h2", null, "Drill Controller", h("a", { className: "h2-link", href: "#logs" }, "Full system log")),
    h("div", { className: "strip" },
      h("div", null,
        h("span", { className: "pill " + state }, drill ? capital(state) : "No data"),
        h("div", { className: "drill-facts" },
          h("div", null, "Hole depth  ",
            // null * 1000 is 0 in js, so check first or a missing depth shows 0.0 mm
            h("b", null, drill && has(drill.hole_depth)
              ? num(drill.hole_depth * 1000, 1) + " mm" : "--")),
          h("div", null, "Trigger below  ",
            h("b", null, num(drill && has(drill.trigger_pressure)
              ? drill.trigger_pressure : props.limit, 1) + " bar")),
          h("div", null, "Last event  ",
            h("b", null, drill ? clockOf(drill.ts) : "--")))),
      h("div", { className: "log" }, lines)));
}

// the subsystems that write to the system log. a log's component is matched
// to one of these, older names are kept as aliases so earlier rows still match
var SUBSYSTEMS = [
  { id: "WVS", name: "Web visualisation", aliases: ["wvs", "webviz", "lcd"] },
  { id: "AQ", name: "Air quality", aliases: ["aq", "air", "enviro"] },
  { id: "TAIP", name: "Target acquisition & image processing", aliases: ["taip", "taq"] },
  { id: "EDM", name: "Enclosure & drilling mechanism", aliases: ["edm", "drill"] }
];

function subsystemOf(component) {
  var name = (component || "").trim().toLowerCase();
  for (var i = 0; i < SUBSYSTEMS.length; i++) {
    if (SUBSYSTEMS[i].aliases.indexOf(name) >= 0) { return SUBSYSTEMS[i].id; }
  }
  return "other";
}

// logged data (HLO-M-3 items 4, 6, 7)
var LOG_TYPES = [
  { id: "readings", name: "Sensor readings" },
  { id: "detections", name: "Target detections and positions" },
  { id: "system_log", name: "System log" }
];

function cell(value, places) {
  return has(value) ? Number(value).toFixed(places) : "";
}

function frameUrl(row) {
  return has(row.frame_id) ? "/frames/" + row.frame_id + ".jpg" : null;
}

// every column says its unit, the sheet marks a value without one as 0
var COLUMNS = {
  readings: [
    { name: "Time", left: true, get: function (r) { return dateTimeOf(r.ts); } },
    { name: "Temperature (°C)", get: function (r) { return cell(r.temperature, 2); } },
    { name: "Pressure (hPa)", get: function (r) { return cell(r.pressure, 1); } },
    { name: "Humidity (%RH)", get: function (r) { return cell(r.humidity, 1); } },
    { name: "Light (lux)", get: function (r) { return cell(r.light, 0); } },
    { name: "Oxidising (kΩ)", get: function (r) { return cell(r.oxidising_kohm, 2); } },
    { name: "Reducing (kΩ)", get: function (r) { return cell(r.reducing_kohm, 2); } },
    { name: "Ammonia (kΩ)", get: function (r) { return cell(r.ammonia_kohm, 2); } },
    { name: "Capture lag (s)", get: function (r) { return cell(r.capture_lag, 2); } }
  ],
  detections: [
    { name: "Time", left: true, get: function (r) { return dateTimeOf(r.ts); } },
    { name: "Type", left: true, get: function (r) { return r.type === "aruco" ? "ArUco" : capital(r.type); } },
    { name: "Valve", get: function (r) { return capital(r.valve_state); } },
    { name: "Gauge reading", get: function (r) {
      return has(r.gauge_value) ? Number(r.gauge_value).toFixed(2) + " " + (r.gauge_units || "bar") : "";
    } },
    { name: "ArUco ID", get: function (r) { return has(r.aruco_id) ? r.aruco_id : ""; } },
    { name: "Camera x (m)", get: function (r) { return cell(r.x, 3); } },
    { name: "Camera y (m)", get: function (r) { return cell(r.y, 3); } },
    { name: "Camera z (m)", get: function (r) { return cell(r.z, 3); } },
    { name: "UAV x (m)", get: function (r) { return cell(r.uav_x, 3); } },
    { name: "UAV y (m)", get: function (r) { return cell(r.uav_y, 3); } },
    { name: "UAV z (m)", get: function (r) { return cell(r.uav_z, 3); } },
    { name: "Confidence (%)", get: function (r) { return has(r.confidence) ? (r.confidence * 100).toFixed(0) : ""; } },
    { name: "Capture lag (s)", get: function (r) { return cell(r.capture_lag, 2); } },
    { name: "Image", link: frameUrl }
  ],
  system_log: [
    { name: "Time", left: true, get: function (r) { return dateTimeOf(r.ts); } },
    { name: "Level", left: true, get: function (r) { return capital(r.level); } },
    { name: "Subsystem", left: true, get: function (r) { return r.component; } },
    { name: "Message", left: true, get: function (r) { return r.message; } },
    { name: "Drill state", get: function (r) { return capital(r.drill_state); } },
    { name: "Hole depth (mm)", get: function (r) { return has(r.hole_depth) ? (r.hole_depth * 1000).toFixed(1) : ""; } },
    { name: "Trigger (bar)", get: function (r) { return cell(r.trigger_pressure, 1); } }
  ]
};

function quote(value) {
  var text = String(value === null || value === undefined ? "" : value);
  return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
}

function toCsv(cols, rows) {
  var lines = [cols.map(function (c) { return quote(c.name); }).join(",")];
  rows.forEach(function (r) {
    lines.push(cols.map(function (c) {
      return quote(c.link ? (c.link(r) || "") : c.get(r));
    }).join(","));
  });
  return lines.join("\r\n");
}

function download(name, text) {
  var url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  var a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
}

function DataTable(props) {
  if (props.rows.length === 0) {
    return h("div", { className: "empty" }, "No rows in this time range");
  }
  // newest at the top, it is what people look for first
  var rows = props.rows.slice(-TABLE_SHOW).reverse();
  return h("div", { className: "table-wrap" },
    h("table", null,
      h("thead", null, h("tr", null, props.cols.map(function (c) {
        return h("th", { key: c.name, className: c.left ? "left" : "" }, c.name);
      }))),
      h("tbody", null, rows.map(function (r, i) {
        return h("tr", { key: (r.id || "") + "-" + i, className: r.level || "" },
          props.cols.map(function (c) {
            if (c.link) {
              var url = c.link(r);
              return h("td", { key: c.name },
                url ? h("a", { href: url, target: "_blank", rel: "noopener" }, "View") : "");
            }
            return h("td", { key: c.name, className: c.left ? "left" : "" }, c.get(r));
          }));
      }))));
}

function LoggedData(props) {
  // pick a time range, get the rows with their timestamps. the system log page
  // is the same thing locked to system_log, with filters
  var fixed = props.fixedType;
  var [type, setType] = useState(fixed || "readings");
  var [from, setFrom] = useState(localInput(Date.now() - TEN_MIN));
  var [to, setTo] = useState(localInput(Date.now()));
  var [rows, setRows] = useState([]);
  var [status, setStatus] = useState({ text: "", error: false });
  var [level, setLevel] = useState("all");
  var [component, setComponent] = useState("all");
  var [hideBeat, setHideBeat] = useState(false);

  function load(kind, start, end) {
    setStatus({ text: "Loading...", error: false });
    var url = "/api/history?type=" + kind + "&from=" + encodeURIComponent(start) +
      "&to=" + encodeURIComponent(end) + "&limit=5000";
    fetch(url)
      .then(function (res) { return res.json(); })
      .then(function (body) {
        if (!body.ok) {
          setRows([]);
          setStatus({ text: body.error || "The request failed", error: true });
          return;
        }
        setRows(body.rows.map(withKohm));
        var text = body.count + " rows from " + dateTimeOf(body.from) + " to " + dateTimeOf(body.to);
        if (body.count >= 5000) { text += " (limit reached, pick a shorter range)"; }
        setStatus({ text: text, error: false });
      })
      .catch(function () {
        setStatus({ text: "Could not reach the web server", error: true });
      });
  }

  useEffect(function () { load(type, from, to); }, []);

  function submit(ev) {
    ev.preventDefault();
    load(type, from, to);
  }

  function lastTen() {
    var start = localInput(Date.now() - TEN_MIN);
    var end = localInput(Date.now());
    setFrom(start);
    setTo(end);
    load(type, start, end);
  }

  function pickType(kind) {
    setType(kind);
    setRows([]);
    load(kind, from, to);
  }

  var shown = rows;
  if (type === "system_log") {
    shown = rows.filter(function (r) {
      if (level !== "all" && r.level !== level) { return false; }
      var who = subsystemOf(r.component);
      if (hideBeat && who === "WVS") { return false; }
      return component === "all" || who === component;
    });
  }
  var cols = COLUMNS[type];

  var filters = null;
  if (type === "system_log") {
    filters = h("div", { className: "form-row" },
      h("label", null, "Level",
        h("select", { value: level, onChange: function (ev) { setLevel(ev.target.value); } },
          ["all", "info", "warning", "error"].map(function (l) {
            return h("option", { key: l, value: l }, capital(l));
          }))),
      h("label", null, "Subsystem",
        h("select", { value: component, onChange: function (ev) { setComponent(ev.target.value); } },
          h("option", { value: "all" }, "All subsystems"),
          SUBSYSTEMS.map(function (s) {
            return h("option", { key: s.id, value: s.id }, s.id + " (" + s.name + ")");
          }))),
      h("label", { className: "check" },
        h("input", { type: "checkbox", checked: hideBeat,
          onChange: function (ev) { setHideBeat(ev.target.checked); } }),
        "Hide WVS heartbeat"));
  }

  return h("div", { className: "section" },
    h("h2", null, props.title),
    props.intro ? h("p", { className: "intro" }, props.intro) : null,
    h("form", { className: "form-row", onSubmit: submit },
      fixed ? null : h("label", null, "Data",
        h("select", { value: type, onChange: function (ev) { pickType(ev.target.value); } },
          LOG_TYPES.map(function (t) { return h("option", { key: t.id, value: t.id }, t.name); }))),
      h("label", null, "From",
        h("input", { type: "datetime-local", step: 1, required: true, value: from,
          onChange: function (ev) { setFrom(ev.target.value); } })),
      h("label", null, "To",
        h("input", { type: "datetime-local", step: 1, required: true, value: to,
          onChange: function (ev) { setTo(ev.target.value); } })),
      h("button", { className: "btn primary", type: "submit" }, "Show"),
      h("button", { className: "btn", type: "button", onClick: lastTen }, "Last 10 min"),
      h("button", {
        className: "btn", type: "button", disabled: shown.length === 0,
        onClick: function () {
          download(type + "_" + from.replace(/[:T]/g, "-") + ".csv", toCsv(cols, shown));
        }
      }, "Download CSV")),
    filters,
    h("div", { className: "status" + (status.error ? " error" : "") },
      status.text + (shown.length !== rows.length ? " (" + shown.length + " shown after filters)" : "")),
    h(DataTable, { cols: cols, rows: shown }));
}

// image history (HLO-M-3 item 4, REQ-F-07)
var IMAGE_FILTERS = [
  { id: "all", name: "All saved frames" },
  { id: "targets", name: "Frames with targets" },
  { id: "valve", name: "Valve" },
  { id: "gauge", name: "Pressure gauge" },
  { id: "aruco", name: "ArUco marker" }
];

function ImageHistory(props) {
  var [from, setFrom] = useState(localInput(Date.now() - TEN_MIN));
  var [to, setTo] = useState(localInput(Date.now()));
  var [filter, setFilter] = useState("all");
  var [frames, setFrames] = useState([]);
  var [index, setIndex] = useState(0);
  var [playing, setPlaying] = useState(false);
  var [speed, setSpeed] = useState(1);
  var [status, setStatus] = useState({ text: "", error: false });

  function load(start, end, kind) {
    setPlaying(false);
    setStatus({ text: "Loading...", error: false });
    var url = "/api/frames?from=" + encodeURIComponent(start) + "&to=" + encodeURIComponent(end) + "&limit=2000";
    if (kind === "targets") { url += "&only_targets=1"; }
    else if (kind !== "all") { url += "&type=" + kind; }
    fetch(url)
      .then(function (res) { return res.json(); })
      .then(function (body) {
        if (!body.ok) {
          setFrames([]);
          setStatus({ text: body.error || "The request failed", error: true });
          return;
        }
        setFrames(body.rows);
        // start on the newest frame
        setIndex(Math.max(0, body.rows.length - 1));
        var text = body.count + " saved frames from " + dateTimeOf(body.from) + " to " + dateTimeOf(body.to);
        if (body.count >= 2000) { text += " (limit reached, pick a shorter range)"; }
        setStatus({ text: text, error: false });
      })
      .catch(function () {
        setStatus({ text: "Could not reach the web server", error: true });
      });
  }

  useEffect(function () { load(from, to, filter); }, []);

  // replay steps one frame every half second, faster at 2x and 5x
  useEffect(function () {
    if (!playing) { return; }
    var id = setInterval(function () {
      setIndex(function (i) { return i + 1; });
    }, 500 / speed);
    return function () { clearInterval(id); };
  }, [playing, speed]);

  useEffect(function () {
    if (playing && index >= frames.length - 1) { setPlaying(false); }
    if (index > frames.length - 1 && frames.length > 0) { setIndex(frames.length - 1); }
  }, [index, playing, frames.length]);

  // the thumbnail strip scrolls sideways, keep the current frame's thumbnail
  // in view (it starts on the newest, at the far right). only the strip scrolls
  var strip = useRef(null);
  useEffect(function () {
    var box = strip.current;
    var on = box && box.querySelector("a.on");
    if (!on || box.scrollWidth <= box.clientWidth) { return; }
    box.scrollLeft = on.offsetLeft - box.offsetLeft - (box.clientWidth - on.offsetWidth) / 2;
  }, [index, frames.length]);

  function submit(ev) {
    ev.preventDefault();
    load(from, to, filter);
  }

  function lastTen() {
    var start = localInput(Date.now() - TEN_MIN);
    var end = localInput(Date.now());
    setFrom(start);
    setTo(end);
    load(start, end, filter);
  }

  function play() {
    if (playing) { setPlaying(false); return; }
    if (index >= frames.length - 1) { setIndex(0); }
    setPlaying(true);
  }

  function jump(i) {
    setPlaying(false);
    setIndex(Math.max(0, Math.min(frames.length - 1, i)));
  }

  var form = h("form", { className: "form-row", onSubmit: submit },
    h("label", null, "From",
      h("input", { type: "datetime-local", step: 1, required: true, value: from,
        onChange: function (ev) { setFrom(ev.target.value); } })),
    h("label", null, "To",
      h("input", { type: "datetime-local", step: 1, required: true, value: to,
        onChange: function (ev) { setTo(ev.target.value); } })),
    h("label", null, "Show",
      h("select", { value: filter, onChange: function (ev) { setFilter(ev.target.value); load(from, to, ev.target.value); } },
        IMAGE_FILTERS.map(function (f) { return h("option", { key: f.id, value: f.id }, f.name); }))),
    h("button", { className: "btn primary", type: "submit" }, "Show"),
    h("button", { className: "btn", type: "button", onClick: lastTen }, "Last 10 min"));

  var statusLine = h("div", { className: "status" + (status.error ? " error" : "") }, status.text);

  if (frames.length === 0) {
    return h("div", { className: "section" }, h("h2", null, "Image History"), form, statusLine,
      h("div", { className: "empty" }, "No saved frames in this time range"));
  }

  var cur = frames[Math.min(index, frames.length - 1)];

  // a window of thumbnails around the current frame
  var first = Math.max(0, Math.min(index - 8, frames.length - 17));
  var thumbs = frames.slice(first, first + 17).map(function (f, i) {
    var at = first + i;
    return h("a", {
      key: f.id, href: f.url, className: at === index ? "on" : "",
      onClick: function (ev) { ev.preventDefault(); jump(at); }
    },
      h("img", { src: f.url, alt: "frame " + f.id, loading: "lazy" }),
      h("span", null, clockOf(f.ts) + (f.n_targets ? "  ·  " + typesText(f.types) : "")));
  });

  var targetList = cur.targets.length === 0
    ? h("div", { className: "empty" }, "No targets on this frame")
    : h("div", { className: "target-list" }, cur.targets.map(function (t) {
      var bits = [];
      if (has(t.confidence)) { bits.push(num(t.confidence * 100, 0) + "% confidence"); }
      var pose = poseText(t);
      if (pose) { bits.push(pose); }
      return h("div", { key: t.id || t.type + t.aruco_id },
        h("b", null, targetText(t)), bits.length ? h("div", { className: "detail" }, bits.join("  ·  ")) : null);
    }));

  return h("div", { className: "section" },
    h("h2", null, "Image History"), form, statusLine,
    h("div", { className: "history" },
      h("div", null,
        h("div", { className: "viewer" }, h("img", { src: cur.url, alt: "saved frame " + cur.id })),
        h("div", { className: "controls" },
          h("button", { className: "btn", type: "button", disabled: index <= 0, onClick: function () { jump(index - 1); } }, "◀"),
          h("button", { className: "btn primary", type: "button", onClick: play }, playing ? "Pause" : "Play"),
          h("button", { className: "btn", type: "button", disabled: index >= frames.length - 1, onClick: function () { jump(index + 1); } }, "▶"),
          h("input", {
            type: "range", min: 0, max: frames.length - 1, value: index,
            onChange: function (ev) { jump(Number(ev.target.value)); }
          }),
          h("select", { value: speed, onChange: function (ev) { setSpeed(Number(ev.target.value)); } },
            [1, 2, 5].map(function (s) { return h("option", { key: s, value: s }, s + "x"); })),
          h("a", { className: "btn", href: cur.url, download: "frame_" + cur.id + ".jpg" }, "Download")),
        h("div", { className: "thumbs", ref: strip }, thumbs)),
      h("div", { className: "history-side" },
        h("div", { className: "k" }, "Frame " + (index + 1) + " of " + frames.length),
        h("div", { className: "when" }, dateTimeOf(cur.ts)),
        h(AgeBadge, { lag: cur.capture_lag, limit: props.ageLimit }),
        h("div", { className: "k gap" }, "Targets on this frame"),
        targetList,
        h("a", { className: "h2-link block", href: cur.url, target: "_blank", rel: "noopener" }, "Open full size"))));
}

// the charts keep a plain list of readings, oldest first

function hasTime(rows, ts) {
  for (var i = 0; i < rows.length; i++) {
    if (rows[i].ts === ts) { return true; }
  }
  return false;
}

function lastFew(rows) {
  return rows.length > POINTS ? rows.slice(-POINTS) : rows;
}

function addPose(setPoses, row) {
  setPoses(function (old) {
    var next = old.concat([row]);
    return next.length > POSE_POINTS ? next.slice(-POSE_POINTS) : next;
  });
}

function addReading(setRows, row) {
  setRows(function (old) {
    // the snapshot and the history both carry the newest one, so check the time
    if (hasTime(old, row.ts)) { return old; }
    return lastFew(old.concat([row]));
  });
}

function mergeHistory(old, rows) {
  // history first, then anything that arrived while it was loading
  var next = rows.slice();
  old.forEach(function (row) {
    if (!hasTime(next, row.ts)) { next.push(row); }
  });
  return lastFew(next);
}

function newestTarget(snap) {
  // the snapshot holds the latest of each type, the newest of those is the last target found
  var all = [snap.valve, snap.gauge].concat(snap.aruco || []).filter(function (t) { return !!t; });
  all.sort(function (a, b) { return a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0; });
  return all.length ? all[all.length - 1] : null;
}

// the page
function App() {
  var [data, setData] = useState({
    info: {}, reading: null, valve: null, gauge: null, markers: {}, inView: [],
    drill: null, logs: [], frame: {}, samples: null, updated: null,
    lcd: null, lastTarget: null
  });
  var [live, setLive] = useState(false);
  var [rows, setRows] = useState([]);
  var [poses, setPoses] = useState([]);
  var [captures, setCaptures] = useState([]);
  var [page, setPage] = useState(pageFromHash());
  var [sound, setSound] = useState({ unlocked: false, muted: false });
  var [lcdBusy, setLcdBusy] = useState(false);
  var [selected, setSelected] = useState(null);   // a saved image shown instead of the live feed
  var [stats, setStats] = useState({});           // target type -> readings summed while in view
  var [clock, setClock] = useState({
    timer: "00:00:00", rec: "00:00:00", quiet: null
  });

  var startedAt = useRef(Date.now());
  var recFrom = useRef(null);
  var lastAt = useRef(null);
  var markerAt = useRef({});   // marker id -> Date.now() its last pose arrived
  var ownLogs = useRef(["WVS"]);   // logs the web viz writes about itself
  var seenAt = useRef({});     // target type -> Date.now() it was last detected

  // the navigation menu changes the #hash, the page follows it
  useEffect(function () {
    function onHash() {
      setPage(pageFromHash());
      window.scrollTo(0, 0);
    }
    window.addEventListener("hashchange", onHash);
    return function () { window.removeEventListener("hashchange", onHash); };
  }, []);

  // the header clocks tick on their own, they are not data from the payload
  useEffect(function () {
    var id = setInterval(function () {
      setClock({
        timer: countUp(Date.now() - startedAt.current),
        rec: recFrom.current ? countUp(Date.now() - recFrom.current) : "00:00:00",
        quiet: lastAt.current ? (Date.now() - lastAt.current) / 1000 : null
      });
    }, 1000);
    return function () { clearInterval(id); };
  }, []);

  // load recent readings so the charts are not empty when the page opens
  useEffect(function () {
    fetch("/api/history?type=readings&limit=" + POINTS)
      .then(function (res) { return res.json(); })
      .then(function (body) {
        if (!body.ok || body.rows.length === 0) { return; }
        setRows(function (old) { return mergeHistory(old, body.rows.map(withKohm)); });
      })
      .catch(function () {
        // nothing logged yet, the stream will fill the charts in instead
      });

    // same for the pose chart, only the aruco rows are wanted
    fetch("/api/history?type=detections&limit=" + POSE_POINTS * 2)
      .then(function (res) { return res.json(); })
      .then(function (body) {
        if (!body.ok) { return; }
        var old = body.rows.filter(function (row) { return row.type === "aruco"; });
        setPoses(function (now) {
          // the stream may already have sent some, keep those after the history
          var fresh = now.filter(function (row) { return !hasTime(old, row.ts); });
          return old.concat(fresh).slice(-POSE_POINTS);
        });
      })
      .catch(function () {});

    // the detection images saved before the page opened
    fetch("/api/frames?only_targets=1&limit=" + STRIP_KEEP)
      .then(function (res) { return res.json(); })
      .then(function (body) {
        if (!body.ok) { return; }
        var saved = body.rows.slice().reverse();
        setCaptures(function (now) {
          var ids = now.map(function (c) { return c.id; });
          return now.concat(saved.filter(function (c) { return ids.indexOf(c.id) < 0; })).slice(0, STRIP_KEEP);
        });
      })
      .catch(function () {});
  }, []);

  // the live push connection, everything on the page comes through here
  useEffect(function () {
    // one source at a time. the browser retries by itself while the source
    // is CONNECTING, but an error response (a 502 from nginx while gunicorn
    // restarts) closes it for good, so then a new one is made after 3 s
    var current = null;
    var retry = null;
    var disposed = false;

    function connect() {
      if (disposed) { return; }
      var es = new EventSource("/stream");
      current = es;

      es.addEventListener("snapshot", function (ev) {
        // sent the moment the connection opens so the panels paint straight away
        var snap = JSON.parse(ev.data);
        setLive(true);
        if (snap.server_time) { clockSkew = msOf(snap.server_time) - Date.now(); }
        if (snap.own_components) { ownLogs.current = snap.own_components; }
        // the server says how long it has been quiet, an old database is not live
        if (snap.quiet !== null && snap.quiet !== undefined) {
          lastAt.current = Date.now() - snap.quiet * 1000;
        }
        if (snap.frame && snap.frame.live && !recFrom.current) {
          recFrom.current = Date.now();
        }
        setData(function (old) {
          var markers = {};
          (snap.aruco || []).forEach(function (m) { markers[m.aruco_id] = m; });
          var at = snap.quiet !== null && snap.quiet !== undefined
            ? Date.now() - snap.quiet * 1000 : Date.now();
          (snap.aruco_in_view || []).forEach(function (id) { markerAt.current[id] = at; });
          return {
            info: snap,
            reading: withKohm(snap.reading),
            valve: snap.valve,
            gauge: snap.gauge,
            markers: markers,
            inView: snap.aruco_in_view || [],
            drill: snap.drill,
            logs: snap.logs || [],
            frame: snap.frame || {},
            samples: snap.samples,
            updated: snap.updated,
            lcd: snap.lcd,
            lastTarget: newestTarget(snap)
          };
        });
        if (snap.reading) { addReading(setRows, withKohm(snap.reading)); }
      });

      es.addEventListener("reading", function (ev) {
        var row = withKohm(JSON.parse(ev.data));
        lastAt.current = Date.now();
        setData(function (old) {
          return Object.assign({}, old, {
            reading: row,
            samples: has(old.samples) ? old.samples + 1 : 1,
            updated: row.ts
          });
        });
        addReading(setRows, row);

        // this reading counts towards the average of every target in view right now
        var now = Date.now();
        setStats(function (old) {
          var next = Object.assign({}, old);
          TARGET_ROWS.forEach(function (r) {
            var at = seenAt.current[r.type];
            if (!at || now - at > IN_VIEW_MS) { return; }
            var s = old[r.type] || { sum: {}, count: {} };
            var sum = Object.assign({}, s.sum);
            var count = Object.assign({}, s.count);
            AVG_COLS.forEach(function (c) {
              if (!has(row[c.key])) { return; }
              sum[c.key] = (sum[c.key] || 0) + row[c.key];
              count[c.key] = (count[c.key] || 0) + 1;
            });
            next[r.type] = { sum: sum, count: count };
          });
          return next;
        });
      });

      es.addEventListener("detection", function (ev) {
        var row = JSON.parse(ev.data);
        lastAt.current = Date.now();
        seenAt.current[row.type] = Date.now();
        announce(row);
        setData(function (old) {
          var next = Object.assign({}, old, { updated: row.ts, lastTarget: row });
          if (row.type === "valve") {
            next.valve = row;
          } else if (row.type === "gauge") {
            next.gauge = row;
          } else {
            next.markers = Object.assign({}, old.markers);
            next.markers[row.aruco_id] = row;
            if (old.inView.indexOf(row.aruco_id) < 0) {
              next.inView = old.inView.concat([row.aruco_id]);
            }
          }
          return next;
        });
        if (row.type === "aruco") {
          markerAt.current[row.aruco_id] = Date.now();
          addPose(setPoses, row);
        }
      });

      es.addEventListener("aruco_view", function (ev) {
        // comes after every taq frame, the ids in it are the only ones in view now
        var view = JSON.parse(ev.data);
        lastAt.current = Date.now();
        setData(function (old) {
          return Object.assign({}, old, { inView: view.ids, updated: view.ts });
        });
      });

      es.addEventListener("log", function (ev) {
        // drill events arrive here too, they are log rows with the drill columns
        var row = JSON.parse(ev.data);
        // the web viz heartbeat is not payload data, the system log page shows it
        if (ownLogs.current.indexOf(row.component) >= 0) { return; }
        lastAt.current = Date.now();
        setData(function (old) {
          var logs = old.logs.concat([row]).slice(-25);
          var next = Object.assign({}, old, { logs: logs, updated: row.ts });
          if (row.drill_state) { next.drill = row; }
          return next;
        });
      });

      es.addEventListener("frame", function (ev) {
        // camera meta only, the picture itself comes down /video_feed
        var meta = JSON.parse(ev.data);
        lastAt.current = Date.now();
        if (!recFrom.current) { recFrom.current = Date.now(); }
        setData(function (old) {
          return Object.assign({}, old, { frame: meta });
        });
      });

      es.addEventListener("capture", function (ev) {
        // a frame with targets was saved, newest goes to the front of the strip
        var item = JSON.parse(ev.data);
        setCaptures(function (old) {
          return [item].concat(old.filter(function (c) { return c.id !== item.id; })).slice(0, STRIP_KEEP);
        });
      });

      es.addEventListener("lcd", function (ev) {
        // someone picked a new lcd display, maybe on another computer
        var lcd = JSON.parse(ev.data);
        setData(function (old) { return Object.assign({}, old, { lcd: lcd }); });
      });

      es.onopen = function () { setLive(true); };
      es.onerror = function () {
        // the browser reconnects by itself, the header just goes grey meanwhile
        setLive(false);
        // except after an error response, then it gives up, so start again
        if (es === current && es.readyState === EventSource.CLOSED) { reconnectLater(); }
      };
    }

    function reconnectLater() {
      // one timer at most, and nothing once the page has gone
      if (disposed || retry) { return; }
      retry = setTimeout(function () {
        retry = null;
        current.close();
        connect();
      }, 3000);
    }

    connect();

    return function () {
      disposed = true;
      clearTimeout(retry);
      current.close();
    };
  }, []);

  function pickLcd(mode) {
    setLcdBusy(true);
    fetch("/api/lcd", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: mode })
    })
      .then(function (res) { return res.json(); })
      .then(function (body) {
        setLcdBusy(false);
        if (body.ok) {
          setData(function (old) {
            return Object.assign({}, old, { lcd: { mode: body.mode, changed: body.changed } });
          });
        }
      })
      .catch(function () { setLcdBusy(false); });
  }

  function unlockSpeech() {
    if (speech.unlocked || !canSpeak()) { return; }
    speech.unlocked = true;
    // speaking inside the click is what tells the browser sound is allowed
    say("Voice alerts on");
    setSound({ unlocked: true, muted: speech.muted });
  }

  // the first click or key press anywhere on the page unlocks speech
  useEffect(function () {
    function unlock(ev) {
      // the voice button does it on its own click, see SoundControls
      if (ev && ev.target && ev.target.closest && ev.target.closest(".voice-allow")) { return; }
      unlockSpeech();
      if (!speech.unlocked) { return; }
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    }
    window.addEventListener("pointerdown", unlock);
    window.addEventListener("keydown", unlock);
    return function () {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  function toggleMute() {
    speech.muted = !speech.muted;
    if (speech.muted && canSpeak()) { window.speechSynthesis.cancel(); }
    if (!speech.muted) {
      // targets already in view get announced again after unmuting
      speech.seen = {};
    }
    setSound({ unlocked: true, muted: speech.muted });
  }

  var markerList = Object.keys(data.markers)
    .sort(function (a, b) { return a - b; })
    .map(function (key) { return data.markers[key]; });

  // in the last frame and heard from recently, so a taq that stops sending
  // does not leave its markers showing as in view forever
  function inView(id) {
    var at = markerAt.current[id];
    return data.inView.indexOf(id) >= 0 && !!at && (Date.now() - at) / 1000 < MARKER_STALE;
  }
  var poseId = poses.length ? poses[poses.length - 1].aruco_id : null;

  var limit = has(data.info.drill_bar) ? data.info.drill_bar : 2.0;
  // the trigger the drill reports wins, so the gauge mark matches the drill panel
  if (data.drill && has(data.drill.trigger_pressure)) {
    limit = data.drill.trigger_pressure;
  }
  var gaugeMax = has(data.info.gauge_max) ? data.info.gauge_max : 10.0;
  var ageLimit = has(data.info.age_limit) ? data.info.age_limit : 4.0;

  var feed = h(FeedPanel, { frame: data.frame, rec: clock.rec, live: live, ageLimit: ageLimit });
  var found = h(TargetFound, { target: data.lastTarget, ageLimit: ageLimit, limit: limit });
  var strip = h(CaptureStrip, { captures: captures });
  var targets = h(TargetPanel, {
    valve: data.valve, gauge: data.gauge, markers: markerList, limit: limit, gaugeMax: gaugeMax,
    inView: inView, poseRows: poses, poseId: poseId
  });
  var air = PHONE.matches
    ? h(ChartTabs, { rows: rows, poseRows: poses, poseId: poseId, start: "gas", tabs: CHART_TABS.slice(1) })
    : h(AirPanel, { rows: rows });
  var readings = h(ReadingsSection, { reading: data.reading, samples: data.samples, ageLimit: ageLimit });
  var drill = h(DrillPanel, { drill: data.drill, logs: data.logs, limit: limit });

  var body;
  if (page === "video") {
    body = h("div", { className: "page" }, feed, found, strip);
  } else if (page === "targets") {
    body = h("div", { className: "page" }, found, targets, drill);
  } else if (page === "air") {
    body = h("div", { className: "page" }, readings, air);
  } else if (page === "logged") {
    body = h("div", { className: "page wide" }, h(LoggedData, {
      key: "logged", title: "Logged Data",
      intro: "Pick a time range to see the logged sensor readings, target detections and positions, or the system log, with their timestamps."
    }));
  } else if (page === "images") {
    body = h("div", { className: "page wide" }, h(ImageHistory, { ageLimit: ageLimit }));
  } else if (page === "logs") {
    body = h("div", { className: "page wide" }, h(LoggedData, {
      key: "logs", fixedType: "system_log", title: "System Operation Log",
      intro: "Log messages from every subsystem (WVS, AQ, TAIP, EDM), including the WVS heartbeat every 10 s."
    }));
  } else {
    // the newest aruco marker is the one the targets table shows
    var lastAruco = null;
    markerList.forEach(function (m) {
      if (!lastAruco || m.ts > lastAruco.ts) { lastAruco = m; }
    });
    body = h(Dashboard, {
      captures: captures, selected: selected, pick: setSelected,
      frame: data.frame, rec: clock.rec, live: live, ageLimit: ageLimit, target: data.lastTarget,
      rows: rows, poseRows: poses, poseId: poseId,
      latest: { valve: data.valve, gauge: data.gauge, aruco: lastAruco },
      stats: stats, limit: limit, drill: data.drill, reading: data.reading
    });
  }

  return h("div", null,
    h(Header, {
      info: data.info, live: live, quiet: clock.quiet, timer: clock.timer,
      lcd: data.lcd, lcdBusy: lcdBusy, pickLcd: pickLcd,
      sound: sound, toggleMute: toggleMute, unlock: unlockSpeech
    }),
    h(NavBar, { page: page }),
    HANDHELD.matches ? h(OperatorHero, {
      info: data.info, live: live, quiet: clock.quiet, timer: clock.timer,
      target: data.lastTarget, gauge: data.gauge, limit: limit, inView: inView
    }) : null,
    body);
}

ReactDOM.createRoot(document.getElementById("root")).render(h(App));
