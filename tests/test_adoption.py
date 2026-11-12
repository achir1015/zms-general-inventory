"""導入說明的範例（祥和貿易）必須真的能在系統跑出說明裡寫的數字，並能匯入會計系統且科目對得上。"""
import json
import os
import re
import sys
from decimal import Decimal

import pytest

from inv import adoption, example

ACCT = os.environ.get("ZMS_ACCT_SRC", r"E:\財務會計幫幫忙\zms-accounting")


def num(s):
    return Decimal(str(s).replace(",", "").strip() or "0")


def table(key, first_col=None):
    for b in adoption.BY_KEY[key]["blocks"]:
        if b[0] == "table" and (first_col is None or b[1][0] == first_col):
            return b[2]
    raise KeyError(key)


def test_opening_matches_manual(biz):
    b = biz
    example.build(b, upto="opening")
    rows = table("adopt_opening_data", "倉庫")
    total = num(rows[-1][4])
    assert sum(num(r[2]) * num(r[3]) for r in rows[:-1]) == total == b.inventory_value()
    chk = {r[0]: num(r[1]) for r in table("adopt_opening", "進銷存系統查詢")}
    bal_c = b.balances("C")
    bal_v = b.balances("V")
    assert sum(r["balance"] for r in bal_c) == chk["應收帳款：未沖帳款合計"]
    assert sum(r["notes"] for r in bal_c) == chk["應收帳款：在途票據"]
    assert sum(r["balance"] for r in bal_v) == chk["應付帳款：未沖帳款合計"]
    assert sum(r["notes"] for r in bal_v) == chk["應付帳款：在途票據"]
    assert b.gl_pending("2025-01-01", "2026-12-31") == {"note": 0, "stock": 0}     # 期初資料都不拋轉


def test_january_matches_manual(biz):
    b = biz
    ids = example.build(b)
    # 日常銷售／採購表的含稅金額
    for key in ("adopt_daily_sales", "adopt_daily_purchase"):
        for r in table(key):
            m = re.search(r"([A-Z]{2}\d{10})", r[1])
            if not m or not r[3][0].isdigit():
                continue
            no = m.group(1)
            if no.startswith(("RC", "PY")):
                rec = next(x for x in b.find_receipts(no[:2] == "RC" and "R" or "P", "2026-01-01", "2026-01-31")
                           if x["r_no"] == no)
                assert rec["applied"] + (rec["fee"] if no.startswith("PY") else 0) == num(r[3]), no
            else:
                assert b.doc_by_no(no)["total"] == num(r[3]), no
    # 月結表
    cost = {r["product"]: r for r in b.cost_month_rows("202601")}
    rows = table("adopt_monthly", "商品")
    for r in rows[:-1]:
        code = r[0].split()[0]
        assert cost[code]["sale_qty"] == num(r[1]) and cost[code]["unit_cost"] == num(r[2])
        assert cost[code]["sale_amt"] == num(r[3])
    assert sum(c["sale_amt"] for c in cost.values()) == num(rows[-1][3])
    # 拋轉傳票表：每一格的「科目 金額」都要在對應傳票上
    vs = b.gl_batch(ids["batch"])["data"]["vouchers"]
    gl = table("adopt_gl_example")
    assert "%d 張傳票" % len(vs) in adoption.BY_KEY["adopt_gl_example"]["blocks"][0][1]
    assert len(gl) == len(vs)
    pat = re.compile(r"(\d{4}) [^\d；（]+? ([\d,]+(?:\.\d+)?)")
    for r in gl:
        ref = r[0].split()[0]
        v = next(v for v in vs if v["ref"] == ref or ref in v["memo"])
        for col, side in ((2, "debit"), (3, "credit")):
            for acct, amt in pat.findall(r[col]):
                got = sum(Decimal(x[side]) for x in v["lines"] if x["account"] == acct)
                assert got == num(amt), (ref, acct, side, got, amt)
            assert sum(num(a) for _, a in pat.findall(r[col])) == sum(Decimal(x[side]) for x in v["lines"]), ref
    # 核對表（進銷存端）
    chk = {r[0]: num(r[1]) for r in table("adopt_gl_check", "進銷存系統查詢")}
    assert b.inventory_value() == chk["庫存查詢：庫存金額合計"]
    assert sum(r["balance"] for r in b.balances("C")) == chk["應收帳款：未沖帳款合計"]
    assert sum(r["notes"] for r in b.balances("C")) == chk["應收帳款：在途票據"]
    assert sum(r["balance"] for r in b.balances("V")) == chk["應付帳款：未沖帳款合計"]
    det = b.line_detail("S", "2026-01-01", "2026-01-31")
    assert sum(r["net"] for r in det) == chk["銷貨明細與毛利：未稅金額合計"]
    assert sum(r["cost"] for r in det) == chk["銷貨明細與毛利：成本合計"]
    _ = ids


