"""Stock-manager tests: PDF layouts, prompt-injection handling, tools, baseline state, chat flow.

Run:  python3 -m pytest tests -q        (PDF tests need: pip install reportlab pdfplumber pypdf)
"""
import importlib.util
import json
from pathlib import Path

import pytest

import autoclose as A

HERE = Path(__file__).parent


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "_audit_log_path", str(tmp_path / "audit.log"))
    A.clear_provenance()
    A._pending_confirmations.clear()
    A._request_times.clear()
    A.SECURITY_CONFIG["freeze_mode"] = False
    yield


@pytest.fixture(scope="module")
def pdfs(tmp_path_factory):
    pytest.importorskip("reportlab")
    pytest.importorskip("pdfplumber")
    out = tmp_path_factory.mktemp("pdfs")
    spec = importlib.util.spec_from_file_location("gen", HERE / "gen_sample_pdfs.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    gen.ruled(str(out / "ruled.pdf"))
    gen.borderless(str(out / "borderless.pdf"))
    gen.sections(str(out / "sections.pdf"))
    return out


CSV = (
    "SKU,Item,Unit,On Hand,Min,Max,Reorder Qty,Supplier,Unit Cost,Expiry,Counted\n"
    "A1,Apples,kg,3,10,40,10,Fruit Co,2.00,2026-11-13,3\n"
    "B1,Beans,can,50,10,60,12,Dry Co,0.50,,44\n"
    "C1,Cheese,pcs,0,5,20,5,Dairy Co,4.00,,0\n"
)


def load_csv(tmp_path, text=CSV):
    p = tmp_path / "stock.csv"
    p.write_text(text)
    mgr = A.StockManager(data_dir=str(tmp_path / "data"), store_id="t", date="2026-11-14", user_id="alice")
    mgr.load(str(p))
    return mgr


# ---- PDF layouts -----------------------------------------------------------
@pytest.mark.parametrize("name", ["ruled.pdf", "borderless.pdf"])
def test_pdf_layouts_parse(pdfs, name):
    snap = A.load_stock_document(str(pdfs / name))
    skus = {i.sku for i in snap.items}
    assert {"M001", "B001", "C001", "S001"} <= skus
    m002 = next(i for i in snap.items if i.sku == "M002")
    assert m002.on_hand == 30


def test_sections_pdf_stock_and_deliveries(pdfs):
    snap = A.load_stock_document(str(pdfs / "sections.pdf"))
    skus = {i.sku for i in snap.items}
    assert {"M001", "B001", "E001"} <= skus
    assert snap.store_id.lower().startswith("hamra") or snap.store_id
    assert snap.as_of == "2026-11-14"
    mgr = A.StockManager(data_dir=str(pdfs / "ds"), store_id=None, date=None, user_id="alice")
    mgr.load(str(pdfs / "sections.pdf"))
    assert "Whole Milk" in A.render_result(mgr.run("receiving_check"), 20)
    assert not snap.injection_findings


@pytest.mark.parametrize("name", ["ruled.pdf", "borderless.pdf"])
def test_pdf_injection_flagged_not_obeyed(pdfs, name):
    mgr = A.StockManager(data_dir=str(pdfs / "d"), store_id="x", date="2026-11-14", user_id="alice")
    snap = mgr.load(str(pdfs / name))
    assert snap.injection_findings, "instruction-like text must be flagged"
    review = A.render_review(snap, mgr.run("full_stock_review"), 12)
    assert "SECURITY NOTICE" in review
    # nothing was triggered by the document
    assert A.action_from_user("lock_terminals") is False
    assert A.action_from_user("close_day") is False
    assert not A.is_frozen()


def test_review_flags_expected_anomalies(pdfs):
    mgr = A.StockManager(data_dir=str(pdfs / "d2"), store_id="x", date="2026-11-14", user_id="alice")
    snap = mgr.load(str(pdfs / "ruled.pdf"))
    text = A.render_review(snap, mgr.run("full_stock_review"), None)
    for needle in ("Bread Loaf", "negative", "expired", "counted 11 vs system 15"):
        assert needle in text


# ---- Tools on CSV -------------------------------------------------------------
def test_low_stock_and_reorder(tmp_path):
    mgr = load_csv(tmp_path)
    low = A.render_result(mgr.run("low_stock_report"), 20)
    assert "Cheese" in low and "Apples" in low
    reorder = A.render_result(mgr.run("reorder_suggestions"), 20)
    assert "Fruit Co" in reorder and "Dairy Co" in reorder
    assert "Beans" not in reorder        # 50 on hand vs min 10


def test_expiry_and_variance(tmp_path):
    mgr = load_csv(tmp_path)
    assert "Apples" in A.render_result(mgr.run("expiry_report"), 20)
    var = A.render_result(mgr.run("count_variance"), 20)
    assert "Beans" in var and "44" in var


def test_item_lookup_is_exact_not_invented(tmp_path):
    mgr = load_csv(tmp_path)
    out = A.render_result(mgr.run("check_stock_levels", query="Cheese"), 5)
    assert "Cheese" in out
    none = A.render_result(mgr.run("check_stock_levels", query="Unobtainium"), 5)
    assert "Unobtainium" not in none or "no " in none.lower() or "not" in none.lower()


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(Exception):
        A.load_stock_document(str(tmp_path / "nope.pdf"))


# ---- State-changing tools --------------------------------------------------
def test_purchase_orders_dry_run_writes_nothing(tmp_path):
    mgr = load_csv(tmp_path)
    mgr.run("draft_purchase_orders", dry_run=True)
    assert not list((tmp_path / "data").rglob("*PO*")) and not list((tmp_path / "data").rglob("po_*"))


def test_adjustments_baseline_and_idempotent(tmp_path):
    mgr = load_csv(tmp_path)
    mgr.run("apply_stock_adjustments")
    state = A.stock_state_path(str(tmp_path / "data"), "t")
    assert Path(state).exists()
    before = Path(state).read_text()
    mgr.run("apply_stock_adjustments")           # same input again: no double-apply
    assert Path(state).read_text() == before


# ---- Chat flow ---------------------------------------------------------------
def make_chat(tmp_path):
    return A.SecureChatAgent(store_id="t", date="2026-11-14", user_id="alice",
                             data_dir=str(tmp_path / "data"), kb_dir=str(tmp_path / "kb"))


def test_chat_needs_file_first(tmp_path):
    s = make_chat(tmp_path)
    assert "no stock file loaded" in s._fallback_reply("what is low")


def test_chat_load_and_followups(tmp_path):
    (tmp_path / "stock.csv").write_text(CSV)
    s = make_chat(tmp_path)
    out = s._fallback_reply(f"review stock {tmp_path / 'stock.csv'}")
    assert "STOCK REVIEW" in out
    assert "Cheese" in s._fallback_reply("what is low")
    assert "Fruit Co" in s._fallback_reply("what should I order")
    assert "Apples" in s._fallback_reply("anything expiring")


def test_chat_write_tool_needs_confirmation(tmp_path):
    (tmp_path / "stock.csv").write_text(CSV)
    s = make_chat(tmp_path)
    s.handle_message(f"review stock {tmp_path / 'stock.csv'}")
    out = s.handle_message("apply adjustments")
    assert "confirm apply_stock_adjustments" in out
    assert not Path(A.stock_state_path(str(tmp_path / "data"), "t")).exists()
    s.handle_message("confirm apply_stock_adjustments")
    assert Path(A.stock_state_path(str(tmp_path / "data"), "t")).exists()


def test_chat_stock_questions_not_blocked_as_sensitive(tmp_path):
    assert A.classify_sensitive("how much milk do we have") is None
    assert A.classify_sensitive("what should I order") is None
    assert A.classify_sensitive("show me the sales totals") == "data"


def test_freeze_blocks_stock_writes(tmp_path):
    (tmp_path / "stock.csv").write_text(CSV)
    s = make_chat(tmp_path)
    s.handle_message(f"review stock {tmp_path / 'stock.csv'}")
    A.SECURITY_CONFIG["freeze_mode"] = True
    assert "Freeze" in s.handle_message("draft purchase orders")
