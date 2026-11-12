"""完整流程：期初 → 採購進貨 → 訂單銷貨 → 銷退 → 收付款與票據 → 盤點 → 報廢 → 月結 → 拋轉傳票。"""
import datetime as dt
import json
from decimal import Decimal as D

import pytest

from inv.core import BizError

SEP = dt.date(2026, 9, 1)


def d(day, m=9):
    return dt.date(2026, m, day)


def setup_masters(b):
    b.save_company(name="測試貿易股份有限公司", tax_id="12345675", inventory_system="P")
    b.save_master("products", dict(code="A", name="商品甲", unit="個", price=200, price2=180, safety_qty=50,
                                   is_stock=1, active=1), True)
    b.save_master("products", dict(code="B", name="商品乙", unit="箱", price=500, is_stock=1, active=1), True)
    b.save_master("products", dict(code="S", name="安裝服務", unit="次", price=1000, is_stock=0, active=1), True)
    b.save_master("customers", dict(code="C1", name="大華商行", short_name="大華", tax_id="", closing_day=25,
                                    pay_days=30, price_level=1, active=1), True)
    b.save_master("vendors", dict(code="V1", name="永興實業", short_name="永興", active=1), True)
    b.save_master("warehouses", dict(code="B", name="門市倉", active=1), True)


