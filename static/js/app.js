// dashboard front end. plain react, no jsx, so there is no build step

var h = React.createElement;
var useState = React.useState;
var useEffect = React.useEffect;
var useRef = React.useRef;

var POINTS = 90;        // how many samples the charts keep on screen
var GAUGE_MAX = 4.0;    // top of the pressure meter, bar

var TEAL = "#2fe0a8";
var PALE = "#9ad5c0";
var AMBER = "#f0a832";
var WHITE = "#dfe7e4";
var GRID = "#16211f";
var DIM = "#40564f";

// little helpers
function clockOf(iso) {
  // the server sends 2026-09-15T10:22:03.417, the panels only want the time
  if (!iso) { return "--:--:--"; }
  var bits = iso.split("T");
  return bits.length > 1 ? bits[1].slice(0, 8) : iso;
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

function utcNow() {
  return new Date().toISOString().slice(11, 19);
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

// header
function HudItem(props) {
  return h("div", { className: "hud-item" },
    h("span", { className: "k" }, props.label),
    h("span", { className: "v" + (props.accent ? " ip" : "") }, props.value));
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

function Header(props) {
  var info = props.info || {};
  var stream = streamState(props);

  return h("div", { className: "topbar" },
    h("div", { className: "brand" },
      h("span", { className: "name" }, "UAV PAYLOAD"),
      h("span", { className: "sub" }, "GROUND CONTROL STATION")),
    h("div", { className: "spacer" }),
    h("div", { className: "hud" },
      h("div", { className: "hud-item" },
        h("span", { className: "k" }, "stream"),
        h("span", { className: "lamp" + (stream.on ? "" : " off") },
          h("span", { className: "bulb" }),
          h("span", null, stream.text))),
      h(HudItem, { label: "payload ip", value: info.payload_ip || "--", accent: true }),
      h(HudItem, { label: "refresh", value: num(info.cadence, 1) + " s" }),
      h(HudItem, { label: "log timer", value: props.timer }),
      h(HudItem, { label: "utc", value: props.utc })));
}

// live detector feed
function feedLine(frame) {
  // the numbers come from the meta sent with each frame, nothing is guessed
  if (!frame || !frame.live) {
    return "no frames received  -  waiting on POST /api/ingest/frame";
  }

  var parts = [];
  parts.push(has(frame.detections) ? frame.detections + " detections" : "detections n/a");
  if (has(frame.inference_ms)) { parts.push("inference " + num(frame.inference_ms, 0) + " ms"); }
  if (frame.model) { parts.push(frame.model); }
  if (has(frame.conf)) { parts.push("conf " + num(frame.conf, 2)); }
  if (has(frame.fps) && frame.fps > 0) { parts.push(num(frame.fps, 1) + " fps"); }
  return parts.join("  -  ");
}

function FeedPanel(props) {
  var frame = props.frame || {};
  var running = frame.live;

  return h("div", { className: "section" },
    h("h2", null, "Live Detector Feed"),
    h("div", { className: "screen" },
      h("img", { src: "/video_feed", alt: "detector feed" }),
      h("div", { className: "cam" }, frame.camera || "CAM 0"),
      h("div", { className: "rec" + (running ? "" : " off") },
        running ? "REC " + props.rec : "NO SIGNAL")),
    h("div", { className: "feed-note" }, feedLine(frame)));
}

// target acquisition
function ValveCard(props) {
  var valve = props.valve;
  var state = valve ? valve.valve_state : null;

  // the card only lights up once a real detection has come in
  var css = "card dark";
  if (state === "open") { css = "card lit-teal"; }
  if (state === "closed") { css = "card lit-amber"; }

  return h("div", { className: css },
    h("div", { className: "k" }, "ball valve"),
    h("div", { className: "big" }, state ? state.toUpperCase() : "NO DATA"),
    h("div", { className: "note" },
      valve ? "detected " + num(valve.confidence * 100, 0) + "%" : "awaiting taq"));
}

function GaugeCard(props) {
  var gauge = props.gauge;
  var value = gauge ? gauge.gauge_value : null;
  var limit = props.limit;
  var over = has(value) && value >= limit;
  var pct = has(value) ? Math.max(0, Math.min(100, (value / GAUGE_MAX) * 100)) : 0;

  return h("div", { className: "card " + (gauge ? "lit-amber" : "dark") },
    h("div", { className: "k" }, "pressure"),
    h("div", { className: "big" }, num(value, 1),
      h("span", { className: "unit" }, gauge ? gauge.gauge_units : "bar")),
    h("div", { className: "meter" },
      h("div", { className: "fill" + (over ? " over" : ""), style: { width: pct + "%" } }),
      // the drill fires at this mark, it comes from the config not the ui
      h("div", { className: "mark", style: { left: (limit / GAUGE_MAX) * 100 + "%" } })),
    h("div", { className: "meter-note" },
      h("span", null, "0"),
      h("span", null, "drill " + num(limit, 1)),
      h("span", null, num(GAUGE_MAX, 1) + " bar")));
}

function ArucoCard(props) {
  var markers = props.markers || [];

  if (markers.length === 0) {
    return h("div", { className: "card" },
      h("div", { className: "k" }, "aruco - pose (m)"),
      h("div", { className: "empty" }, "no markers in view"));
  }

  var rows = markers.map(function (m) {
    return h("tr", { key: m.aruco_id },
      h("td", null, m.aruco_id),
      h("td", null, num(m.x, 3)),
      h("td", null, num(m.y, 3)),
      h("td", null, num(m.z, 3)));
  });

  return h("div", { className: "card" },
    h("div", { className: "k" }, "aruco - pose (m)"),
    h("table", { style: { marginTop: "8px" } },
      h("thead", null, h("tr", null,
        h("th", null, "id"), h("th", null, "x"), h("th", null, "y"), h("th", null, "z"))),
      h("tbody", null, rows)));
}

function TargetPanel(props) {
  return h("div", { className: "section" },
    h("h2", null, "Target Acquisition"),
    h("div", { className: "cards" },
      h(ValveCard, { valve: props.valve }),
      h(GaugeCard, { gauge: props.gauge, limit: props.limit }),
      h(ArucoCard, { markers: props.markers })));
}

// charts
function makeScales(props) {
  var axis = {
    grid: { color: GRID, drawTicks: false },
    border: { color: GRID },
    ticks: { color: DIM, font: { size: 9 }, maxTicksLimit: 5, padding: 4 }
  };

  var scales = {
    x: {
      grid: { color: GRID, drawTicks: false },
      border: { color: GRID },
      ticks: { color: DIM, font: { size: 8 }, maxTicksLimit: 6, maxRotation: 0 }
    },
    y: axis
  };

  // the temperature chart needs a second axis on the right for humidity
  if (props.twoAxis) {
    scales.y2 = {
      position: "right",
      grid: { drawOnChartArea: false },
      border: { color: GRID },
      ticks: { color: DIM, font: { size: 9 }, maxTicksLimit: 5 }
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
        borderWidth: 1.4,
        pointRadius: 0,
        tension: 0.3,
        spanGaps: true,
        yAxisID: s.axis || "y"
      };
    });

    chart.current = new Chart(canvas.current.getContext("2d"), {
      type: "line",
      data: { labels: [], datasets: sets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: makeScales(props),
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#0c1211",
            borderColor: "#1a2422",
            borderWidth: 1,
            titleColor: WHITE,
            bodyColor: WHITE,
            titleFont: { family: "monospace", size: 10 },
            bodyFont: { family: "monospace", size: 10 }
          }
        }
      }
    });

    return function () { chart.current.destroy(); };
  }, []);

  // no animation so the chart keeps up with one sample a second
  useEffect(function () {
    if (!chart.current) { return; }
    chart.current.data.labels = props.labels;
    props.series.forEach(function (s, i) {
      chart.current.data.datasets[i].data = s.data;
    });
    chart.current.update("none");
  });

  return h("div", { className: "chart-box" }, h("canvas", { ref: canvas }));
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
    h(Tile, { name: "temperature", value: num(r.temperature, 1), unit: "C" }),
    h(Tile, { name: "pressure", value: num(r.pressure, 0), unit: "hPa" }),
    h(Tile, { name: "humidity", value: num(r.humidity, 0), unit: "%RH" }),
    h(Tile, { name: "light", value: num(r.light, 0), unit: "lux" }),
    h(Tile, { name: "oxidising", value: num(r.oxidising_ppm, 1), unit: "ppm" }),
    h(Tile, { name: "reducing", value: num(r.reducing_ppm, 1), unit: "ppm" }),
    h(Tile, { name: "ammonia nh3", value: num(r.ammonia_ppm, 1), unit: "ppm" }),
    h(Tile, { name: "samples", value: grouped(props.samples), unit: "rows", accent: true }));
}

