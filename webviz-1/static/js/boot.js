// loads react and chart.js then app.js, from static/vendor so the pi works offline

var LIBS = [
  ["/static/vendor/react.production.min.js",
   "https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.production.min.js"],
  ["/static/vendor/react-dom.production.min.js",
   "https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom.production.min.js"],
  ["/static/vendor/chart.umd.min.js",
   "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"]
];

function loadOne(urls, done) {
  var tag = document.createElement("script");
  tag.src = urls[0];
  tag.onload = done;
  tag.onerror = function () {
    // local copy is not there, go and get it from the cdn instead
    var backup = document.createElement("script");
    backup.src = urls[1];
    backup.onload = done;
    backup.onerror = function () {
      showError("could not load " + urls[0] + " or the cdn copy");
    };
    document.body.appendChild(backup);
  };
  document.body.appendChild(tag);
}

function loadAll(list, index, done) {
  if (index >= list.length) {
    done();
    return;
  }
  loadOne(list[index], function () {
    loadAll(list, index + 1, done);
  });
}

function showError(text) {
  document.getElementById("root").innerHTML =
    '<p class="booting">' + text + "</p>";
}

loadAll(LIBS, 0, function () {
  var tag = document.createElement("script");
  tag.src = "/static/js/app.js";
  document.body.appendChild(tag);
});