def test_full_flow(biz):
    b = biz
    setup_masters(b)
    # 期初庫存 A 10 個 @100
    b.save_doc(None, dict(doc_type="OPEN", doc_date=d(1), warehouse="A"), [dict(product="A", qty=10, price=100)])
    assert b.stock_qty("A", "A") == 10
    # 採購 → 進貨（帶單）
    po = b.save_doc(None, dict(doc_type="PO", doc_date=d(2), partner="V1"), [dict(product="A", qty=20, price=110)])
    src = b.open_source_lines("PI", "V1")
    assert len(src) == 1 and src[0]["remain"] == 20
    pi = b.save_doc(None, dict(doc_type="PI", doc_date=d(3), partner="V1", warehouse="A", tax_type=1,
                               invoice_no="AB12345678"),
                    [dict(product="A", qty=20, price=110, src_line_id=src[0]["id"])])
    h = b.doc(pi)
    assert (h["amount"], h["tax"], h["total"]) == (D("2200.00"), D("110.00"), D("2310.00"))
    assert b.tracking("PO") == []                       # 採購單已全部進貨
    with pytest.raises(BizError):                       # 超量轉單
        b.save_doc(None, dict(doc_type="PI", doc_date=d(3), partner="V1"),
                   [dict(product="A", qty=1, price=110, src_line_id=src[0]["id"])])
    # 訂單 → 銷貨（含勞務）
    so = b.save_doc(None, dict(doc_type="SO", doc_date=d(4), partner="C1"),
                    [dict(product="A", qty=15, price=200), dict(product="S", qty=1, price=1000)])
    sl = b.open_source_lines("SI", "C1")
    si = b.save_doc(None, dict(doc_type="SI", doc_date=d(5), partner="C1", warehouse="A", tax_type=1),
                    [dict(product=x["product"], qty=x["remain"], price=x["price"], src_line_id=x["id"]) for x in sl])
    h = b.doc(si)
    assert h["total"] == D("4200.00")                   # (3000+1000)×1.05
    assert b.stock_qty("A") == 15
    # 庫存不足
    with pytest.raises(BizError, match="庫存不足"):
        b.save_doc(None, dict(doc_type="SI", doc_date=d(5), partner="C1"), [dict(product="A", qty=100, price=200)])
    # 銷退 2 個（帶原銷貨單）
    sil = [ln for ln in b.doc(si)["lines"] if ln["product"] == "A"][0]
    sr = b.save_doc(None, dict(doc_type="SR", doc_date=d(6), partner="C1", warehouse="A"),
                    [dict(product="A", qty=2, price=200, src_line_id=sil["id"])])
    assert b.doc(sr)["total"] == D("420.00")
    assert b.stock_qty("A") == 17
    # 調撥 5 個到門市倉
    b.save_doc(None, dict(doc_type="TR", doc_date=d(7), warehouse="A", warehouse2="B"), [dict(product="A", qty=5)])
    assert b.stock_qty("A", "A") == 12 and b.stock_qty("A", "B") == 5
    # 收款：銀行 2,000＋支票 1,780＝3,780（4,200－420）
    items = b.open_items("C", "C1")
    assert sum(i["remain"] for i in items) == D("3780.00")
    applies = [dict(doc_id=i, amount=a) for i, a in b.auto_apply("C", "C1", D("3780"))]
    with pytest.raises(BizError, match="不平衡"):
        b.save_receipt("R", dict(r_date=d(10), partner="C1", bank=2000, bank_account="B01"), applies)
    rc = b.save_receipt("R", dict(r_date=d(10), partner="C1", bank=1985, fee=15, bank_account="B01"), applies,
                        notes=[dict(note_no="AA0001", bank="台灣銀行", amount=1780, due_date=d(30, 10))])
    assert b.open_items("C", "C1") == []
    # 付款：開票 2,310
    py = b.save_receipt("P", dict(r_date=d(12), partner="V1", bank_account="B01"),
                        [dict(doc_id=pi, amount=2310)],
                        notes=[dict(note_no="CK0001", amount=2310, due_date=d(15, 10))])
    with pytest.raises(BizError):
        b.void_doc(pi)                                  # 已沖帳不能作廢
    # 票據：應收託收 → 兌現；應付兌現
    rn = b.find_notes("R")[0]
    b.note_event([rn["id"]], "collect", d(20), bank_account="B01")
    done, errs = b.note_event([rn["id"]], "clear", d(28))
    assert done and not errs
    pn = b.find_notes("P")[0]
    b.note_event([pn["id"]], "pay", d(29))
    # 盤點：A 倉帳面 12，實盤 11
    cnt = b.create_count("A", d(25))
    lines = b.doc(cnt)["lines"]
    assert lines[0]["book_qty"] == 12
    b.save_doc(cnt, b.doc(cnt), [dict(product=ln["product"], book_qty=ln["book_qty"], count_qty=11) for ln in lines])
    adj = b.count_to_adjust(cnt)
    assert b.doc(adj)["lines"][0]["qty"] == -1
    assert b.stock_qty("A", "A") == 11
    # 報廢 1 個
    b.save_doc(None, dict(doc_type="SCR", doc_date=d(26), warehouse="B", reason="損壞"), [dict(product="A", qty=1)])
    assert b.stock_qty("A") == 15
    # 月結 9 月：單位成本＝(1,000＋2,200)÷30＝106.6667
    assert b.cost_status()["next"] == "202609"
    b.close_month("202609")
    row = b.cost_month_rows("202609")[0]
    assert row["unit_cost"] == D("106.6667")
    assert row["sale_qty"] == 13 and row["close_qty"] == 15
    assert row["open_amt"] + row["in_amt"] - row["sale_amt"] - row["other_amt"] == row["close_amt"]
    with pytest.raises(BizError, match="月結"):
        b.save_doc(None, dict(doc_type="SCR", doc_date=d(27), warehouse="A"), [dict(product="A", qty=1)])
    # 拋轉傳票
    vouchers, sources = b.gl_preview(d(1), d(30))
    for v in vouchers:
        assert sum(x["debit"] for x in v["lines"]) == sum(x["credit"] for x in v["lines"]) > 0
    refs = {v["ref"] for v in vouchers}
    assert "COST202609" in refs and b.doc(si)["doc_no"] in refs
    cost_v = next(v for v in vouchers if v["ref"] == "COST202609")
    cogs = sum(x["debit"] for x in cost_v["lines"] if x["account"] == "5111")
    assert cogs == row["sale_amt"]
    bid = b.create_gl_batch(d(1), d(30))
    batch = b.gl_batch(bid)
    data = json.loads(json.dumps(batch["data"]))
    assert data["format"] == "zms-gl" and data["company"]["tax_id"] == "12345675"
    accounts = {a["code"] for a in data["accounts"]}
    assert {"1141", "4111", "2161", "1211", "1161", "2131", "5111", "1131", "2121", "1113", "6233"} <= accounts
    with pytest.raises(BizError, match="拋轉"):
        b.void_doc(sr)
    assert b.gl_pending(d(1), d(30)) == {"note": 0, "stock": 0}
    b.cancel_gl_batch(bid)
    assert b.gl_pending(d(1), d(30))["sales"] == 2
    # 每日彙總模式
    v2, _ = b.gl_preview(d(1), d(30), mode="day")
    assert len(v2) <= len(vouchers) and all(x["ref"].isupper() or "-" in x["ref"] for x in v2)
    # 報表
    assert b.ranking("product", "S", d(1), d(30))[0]["k"] in ("A", "S")
    card = b.stock_card("A", d(1), d(30))
    assert card["closing"] == 15
    assert b.statement("C", "C1", d(1), d(30))["closing"] == 0
    assert b.dashboard()["month_sales"] is not None
    b.reopen_month("202609")
    assert b.closed_ym() == ""


