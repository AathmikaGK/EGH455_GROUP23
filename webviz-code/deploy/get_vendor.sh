#!/bin/sh
# downloads react and chart.js into static/vendor so the pi works offline

DIR="$(dirname "$0")/../static/vendor"
mkdir -p "$DIR"

curl -L -o "$DIR/react.production.min.js" \
  https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.production.min.js
curl -L -o "$DIR/react-dom.production.min.js" \
  https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom.production.min.js
curl -L -o "$DIR/chart.umd.min.js" \
  https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js

echo "vendor files downloaded into static/vendor"
