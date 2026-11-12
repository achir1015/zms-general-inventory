"""報表：首頁數字、銷貨／進貨明細、排行、月份統計、庫存表、商品異動卡、安全存量、進銷存彙總。"""
import datetime as dt
from decimal import Decimal

from . import rocdate
from .core import D0, date, money
from .doctypes import DOC_TYPES

SIGN = {"SI": 1, "SR": -1, "PI": 1, "PR": -1, "QT": 1, "SO": 1, "PO": 1}


class ReportsMixin:
    # ================================================================ 首頁
    def dashboard(self):
        today = rocdate.today()
        m1 = today.replace(day=1)
        out = {}
        r = self.db.row("SELECT SUM(CASE WHEN doc_type='SI' THEN amount ELSE -amount END) s FROM docs WHERE status=1 "
                        "AND doc_type IN ('SI','SR') AND doc_date BETWEEN %s AND %s", (m1, today))
        out["month_sales"] = r["s"] or D0
        out["today_sales"] = self.db.value("SELECT SUM(CASE WHEN doc_type='SI' THEN amount ELSE -amount END) FROM docs "
                                           "WHERE status=1 AND doc_type IN ('SI','SR') AND doc_date=%s", (today,)) or D0
        out["month_purchase"] = self.db.value(
            "SELECT SUM(CASE WHEN doc_type='PI' THEN amount ELSE -amount END) FROM docs WHERE status=1 AND doc_type IN "
            "('PI','PR') AND doc_date BETWEEN %s AND %s", (m1, today)) or D0
        if self.see_cost:
            c = self.db.value("SELECT SUM(CASE WHEN d.doc_type='SI' THEN l.cost ELSE -l.cost END) FROM doc_lines l JOIN "
                              "docs d ON d.id=l.doc_id WHERE d.status=1 AND d.discount_only=0 AND d.doc_type IN "
                              "('SI','SR') AND d.doc_date BETWEEN %s AND %s", (m1, today)) or D0
            out["month_margin"] = out["month_sales"] - c
            out["stock_value"] = self.inventory_value()
        ar = self.db.value("SELECT SUM(CASE WHEN doc_type='SR' THEN -total ELSE total END) FROM docs WHERE status=1 AND "
                           "doc_type IN ('SI','SR','ARO','NTR')") or D0
        ar -= self.db.value("SELECT SUM(applied) FROM receipts WHERE status=1 AND kind='R'") or D0
        ap = self.db.value("SELECT SUM(CASE WHEN doc_type='PR' THEN -total ELSE total END) FROM docs WHERE status=1 AND "
                           "doc_type IN ('PI','PR','APO','NTP')") or D0
        ap -= self.db.value("SELECT SUM(applied) FROM receipts WHERE status=1 AND kind='P'") or D0
        out["ar"], out["ap"] = ar, ap
        out["low_stock"] = len(self.low_stock())
        out["open_so"] = len({r["doc_id"] for r in self.tracking("SO")})
        out["open_po"] = len({r["doc_id"] for r in self.tracking("PO")})
        out["notes_due"] = self.notes_due(14)
        out["closed_ym"] = self.closed_ym()
        out["gl_pending"] = sum(self.gl_pending(dt.date(2000, 1, 1), today).values()) if self.can("GL", 1) else 0
        # 近 12 個月銷貨與進貨
        start = (m1 - dt.timedelta(days=330)).replace(day=1)
        rows = self.db.rows("SELECT DATE_FORMAT(doc_date, '%%Y%%m') ym, doc_type, SUM(amount) s FROM docs WHERE "
                            "status=1 AND doc_type IN ('SI','SR','PI','PR') AND doc_date>=%s GROUP BY ym, doc_type",
                            (start,))
        months = []
        y, m = start.year, start.month
        for _ in range(12):
            key = "%04d%02d" % (y, m)
            s = sum((r["s"] * SIGN[r["doc_type"]] for r in rows if r["ym"] == key and r["doc_type"] in ("SI", "SR")), D0)
            p = sum((r["s"] * SIGN[r["doc_type"]] for r in rows if r["ym"] == key and r["doc_type"] in ("PI", "PR")), D0)
            months.append(dict(ym=key, sales=s, purchase=p))
            m += 1
            if m > 12:
                y, m = y + 1, 1
        out["months"] = months
        out["top_products"] = self.ranking("product", "S", m1, today)[:5]
        return out

    # ================================================================ 明細
    def line_detail(self, side, start, end, partner="", product="", category="", warehouse=""):
        """銷貨（side=S：銷貨＋銷退）或進貨（P：進貨＋進退）明細，退回為負數。"""
        self.need("RPT", 1)
        types = ("SI", "SR") if side == "S" else ("PI", "PR")
        where = ["d.status=1", "d.doc_type IN ('%s','%s')" % types, "d.doc_date BETWEEN %s AND %s"]
        args = [date(start), date(end)]
        for cond, v in (("d.partner=%s", partner), ("l.product=%s", product), ("p.category=%s", category),
                        ("d.warehouse=%s", warehouse)):
            if v:
                where.append(cond)
                args.append(v)
        rows = self.db.rows(
            "SELECT d.doc_date, d.doc_no, d.doc_type, d.partner, d.discount_only, COALESCE(c.short_name, c.name) "
            "partner_show, l.product, l.name, l.unit, l.qty, l.price, l.net, l.cost, p.category FROM doc_lines l "
            "JOIN docs d ON d.id=l.doc_id LEFT JOIN products p ON p.code=l.product LEFT JOIN partners c ON "
            "c.kind=d.partner_kind AND c.code=d.partner WHERE %s ORDER BY d.doc_date, d.doc_no, l.line_no"
            % " AND ".join(where), tuple(args))
        for r in rows:
            sg = SIGN[r["doc_type"]]
            r["type_name"] = DOC_TYPES[r["doc_type"]]["short"] + ("折讓" if r["discount_only"] else "")
            r["qty"] = r["qty"] * sg
            r["net"] = r["net"] * sg
            if side == "S" and self.see_cost:
                r["cost"] = (r["cost"] or D0) * sg if not r["discount_only"] else D0
                r["margin"] = r["net"] - r["cost"]
                r["margin_rate"] = _rate(r["margin"], r["net"])
            else:
                r["cost"] = r["margin"] = r["margin_rate"] = None
        return rows

    def ranking(self, by, side, start, end, limit=None):
        """排行：by＝product 商品、partner 客戶／廠商、employee 業務員、category 類別。"""
        self.need("RPT", 1)
        types = ("SI", "SR") if side == "S" else ("PI", "PR")
        col = {"product": "l.product", "partner": "d.partner", "employee": "d.employee", "category": "p.category"}[by]
        rows = self.db.rows(
            "SELECT %s k, SUM(CASE WHEN d.doc_type IN ('SI','PI') THEN l.qty WHEN d.discount_only=1 THEN 0 ELSE -l.qty "
            "END) qty, SUM(CASE WHEN d.doc_type IN ('SI','PI') THEN l.net ELSE -l.net END) net, "
            "SUM(CASE WHEN d.discount_only=1 THEN 0 WHEN d.doc_type IN ('SI','PI') THEN l.cost ELSE -l.cost END) cost, "
            "COUNT(DISTINCT d.id) docs FROM doc_lines l JOIN docs d ON d.id=l.doc_id LEFT JOIN products p ON "
            "p.code=l.product WHERE d.status=1 AND d.doc_type IN ('%s','%s') AND d.doc_date BETWEEN %%s AND %%s "
            "GROUP BY k ORDER BY net DESC" % ((col,) + types), (date(start), date(end)))
        names = {}
        if by == "product":
            names = {r["code"]: (r["name"], r["unit"]) for r in self.db.rows("SELECT code, name, unit FROM products")}
        elif by == "partner":
            names = {r["code"]: (r["short_name"] or r["name"], "") for r in
                     self.db.rows("SELECT code, name, short_name FROM partners WHERE kind=%s",
                                  ("C" if side == "S" else "V",))}
        elif by == "employee":
            names = {r["code"]: (r["name"], "") for r in self.db.rows("SELECT code, name FROM employees")}
        else:
            names = {r["code"]: (r["name"], "") for r in self.db.rows("SELECT code, name FROM categories")}
        total = sum((r["net"] or D0 for r in rows), D0)
        for i, r in enumerate(rows, 1):
            r["rank"] = i
            r["name"], r["unit"] = names.get(r["k"], (r["k"] or "（未指定）", ""))
            r["share"] = _rate(r["net"], total)
            if side == "S" and self.see_cost:
                r["margin"] = (r["net"] or D0) - (r["cost"] or D0)
                r["margin_rate"] = _rate(r["margin"], r["net"])
            else:
                r["cost"] = r["margin"] = r["margin_rate"] = None
        return rows[:limit] if limit else rows

    def monthly(self, year):
        """年度各月：銷貨淨額、成本、毛利、進貨淨額。"""
        self.need("RPT", 1)
        rows = self.db.rows(
            "SELECT MONTH(d.doc_date) m, d.doc_type, SUM(l.net) net, SUM(CASE WHEN d.discount_only=1 THEN 0 ELSE l.cost "
            "END) cost FROM doc_lines l JOIN docs d ON d.id=l.doc_id WHERE d.status=1 AND d.doc_type IN "
            "('SI','SR','PI','PR') AND YEAR(d.doc_date)=%s GROUP BY m, d.doc_type", (int(year),))
        out = []
        for m in range(1, 13):
            s = sum((r["net"] * SIGN[r["doc_type"]] for r in rows if r["m"] == m and r["doc_type"] in ("SI", "SR")), D0)
            c = sum(((r["cost"] or D0) * SIGN[r["doc_type"]] for r in rows if r["m"] == m and r["doc_type"] in
                     ("SI", "SR")), D0)
            p = sum((r["net"] * SIGN[r["doc_type"]] for r in rows if r["m"] == m and r["doc_type"] in ("PI", "PR")), D0)
            row = dict(month="%d 月" % m, m=m, sales=s, purchase=p, cost=None, margin=None, margin_rate=None)
            if self.see_cost:
                row.update(cost=c, margin=s - c, margin_rate=_rate(s - c, s))
            out.append(row)
        return out

    # ================================================================ 庫存
    def stock_list(self, warehouse="", category="", show_zero=False, search=""):
        self.need("RPT", 1) if not self.can("STK", 1) else None
        whs = [w["code"] for w in self.db.rows("SELECT code FROM warehouses WHERE active=1 ORDER BY is_default DESC, code")]
        where, args = ["p.is_stock=1"], []
        if category:
            where.append("p.category=%s")
            args.append(category)
        if search:
            where.append("(p.code LIKE %s OR p.name LIKE %s OR p.barcode LIKE %s)")
            args += ["%" + search + "%"] * 3
        prods = self.db.rows("SELECT p.code, p.name, p.spec, p.unit, p.category, p.avg_cost, p.safety_qty, p.price FROM "
                             "products p WHERE %s ORDER BY p.code" % " AND ".join(where), tuple(args))
        st = {}
        for r in self.db.rows("SELECT product, warehouse, qty FROM stock"):
            st.setdefault(r["product"], {})[r["warehouse"]] = r["qty"]
        out = []
        for p in prods:
            s = st.get(p["code"], {})
            q = s.get(warehouse, D0) if warehouse else sum(s.values(), D0)
            if not q and not show_zero:
                continue
            p["qty"] = q
            for w in whs:
                p["wh_" + w] = s.get(w, D0)
            p["value"] = money(q * (p["avg_cost"] or 0)) if self.see_cost else None
            if not self.see_cost:
                p["avg_cost"] = None
            p["low"] = p["safety_qty"] and q < p["safety_qty"]
            out.append(p)
        return out, whs

    def stock_card(self, product, start, end, warehouse=""):
        """商品異動明細（庫存卡）：期初、每筆異動、結存。"""
        self.need("RPT", 1) if not self.can("STK", 1) else None
        start, end = date(start), date(end)
        wsql = " AND m.warehouse=%s" if warehouse else ""
        wargs = (warehouse,) if warehouse else ()
        opening = self.db.value("SELECT SUM(qty) FROM stock_moves m WHERE product=%s AND move_date<%s" + wsql,
                                (product, start) + wargs) or D0
        rows = self.db.rows(
            "SELECT m.move_date, m.qty, m.warehouse, m.doc_type, d.doc_no, d.id doc_id, d.partner, d.partner_kind, "
            "d.reason, d.memo, l.price, COALESCE(c.short_name, c.name) partner_show FROM stock_moves m JOIN docs d ON "
            "d.id=m.doc_id JOIN doc_lines l ON l.id=m.line_id LEFT JOIN partners c ON c.kind=d.partner_kind AND "
            "c.code=d.partner WHERE m.product=%s AND m.move_date BETWEEN %s AND %s" + wsql +
            " ORDER BY m.move_date, d.doc_no, m.id", (product, start, end) + wargs)
        bal = opening
        for r in rows:
            bal += r["qty"]
            r["in_qty"] = r["qty"] if r["qty"] > 0 else None
            r["out_qty"] = -r["qty"] if r["qty"] < 0 else None
            r["balance"] = bal
            r["type_name"] = DOC_TYPES[r["doc_type"]]["short"]
            r["who"] = r["partner_show"] or r["reason"] or r["memo"]
            if r["doc_type"] in ("IN", "OPEN") and not self.see_cost:
                r["price"] = None
        return dict(opening=opening, rows=rows, closing=bal)

    def low_stock(self):
        """低於安全存量：建議採購量＝安全存量×2－現有－已採購未進貨。"""
        rows = self.db.rows("SELECT p.code, p.name, p.unit, p.safety_qty, p.vendor, COALESCE(SUM(s.qty), 0) qty FROM "
                            "products p LEFT JOIN stock s ON s.product=p.code WHERE p.active=1 AND p.is_stock=1 AND "
                            "p.safety_qty>0 GROUP BY p.code HAVING qty<p.safety_qty ORDER BY p.code")
        if not rows:
            return []
        on_order = {}
        for r in self.tracking("PO"):
            on_order[r["product"]] = on_order.get(r["product"], D0) + r["remain"]
        for r in rows:
            r["on_order"] = on_order.get(r["code"], D0)
            r["suggest"] = max(D0, r["safety_qty"] * 2 - r["qty"] - r["on_order"])
        return rows

    def inout_summary(self, start, end, warehouse="", category=""):
        """進銷存彙總表（數量）：期初、進貨、銷貨、其他入、其他出、結存。"""
        self.need("RPT", 1)
        start, end = date(start), date(end)
        w = " AND m.warehouse=%s" if warehouse else ""
        wa = (warehouse,) if warehouse else ()
        open_q = {r["product"]: r["q"] for r in self.db.rows(
            "SELECT product, SUM(qty) q FROM stock_moves m WHERE move_date<%s" + w + " GROUP BY product", (start,) + wa)}
        mv = self.db.rows("SELECT product, doc_type, SUM(qty) q FROM stock_moves m WHERE move_date BETWEEN %s AND %s" + w +
                          " GROUP BY product, doc_type", (start, end) + wa)
        prods = {r["code"]: r for r in self.db.rows(
            "SELECT code, name, unit, category, avg_cost FROM products WHERE is_stock=1" +
            (" AND category=%s" if category else ""), (category,) if category else ())}
        acc = {}
        for code in set(open_q) | {r["product"] for r in mv}:
            if code not in prods:
                continue
            acc[code] = dict(product=code, name=prods[code]["name"], unit=prods[code]["unit"],
                             open=open_q.get(code, D0), purchase=D0, sales=D0, other_in=D0, other_out=D0)
        for r in mv:
            a = acc.get(r["product"])
            if not a:
                continue
            t, q = r["doc_type"], r["q"]
            if t in ("PI", "PR"):
                a["purchase"] += q
            elif t in ("SI", "SR"):
                a["sales"] -= q
            elif q > 0:
                a["other_in"] += q
            else:
                a["other_out"] -= q
        out = []
        for a in sorted(acc.values(), key=lambda x: x["product"]):
            a["close"] = a["open"] + a["purchase"] - a["sales"] + a["other_in"] - a["other_out"]
            a["value"] = money(a["close"] * (prods[a["product"]]["avg_cost"] or 0)) if self.see_cost else None
            if any(a[k] for k in ("open", "purchase", "sales", "other_in", "other_out")):
                out.append(a)
        return out

    def doc_summary(self, types, start, end):
        """各類單據筆數與金額（盤點、報廢、調整等）。"""
        rows = self.find_docs(types, start, end)
        return rows


def _rate(a, b):
    try:
        return (Decimal(a) / Decimal(b) * 100).quantize(Decimal("0.1")) if b else None
    except Exception:
        return None
