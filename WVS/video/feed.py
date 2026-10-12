import os
import time
from flask import Blueprint, Response, send_file
import config
from video import capture, frames

# the mjpeg route reads the live buffer, the saved frames route reads captures/

video_bp = Blueprint("video", __name__)

BOUNDARY = "wvsframe"


def part(jpg):
    head = ("--%s\r\nContent-Type: image/jpeg\r\n"
            "Content-Length: %d\r\n\r\n" % (BOUNDARY, len(jpg)))
    return head.encode("ascii") + jpg + b"\r\n"


def mjpeg_stream():
    seen = -1
    sent_blank = 0.0

    while True:
        # blocks until a new frame lands, so the browser gets it straight away
        seq, jpg = frames.wait_for_frame(seen, 1.0)

        if seq != seen and jpg is not None:
            seen = seq
            yield part(jpg)
            continue

        # nothing came in, show the no signal card and keep the connection awake
        if not frames.is_fresh() and time.time() - sent_blank > 1.0:
            blank = frames.no_signal()
            sent_blank = time.time()
            if blank is not None:
                yield part(blank)


@video_bp.route("/video_feed")
def video_feed():
    if config.VIDEO_SOURCE == "device" and not frames.have_cv2:
        return Response("opencv is not installed, run pip install -r requirements.txt",
                        status=503, mimetype="text/plain")

    r = Response(mjpeg_stream(),
                 mimetype="multipart/x-mixed-replace; boundary=" + BOUNDARY)
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    r.headers["X-Accel-Buffering"] = "no"
    return r


@video_bp.route("/frames/<int:frame_id>.jpg")
def saved_frame(frame_id):
    # the id alone gives the path, so this only ever reads inside captures/
    path = capture.full_path(frame_id)
    if not os.path.isfile(path):
        return Response("no saved frame %d, it may have been cleaned up" % frame_id,
                        status=404, mimetype="text/plain")
    # a saved frame never changes, so browsers can keep it
    return send_file(path, mimetype="image/jpeg", max_age=3600)
