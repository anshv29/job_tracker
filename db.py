import os

import psycopg2
from dotenv import load_dotenv

from ats import detect_ats

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

_conn = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS applications (
    id BIGSERIAL PRIMARY KEY,
    job_key TEXT NOT NULL UNIQUE,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    ats TEXT NOT NULL DEFAULT 'other'
        CHECK (ats IN ('greenhouse', 'lever', 'workday', 'successfactors', 'other')),
    location TEXT,
    source TEXT,
    fit_reason TEXT,
    grad_restriction TEXT
        CHECK (grad_restriction IS NULL OR grad_restriction IN ('none', 'specific', 'unclear')),
    status TEXT NOT NULL DEFAULT 'found'
        CHECK (status IN ('found', 'filtered_out', 'eligible', 'needs_review', 'submitted', 'failed')),
    status_reason TEXT,
    draft_answer TEXT,
    found_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at TIMESTAMPTZ,
    screenshot_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications (status);
CREATE INDEX IF NOT EXISTS idx_applications_applied_at ON applications (applied_at);
"""

# Columns update_application() is allowed to change. A fixed list means a typo
# or a bad caller can never turn into arbitrary SQL.
UPDATABLE_COLUMNS = {
    "status", "status_reason", "draft_answer", "fit_reason",
    "grad_restriction", "applied_at", "screenshot_path", "ats",
}


def get_connection():
    """Returns a cached connection, or None if the database can't be reached.

    Never raises: the scraper must still send its alert emails when Supabase
    is down, so callers just check for None and carry on.
    """
    global _conn
    if _conn is not None and not _conn.closed:
        return _conn

    if not DATABASE_URL:
        print("Warning: DATABASE_URL is not set, skipping database writes")
        return None

    try:
        _conn = psycopg2.connect(
            DATABASE_URL,
            # Short timeouts so a dead database costs seconds, not the 10 minute
            # workflow timeout that the hourly scheduler depends on.
            connect_timeout=5,
            options="-c statement_timeout=5000",
        )
        _conn.autocommit = True
        return _conn
    except Exception as e:
        print(f"Warning: could not connect to database: {e}")
        _conn = None
        return None


def init_schema(conn):
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)


def insert_application(conn, job, source, ats, status="found", status_reason=None,
                       fit_reason=None, grad_restriction=None):
    """Inserts one job. Returns True if a new row was added, False otherwise.

    ON CONFLICT DO NOTHING is what makes hourly reruns safe: the same job_key
    can be offered again and again and only the first insert sticks.
    Never raises, for the same reason get_connection() never raises.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO applications
                    (job_key, company, title, url, ats, location, source,
                     status, status_reason, fit_reason, grad_restriction)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (job_key) DO NOTHING
                """,
                (
                    job["id"], job["company"], job["title"], job["url"], ats,
                    job.get("location"), source, status, status_reason,
                    fit_reason, grad_restriction,
                ),
            )
            return cur.rowcount == 1
    except Exception as e:
        print(f"Warning: could not insert application {job.get('id')}: {e}")
        return False


def save_job(job, source, **extra):
    """One call for the connectors: connect, detect the ATS, insert.

    Every connector needs these same three steps, so they live here once.
    A missing connection just means the row isn't saved, the email still goes.
    """
    conn = get_connection()
    if conn is None:
        return False
    return insert_application(conn, job, source=source, ats=detect_ats(job["url"]), **extra)


def update_application(conn, job_key, **fields):
    bad = set(fields) - UPDATABLE_COLUMNS
    if bad:
        raise ValueError(f"Cannot update columns: {sorted(bad)}")
    if not fields:
        return

    assignments = ", ".join(f"{col} = %s" for col in fields)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE applications SET {assignments} WHERE job_key = %s",
            (*fields.values(), job_key),
        )


def fetch_by_status(conn, status, limit=None):
    sql = "SELECT * FROM applications WHERE status = %s ORDER BY found_at ASC"
    params = [status]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [c.name for c in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_by_job_key(conn, job_key):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM applications WHERE job_key = %s", (job_key,))
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip([c.name for c in cur.description], row))


def delete_application(conn, job_key):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM applications WHERE job_key = %s", (job_key,))


if __name__ == "__main__":
    # Real round trip against the live database: this is the Phase 1 test.
    conn = get_connection()
    if conn is None:
        raise SystemExit("Could not connect, check DATABASE_URL in .env")

    init_schema(conn)
    print("Schema ready")

    test_job = {
        "id": "smoketest-000",
        "title": "Smoke Test Intern",
        "company": "TestCo",
        "url": "https://boards.greenhouse.io/testco/jobs/1",
        "location": "Remote",
    }

    delete_application(conn, test_job["id"])  # clean slate if a past run died midway

    print("Insert new row:", insert_application(conn, test_job, source="smoketest", ats="greenhouse"))
    print("Insert same job_key again (should be False):",
          insert_application(conn, test_job, source="smoketest", ats="greenhouse"))
    print("Read back:", get_by_job_key(conn, test_job["id"]))

    delete_application(conn, test_job["id"])
    print("After delete (should be None):", get_by_job_key(conn, test_job["id"]))