@pytest.mark.skipif(not os.path.isdir(os.path.join(ACCT, "acct")), reason="沒有會計系統原始碼")
def test_january_in_accounting(biz, server):
    """1 月拋轉匯入會計系統（含開帳），核對表的會計科目餘額要與說明一致。"""
    sys.path.insert(0, ACCT)
    from acct.books import Books
    from acct.database import DB as ADB
    from acct.settings import Settings as ASettings
    st = ASettings(port=server.port, password=server.password, database="acct_adopt_test",
                   mariadb_bin=server.mariadb_bin, datadir=server.datadir)
    d = ADB(st)
    c = d.connect(use_db=False)
    with c.cursor() as cur:
        cur.execute("DROP DATABASE IF EXISTS acct_adopt_test")
    c.close()
    d.prepare()
    a = Books(d)
    a.create_first_admin("admin", "會計", "admin123")
    a.login("admin", "admin123")
    a.save_company(name="祥和貿易股份有限公司", tax_id="53212539", owner="", phone="", address="",
                   fiscal_start_month=1, auto_post=1, separate_approver=0)
    for k, code, name in (("C", "C001", "大成貿易"), ("C", "C002", "永信科技"), ("V", "V001", "永豐材料行"),
                          ("V", "V002", "全國物流")):
        a.save_master("customers" if k == "C" else "vendors", dict(code=code, name=name, active=1), True)
    # 會計系統開帳（只列與進銷存有關的科目，其餘以銀行存款平衡）
    lines = [dict(account="1211", debit=920000), dict(account="1141", debit=280000, partner="C001"),
             dict(account="1141", debit=180000, partner="C002"), dict(account="1131", debit=120000, partner="C001"),
             dict(account="2131", credit=250000, partner="V001"), dict(account="2131", credit=130000, partner="V002"),
             dict(account="2121", credit=150000, partner="V001"), dict(account="3111", credit=970000)]
    a.save_voucher(None, "115/01/01", "開帳", "期初開帳", lines)
    ids = example.build(biz)
    batch = json.loads(json.dumps(biz.gl_batch(ids["batch"])["data"]))
    res = a.import_gl_batch(batch)
    assert res["count"] == 14

    def bal(*accts):
        return a.db.value("SELECT SUM(debit-credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE "
                          "v.status=2 AND l.account IN (%s)" % ",".join("'%s'" % x for x in accts)) or Decimal(0)
    chk = {r[2].split()[0]: num(r[3]) for r in table("adopt_gl_check", "進銷存系統查詢")}
    assert bal("1211") == chk["1211"]
    assert bal("1141") == chk["1141"]
    assert bal("1131") == chk["1131"]
    assert -bal("2131") == chk["2131"]
    assert -bal("2121") == chk["2121"]
    assert -bal("4111", "4112") == chk["4111"]
    assert bal("5111") == chk["5111"]
    d.close()


def test_spoken_text():
    for s in adoption.SECTIONS:
        t = adoption.spoken(s)
        assert t.startswith(s["title"]) and len(t) > 60


def test_example_periodic(biz):
    """定期盤存制：期初月份不產生分錄；1 月銷貨成本＝進貨－進退－存貨增加＝永續制的成本＋報廢＋盤虧＋領用。"""
    b = biz
    b.save_company(inventory_system="D")
    orig = b.save_company

    def keep_d(**kw):
        kw["inventory_system"] = "D"
        return orig(**kw)
    b.save_company = keep_d
    ids = example.build(b)
    v = next(v for v in b.gl_batch(ids["batch"])["data"]["vouchers"] if v["ref"] == "COST202601")
    amt = {(x["account"], "D" if Decimal(x["debit"]) else "C"): Decimal(x["debit"]) or Decimal(x["credit"])
           for x in v["lines"]}
    assert amt[("5111", "D")] == Decimal("178650.00")
    assert amt[("5112", "C")] == Decimal("225000.00") and amt[("5113", "D")] == Decimal("4500.00")
    assert amt[("1211", "D")] == Decimal("41850.00")
    pi = next(v for v in b.gl_batch(ids["batch"])["data"]["vouchers"] if v["ref"].startswith("PI"))
    assert any(x["account"] == "5112" for x in pi["lines"])
