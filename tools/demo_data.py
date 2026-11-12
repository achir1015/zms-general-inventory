"""開發用：在開發資料庫（data/）建立示範公司與三個月的交易，方便看畫面與測試。

用法：.venv\\Scripts\\python tools\\demo_data.py   （帳號 admin／admin123；會清空開發資料庫）
"""
import datetime as dt
import os
import random
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from inv.biz import Biz  # noqa: E402
from inv.database import DB  # noqa: E402
from inv.dbserver import LocalDatabaseServer  # noqa: E402
from inv.settings import Settings  # noqa: E402

PRODUCTS = [("P001", "不鏽鋼保溫杯 500ml", "銀色", "個", 450, 380, 250, 30),
            ("P002", "A4 影印紙 80磅", "500張/包", "包", 135, 120, 92, 200),
            ("P003", "無線滑鼠", "黑色", "個", 590, 520, 330, 20),
            ("P004", "原子筆 0.5mm", "藍色 12支/盒", "盒", 120, 100, 62, 50),
            ("P005", "檔案夾 A4", "透明 10入", "包", 85, 72, 41, 60),
            ("P006", "桌上型計算機", "12位數", "台", 480, 420, 260, 10),
            ("P007", "釘書機", "10號", "個", 160, 140, 78, 15),
            ("P008", "便利貼 3x3", "黃色 5本", "組", 99, 85, 48, 40),
            ("S001", "到府安裝服務", "", "次", 800, 800, 0, 0)]


