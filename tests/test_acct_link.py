"""與「資料助秘之一般公司會計」的拋轉整合測試：進銷存產生的批次，真的匯入會計系統並產生平衡的傳票。
（本機沒有會計系統原始碼時略過）"""
import datetime as dt
import json
import os
import sys

import pytest

ACCT = os.environ.get("ZMS_ACCT_SRC", r"E:\財務會計幫幫忙\zms-accounting")
pytestmark = pytest.mark.skipif(not os.path.isdir(os.path.join(ACCT, "acct")), reason="沒有會計系統原始碼")


@pytest.fixture()
def acct_books(server):
    sys.path.insert(0, ACCT)
    from acct.books import Books
    from acct.database import DB as ADB
    from acct.settings import Settings as ASettings
    st = ASettings(port=server.port, password=server.password, database="acct_link_test",
                   mariadb_bin=server.mariadb_bin, datadir=server.datadir)
    d = ADB(st)
    c = d.connect(use_db=False)
    with c.cursor() as cur:
        cur.execute("DROP DATABASE IF EXISTS acct_link_test")
    c.close()
    d.prepare()
    b = Books(d)
    b.create_first_admin("admin", "會計", "admin123")
    b.login("admin", "admin123")
    b.save_company(name="測試貿易股份有限公司", tax_id="12345675", owner="", phone="", address="",
                   fiscal_start_month=1, auto_post=0, separate_approver=0)
    yield b
    d.close()


def test_batch_into_accounting(biz, acct_books):
    from tests.test_flow import d, setup_masters
    b = biz
    setup_masters(b)
    b.save_doc(None, dict(doc_type="OPEN", doc_date=d(1), warehouse="A"), [dict(product="A", qty=10, price=100)])
    pi = b.save_doc(None, dict(doc_type="PI", doc_date=d(3), partner="V1"), [dict(product="A", qty=20, price=110)])
    si = b.save_doc(None, dict(doc_type="SI", doc_date=d(5), partner="C1"), [dict(product="A", qty=15, price=200)])
    b.save_receipt("R", dict(r_date=d(10), partner="C1", bank=3150, bank_account="B01"), [dict(doc_id=si, amount=3150)])
    b.save_receipt("P", dict(r_date=d(12), partner="V1", bank_account="B01"), [dict(doc_id=pi, amount=2310)],
                   notes=[dict(note_no="CK1", amount=2310, due_date=d(15, 10))])
    b.save_doc(None, dict(doc_type="SCR", doc_date=d(20), warehouse="A"), [dict(product="A", qty=1)])
    b.close_month("202609")
    b.save_doc(None, dict(doc_type="WD", doc_date=d(1, 10)), [dict(product="A", amount=300)])
    bid = b.create_gl_batch(d(1), d(1, 10))
    batch = json.loads(json.dumps(b.gl_batch(bid)["data"]))

    a = acct_books
    pv = a.preview_gl_batch(batch)
    assert pv["count"] == len(batch["vouchers"])
    assert "1219 備抵存貨跌價損失" in pv["created"]["accounts"] or \
        a.db.value("SELECT 1 FROM accounts WHERE code='1219'")
    assert a.db.value("SELECT COUNT(*) FROM vouchers") == 0          # 試匯入不寫入
    res = a.import_gl_batch(batch)
    assert res["count"] == len(batch["vouchers"])
    with pytest.raises(Exception, match="已在"):
        a.import_gl_batch(batch)                                        # 不重複匯入
    # 會計端借貸平衡、往來對象已建立
    td, tc = a.db.row("SELECT SUM(debit) d, SUM(credit) c FROM voucher_lines").values()
    assert td == tc
    assert a.db.value("SELECT name FROM partners WHERE kind='C' AND code='C1'") == "大華商行"
    ar = a.db.value("SELECT SUM(debit-credit) FROM voucher_lines WHERE account='1141'")
    assert ar == 0                                                      # 銷貨 3,150 已全額收款
    inv = a.db.value("SELECT SUM(debit-credit) FROM voucher_lines WHERE account='1211'")
    row = b.cost_month_rows("202609")[0]
    assert inv == row["close_amt"] - 1000                               # 存貨科目變動＝月結結存－期初庫存（期初在會計開帳）
    st = a.gl_import_status(batch["batch_uid"])
    assert st["voucher_count"] == res["count"]
    # 取消匯入 → 進銷存取消拋轉
    a.cancel_gl_import(batch["batch_uid"])
    assert a.db.value("SELECT COUNT(*) FROM vouchers") == 0
    b.cancel_gl_batch(bid)
    assert b.gl_pending(d(1), d(1, 10))["sales"] == 1
    # 公司統編不同時擋下
    batch["company"]["tax_id"] = "99999999"
    batch["batch_uid"] += "x"
    with pytest.raises(Exception, match="不同"):
        a.import_gl_batch(batch)
    _ = dt


def test_direct_send_over_api(biz, acct_books):
    """直接傳送：透過會計系統的手機連線服務（HTTP API）送出與取消。"""
    from acct.api import ApiServer
    from inv.gl import AcctClient
    from tests.test_flow import d, setup_masters
    b = biz
    setup_masters(b)
    b.save_doc(None, dict(doc_type="OPEN", doc_date=d(1), warehouse="A"), [dict(product="A", qty=10, price=100)])
    b.save_doc(None, dict(doc_type="SI", doc_date=d(5), partner="C1"), [dict(product="A", qty=3, price=200)])
    bid = b.create_gl_batch(d(1), d(30))
    api = ApiServer(acct_books.db, port=8799, host="127.0.0.1")
    api.start()
    try:
        cl = AcctClient("127.0.0.1:8799", "admin", "admin123")
        assert cl.ping()["app"] == "資料助秘之一般公司會計"
        res = b.send_gl_batch(bid, cl)
        assert res["count"] == 1 and str(res["total"]) == "630.00"
        assert b.gl_batch(bid)["status"] == 2
        assert acct_books.db.value("SELECT COUNT(*) FROM vouchers") == 1
        with pytest.raises(Exception, match="密碼"):
            AcctClient("127.0.0.1:8799", "admin", "wrong").login()
        b.cancel_gl_batch(bid, AcctClient("127.0.0.1:8799", "admin", "admin123"))
        assert acct_books.db.value("SELECT COUNT(*) FROM vouchers") == 0
        assert b.gl_batch(bid)["status"] == 9
    finally:
        api.stop()
