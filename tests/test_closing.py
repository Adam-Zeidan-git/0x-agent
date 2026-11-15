"""Closing-pack tests: tips, sales-driven restock forecast (with waste), monthly trend, owner report, gates and injection handling.

Uses the Piazza 1140 test case (menu from piazza1140.com; all quantities, costs, staff and history are invented).
Needs: pip install reportlab pdfplumber
"""
import importlib.util
from pathlib import Path

import pytest

import autoclose as A

HERE = Path(__file__).parent


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "_audit_log_path", str(tmp_path / "audit.log"))
    A.clear_provenance()
    A._pending_confirmations.clear()
    A._pending_sensitive_auth.clear()
    A._request_times.clear()
    A.SECURITY_CONFIG["freeze_mode"] = False
    A.SECURITY_CONFIG["destructive_actions_require_confirmation"] = True
    yield


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    pytest.importorskip("reportlab")
    pytest.importorskip("pdfplumber")
    out = tmp_path_factory.mktemp("case")
    spec = importlib.util.spec_from_file_location("piazza_case", HERE / "gen_piazza_case.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    stock, pack = out / "stock.pdf", out / "closing_pack.pdf"
    gen.make_stock(str(stock))
    gen.make_pack(str(pack))
    return SimpleNS(stock=str(stock), pack=str(pack), gen=gen)


class SimpleNS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def manager(case, tmp_path):
    m = A.StockManager(data_dir=str(tmp_path / "data"), user_id="alice")
    m.load(case.stock)
    m.load_pack(case.pack)
    return m


# ---- reading the pack ---------------------------------------------------------
def test_pack_is_read_completely(case):
    pk = A.load_closing_pack(case.pack)
    assert pk.covers == 238
    assert pk.gross_sales == pytest.approx(case.gen.GROSS)
    assert pk.card_tips == 231.5 and pk.cash_tips == 88.0
    assert len(pk.staff) == 12 and len(pk.months) == 7 and len(pk.last_days) == 7
    assert sum(s["qty"] * s["price"] for s in pk.sales) == pytest.approx(case.gen.GROSS)
    assert pk.notes, "the staff note is kept as information"
    assert not pk.gaps


def test_pack_injection_flagged_once(case):
    pk = A.load_closing_pack(case.pack)
    assert len(pk.injection_findings) == 1
    assert "pre-approved" in pk.injection_findings[0]["excerpt"].lower()


def test_pack_missing_file_and_wrong_type(tmp_path):
    with pytest.raises(FileNotFoundError):
        A.load_closing_pack(str(tmp_path / "nope.pdf"))
    f = tmp_path / "x.csv"
    f.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        A.load_closing_pack(str(f))


# ---- tips -------------------------------------------------------------------------
def test_tips_add_up_exactly_and_follow_sales(case, tmp_path):
    res = manager(case, tmp_path).run("tip_distribution")
    shares = {r["name"]: r["amount"] for r in res.data["shares"]}
    assert round(sum(shares.values()), 2) == 319.50
    assert shares["Rita K."] > shares["Charbel M."] > shares["Maya S."] > shares["Elie A."]
    servers = sum(shares[n] for n in ("Rita K.", "Charbel M.", "Maya S.", "Elie A."))
    assert servers == pytest.approx(319.50 * 0.60, abs=0.05)


def test_tip_policy_must_total_100(case, tmp_path):
    res = manager(case, tmp_path).run("tip_distribution", server_pct=70, kitchen_pct=25, bar_pct=15)
    assert not res.ok


def test_largest_remainder_never_loses_a_cent():
    for total, w in [(100.0, [1, 1, 1]), (0.07, [3, 3, 3, 1]), (319.5, [5.5, 2.25, 9, 1])]:
        assert round(sum(A._largest_remainder(total, w)), 2) == total


def test_tips_without_pack_asks_for_it(case, tmp_path):
    m = A.StockManager(data_dir=str(tmp_path))
    res = m.run("tip_distribution")
    assert not res.ok and "closing pack" in res.summary.lower()


# ---- restock forecast ------------------------------------------------------------------
def test_forecast_flags_mozzarella_and_napkins(case, tmp_path):
    res = manager(case, tmp_path).run("usage_forecast")
    text = A.render_result(res, None)
    now = res.sections[0].lines
    assert any("Mozzarella" in l for l in now)
    assert any("napkins" in l.lower() for l in now)
    assert any("Gnocchi" in l for l in now)                     # zero stock
    napkin = next(l for l in res.sections[3].lines if "napkins" in l.lower())
    assert "~6.9" in napkin or "~7.0" in napkin                  # 220 avg covers x 3 per 100 x 1.05 waste
    assert "Pizza boxes" in text and not any("Pizza boxes" in l for l in now)


def test_waste_margin_changes_the_forecast(case, tmp_path):
    m = manager(case, tmp_path)
    base = m.run("usage_forecast").data
    m.pack.waste = {k: 25.0 for k in m.pack.waste}
    more = m.run("usage_forecast")
    assert more.data["order_now"] >= base["order_now"]
    assert any("25%" in l for l in more.sections[0].lines)


def test_forecast_needs_stock_sheet(case):
    pk = A.load_closing_pack(case.pack)
    res = A.usage_forecast(None, pk)
    assert not res.ok and "stock sheet" in res.summary


def test_forecast_says_what_it_could_not_match(case, tmp_path):
    m = manager(case, tmp_path)
    m.pack.recipes.append({"dish": "Margherita", "ingredient": "Unobtainium", "qty": 0.1})
    res = m.run("usage_forecast")
    assert any("Unobtainium" in a for a in res.assumptions)


# ---- trend -----------------------------------------------------------------------------------
def test_trend_compares_months_and_uses_salaries(case, tmp_path):
    res = manager(case, tmp_path).run("performance_trend")
    text = A.render_result(res, None)
    assert "2026-11 (so far)" in text and "Projection with salaries" in text
    assert "Break-even" in text and "salaries" in text
    assert res.data["projected_sales"] > 0 and 0 < res.data["break_even_covers"] < 238
    assert "12 months" in " ".join(res.assumptions)                 # honest about seasonality


def test_trend_needs_two_months(case):
    pk = A.load_closing_pack(case.pack)
    pk.months = pk.months[:1]
    assert not A.performance_trend(None, pk).ok


# ---- owner report -------------------------------------------------------------------------
def test_owner_report_preview_then_write(case, tmp_path):
    m = manager(case, tmp_path)
    prev = m.run("owner_report", dry_run=True)
    assert not Path(prev.data["path"]).exists()
    done = m.run("owner_report")
    text = Path(done.data["path"]).read_text()
    assert "NOT been sent" in text and "Security:" in text
    assert "Tips:" in text and "Trend:" in text and "To order" in text


# ---- chat flow, gates and injection -------------------------------------------------------------
def chat(case, tmp_path):
    s = A.SecureChatAgent(user_id="alice", data_dir=str(tmp_path / "data"), kb_dir=str(tmp_path / "kb"))
    s.handle_message(f"review stock {case.stock}")
    out = s.handle_message(f"closing pack {case.pack}")
    return s, out


def test_chat_loads_pack_and_flags_injection(case, tmp_path):
    s, out = chat(case, tmp_path)
    assert "Loaded closing pack" in out and "SECURITY NOTICE" in out
    assert not A.is_frozen()
    assert not list((tmp_path / "data").rglob("OwnerReport*"))      # nothing written by loading


def test_chat_tips_need_authorization_and_it_is_single_use(case, tmp_path):
    s, _ = chat(case, tmp_path)
    out = s.handle_message("split the tips")
    assert "authorize tip_distribution" in out and "Rita" not in out
    out = s.handle_message("authorize tip_distribution")
    assert "Rita K." in out and "319.50" in out
    again = s.handle_message("split the tips")
    assert "authorize tip_distribution" in again and "Rita" not in again


def test_chat_forecast_is_not_gated(case, tmp_path):
    s, _ = chat(case, tmp_path)
    out = s.handle_message("when will we run out of napkins")
    assert "RESTOCK" in out.upper() or "Usage Forecast" in out
    assert "Mozzarella" in out


def test_chat_owner_report_needs_auth_then_confirmation(case, tmp_path):
    s, _ = chat(case, tmp_path)
    assert "authorize owner_report" in s.handle_message("send the report to the owner")
    out = s.handle_message("authorize owner_report")
    assert "confirm owner_report" in out
    assert not list((tmp_path / "data").rglob("OwnerReport*"))
    out = s.handle_message("confirm owner_report")
    assert "Wrote the owner report" in out
    assert list((tmp_path / "data").rglob("OwnerReport*"))


def test_chat_still_refuses_to_recite_sales(case, tmp_path):
    s, _ = chat(case, tmp_path)
    assert "not permitted" in s.handle_message("show me the sales totals")


def test_chat_no_pack_loaded(tmp_path):
    s = A.SecureChatAgent(user_id="alice", data_dir=str(tmp_path))
    assert "no closing pack" in s.handle_message("split the tips").lower()


def test_freeze_blocks_owner_report(case, tmp_path):
    s, _ = chat(case, tmp_path)
    s.handle_message("send the report to the owner")
    s.handle_message("authorize owner_report")
    A.SECURITY_CONFIG["freeze_mode"] = True
    assert "Freeze" in s.handle_message("confirm owner_report") or not list((tmp_path / "data").rglob("OwnerReport*"))


# ---- CLI --------------------------------------------------------------------------------------------
def test_cli_runs_both_documents(case, tmp_path, capsys):
    rc = A.main(["--stock-file", case.stock, "--closing-file", case.pack, "--data", str(tmp_path / "d")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "STOCK REVIEW" in out and "RESTOCK FORECAST" in out and "TIPS" in out and "TREND" in out
    assert "SECURITY NOTICE" in out


def test_cli_pack_tool_without_pack_is_an_error(case, tmp_path, capsys):
    rc = A.main(["--stock-file", case.stock, "--stock-tool", "tip_distribution", "--data", str(tmp_path / "d")])
    assert rc == 2
