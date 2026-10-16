from flask import Blueprint, Response, stream_with_context

from live import bus

# the sse endpoint the dashboard keeps open. one connection per browser tab

live_bp = Blueprint("live", __name__)


@live_bp.route("/stream")
def stream():
    q = bus.subscribe()

    def run():
        try:
            for packet in bus.feed(q):
                yield packet
        finally:
            # the generator ends when the browser goes away
            bus.unsubscribe(q)

    r = Response(stream_with_context(run()), mimetype="text/event-stream")
    r.headers["Cache-Control"] = "no-cache"
    r.headers["Connection"] = "keep-alive"
    # tells nginx not to sit on the messages
    r.headers["X-Accel-Buffering"] = "no"
    return r
