"""手機連線：真的啟動 API 服務，用 RemoteBooks 走 HTTP 測試（與電腦版同一套服務、同一套權限）。"""
import datetime as dt
from decimal import Decimal

import pytest

from inv.api import ApiServer
from inv.core import BizError
from inv.remote import Client, RemoteBooks
from inv.seed import ROLES

PORT = 8798


@pytest.fixture()
def api(biz):
    from tests.test_flow import setup_masters
    setup_masters(biz)
    biz.save_user("sales", "業務小王", "業務人員", False, True, ROLES["業務人員"], pw="pass123", is_new=True)
    srv = ApiServer(biz.db, port=PORT, host="127.0.0.1")
    srv.start()
    yield srv
    srv.stop()


def connect(uid, pw):
    rb = RemoteBooks(Client("127.0.0.1:%d" % PORT))
    rb.login(uid, pw)
    return rb


def test_ping_and_login(api):
    c = Client("http://127.0.0.1:%d" % PORT)
    assert c.ping()["app"] == "資料助秘之一般公司進銷存"
    rb = RemoteBooks(c)
    with pytest.raises(BizError, match="帳號或密碼錯誤"):
        rb.login("admin", "wrong")
    rb.login("admin", "admin123")
    assert rb.user["uid"] == "admin" and "pw_hash" not in rb.user and rb.can("SYS") and rb.see_cost


def test_full_roundtrip(api):
    rb = connect("admin", "admin123")
    rb.save_doc(None, dict(doc_type="OPEN", doc_date="115/09/01", warehouse="A"), [dict(product="A", qty=10, price=100)])
    sid = rb.save_doc(None, dict(doc_type="SI", doc_date="115/09/05", partner="C1"),
                      [dict(product="A", qty="2", price="200")])
    d = rb.doc(sid)
    assert d["total"] == Decimal("420.00") and isinstance(d["doc_date"], dt.date)
    rows, whs = rb.stock_list()
    assert rows[0]["qty"] == Decimal(8) and "A" in whs
    rid = rb.save_receipt("R", dict(r_date="115/09/06", partner="C1", cash="420"), [dict(doc_id=sid, amount=420)])
    assert rb.receipt(rid)["applied"] == Decimal("420.00")
    assert rb.dashboard()["month_sales"] is not None
    assert [p["code"] for p in rb.product_list()] == ["A", "B", "S"]


def test_permissions_enforced_on_server(api, biz):
    rb = connect("sales", "pass123")
    assert not rb.can("SYS") and not rb.see_cost
    with pytest.raises(BizError, match="系統管理"):
        rb.save_company(name="X")                     # 手機端本地沒擋，電腦端擋下
    with pytest.raises(BizError, match="採購"):
        rb.save_doc(None, dict(doc_type="PI", partner="V1"), [dict(product="A", qty=1, price=1)])
    assert rb.master_rows("products")[0]["avg_cost"] is None
    for bad in ("login", "db", "export_gl_batch", "send_gl_batch", "cancel_gl_batch", "_clean_lines"):
        with pytest.raises(BizError, match="不允許"):
            rb._c.call("books", bad, [], {})
    biz.save_user("sales", "業務小王", "業務人員", False, False, ROLES["業務人員"], is_new=False)
    with pytest.raises(BizError, match="停用"):
        rb.product_list()


def test_client_ip_trust():
    from inv.api import client_ip
    h = {"Cf-Connecting-Ip": "203.0.113.9", "X-Forwarded-For": "198.51.100.1"}
    assert client_ip("127.0.0.1", h) == "203.0.113.9"
    assert client_ip("192.168.6.50", h) == "192.168.6.50"


def test_switch_to_alternate_url(api):
    c = Client("127.0.0.1:1", alternates=["127.0.0.1:%d" % PORT])
    rb = RemoteBooks(c)
    switched = []
    c.on_switch = switched.append
    rb.login("admin", "admin123")
    assert c.url.endswith(":%d" % PORT) and switched


def test_login_throttle(api):
    rb = RemoteBooks(Client("127.0.0.1:%d" % PORT))
    for _ in range(8):
        with pytest.raises(BizError):
            rb.login("admin", "bad")
    with pytest.raises(BizError, match="次數太多"):
        rb.login("admin", "admin123")
