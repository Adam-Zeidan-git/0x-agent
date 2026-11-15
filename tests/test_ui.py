"""Smoke tests for the web interface (runs the real engine on the sample cases)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import autoclose_ui as ui

client = TestClient(ui.app)
SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def test_page_and_info():
    assert "Run 0x" in client.get("/").text
    info = client.get("/api/info").json()
    assert any(c["id"] == "piazza1140" for c in info["cases"])
    names = {t["name"] for t in info["tools"]}
    assert "full_stock_review" in names and "draft_purchase_orders" not in names


def test_sample_case_runs_and_flags_injection():
    r = client.post("/api/run", json={"case": "piazza1140"})
    assert r.status_code == 200
    d = r.json()
    assert len(d["security"]) >= 3 and d["issues"]
    assert "STOCK REVIEW" in d["report"]


def test_tip_split_total_is_exact():
    r = client.post("/api/run", json={"case": "piazza1140", "tool": "tip_distribution"})
    assert r.status_code == 200 and "319.50" in r.json()["report"]


def test_write_tool_is_refused():
    r = client.post("/api/run", json={"case": "piazza1140", "tool": "draft_purchase_orders"})
    assert r.status_code == 400


def test_upload_then_run():
    pdf = SAMPLES / "cafe_beirut" / "cafe_stock_2026-11-15.pdf"
    up = client.post("/api/upload", params={"name": pdf.name}, content=pdf.read_bytes())
    assert up.status_code == 200
    r = client.post("/api/run", json={"stock_token": up.json()["token"], "tool": "low_stock_report"})
    assert r.status_code == 200 and "Low Stock" in r.json()["report"]


def test_bad_upload_rejected():
    assert client.post("/api/upload", params={"name": "evil.exe"}, content=b"x").status_code == 400
