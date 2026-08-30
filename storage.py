import sqlite3

def init_db():
    conn = sqlite3.connect("jobs.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seen_jobs (
            id TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            url TEXT,
            first_seen TEXT
        )
    """)
    conn.commit()
    return conn

def has_seen(conn, job_id):
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM seen_jobs WHERE id = ?", (job_id,))
    return cursor.fetchone() is not None

def mark_seen(conn, job):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO seen_jobs (id, title, company, url, first_seen)
        VALUES (?, ?, ?, ?, datetime('now'))
    """, (job["id"], job["title"], job["company"], job["url"]))
    conn.commit()

if __name__ == "__main__":
    conn = init_db()
    test_job = {"id": "TEST-999", "title": "Test Job", "company": "TestCo", "url": "http://test.com"}

    print("Seen before insert:", has_seen(conn, "TEST-999"))
    mark_seen(conn, test_job)
    print("Seen after insert:", has_seen(conn, "TEST-999"))