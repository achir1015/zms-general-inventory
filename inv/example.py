"""導入說明的範例公司「祥和貿易」：期初資料與 115 年 1 月的交易。

說明手冊裡的數字（期初庫存、單據金額、拋轉傳票）都由這裡實際跑出來，tests/test_adoption.py 會核對兩邊一致。
期初金額與「資料助秘之一般公司會計」導入說明的期初餘額表相同（存貨 920,000、應收 C001 280,000、C002 180,000、
應收票據 120,000、應付 V001 250,000、V002 130,000、應付票據 150,000）。
"""
import datetime as dt

OPEN_DATE = dt.date(2025, 12, 31)          # 114/12/31


def D(m, d):
    return dt.date(2026, m, d)             # 115 年


PRODUCTS = [  # 編號, 品名, 規格, 單位, 售價, 批發價, 標準進價, 安全存量, 主要供應商
    ("P001", "A4 影印紙 80磅", "5包/箱", "箱", 620, 560, 450, 150, "V001"),
    ("P002", "多功能事務機", "彩色雷射", "台", 18000, 16500, 12000, 5, "V003"),
    ("P003", "碳粉匣", "黑色 高容量", "個", 2600, 2400, 1800, 30, "V003"),
    ("P004", "人體工學辦公椅", "網背 灰色", "張", 3900, 3500, 2500, 10, "V001"),
    ("P005", "四層公文櫃", "鋼製 A4", "座", 4800, 4400, 3250, 5, "V001"),
    ("P006", "原子筆", "藍 50支/盒", "盒", 120, 100, 65, 200, "V001"),
    ("S001", "到府安裝服務", "", "次", 1500, 1500, 0, 0, ""),
]
CUSTOMERS = [  # 代號, 名稱, 簡稱, 統編, 結帳日, 收款天數, 價格等級
    ("C001", "大成貿易股份有限公司", "大成貿易", "12345675", 25, 30, 2),
    ("C002", "永信科技有限公司", "永信科技", "24567892", 0, 30, 1),
    ("C003", "和平國民小學", "和平國小", "", 0, 30, 1),
]
VENDORS = [
    ("V001", "永豐材料行", "永豐材料", 0, 30),
    ("V002", "全國物流股份有限公司", "全國物流", 0, 30),
    ("V003", "光華事務機器股份有限公司", "光華事務機", 0, 60),
]
# 期初庫存：倉庫 → [(商品, 數量, 單位成本)]
OPENING_STOCK = {
    "A": [("P001", 500, 450), ("P002", 20, 12000), ("P003", 100, 1800), ("P004", 40, 2500), ("P005", 20, 3250),
          ("P006", 800, 65)],
    "B": [("P001", 100, 450), ("P006", 200, 65)],
}
# 期初應收／應付（未收未付的單據）
OPENING_AR = [("C001", 280000, "114/12 出貨未收（發票 ZX12345601～05）"), ("C001", 120000, "已收支票 AK1234567 未兌現"),
              ("C002", 180000, "114/12 出貨未收")]
OPENING_AP = [("V001", 250000, "114/12 進貨未付"), ("V001", 150000, "已開支票 CK0000881 未兌現"),
              ("V002", 130000, "114/11～12 運費未付")]


