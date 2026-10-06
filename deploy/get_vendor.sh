#!/bin/sh
# downloads react, chart.js and the carlito font into static/vendor so the pi works offline

DIR="$(dirname "$0")/../static/vendor"
mkdir -p "$DIR"

curl -L -o "$DIR/react.production.min.js" \
  https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.production.min.js
curl -L -o "$DIR/react-dom.production.min.js" \
  https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom.production.min.js
curl -L -o "$DIR/chart.umd.min.js" \
  https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js

# carlito has the same letter widths as calibri, open font licence
for w in 400 700; do
  curl -L -o "$DIR/carlito-$w.woff2"     "https://cdn.jsdelivr.net/npm/@fontsource/carlito@5/files/carlito-latin-$w-normal.woff2"
done

echo "vendor files downloaded into static/vendor"
