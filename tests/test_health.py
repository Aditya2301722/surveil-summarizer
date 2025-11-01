# tests/test_health.py
import sqlite3
import pytest
from fastapi.testclient import TestClient
import src.app.main as main  # imports your FastAPI app

@pytest.fixture(autouse=True)
def use_in_memory_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            summary TEXT NOT NULL
        )
    """)
    conn.commit()
    main.conn = conn
    yield
    conn.close()

@pytest.fixture
def client():
    return TestClient(main.app)

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    payload = r.json()
    assert payload.get("status") == "ok"
    assert "time" in payload

def test_reports_flow(client):
    sample = "pytest: sample report"
    p = client.post("/reports", json={"summary": sample})
    assert p.status_code == 200
    data = p.json()
    assert "id" in data and data["summary"] == sample
    latest = client.get("/latest-report")
    assert latest.status_code == 200
    assert latest.json()["summary"] == sample