def main():
    st = Settings.load()
    srv = LocalDatabaseServer(st)
    srv.start()
    db = DB(st)
    c = db.connect(use_db=False)
    with c.cursor() as cur:
        cur.execute("DROP DATABASE IF EXISTS `%s`" % st.database)
    c.close()
    db.prepare()
    st.save()
    b = Biz(db)
    b.create_first_admin("admin", "林經理", "admin123")
    b.login("admin", "admin123")
    b.save_company(name="祥和貿易股份有限公司", short_name="祥和貿易", tax_id="12345675", owner="王大明",
                   phone="02-2700-1234", address="臺北市大安區和平東路二段 100 號", inventory_system="P",
                   doc_footer="匯款帳號：台灣銀行 大安分行 123-456-789012　戶名：祥和貿易股份有限公司")
    b.save_master("warehouses", dict(code="B", name="門市倉", active=1), True)
    b.save_master("bank_accounts", dict(code="B02", name="甲存帳戶", bank_name="台灣銀行 大安分行",
                                        account_no="123-456-789012", gl_account="1113", active=1), True)
    for code, name in (("E01", "吳業務"), ("E02", "黃採購"), ("E03", "周倉管")):
        b.save_master("employees", dict(code=code, name=name, active=1), True)
    vend = [("V001", "永興實業股份有限公司", "永興"), ("V002", "大同文具有限公司", "大同文具"),
            ("V003", "光明電子股份有限公司", "光明電子")]
    for code, name, short in vend:
        b.save_master("vendors", dict(code=code, name=name, short_name=short, closing_day=0, pay_days=30, active=1),
                      True)
    cust = [("C001", "大華商行有限公司", "大華商行", 25), ("C002", "新光科技股份有限公司", "新光科技", 0),
            ("C003", "仁愛國民小學", "仁愛國小", 0), ("C004", "美好生活事業有限公司", "美好生活", 20)]
    for code, name, short, cd in cust:
        b.save_master("customers", dict(code=code, name=name, short_name=short, closing_day=cd, pay_days=30,
                                        price_level=2 if code == "C001" else 1, salesman="E01", active=1), True)
    vmap = {"P001": "V001", "P003": "V003", "P006": "V003"}
    for code, name, spec, unit, p1, p2, cost, safety in PRODUCTS:
        b.save_master("products", dict(code=code, name=name, spec=spec, unit=unit, price=p1, price2=p2,
                                       std_cost=cost, safety_qty=safety, category="09" if code[0] == "S" else "01",
                                       vendor=vmap.get(code, "V002"), is_stock=0 if code[0] == "S" else 1, active=1),
                      True)
    random.seed(7)
    d0 = dt.date(2026, 8, 31)
    b.save_doc(None, dict(doc_type="OPEN", doc_date=d0, warehouse="A", memo="上線期初庫存"),
               [dict(product=p[0], qty=p[7] * 2 + 20, price=p[6]) for p in PRODUCTS if p[0][0] == "P"])
    b.save_doc(None, dict(doc_type="OPEN", doc_date=d0, warehouse="B", memo="上線期初庫存（門市）"),
               [dict(product=p[0], qty=10, price=p[6]) for p in PRODUCTS[:5]])
    b.save_doc(None, dict(doc_type="ARO", doc_date=d0, partner="C001", total=86500, memo="114/08 未收貨款"), [])
    b.save_doc(None, dict(doc_type="APO", doc_date=d0, partner="V001", total=42000, memo="114/08 未付貨款"), [])
    for month in (9, 10, 11):
        last = 30 if month in (9, 11) else 31
        if month == 11:
            last = 12
        for day in range(1, last + 1, 3):
            d = dt.date(2026, month, day)
            v = random.choice(vend)[0]
            items = random.sample([p for p in PRODUCTS if p[0][0] == "P" and vmap.get(p[0], "V002") == v] or
                                  [PRODUCTS[1]], k=1)
            po = b.save_doc(None, dict(doc_type="PO", doc_date=d, partner=v, employee="E02"),
                            [dict(product=p[0], qty=random.randint(20, 60), price=p[6]) for p in items])
            src = b.open_source_lines("PI", v)
            b.save_doc(None, dict(doc_type="PI", doc_date=d + dt.timedelta(days=1), partner=v, warehouse="A",
                                  invoice_no="AB%08d" % random.randint(1, 99999999)),
                       [dict(product=x["product"], qty=x["remain"], price=x["price"], src_line_id=x["id"])
                        for x in src if x["doc_id"] == po])
            for _ in range(2):
                cst = random.choice(cust)[0]
                prods = random.sample([p for p in PRODUCTS], k=3)
                lines = []
                for p in prods:
                    q = 1 if p[0][0] == "S" else random.randint(2, 12)
                    if p[0][0] == "P" and b.stock_qty(p[0], "A") < q:
                        continue
                    lines.append(dict(product=p[0], qty=q, price=b.suggest_price(p[0], "C", cst)))
                if lines:
                    b.save_doc(None, dict(doc_type="SI", doc_date=d + dt.timedelta(days=1), partner=cst, warehouse="A",
                                          employee="E01", invoice_no="ZX%08d" % random.randint(1, 99999999)), lines)
    # 退貨、調撥、報廢
    si = b.find_docs("SI", dt.date(2026, 10, 1), dt.date(2026, 10, 31))[-1]
    ln = b.doc(si["id"])["lines"][0]
    b.save_doc(None, dict(doc_type="SR", doc_date=dt.date(2026, 10, 20), partner=si["partner"], warehouse="A",
                          memo="外箱破損退回"), [dict(product=ln["product"], qty=1, price=ln["price"],
                                                    src_line_id=ln["id"])])
    b.save_doc(None, dict(doc_type="TR", doc_date=dt.date(2026, 9, 15), warehouse="A", warehouse2="B"),
               [dict(product="P002", qty=20), dict(product="P004", qty=10)])
    b.save_doc(None, dict(doc_type="SCR", doc_date=dt.date(2026, 10, 25), warehouse="A", reason="損壞"),
               [dict(product="P001", qty=2)])
    # 收款（含支票）、付款（開票）
    for cst in ("C001", "C002"):
        items = [i for i in b.open_items("C", cst) if i["doc_date"] < dt.date(2026, 10, 1)]
        tot = sum(i["remain"] for i in items)
        if tot > 0:
            note = (tot // 3).quantize(1)
            b.save_receipt("R", dict(r_date=dt.date(2026, 10, 10), partner=cst, bank=tot - note, bank_account="B01"),
                           [dict(doc_id=i["id"], amount=i["remain"]) for i in items],
                           notes=[dict(note_no="AK%07d" % random.randint(1, 9999999), bank="第一銀行", amount=note,
                                       due_date=dt.date(2026, 11, 25))])
    items = b.open_items("V", "V001")
    tot = sum(i["remain"] for i in items if i["doc_date"] < dt.date(2026, 10, 1))
    if tot > 0:
        b.save_receipt("P", dict(r_date=dt.date(2026, 10, 5), partner="V001", bank_account="B02"),
                       [dict(doc_id=i["id"], amount=i["remain"]) for i in items if i["doc_date"] < dt.date(2026, 10, 1)],
                       notes=[dict(note_no="CK0012345", amount=tot, due_date=dt.date(2026, 11, 20))])
    b.save_doc(None, dict(doc_type="SO", doc_date=dt.date(2026, 11, 10), partner="C003", due_date="115/11/20"),
               [dict(product="P002", qty=100, price=135), dict(product="P004", qty=30, price=120)])
    b.close_month("202608")
    b.close_month("202609")
    b.close_month("202610")
    print("ok：admin／admin123，", b.dashboard()["month_sales"])
    srv.stop()


if __name__ == "__main__":
    main()