def test_bounce_and_endorse(biz):
    b = biz
    setup_masters(b)
    b.save_doc(None, dict(doc_type="ARO", doc_date=d(1), partner="C1", total=5000), [])
    b.save_doc(None, dict(doc_type="APO", doc_date=d(1), partner="V1", total=3000), [])
    b.save_receipt("R", dict(r_date=d(2), partner="C1"), [dict(doc_id=b.open_items("C", "C1")[0]["id"], amount=5000)],
                   notes=[dict(note_no="N1", amount=3000, due_date=d(30)), dict(note_no="N2", amount=2000,
                                                                                due_date=d(30))])
    n1, n2 = b.find_notes("R")
    # 轉付 N1 給廠商
    b.save_receipt("P", dict(r_date=d(3), partner="V1"), [dict(doc_id=b.open_items("V", "V1")[0]["id"], amount=3000)],
                   endorse=[n1["id"]])
    assert b.find_notes("R", status=5)[0]["note_no"] == "N1"
    # N2 退票 → 重新應收 2,000
    b.note_event([n2["id"]], "bounce", d(10))
    assert sum(i["remain"] for i in b.open_items("C", "C1")) == 2000
    v, _ = b.gl_preview(d(1), d(30), scopes=["note", "payment"])
    assert any("退票" in x["memo"] for x in v)
    pay = next(x for x in v if x["ref"].startswith("PY"))
    assert any(ln["account"] == "1131" and ln["credit"] == 3000 for ln in pay["lines"])
    b.undo_note_event(n2["id"])
    assert sum(i["remain"] for i in b.open_items("C", "C1")) == 0
    # 預收：多收 500
    si = b.save_doc(None, dict(doc_type="SI", doc_date=d(5), partner="C1"), [dict(product="S", qty=1, price=1000)])
    b.save_receipt("R", dict(r_date=d(6), partner="C1", cash=1550), [dict(doc_id=si, amount=1050)],
                   ) if False else None
    rid = b.save_receipt("R", dict(r_date=d(6), partner="C1", cash=1550, to_advance=500),
                         [dict(doc_id=si, amount=1050)])
    assert b.advance_balance("R", "C1") == 500
    b.void_receipt(rid)
    assert b.advance_balance("R", "C1") == 0


def test_permissions(biz):
    b = biz
    setup_masters(b)
    b.save_user("sales", "業務小王", "業務人員", False, True, None or __import__("inv.seed", fromlist=["ROLES"]).ROLES[
        "業務人員"], pw="sales123", is_new=True)
    b.logout()
    b.login("sales", "sales123")
    with pytest.raises(BizError, match="權限"):
        b.save_doc(None, dict(doc_type="PI", doc_date=d(3), partner="V1"), [dict(product="A", qty=1, price=1)])
    assert b.master_rows("products")[0]["avg_cost"] is None      # 看不到成本
    b.save_doc(None, dict(doc_type="QT", doc_date=d(3), partner="C1"), [dict(product="A", qty=1, price=200)])
