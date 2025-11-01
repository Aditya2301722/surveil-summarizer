# src/app/main.py
from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime, timezone
import sqlite3
import os

# Database file path (created in project root)
DB_PATH = os.environ.get("REPORTS_DB", "reports.db")

app = FastAPI(title="Surveil Summarizer (dev)")

def get_conn():
    """
    Return a sqlite3 connection and ensure the 'reports' table exists.
    check_same_thread=False allows the connection object to be used from FastAPI worker threads.
    This simple pattern is fine for development; in production you'd use a proper DB pool.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            summary TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

# Single global connection for this simple tutorial
conn = get_conn()

class ReportIn(BaseModel):
    summary: str

@app.get("/health")
def health():
    """Health endpoint — quick check that the service is alive."""
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}

@app.post("/reports")
def add_report(item: ReportIn):
    """
    Add a short textual report. Example POST body: {"summary": "Two people at north gate"}.
    Returns: id, timestamp, and the saved summary.
    """
    ts = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute("INSERT INTO reports (ts, summary) VALUES (?, ?)", (ts, item.summary))
    conn.commit()
    return {"id": cur.lastrowid, "ts": ts, "summary": item.summary}

@app.get("/latest-report")
def latest_report():
    """Return the most recent saved report (or nulls if none exist)."""
    cur = conn.cursor()
    row = cur.execute("SELECT id, ts, summary FROM reports ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return {"id": None, "ts": None, "summary": None}
    return {"id": row[0], "ts": row[1], "summary": row[2]}

