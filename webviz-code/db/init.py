import os
import sys

# lets the script run either as "python -m db.init" or "python db/init.py"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from db import conn as dbconn

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_FILE = os.path.join(HERE, "schema.sql")


def read_statements():
    # pymysql takes one statement at a time, so split the file on semicolons
    with open(SCHEMA_FILE, "r") as f:
        text = f.read()

    lines = []
    for line in text.splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    text = "\n".join(lines)

    parts = []
    for bit in text.split(";"):
        if bit.strip():
            parts.append(bit.strip())
    return parts


def build_database():
    print("connecting to mariadb on %s as %s" % (config.DB_HOST, config.DB_ROOT_USER))
    c = dbconn.get_conn(as_root=True, use_db=False)
    cur = c.cursor()

    for stmt in read_statements():
        first_line = stmt.splitlines()[0].strip()
        print("  ->", first_line[:70])
        cur.execute(stmt)

    cur.close()
    c.close()
    print("database '%s' is ready" % config.DB_NAME)


def show_tables():
    c = dbconn.get_conn()
    cur = c.cursor()
    cur.execute("SHOW TABLES")
    rows = cur.fetchall()
    print("tables now in %s:" % config.DB_NAME)
    for r in rows:
        name = list(r.values())[0]
        cur.execute("SELECT COUNT(*) AS n FROM %s" % name)
        n = cur.fetchone()["n"]
        print("   %-12s %d rows" % (name, n))
    cur.close()
    c.close()


if __name__ == "__main__":
    build_database()
    show_tables()
