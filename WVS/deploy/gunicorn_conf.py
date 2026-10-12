# gunicorn settings for the pi

bind = "127.0.0.1:8000"
workers = 1                 # one on purpose, a second means a second writer
worker_class = "gthread"    # the stream and the video hold a request open
threads = 16

timeout = 0                 # a stream stays open, so no request timeout
graceful_timeout = 30
keepalive = 5

accesslog = "-"
errorlog = "-"
loglevel = "info"
proc_name = "wvs"