function AirPanel(props) {
  var rows = props.rows;
  var labels = rows.map(function (row) { return clockOf(row.ts); });

  var gas = [
    { name: "Oxidising", colour: TEAL, data: column(rows, "oxidising_ppm") },
    { name: "Reducing", colour: PALE, data: column(rows, "reducing_ppm") },
    { name: "Ammonia", colour: AMBER, data: column(rows, "ammonia_ppm") }
  ];

  var climate = [
    { name: "Temp C", colour: WHITE, data: column(rows, "temperature") },
    { name: "Humidity %", colour: TEAL, data: column(rows, "humidity"), axis: "y2" }
  ];

  return h("div", { className: "section" },
    h("h2", null, "Air Quality Trends"),
    h(ChartHead, { name: "Gas concentration (ppm)", series: gas }),
    h(LineChart, { labels: labels, series: gas }),
    h(ChartHead, { name: "Temperature & Humidity", series: climate }),
    h(LineChart, { labels: labels, series: climate, twoAxis: true }));
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
    lines = [h("div", { key: "none", className: "none" }, "no log messages received")];
  }

  return h("div", { className: "section" },
    h("h2", null, "Drill Controller"),
    h("div", { className: "strip" },
      h("div", null,
        h("span", { className: "pill " + state }, drill ? state : "no data"),
        h("div", { className: "drill-facts" },
          h("div", null, "hole depth  ",
            h("b", null, drill ? num(drill.hole_depth * 1000, 1) + " mm" : "--")),
          h("div", null, "trigger  ",
            h("b", null, num(drill && has(drill.trigger_pressure)
              ? drill.trigger_pressure : props.limit, 1) + " bar")),
          h("div", null, "last event  ",
            h("b", null, drill ? clockOf(drill.ts) : "--")))),
      h("div", { className: "log" }, lines)));
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