def build(b, upto=None):
    """在 Biz（已登入、空資料庫）建立範例；回傳各單據 id 供說明與測試使用。"""
    ids = {}
    b.save_company(name="祥和貿易股份有限公司", short_name="祥和貿易", tax_id="53212539", owner="王大明",
                   phone="02-2700-1234", address="臺北市大安區和平東路二段 100 號", inventory_system="P",
                   doc_footer="匯款帳號：台灣銀行 大安分行 123-456-789012　戶名：祥和貿易股份有限公司")
    b.save_master("warehouses", dict(code="B", name="門市倉", active=1), True)
    b.save_master("bank_accounts", dict(code="B01", name="台銀活存", bank_name="台灣銀行 大安分行",
                                        account_no="123-456-789012", gl_account="1113", active=1), False)
    b.save_master("bank_accounts", dict(code="B02", name="台銀甲存", bank_name="台灣銀行 大安分行",
                                        account_no="123-456-789099", gl_account="1113", active=1), True)
    for code, name in (("E01", "吳業務"), ("E02", "黃採購"), ("E03", "周倉管")):
        b.save_master("employees", dict(code=code, name=name, active=1), True)
    for code, name, short, cd, days in VENDORS:
        b.save_master("vendors", dict(code=code, name=name, short_name=short, closing_day=cd, pay_days=days, active=1),
                      True)
    for code, name, short, tax, cd, days, lvl in CUSTOMERS:
        b.save_master("customers", dict(code=code, name=name, short_name=short, tax_id=tax, closing_day=cd,
                                        pay_days=days, price_level=lvl, salesman="E01", active=1), True)
    for code, name, spec, unit, p1, p2, cost, safety, vend in PRODUCTS:
        b.save_master("products", dict(code=code, name=name, spec=spec, unit=unit, price=p1, price2=p2, std_cost=cost,
                                       safety_qty=safety, vendor=vend, category="09" if code[0] == "S" else "01",
                                       is_stock=0 if code[0] == "S" else 1, active=1), True)
    # ---- 期初
    for wh, items in OPENING_STOCK.items():
        ids["open_" + wh] = b.save_doc(None, dict(doc_type="OPEN", doc_date=OPEN_DATE, warehouse=wh, memo="期初庫存"),
                                       [dict(product=p, qty=q, price=c) for p, q, c in items])
    for i, (c, amt, memo) in enumerate(OPENING_AR):
        ids["aro%d" % i] = b.save_doc(None, dict(doc_type="ARO", doc_date=OPEN_DATE, partner=c, total=amt, memo=memo),
                                      [])
    for i, (v, amt, memo) in enumerate(OPENING_AP):
        ids["apo%d" % i] = b.save_doc(None, dict(doc_type="APO", doc_date=OPEN_DATE, partner=v, total=amt, memo=memo),
                                      [])
    # 期初在手支票：用收款／付款單把票據登進系統（日期同期初）
    ids["r_open"] = b.save_receipt("R", dict(r_date=OPEN_DATE, partner="C001", memo="期初在手支票", opening=True),
                                   [dict(doc_id=ids["aro1"], amount=120000)],
                                   notes=[dict(note_no="AK1234567", bank="第一銀行 民生分行", amount=120000,
                                               due_date=D(1, 20))])
    ids["p_open"] = b.save_receipt("P", dict(r_date=OPEN_DATE, partner="V001", bank_account="B02",
                                             memo="期初已開未兌現支票", opening=True), [dict(doc_id=ids["apo1"], amount=150000)],
                                   notes=[dict(note_no="CK0000881", amount=150000, due_date=D(1, 15))])
    b.close_month("202512")                 # 期初月份先月結（只有期初庫存，不產生分錄）
    if upto == "opening":
        return ids
    # ---- 115 年 1 月：銷售
    ids["qt"] = b.save_doc(None, dict(doc_type="QT", doc_date=D(1, 3), partner="C002", employee="E01"),
                           [dict(product="P002", qty=3, price=18000), dict(product="P003", qty=10, price=2600)])
    ids["so"] = b.save_doc(None, dict(doc_type="SO", doc_date=D(1, 5), partner="C002", employee="E01",
                                      due_date="115/01/12", memo="報價轉訂單"),
                           [dict(product="P002", qty=3, price=18000), dict(product="P003", qty=10, price=2600)])
    so_lines = b.doc(ids["so"])["lines"]
    ids["si1"] = b.save_doc(None, dict(doc_type="SI", doc_date=D(1, 6), partner="C002", warehouse="A", employee="E01",
                                       invoice_no="AB10000001"),
                            [dict(product="P002", qty=2, price=18000, src_line_id=so_lines[0]["id"]),
                             dict(product="P003", qty=10, price=2600, src_line_id=so_lines[1]["id"])])
    ids["si2"] = b.save_doc(None, dict(doc_type="SI", doc_date=D(1, 12), partner="C002", warehouse="A", employee="E01",
                                       invoice_no="AB10000015"),
                            [dict(product="P002", qty=1, price=18000, src_line_id=so_lines[0]["id"]),
                             dict(product="S001", qty=1, price=1500)])
    si1_p003 = [ln for ln in b.doc(ids["si1"])["lines"] if ln["product"] == "P003"][0]
    ids["sr"] = b.save_doc(None, dict(doc_type="SR", doc_date=D(1, 15), partner="C002", warehouse="A",
                                      memo="碳粉匣外盒破損退回"),
                           [dict(product="P003", qty=1, price=2600, src_line_id=si1_p003["id"])])
    ids["si3"] = b.save_doc(None, dict(doc_type="SI", doc_date=D(1, 8), partner="C001", warehouse="A", employee="E01",
                                       invoice_no="AB10000008"),
                            [dict(product="P001", qty=200, price=560), dict(product="P006", qty=300, price=100)])
    ids["si4"] = b.save_doc(None, dict(doc_type="SI", doc_date=D(1, 21), partner="C003", warehouse="B",
                                       invoice_no="AB10000022", tax_type=2),
                            [dict(product="P001", qty=20, price=620), dict(product="P006", qty=50, price=120)])
    # ---- 採購、進貨、進退
    ids["po"] = b.save_doc(None, dict(doc_type="PO", doc_date=D(1, 4), partner="V001", employee="E02"),
                           [dict(product="P001", qty=300, price=450)])
    pol = b.doc(ids["po"])["lines"][0]
    ids["pi1"] = b.save_doc(None, dict(doc_type="PI", doc_date=D(1, 7), partner="V001", warehouse="A",
                                       invoice_no="QK20000101"), [dict(product="P001", qty=300, price=450,
                                                                       src_line_id=pol["id"])])
    ids["pi2"] = b.save_doc(None, dict(doc_type="PI", doc_date=D(1, 9), partner="V003", warehouse="A",
                                       invoice_no="QK20000155"), [dict(product="P003", qty=50, price=1800)])
    pi1l = b.doc(ids["pi1"])["lines"][0]
    ids["pr"] = b.save_doc(None, dict(doc_type="PR", doc_date=D(1, 20), partner="V001", warehouse="A",
                                      memo="受潮退回"), [dict(product="P001", qty=10, price=450, src_line_id=pi1l["id"])])
    # ---- 倉庫
    ids["tr"] = b.save_doc(None, dict(doc_type="TR", doc_date=D(1, 16), warehouse="A", warehouse2="B"),
                           [dict(product="P003", qty=10)])
    ids["out"] = b.save_doc(None, dict(doc_type="OUT", doc_date=D(1, 22), warehouse="A", reason="內部領用",
                                       gl_account="6213", memo="行政部文具"), [dict(product="P006", qty=20)])
    ids["scr"] = b.save_doc(None, dict(doc_type="SCR", doc_date=D(1, 23), warehouse="A", reason="損壞"),
                            [dict(product="P004", qty=1)])
    ids["cnt"] = b.create_count("B", D(1, 31))
    lines = b.doc(ids["cnt"])["lines"]
    counted = {"P001": 78, "P003": 10, "P006": 150}           # 帳面 P001 80、P003 10、P006 150
    b.save_doc(ids["cnt"], b.doc(ids["cnt"]), [dict(product=ln["product"], book_qty=ln["book_qty"],
                                                    count_qty=counted.get(ln["product"], ln["book_qty"]))
                                               for ln in lines])
    ids["adj"] = b.count_to_adjust(ids["cnt"])
    # ---- 收款、付款、票據
    ids["rc1"] = b.save_receipt("R", dict(r_date=D(1, 5), partner="C001", bank=105000, bank_account="B01",
                                          memo="大成貿易匯入貨款"), [dict(doc_id=ids["aro0"], amount=105000)])
    ar_c002 = b.open_items("C", "C002", D(1, 25))
    tot = sum(i["remain"] for i in ar_c002 if i["doc_type"] != "ARO")
    ids["rc2"] = b.save_receipt("R", dict(r_date=D(1, 25), partner="C002", memo="永信科技 1 月貨款"),
                                [dict(doc_id=i["id"], amount=i["remain"]) for i in ar_c002 if i["doc_type"] != "ARO"],
                                notes=[dict(note_no="BX7654321", bank="華南銀行 內湖分行", amount=tot,
                                            due_date=D(2, 28))])
    ids["py1"] = b.save_receipt("P", dict(r_date=D(1, 31), partner="V001", bank=250030, fee=30, bank_account="B01",
                                          memo="支付 114/12 貨款"), [dict(doc_id=ids["apo0"], amount=250000)])
    notes = {n["note_no"]: n for n in b.find_notes("R") + b.find_notes("P")}
    b.note_event([notes["CK0000881"]["id"]], "pay", D(1, 15))
    b.note_event([notes["AK1234567"]["id"]], "collect", D(1, 16), bank_account="B01")
    b.note_event([notes["AK1234567"]["id"]], "clear", D(1, 20))
    if upto == "january":
        return ids
    # ---- 月底：月結、拋轉
    b.close_month("202601")
    ids["batch"] = b.create_gl_batch(D(1, 1), D(1, 31))
    return ids
