"""單據：新增修改作廢、帶單（訂單轉銷貨等）、庫存異動、盤點轉調整。"""
import datetime as dt
from decimal import Decimal

from . import rocdate
from .core import D0, BizError, date, money, price, qty
from .doctypes import COST_IN, DOC_TYPES, PK_NAMES, TAX_TYPES

STATUS = {1: "有效", 9: "作廢"}


class DocsMixin:
    # ================================================================ 共用檢查
    def closed_ym(self):
        return self.db.value("SELECT stock_closed_ym FROM company WHERE id=1") or ""

    def _check_open(self, d: dt.date, what="單據"):
        c = self.closed_ym()
        if c and rocdate.ym(d) <= c:
            raise BizError("%s 已完成成本月結（關帳），不能再新增或修改該月份的%s；"
                           "如需更正，請先在「成本月結」取消該月的月結" % (rocdate.ym_show(c), what))

    def next_doc_no(self, doc_type, d: dt.date) -> str:
        prefix = doc_type + rocdate.compact(d)
        last = self.db.value("SELECT MAX(doc_no) FROM docs WHERE doc_no LIKE %s", (prefix + "%",))
        seq = int(last[len(prefix):]) + 1 if last else 1
        return "%s%03d" % (prefix, seq)

    # ================================================================ 查詢
    def doc(self, doc_id):
        h = self.db.row("SELECT * FROM docs WHERE id=%s", (doc_id,))
        if not h:
            raise BizError("單據不存在")
        h["lines"] = self.db.rows("SELECT * FROM doc_lines WHERE doc_id=%s ORDER BY line_no", (doc_id,))
        t = DOC_TYPES[h["doc_type"]]
        if t.get("track") or h["doc_type"] in ("SI", "PI"):
            done = self._done_qty([ln["id"] for ln in h["lines"]])
            for ln in h["lines"]:
                ln["done_qty"] = done.get(ln["id"], D0)
        if h["partner"]:
            p = self.partner(h["partner_kind"], h["partner"])
            h["partner_name"] = (p or {}).get("name", "")
        if h["src_doc_id"]:
            h["src_doc_no"] = self.db.value("SELECT doc_no FROM docs WHERE id=%s", (h["src_doc_id"],))
        if not self.see_cost:
            for ln in h["lines"]:
                ln["cost"] = None
            if h["doc_type"] in ("IN", "OPEN"):
                for ln in h["lines"]:
                    ln["price"] = ln["amount"] = None
        return h

    def doc_by_no(self, no):
        r = self.db.row("SELECT id FROM docs WHERE doc_no=%s", (no,))
        return self.doc(r["id"]) if r else None

    def _done_qty(self, line_ids):
        """來源明細已被轉出（或退回）的數量。"""
        if not line_ids:
            return {}
        rows = self.db.rows("SELECT l.src_line_id, SUM(l.qty) q FROM doc_lines l JOIN docs d ON d.id=l.doc_id "
                            "WHERE d.status=1 AND l.src_line_id IN (%s) GROUP BY l.src_line_id"
                            % ",".join(str(int(i)) for i in line_ids))
        return {r["src_line_id"]: r["q"] or D0 for r in rows}

    def find_docs(self, types, start=None, end=None, partner="", keyword="", status=1, limit=2000, product=""):
        types = [types] if isinstance(types, str) else list(types)
        where = ["d.doc_type IN (%s)" % ",".join(["%s"] * len(types))]
        args = list(types)
        if start:
            where.append("d.doc_date>=%s")
            args.append(date(start))
        if end:
            where.append("d.doc_date<=%s")
            args.append(date(end))
        if partner:
            where.append("d.partner=%s")
            args.append(partner)
        if status is not None:
            where.append("d.status=%s")
            args.append(status)
        if keyword:
            where.append("(d.doc_no LIKE %s OR d.memo LIKE %s OR d.ref_no LIKE %s OR d.invoice_no LIKE %s OR "
                         "p.name LIKE %s)")
            args += ["%" + keyword + "%"] * 5
        if product:
            where.append("EXISTS (SELECT 1 FROM doc_lines x WHERE x.doc_id=d.id AND x.product=%s)")
            args.append(product)
        rows = self.db.rows(
            "SELECT d.*, COALESCE(p.short_name, '') short_name, COALESCE(p.name, '') partner_name, "
            "w.name wh_name FROM docs d LEFT JOIN partners p ON p.kind=d.partner_kind AND p.code=d.partner "
            "LEFT JOIN warehouses w ON w.code=d.warehouse WHERE %s ORDER BY d.doc_date DESC, d.doc_no DESC LIMIT %%s"
            % " AND ".join(where), tuple(args) + (limit,))
        for r in rows:
            r["type_name"] = DOC_TYPES[r["doc_type"]]["short"]
            r["partner_show"] = r["short_name"] or r["partner_name"]
        return rows

    # ================================================================ 價格建議
    def suggest_price(self, product, partner_kind="", partner_code=""):
        p = self.product(product)
        if not p:
            return D0
        if partner_kind == "V":
            last = self.db.value(
                "SELECT l.price FROM doc_lines l JOIN docs d ON d.id=l.doc_id WHERE d.status=1 AND d.doc_type='PI' "
                "AND d.partner=%s AND l.product=%s ORDER BY d.doc_date DESC, d.id DESC LIMIT 1", (partner_code, product))
            return Decimal(last) if last is not None else (p["last_cost"] or p["std_cost"])
        level = 1
        if partner_kind == "C" and partner_code:
            level = (self.partner("C", partner_code) or {}).get("price_level") or 1
        if level == 3:
            last = self.db.value(
                "SELECT l.price FROM doc_lines l JOIN docs d ON d.id=l.doc_id WHERE d.status=1 AND d.doc_type='SI' "
                "AND d.partner=%s AND l.product=%s ORDER BY d.doc_date DESC, d.id DESC LIMIT 1", (partner_code, product))
            if last is not None:
                return Decimal(last)
        if level == 2 and p["price2"]:
            return p["price2"]
        return p["price"]

    def last_deals(self, product, partner_kind, partner_code, limit=5):
        dt_ = "SI" if partner_kind == "C" else "PI"
        return self.db.rows(
            "SELECT d.doc_date, d.doc_no, l.qty, l.price FROM doc_lines l JOIN docs d ON d.id=l.doc_id WHERE d.status=1 "
            "AND d.doc_type=%s AND d.partner=%s AND l.product=%s ORDER BY d.doc_date DESC, d.id DESC LIMIT %s",
            (dt_, partner_code, product, limit))

    # ================================================================ 庫存
    def stock_qty(self, product, warehouse=None):
        if warehouse:
            return self.db.value("SELECT qty FROM stock WHERE product=%s AND warehouse=%s", (product, warehouse)) or D0
        return self.db.value("SELECT SUM(qty) FROM stock WHERE product=%s", (product,)) or D0

    def stock_at(self, product, warehouse, d, exclude_doc=None):
        sql = "SELECT SUM(qty) FROM stock_moves WHERE product=%s AND warehouse=%s AND move_date<=%s"
        args = [product, warehouse, d]
        if exclude_doc:
            sql += " AND doc_id<>%s"
            args.append(exclude_doc)
        return self.db.value(sql, tuple(args)) or D0

    def _moves_for(self, h, lines):
        t = DOC_TYPES[h["doc_type"]]
        st = t["stock"]
        if not st or st == "C" or h.get("discount_only"):
            return []
        stocked = {r["code"] for r in self.db.rows(
            "SELECT code FROM products WHERE is_stock=1 AND code IN (%s)" % ",".join(["%s"] * len(lines)),
            tuple(ln["product"] for ln in lines))} if lines else set()
        out = []
        for ln in lines:
            if ln["product"] not in stocked or not ln["qty"]:
                continue
            q = ln["qty"]
            if st == "T":
                out.append((ln, h["warehouse"], -q))
                out.append((ln, h["warehouse2"], q))
            elif st == "A":
                out.append((ln, h["warehouse"], q))
            else:
                out.append((ln, h["warehouse"], q * st))
        return out

    def _apply_stock(self, changes, sign=1):
        for (prod, wh), q in changes.items():
            if q:
                self.db.exec("INSERT INTO stock (product, warehouse, qty) VALUES (%s, %s, %s) "
                             "ON DUPLICATE KEY UPDATE qty=qty+VALUES(qty)", (prod, wh, q * sign))

    def _old_moves(self, doc_id):
        ch = {}
        for r in self.db.rows("SELECT product, warehouse, qty FROM stock_moves WHERE doc_id=%s", (doc_id,)):
            ch[(r["product"], r["warehouse"])] = ch.get((r["product"], r["warehouse"]), D0) + r["qty"]
        return ch

    def rebuild_stock(self):
        """依異動帳重算庫存數量（系統維護用）。"""
        self.need("STK")
        with self.db.transaction():
            self.db.exec("DELETE FROM stock")
            self.db.exec("INSERT INTO stock (product, warehouse, qty) SELECT product, warehouse, SUM(qty) "
                         "FROM stock_moves GROUP BY product, warehouse")
        self.log("stock_rebuild")

    # ================================================================ 存檔
    def save_doc(self, doc_id, header: dict, lines: list):
        """新增（doc_id=None）或修改單據；回傳單據 id。"""
        code = header.get("doc_type")
        if code not in DOC_TYPES:
            raise BizError("單據種類不正確")
        t = DOC_TYPES[code]
        self.need(t["func"])
        comp = self.company()
        old = None
        if doc_id:
            old = self.db.row("SELECT * FROM docs WHERE id=%s", (doc_id,))
            if not old:
                raise BizError("單據不存在")
            if old["status"] != 1:
                raise BizError("單據 %s 已作廢，不能修改" % old["doc_no"])
            if old["gl_batch_id"]:
                raise BizError("單據 %s 已拋轉會計，請先取消拋轉才能修改" % old["doc_no"])
            if old["doc_type"] == "CNT" and old["closed"]:
                raise BizError("盤點單已轉成調整單，不能修改")
            if old["doc_type"] in ("SI", "PI", "SR", "PR", "ARO", "APO") and self.db.value(
                    "SELECT 1 FROM receipt_applies a JOIN receipts r ON r.id=a.receipt_id WHERE a.doc_id=%s "
                    "AND r.status=1 LIMIT 1", (doc_id,)):
                raise BizError("單據 %s 已有收付款沖帳，請先作廢該收付款單" % old["doc_no"])
            if t.get("track") and self.db.value(
                    "SELECT 1 FROM doc_lines l JOIN docs d ON d.id=l.doc_id WHERE d.status=1 AND l.src_line_id IN "
                    "(SELECT id FROM doc_lines WHERE doc_id=%s) LIMIT 1", (doc_id,)):
                raise BizError("單據 %s 已有後續單據（已轉出貨／進貨），不能修改" % old["doc_no"])
            if t["stock"]:
                self._check_open(old["doc_date"])
        h = self._clean_header(code, header, comp)
        if t["stock"] or code == "WD":
            self._check_open(h["doc_date"])
        clean = self._clean_lines(code, h, lines, comp, doc_id)
        self._totals(code, h, clean)
        moves = self._moves_for(h, clean)
        new_ch = {}
        for ln, wh, q in moves:
            new_ch[(ln["product"], wh)] = new_ch.get((ln["product"], wh), D0) + q
        old_ch = self._old_moves(doc_id) if doc_id else {}
        self._check_negative(comp, new_ch, old_ch)
        cols = ("doc_type", "doc_date", "partner_kind", "partner", "warehouse", "warehouse2", "dept", "employee",
                "ref_no", "invoice_no", "tax_type", "tax_rate", "amount", "tax", "total", "discount_only",
                "gl_account", "reason", "memo", "due_date", "src_doc_id")
        with self.db.transaction():
            if doc_id:
                no = old["doc_no"]
                if old["doc_date"] != h["doc_date"] and rocdate.compact(old["doc_date"]) != rocdate.compact(h["doc_date"]):
                    no = self.next_doc_no(code, h["doc_date"])
                self.db.exec("UPDATE docs SET doc_no=%%s, %s, updated_by=%%s, updated_at=NOW() WHERE id=%%s"
                             % ", ".join("%s=%%s" % c for c in cols),
                             (no,) + tuple(h[c] for c in cols) + (self.uid, doc_id))
                self.db.exec("DELETE FROM doc_lines WHERE doc_id=%s", (doc_id,))
                self.db.exec("DELETE FROM stock_moves WHERE doc_id=%s", (doc_id,))
                self._apply_stock(old_ch, -1)
                action = "doc_edit"
            else:
                no = self.next_doc_no(code, h["doc_date"])
                doc_id = self.db.exec("INSERT INTO docs (doc_no, %s, created_by) VALUES (%%s, %s, %%s)"
                                      % (", ".join(cols), ", ".join(["%s"] * len(cols))),
                                      (no,) + tuple(h[c] for c in cols) + (self.uid,))
                action = "doc_new"
            for i, ln in enumerate(clean, 1):
                ln["id"] = self.db.exec(
                    "INSERT INTO doc_lines (doc_id, line_no, product, name, unit, qty, price, amount, net, cost, "
                    "book_qty, count_qty, src_line_id, memo) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s)", (doc_id, i, ln["product"], ln["name"], ln["unit"], ln["qty"], ln["price"], ln["amount"],
                                ln["net"], ln["cost"], ln["book_qty"], ln["count_qty"], ln["src_line_id"], ln["memo"]))
            self.db.exec_many("INSERT INTO stock_moves (doc_id, line_id, doc_type, move_date, product, warehouse, qty) "
                              "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                              [(doc_id, ln["id"], code, h["doc_date"], ln["product"], wh, q) for ln, wh, q in moves])
            self._apply_stock(new_ch)
            self._after_save(code, h, clean)
        self.log(action, no, "%s %s" % (t["short"], h["total"]))
        return doc_id

    def _clean_header(self, code, header, comp):
        t = DOC_TYPES[code]
        h = dict(doc_type=code, doc_date=date(header.get("doc_date") or rocdate.today()))
        h["partner_kind"] = t["pk"]
        h["partner"] = (header.get("partner") or "").strip()
        if t["pk"]:
            if not h["partner"]:
                raise BizError("請選擇%s" % PK_NAMES[t["pk"]])
            if not self.partner(t["pk"], h["partner"]):
                raise BizError("找不到%s %s" % (PK_NAMES[t["pk"]], h["partner"]))
        for k in ("warehouse", "warehouse2", "dept", "employee", "ref_no", "invoice_no", "gl_account", "reason",
                  "memo"):
            h[k] = (header.get(k) or "").strip()
        if t["stock"] and t["stock"] != 0 and not t.get("header_only"):
            if not h["warehouse"]:
                h["warehouse"] = self.default_warehouse()
            if not self.db.value("SELECT 1 FROM warehouses WHERE code=%s", (h["warehouse"],)):
                raise BizError("請選擇倉庫")
        if t["stock"] == "T":
            if not h["warehouse2"] or h["warehouse2"] == h["warehouse"]:
                raise BizError("調撥單的撥入倉要選擇與撥出倉不同的倉庫")
            if not self.db.value("SELECT 1 FROM warehouses WHERE code=%s", (h["warehouse2"],)):
                raise BizError("撥入倉不存在")
        else:
            h["warehouse2"] = ""
        if t["tax"]:
            h["tax_type"] = int(header.get("tax_type") or comp.get("default_tax_type") or 1)
            if h["tax_type"] not in TAX_TYPES:
                raise BizError("稅別不正確")
            h["tax_rate"] = Decimal(str(comp.get("tax_rate") or 5)) if h["tax_type"] in (1, 2) else D0
        else:
            h["tax_type"], h["tax_rate"] = 4, D0
        h["discount_only"] = int(bool(header.get("discount_only"))) if t.get("allow_discount") else 0
        dd = header.get("due_date")
        h["due_date"] = date(dd) if dd else None
        h["src_doc_id"] = header.get("src_doc_id") or None
        h["header_total"] = money(header.get("total")) if t.get("header_only") else D0
        if t.get("header_only") and not h["header_total"]:
            raise BizError("請輸入金額")
        return h

    def _clean_lines(self, code, h, lines, comp, doc_id):
        t = DOC_TYPES[code]
        if t.get("header_only"):
            return []
        out = []
        prods = {}
        src_ids = []
        for i, ln in enumerate(lines, 1):
            pc = (ln.get("product") or "").strip()
            if not pc and not ln.get("qty") and not ln.get("amount"):
                continue
            p = prods.get(pc) or self.db.row("SELECT * FROM products WHERE code=%s", (pc,))
            if not p:
                raise BizError("第 %d 行：找不到商品 %s" % (i, pc or "（空白）"))
            prods[pc] = p
            if not p["active"] and not doc_id:
                raise BizError("第 %d 行：商品 %s 已停用" % (i, pc))
            if t["stock"] not in (0,) and code not in ("SI", "SR", "PI", "PR") and not p["is_stock"]:
                raise BizError("第 %d 行：%s 是不計庫存的勞務／費用類商品" % (i, p["name"]))
            q = qty(ln.get("qty"))
            pr = price(ln.get("price")) if t["price"] else D0
            row = dict(product=pc, name=(ln.get("name") or p["name"]).strip()[:80], unit=p["unit"], qty=q, price=pr,
                       amount=D0, net=D0, cost=D0, book_qty=D0, count_qty=None,
                       src_line_id=ln.get("src_line_id") or None, memo=(ln.get("memo") or "").strip()[:100])
            if t.get("amount_only"):
                row["qty"], row["price"] = D0, D0
                row["amount"] = money(ln.get("amount"))
                if not row["amount"]:
                    raise BizError("第 %d 行：請輸入提列金額（迴轉請輸入負數）" % i)
            elif h["discount_only"]:
                row["qty"], row["price"] = D0, D0
                row["amount"] = money(ln.get("amount"))
                if row["amount"] <= 0:
                    raise BizError("第 %d 行：請輸入折讓金額" % i)
            elif code == "CNT":
                row["count_qty"] = None if ln.get("count_qty") in (None, "") else qty(ln.get("count_qty"))
                row["book_qty"] = qty(ln.get("book_qty")) if ln.get("book_qty") not in (None, "") else \
                    self.stock_at(pc, h["warehouse"], h["doc_date"])
                row["qty"] = (row["count_qty"] - row["book_qty"]) if row["count_qty"] is not None else D0
            else:
                if code == "ADJ":
                    if not q:
                        raise BizError("第 %d 行：請輸入調整數量（增加為正、減少為負）" % i)
                elif q <= 0:
                    raise BizError("第 %d 行：數量要大於 0" % i)
                if pr < 0:
                    raise BizError("第 %d 行：單價不能是負數" % i)
                row["amount"] = money(q * pr)
            if row["src_line_id"]:
                src_ids.append((i, row))
            out.append(row)
        if not out:
            raise BizError("請至少輸入一筆明細")
        if code == "CNT":
            seen = set()
            for r in out:
                if r["product"] in seen:
                    raise BizError("盤點單同一商品只能出現一次：%s" % r["product"])
                seen.add(r["product"])
        self._check_sources(code, h, src_ids, doc_id)
        # 成本估計（出庫類用目前平均成本；月結時改成實際月加權平均）
        for r in out:
            p = prods[r["product"]]
            if code in ("SI", "SR", "OUT", "SCR"):
                r["cost"] = money(abs(r["qty"]) * (p["avg_cost"] or p["std_cost"] or 0))
            elif code == "ADJ":
                r["cost"] = money(r["qty"] * (p["avg_cost"] or p["std_cost"] or 0))
        return out

    def _check_sources(self, code, h, src_ids, doc_id):
        if not src_ids:
            return
        t = DOC_TYPES[code]
        ids = [r["src_line_id"] for _, r in src_ids]
        src = {r["id"]: r for r in self.db.rows(
            "SELECT l.id, l.qty, l.product, d.doc_type, d.partner, d.status, d.closed, d.doc_no FROM doc_lines l "
            "JOIN docs d ON d.id=l.doc_id WHERE l.id IN (%s)" % ",".join(str(int(i)) for i in ids))}
        done = {}
        for r in self.db.rows("SELECT l.src_line_id, SUM(l.qty) q FROM doc_lines l JOIN docs d ON d.id=l.doc_id "
                              "WHERE d.status=1 AND d.id<>%%s AND l.src_line_id IN (%s) GROUP BY l.src_line_id"
                              % ",".join(str(int(i)) for i in ids), (doc_id or 0,)):
            done[r["src_line_id"]] = r["q"] or D0
        used = {}
        for i, row in src_ids:
            s = src.get(row["src_line_id"])
            if not s or s["status"] != 1:
                raise BizError("第 %d 行：來源單據明細不存在或已作廢" % i)
            if s["doc_type"] not in t["src"] or s["partner"] != h["partner"] or s["product"] != row["product"]:
                raise BizError("第 %d 行：來源單據 %s 與本單的對象或商品不符" % (i, s["doc_no"]))
            if h["discount_only"] or code in ("SO",):
                continue
            used[s["id"]] = used.get(s["id"], D0) + row["qty"]
            remain = s["qty"] - done.get(s["id"], D0)
            if used[s["id"]] > remain:
                verb = "退回" if code in ("SR", "PR") else "轉出"
                raise BizError("第 %d 行：%s 超過來源單據 %s 可%s的數量（剩 %s）"
                               % (i, row["product"], s["doc_no"], verb, _q(remain)))

    def _totals(self, code, h, lines):
        t = DOC_TYPES[code]
        if t.get("header_only"):
            h["amount"], h["tax"], h["total"] = h["header_total"], D0, h["header_total"]
            return
        s = sum((ln["amount"] for ln in lines), D0)
        rate = h["tax_rate"] / 100 if h["tax_rate"] else D0
        if not t["tax"]:
            amount, tax = s, D0
        elif h["tax_type"] == 2:
            tax = money(s * rate / (1 + rate))
            amount = s - tax
        else:
            amount = s
            tax = money(s * rate) if h["tax_type"] == 1 else D0
        h["amount"], h["tax"], h["total"] = amount, tax, amount + tax
        # 未稅金額分攤到各行（內含稅時）
        if h["tax_type"] == 2 and s:
            left = amount
            for i, ln in enumerate(lines):
                if i == len(lines) - 1:
                    ln["net"] = left
                else:
                    ln["net"] = money(ln["amount"] * amount / s)
                    left -= ln["net"]
        else:
            for ln in lines:
                ln["net"] = ln["amount"]
        if code in ("IN", "OPEN"):
            for ln in lines:
                ln["cost"] = ln["amount"]
        if code == "PR" and not h["discount_only"]:
            for ln in lines:
                ln["cost"] = ln["net"]

    def _check_negative(self, comp, new_ch, old_ch):
        if comp.get("allow_negative"):
            return
        for (prod, wh), q in new_ch.items():
            delta = q - old_ch.get((prod, wh), D0)
            if delta >= 0:
                continue
            cur = self.stock_qty(prod, wh)
            if cur + delta < 0:
                name = self.db.value("SELECT name FROM products WHERE code=%s", (prod,)) or prod
                raise BizError("庫存不足：%s（%s）在 %s 倉只剩 %s，本單要出 %s。"
                               "若要允許負庫存，請到公司設定開啟" % (name, prod, wh, _q(cur), _q(-delta)))

    def _after_save(self, code, h, lines):
        """進貨更新最近進價；進貨／期初／其他入庫以移動平均估計平均成本（月結時再精算）。"""
        if code not in COST_IN or h.get("discount_only"):
            return
        for ln in lines:
            if not ln["qty"]:
                continue
            unit = ln["net"] / ln["qty"]
            p = self.db.row("SELECT avg_cost FROM products WHERE code=%s", (ln["product"],))
            onhand = self.stock_qty(ln["product"]) - ln["qty"]
            base = onhand if onhand > 0 else D0
            avg = ((base * (p["avg_cost"] or D0)) + ln["net"]) / (base + ln["qty"]) if base + ln["qty"] else unit
            sets = "avg_cost=%s" + (", last_cost=%s" if code == "PI" else "")
            args = (price(avg),) + ((price(unit),) if code == "PI" else ()) + (ln["product"],)
            self.db.exec("UPDATE products SET %s WHERE code=%%s" % sets, args)

    # ================================================================ 作廢、結案
    def void_doc(self, doc_id):
        h = self.db.row("SELECT * FROM docs WHERE id=%s", (doc_id,))
        if not h:
            raise BizError("單據不存在")
        t = DOC_TYPES[h["doc_type"]]
        self.need(t["func"])
        if h["status"] == 9:
            return
        if h["gl_batch_id"]:
            raise BizError("單據已拋轉會計，請先取消拋轉")
        if t["stock"] or h["doc_type"] == "WD":
            self._check_open(h["doc_date"])
        if self.db.value("SELECT 1 FROM receipt_applies a JOIN receipts r ON r.id=a.receipt_id WHERE a.doc_id=%s "
                         "AND r.status=1 LIMIT 1", (doc_id,)):
            raise BizError("此單據已有收付款沖帳，請先作廢收付款單")
        if self.db.value("SELECT d.doc_no FROM doc_lines l JOIN docs d ON d.id=l.doc_id WHERE d.status=1 AND "
                         "l.src_line_id IN (SELECT id FROM doc_lines WHERE doc_id=%s) LIMIT 1", (doc_id,)):
            raise BizError("此單據已有後續單據（轉出貨、進貨或退回），請先作廢後續單據")
        if h["doc_type"] == "CNT" and h["closed"]:
            raise BizError("盤點單已轉調整單，請先作廢該調整單")
        old_ch = self._old_moves(doc_id)
        comp = self.company()
        neg = {k: -v for k, v in old_ch.items()}
        self._check_negative(comp, neg, {})
        with self.db.transaction():
            self.db.exec("UPDATE docs SET status=9, voided_by=%s, voided_at=NOW() WHERE id=%s", (self.uid, doc_id))
            self.db.exec("DELETE FROM stock_moves WHERE doc_id=%s", (doc_id,))
            self._apply_stock(old_ch, -1)
            if h["doc_type"] == "ADJ" and h["src_doc_id"]:
                self.db.exec("UPDATE docs SET closed=0 WHERE id=%s AND doc_type='CNT'", (h["src_doc_id"],))
        self.log("doc_void", h["doc_no"])

    def close_order(self, doc_id, closed=True):
        h = self.db.row("SELECT * FROM docs WHERE id=%s", (doc_id,))
        if not h or not DOC_TYPES[h["doc_type"]].get("track"):
            raise BizError("只有訂單與採購單可以結案")
        self.need(DOC_TYPES[h["doc_type"]]["func"])
        self.db.exec("UPDATE docs SET closed=%s WHERE id=%s", (int(bool(closed)), doc_id))
        self.log("doc_close" if closed else "doc_reopen", h["doc_no"])

    # ================================================================ 帶單
    def open_source_lines(self, code, partner):
        """可帶入本單的來源明細（訂單未出貨、採購未進貨、已銷貨／進貨可退回）。"""
        t = DOC_TYPES[code]
        if not t["src"]:
            return []
        rows = self.db.rows(
            "SELECT l.*, d.doc_no, d.doc_date, d.doc_type, d.tax_type, d.warehouse FROM doc_lines l JOIN docs d "
            "ON d.id=l.doc_id WHERE d.status=1 AND d.closed=0 AND d.doc_type IN (%s) AND d.partner=%%s AND l.qty>0 "
            "ORDER BY d.doc_date, d.doc_no, l.line_no" % ",".join("'%s'" % s for s in t["src"]), (partner,))
        done = self._done_qty([r["id"] for r in rows])
        out = []
        for r in rows:
            r["remain"] = r["qty"] - done.get(r["id"], D0)
            if r["remain"] > 0 or code in ("SR", "PR"):
                if r["remain"] > 0:
                    out.append(r)
        return out

    def tracking(self, code, partner="", only_open=True):
        """訂單未出貨／採購單未進貨明細。"""
        rows = self.db.rows(
            "SELECT l.id, l.product, l.name, l.qty, l.price, d.id doc_id, d.doc_no, d.doc_date, d.due_date, d.partner, "
            "d.closed, p.short_name, p.name partner_name FROM doc_lines l JOIN docs d ON d.id=l.doc_id "
            "LEFT JOIN partners p ON p.kind=d.partner_kind AND p.code=d.partner WHERE d.status=1 AND d.doc_type=%s"
            + (" AND d.partner=%s" if partner else "") + " ORDER BY d.doc_date, d.doc_no, l.line_no",
            (code, partner) if partner else (code,))
        done = self._done_qty([r["id"] for r in rows])
        for r in rows:
            r["done"] = done.get(r["id"], D0)
            r["remain"] = r["qty"] - r["done"]
            r["partner_show"] = r["short_name"] or r["partner_name"]
            r["remain_amt"] = money(r["remain"] * r["price"])
        if only_open:
            rows = [r for r in rows if r["remain"] > 0 and not r["closed"]]
        return rows

    # ================================================================ 盤點
    def create_count(self, warehouse, d, category="", include_zero=False):
        """依倉庫（與類別）載入商品，帶出盤點日的帳面數量，建立盤點單。"""
        self.need("STK")
        d = date(d)
        sql = "SELECT code, name FROM products WHERE active=1 AND is_stock=1" + (" AND category=%s" if category else "")
        prods = self.db.rows(sql + " ORDER BY code", (category,) if category else ())
        lines = []
        for p in prods:
            bq = self.stock_at(p["code"], warehouse, d)
            if bq or include_zero:
                lines.append(dict(product=p["code"], book_qty=bq, count_qty=None))
        if not lines:
            raise BizError("此倉庫（類別）沒有庫存商品可以盤點；可勾選「包含零庫存商品」")
        return self.save_doc(None, dict(doc_type="CNT", doc_date=d, warehouse=warehouse,
                                        memo="盤點" + (" 類別 %s" % category if category else "")), lines)

    def refresh_count_book(self, doc_id):
        h = self.doc(doc_id)
        lines = [dict(product=ln["product"], count_qty=ln["count_qty"], memo=ln["memo"],
                      book_qty=self.stock_at(ln["product"], h["warehouse"], h["doc_date"], exclude_doc=doc_id))
                 for ln in h["lines"]]
        return self.save_doc(doc_id, h, lines)

    def count_to_adjust(self, doc_id, uncounted_as_zero=False):
        """盤差轉庫存調整單（日期同盤點日）。"""
        self.need("STK")
        h = self.doc(doc_id)
        if h["doc_type"] != "CNT" or h["status"] != 1:
            raise BizError("不是有效的盤點單")
        if h["closed"]:
            raise BizError("此盤點單已轉過調整單")
        missing = [ln for ln in h["lines"] if ln["count_qty"] is None]
        if missing and not uncounted_as_zero:
            raise BizError("還有 %d 項商品沒有輸入實盤數量（例如 %s）" % (len(missing), missing[0]["product"]))
        lines = []
        for ln in h["lines"]:
            cq = ln["count_qty"] if ln["count_qty"] is not None else D0
            diff = cq - ln["book_qty"]
            if diff:
                lines.append(dict(product=ln["product"], qty=diff, memo="帳面 %s 實盤 %s" % (_q(ln["book_qty"]), _q(cq))))
        if not lines:
            self.db.exec("UPDATE docs SET closed=1 WHERE id=%s", (doc_id,))
            self.log("count_done", h["doc_no"], "無盤差")
            return None
        adj = self.save_doc(None, dict(doc_type="ADJ", doc_date=h["doc_date"], warehouse=h["warehouse"],
                                       reason="盤點差異", memo="盤點單 %s 盤差轉入" % h["doc_no"],
                                       src_doc_id=doc_id), lines)
        self.db.exec("UPDATE docs SET closed=1 WHERE id=%s", (doc_id,))
        self.log("count_adjust", h["doc_no"])
        return adj


def _q(v):
    v = Decimal(str(v or 0))
    s = "{:,.3f}".format(v).rstrip("0").rstrip(".")
    return s or "0"