function column(rows, name) {
  return rows.map(function (row) { return row[name]; });
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

// the page
function App() {
  var [data, setData] = useState({
    info: {}, reading: null, valve: null, gauge: null, markers: {},
    drill: null, logs: [], frame: {}, samples: null, updated: null
  });
  var [live, setLive] = useState(false);
  var [rows, setRows] = useState([]);
  var [clock, setClock] = useState({
    timer: "00:00:00", utc: utcNow(), rec: "00:00:00", quiet: null
  });

  var startedAt = useRef(Date.now());
  var recFrom = useRef(null);
  var lastAt = useRef(null);

  // the header clocks tick on their own, they are not data from the payload
  useEffect(function () {
    var id = setInterval(function () {
      setClock({
        timer: countUp(Date.now() - startedAt.current),
        utc: utcNow(),
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
        setRows(function (old) { return mergeHistory(old, body.rows); });
      })
      .catch(function () {
        // nothing logged yet, the stream will fill the charts in instead
      });
  }, []);

  // the live push connection, everything on the page comes through here
  useEffect(function () {
    var es = new EventSource("/stream");

    es.addEventListener("snapshot", function (ev) {
      // sent the moment the connection opens so the panels paint straight away
      var snap = JSON.parse(ev.data);
      setLive(true);
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
        return {
          info: snap,
          reading: snap.reading,
          valve: snap.valve,
          gauge: snap.gauge,
          markers: markers,
          drill: snap.drill,
          logs: snap.logs || [],
          frame: snap.frame || {},
          samples: snap.samples,
          updated: snap.updated
        };
      });
      if (snap.reading) { addReading(setRows, snap.reading); }
    });

    es.addEventListener("reading", function (ev) {
      var row = JSON.parse(ev.data);
      lastAt.current = Date.now();
      setData(function (old) {
        return Object.assign({}, old, {
          reading: row,
          samples: has(old.samples) ? old.samples + 1 : 1,
          updated: row.ts
        });
      });
      addReading(setRows, row);
    });

    es.addEventListener("detection", function (ev) {
      var row = JSON.parse(ev.data);
      lastAt.current = Date.now();
      setData(function (old) {
        var next = Object.assign({}, old, { updated: row.ts });
        if (row.type === "valve") {
          next.valve = row;
        } else if (row.type === "gauge") {
          next.gauge = row;
        } else {
          next.markers = Object.assign({}, old.markers);
          next.markers[row.aruco_id] = row;
        }
        return next;
      });
    });

    es.addEventListener("log", function (ev) {
      // drill events arrive here too, they are log rows with the drill columns
      var row = JSON.parse(ev.data);
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

    es.onopen = function () { setLive(true); };
    es.onerror = function () {
      // the browser reconnects by itself, the header just goes grey meanwhile
      setLive(false);
    };

    return function () { es.close(); };
  }, []);

  var markerList = Object.keys(data.markers)
    .sort(function (a, b) { return a - b; })
    .map(function (key) { return data.markers[key]; });

  var limit = has(data.info.drill_bar) ? data.info.drill_bar : 2.0;

  return h("div", null,
    h(Header, {
      info: data.info, live: live, quiet: clock.quiet,
      timer: clock.timer, utc: clock.utc
    }),
    h("div", { className: "main" },
      h("div", { className: "col" },
        h(FeedPanel, { frame: data.frame, rec: clock.rec }),
        h(TargetPanel, {
          valve: data.valve, gauge: data.gauge, markers: markerList, limit: limit
        })),
      h("div", { className: "col right" },
        h(AirPanel, { rows: rows }),
        h("div", { className: "section" },
          h("h2", null, "Current Readings"),
          h(ReadingTiles, { reading: data.reading, samples: data.samples })),
        h(DrillPanel, { drill: data.drill, logs: data.logs, limit: limit }))));
}

ReactDOM.createRoot(document.getElementById("root")).render(h(App));
