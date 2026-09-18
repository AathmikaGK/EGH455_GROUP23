from flask import Flask, render_template

import config
from api.routes import api_bp
from db import store
from ingestion import writer
from live.stream import live_bp
from video import frames
from video.feed import video_bp

# entry point. this app makes no data of its own, it shows what gets sent to it

started = False


def make_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")

    app.register_blueprint(api_bp)
    app.register_blueprint(live_bp)
    app.register_blueprint(video_bp)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/healthz")
    def healthz():
        return {"ok": True}

    start_background()
    return app


def start_background():
    # store first so the writer knows whether mariadb is there
    global started
    if started:
        return
    started = True

    store.start_store()
    writer.start_writer()

    if config.VIDEO_SOURCE == "device":
        frames.start_device()
    else:
        print("[video] waiting for frames on POST /api/ingest/frame")

    print("[app] ready, waiting for the subsystems to send data")


app = make_app()


if __name__ == "__main__":
    print("dashboard on http://%s:%d" % (config.HOST, config.PORT))
    # threaded so the stream and video do not block, no reloader or we get two writers
    app.run(host=config.HOST, port=config.PORT, threaded=True,
            debug=False, use_reloader=False)
