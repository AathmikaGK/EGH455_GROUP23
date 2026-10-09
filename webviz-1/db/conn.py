import config

try:
    import pymysql
    from pymysql.cursors import DictCursor
    have_pymysql = True
except ImportError:
    have_pymysql = False


def get_conn(as_root=False, use_db=True):
    # as_root is only for the init script, the app logs in as webviz
    if not have_pymysql:
        raise RuntimeError("install requirements.txt")

    user = config.DB_ROOT_USER if as_root else config.DB_USER
    password = config.DB_ROOT_PASS if as_root else config.DB_PASS

    args = {
        "host": config.DB_HOST,
        "port": config.DB_PORT,
        "user": user,
        "password": password,
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": True,
    }
    if use_db:
        args["database"] = config.DB_NAME
    return pymysql.connect(**args)


def db_is_up():
    # quick check so the app can fall back to memory instead of crashing
    if not config.USE_DB or not have_pymysql:
        return False
    try:
        c = get_conn()
        c.close()
        return True
    except Exception:
        return False
