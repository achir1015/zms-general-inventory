"""成本月結（月加權平均）、庫存關帳、呆滯品分析與跌價提列。

月加權平均單位成本＝（上月結存金額＋本月進貨淨額＋期初／其他入庫金額）÷（上月結存量＋本月入庫量）
本月銷貨、銷退、領用、報廢、數量修正（盤盈虧）都以這個單位成本計價，並回寫到單據明細的成本，
供毛利報表與「庫存月結傳票」使用。
"""
import datetime as dt
from decimal import Decimal

from . import rocdate
from .core import D0, BizError, date, money, price

OUT_SALE = {"SI": 1, "SR": -1}            # 銷貨成本：銷貨＋、銷退－
OUT_OTHER = {"OUT": 1, "SCR": 1, "ADJ": -1}   # 其他出庫（ADJ 數量為負時是出）


def ym_add(ym, n):
    y, m = int(ym[:4]), int(ym[4:])
    m += n
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    return "%04d%02d" % (y, m)


def ym_range(ym):
    first = dt.date(int(ym[:4]), int(ym[4:]), 1)
    return first, rocdate.month_last(first)


class CostMixin:
    # ================================================================ 月結
    def cost_status(self):
        closed = self.closed_ym()
        first = self.db.value("SELECT MIN(move_date) FROM stock_moves")
        first_doc = self.db.value("SELECT MIN(doc_date) FROM docs WHERE status=1 AND doc_type IN "
                                  "('PI','PR','SI','SR','OPEN','IN','OUT','SCR','ADJ','TR','WD')")
        start = min([d for d in (first, first_doc) if d] or [rocdate.today()])
        nxt = ym_add(closed, 1) if closed else rocdate.ym(start)
        rows = self.db.rows("SELECT c.*, b.batch_no FROM cost_closes c LEFT JOIN gl_batches b ON b.id=c.gl_batch_id "
                            "ORDER BY c.ym DESC")
        return dict(closed=closed, next=nxt, history=rows)

    def close_month(self, ym):
        self.need("CLS")
        st = self.cost_status()
        if ym != st["next"]:
            raise BizError("月結要依序進行：下一個應月結的月份是 %s" % rocdate.ym_show(st["next"]))
        if ym > rocdate.ym(rocdate.today()):
            raise BizError("不能月結未來的月份")
        first, last = ym_range(ym)
        prev = ym_add(ym, -1)
        opening = {r["product"]: r for r in self.db.rows("SELECT * FROM cost_months WHERE ym=%s", (prev,))}
        lines = self.db.rows(
            "SELECT l.id, l.product, l.qty, l.net, l.amount, d.doc_type, d.discount_only FROM doc_lines l "
            "JOIN docs d ON d.id=l.doc_id JOIN products p ON p.code=l.product WHERE d.status=1 AND p.is_stock=1 "
            "AND d.doc_date BETWEEN %s AND %s AND d.doc_type IN ('PI','PR','OPEN','IN','SI','SR','OUT','SCR','ADJ') "
            "ORDER BY d.doc_date, d.id, l.line_no", (first, last))
        prods = {}

        def P(code):
            if code not in prods:
                o = opening.get(code)
                prods[code] = dict(open_qty=o["close_qty"] if o else D0, open_amt=o["close_amt"] if o else D0,
                                   in_qty=D0, in_amt=D0, outs=[], prev_unit=o["unit_cost"] if o else None)
            return prods[code]

        for code in opening:
            if opening[code]["close_qty"] or opening[code]["close_amt"]:
                P(code)
        for ln in lines:
            x = P(ln["product"])
            t = ln["doc_type"]
            if t == "PI":
                if ln["discount_only"]:
                    x["in_amt"] += ln["net"]
                else:
                    x["in_qty"] += ln["qty"]
                    x["in_amt"] += ln["net"]
            elif t == "PR":
                if ln["discount_only"]:
                    x["in_amt"] -= ln["net"]
                else:
                    x["in_qty"] -= ln["qty"]
                    x["in_amt"] -= ln["net"]
            elif t in ("OPEN", "IN"):
                x["in_qty"] += ln["qty"]
                x["in_amt"] += ln["amount"]
            elif t in ("SI", "SR"):
                if not ln["discount_only"]:
                    x["outs"].append((ln, "sale", ln["qty"] * OUT_SALE[t]))
            else:
                x["outs"].append((ln, "other", ln["qty"] * OUT_OTHER[t]))
        rows, line_costs = [], []
        for code, x in prods.items():
            base_q = x["open_qty"] + x["in_qty"]
            base_a = x["open_amt"] + x["in_amt"]
            if base_q > 0:
                unit = base_a / base_q
            else:
                p = self.db.row("SELECT avg_cost, std_cost, last_cost FROM products WHERE code=%s", (code,)) or {}
                unit = x["prev_unit"] or p.get("avg_cost") or p.get("last_cost") or p.get("std_cost") or D0
            unit = Decimal(unit)
            sale_q = sale_a = other_q = other_a = D0
            costs = []
            for ln, kind, q in x["outs"]:
                c = money(q * unit)
                costs.append([ln, kind, q, c])
            close_q = base_q - sum((c[2] for c in costs), D0)
            residual = base_a - sum((c[3] for c in costs), D0)
            if close_q == 0 and residual and costs:            # 全部出清：尾差併入出貨量最大的一筆
                big = max(costs, key=lambda c: abs(c[2]))
                big[3] += residual
            for ln, kind, q, c in costs:
                if kind == "sale":
                    sale_q += q
                    sale_a += c
                else:
                    other_q += q
                    other_a += c
                sign = -1 if ln["doc_type"] == "ADJ" else 1      # 調整單的成本與數量同號（增加為正）
                line_costs.append((abs(c) if ln["doc_type"] != "ADJ" else c * sign, ln["id"]))
            close_a = base_a - sale_a - other_a
            if close_q == 0:
                close_a = D0
            rows.append((ym, code, x["open_qty"], x["open_amt"], x["in_qty"], x["in_amt"], sale_q, sale_a, other_q,
                         other_a, close_q, close_a, price(unit)))
        with self.db.transaction():
            self.db.exec("DELETE FROM cost_months WHERE ym=%s", (ym,))
            self.db.exec_many("INSERT INTO cost_months (ym, product, open_qty, open_amt, in_qty, in_amt, sale_qty, "
                              "sale_amt, other_qty, other_amt, close_qty, close_amt, unit_cost) VALUES (%s, %s, %s, "
                              "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", rows)
            # 調整單：成本＝數量×單位成本（增加為正）；其他出庫類存正數
            fixed = []
            for c, lid in line_costs:
                fixed.append((c, lid))
            self.db.exec_many("UPDATE doc_lines SET cost=%s WHERE id=%s", fixed)
            self.db.exec_many("UPDATE products SET avg_cost=%s WHERE code=%s",
                              [(r[12], r[1]) for r in rows if r[12]])
            self.db.exec("INSERT INTO cost_closes (ym, closed_by) VALUES (%s, %s)", (ym, self.uid))
            self.db.exec("UPDATE company SET stock_closed_ym=%s WHERE id=1", (ym,))
        self.log("cost_close", ym, "%d 項商品" % len(rows))
        return len(rows)

    def reopen_month(self, ym):
        self.need("CLS")
        closed = self.closed_ym()
        if ym != closed:
            raise BizError("只能取消最近一次月結（%s）" % (rocdate.ym_show(closed) if closed else "尚未月結"))
        c = self.db.row("SELECT * FROM cost_closes WHERE ym=%s", (ym,))
        if c and c["gl_batch_id"]:
            raise BizError("該月的庫存成本傳票已拋轉會計，請先取消拋轉")
        prev = self.db.value("SELECT MAX(ym) FROM cost_closes WHERE ym<%s", (ym,)) or ""
        with self.db.transaction():
            self.db.exec("DELETE FROM cost_months WHERE ym=%s", (ym,))
            self.db.exec("DELETE FROM cost_closes WHERE ym=%s", (ym,))
            self.db.exec("UPDATE company SET stock_closed_ym=%s WHERE id=1", (prev,))
        self.log("cost_reopen", ym)

    def cost_month_rows(self, ym):
        self.need("RPT", 1)
        rows = self.db.rows("SELECT c.*, p.name, p.unit, p.category FROM cost_months c JOIN products p ON "
                            "p.code=c.product WHERE c.ym=%s ORDER BY c.product", (ym,))
        if not self.see_cost:
            for r in rows:
                for k in ("open_amt", "in_amt", "sale_amt", "other_amt", "close_amt", "unit_cost"):
                    r[k] = None
        return rows

    # ================================================================ 呆滯品、跌價提列
    def dead_stock(self, days=None, as_of=None, warehouse=""):
        self.need("RPT", 1)
        comp = self.company()
        days = int(days or comp.get("dead_days") or 180)
        as_of = date(as_of or rocdate.today())
        cutoff = as_of - dt.timedelta(days=days)
        sql = ("SELECT s.product, SUM(s.qty) qty FROM stock s JOIN products p ON p.code=s.product WHERE p.is_stock=1"
               + (" AND s.warehouse=%s" if warehouse else "") + " GROUP BY s.product HAVING SUM(s.qty)>0")
        stock = self.db.rows(sql, (warehouse,) if warehouse else ())
        out = []
        for s in stock:
            last_out = self.db.value("SELECT MAX(move_date) FROM stock_moves WHERE product=%s AND qty<0 AND doc_type "
                                     "IN ('SI','OUT') AND move_date<=%s", (s["product"], as_of))
            if last_out and last_out > cutoff:
                continue
            last_in = self.db.value("SELECT MAX(move_date) FROM stock_moves WHERE product=%s AND qty>0 AND doc_type "
                                    "IN ('PI','OPEN','IN') AND move_date<=%s", (s["product"], as_of))
            if last_in and last_in > cutoff and not last_out:
                continue                                   # 最近才進貨，還不算呆滯
            p = self.db.row("SELECT name, unit, avg_cost, category FROM products WHERE code=%s", (s["product"],))
            prov = self.db.value("SELECT SUM(l.amount) FROM doc_lines l JOIN docs d ON d.id=l.doc_id WHERE d.status=1 "
                                 "AND d.doc_type='WD' AND l.product=%s", (s["product"],)) or D0
            value = money(s["qty"] * (p["avg_cost"] or 0))
            ref = last_out or last_in
            out.append(dict(product=s["product"], name=p["name"], unit=p["unit"], category=p["category"], qty=s["qty"],
                            avg_cost=p["avg_cost"] if self.see_cost else None, value=value if self.see_cost else None,
                            last_in=last_in, last_out=last_out, idle_days=(as_of - ref).days if ref else None,
                            provision=prov if self.see_cost else None,
                            net_value=(value - prov) if self.see_cost else None))
        out.sort(key=lambda r: -(r["idle_days"] or 99999))
        return out

    def provision_balance(self):
        return self.db.value("SELECT SUM(l.amount) FROM doc_lines l JOIN docs d ON d.id=l.doc_id WHERE d.status=1 AND "
                             "d.doc_type='WD'") or D0

    def inventory_value(self):
        if not self.see_cost:
            return None
        return self.db.value("SELECT SUM(s.qty*p.avg_cost) FROM stock s JOIN products p ON p.code=s.product "
                             "WHERE p.is_stock=1") or D0
