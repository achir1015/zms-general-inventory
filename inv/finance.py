"""應收應付：未沖帳款、收款／付款沖帳（現金、匯款、票據、轉付、折讓、手續費、預收預付）、
對帳單、帳齡分析；應收／應付票據的託收、兌現、退票、撤票、作廢。
"""
import datetime as dt
from decimal import Decimal

from . import rocdate
from .core import D0, BizError, date, money

AR_TYPES = {"C": {"SI": 1, "SR": -1, "ARO": 1, "NTR": 1}, "V": {"PI": 1, "PR": -1, "APO": 1, "NTP": 1}}
R_KIND = {"R": "C", "P": "V"}            # 收款對客戶、付款對廠商
R_FUNC = {"R": "AR", "P": "AP"}
R_NAME = {"R": "收款單", "P": "付款單"}

NOTE_STATUS = {1: "收票（在庫）", 2: "託收中", 3: "已兌現", 4: "退票", 5: "已轉付", 6: "已撤回",
               11: "已開票", 12: "已兌現", 13: "作廢退回"}
# 票據異動：事件 → (票據種類, 允許的原狀態, 新狀態, 名稱)
NOTE_EVENTS = {
    "collect": ("R", (1,), 2, "託收"),
    "clear": ("R", (1, 2), 3, "兌現"),
    "bounce": ("R", (1, 2), 4, "退票"),
    "withdraw": ("R", (1,), 6, "撤票（退還客戶）"),
    "pay": ("P", (11,), 12, "兌現（付款）"),
    "cancel": ("P", (11,), 13, "作廢退回"),
}


class FinanceMixin:
    # ================================================================ 帳款
    def open_items(self, pk, partner, as_of=None, include_zero=False):
        """未沖帳款：每張應收（付）單據的金額、已沖、未沖（銷退／進退為負數）。"""
        types = AR_TYPES[pk]
        args = [pk, partner] if partner else [pk]
        sql = ("SELECT d.id, d.doc_type, d.doc_no, d.doc_date, d.due_date, d.partner, d.total, d.invoice_no, d.memo, "
               "COALESCE(p.short_name, p.name) partner_show FROM docs d LEFT JOIN partners p ON p.kind=d.partner_kind "
               "AND p.code=d.partner WHERE d.status=1 AND d.partner_kind=%s"
               + (" AND d.partner=%s" if partner else "") + " AND d.doc_type IN (%s)" % ",".join("'%s'" % t for t in types))
        if as_of:
            sql += " AND d.doc_date<=%s"
            args.append(date(as_of))
        rows = self.db.rows(sql + " ORDER BY d.doc_date, d.doc_no", tuple(args))
        ap = self._applied([r["id"] for r in rows], as_of)
        out = []
        for r in rows:
            sign = types[r["doc_type"]]
            r["amount"] = r["total"] * sign
            r["applied"] = ap.get(r["id"], D0)
            r["remain"] = r["amount"] - r["applied"]
            if r["remain"] or include_zero:
                out.append(r)
        return out

    def _applied(self, ids, as_of=None):
        if not ids:
            return {}
        sql = ("SELECT a.doc_id, SUM(a.amount) s FROM receipt_applies a JOIN receipts r ON r.id=a.receipt_id "
               "WHERE r.status=1 AND a.doc_id IN (%s)" % ",".join(str(int(i)) for i in ids))
        args = ()
        if as_of:
            sql += " AND r.r_date<=%s"
            args = (date(as_of),)
        return {r["doc_id"]: r["s"] or D0 for r in self.db.rows(sql + " GROUP BY a.doc_id", args)}

    def advance_balance(self, kind, partner, exclude_receipt=None):
        r = self.db.row("SELECT SUM(to_advance) a, SUM(use_advance) u FROM receipts WHERE status=1 AND kind=%s AND "
                        "partner=%s AND id<>%s", (kind, partner, exclude_receipt or 0))
        return (r["a"] or D0) - (r["u"] or D0)

    def balances(self, pk):
        """各客戶（廠商）應收（付）餘額、預收（付）、在庫票據。"""
        self.need("AR" if pk == "C" else "AP", 1)
        kind = "R" if pk == "C" else "P"
        rows = self.db.rows("SELECT code, name, short_name, phone, contact FROM partners WHERE kind=%s ORDER BY code",
                            (pk,))
        items = self.open_items(pk, "")
        bal = {}
        for it in items:
            bal[it["partner"]] = bal.get(it["partner"], D0) + it["remain"]
        adv = {r["partner"]: (r["a"] or D0) - (r["u"] or D0) for r in self.db.rows(
            "SELECT partner, SUM(to_advance) a, SUM(use_advance) u FROM receipts WHERE status=1 AND kind=%s "
            "GROUP BY partner", (kind,))}
        nst = (1, 2) if pk == "C" else (11,)
        notes = {r["partner"]: r["s"] for r in self.db.rows(
            "SELECT partner, SUM(amount) s FROM notes WHERE kind=%%s AND status IN (%s) GROUP BY partner"
            % ",".join(str(s) for s in nst), (kind,))}
        out = []
        for r in rows:
            b, a, n = bal.get(r["code"], D0), adv.get(r["code"], D0), notes.get(r["code"], D0)
            if b or a or n:
                r.update(balance=b, advance=a, notes=n, net=b - a, partner_show=r["short_name"] or r["name"])
                out.append(r)
        return out

    def aging(self, pk, as_of=None, by_due=False):
        """帳齡分析：0–30、31–60、61–90、91–180、180 天以上。"""
        self.need("AR" if pk == "C" else "AP", 1)
        as_of = date(as_of or rocdate.today())
        buckets = [(30, "d30"), (60, "d60"), (90, "d90"), (180, "d180"), (10 ** 6, "over")]
        res = {}
        for it in self.open_items(pk, "", as_of):
            base = (it["due_date"] or it["doc_date"]) if by_due else it["doc_date"]
            days = (as_of - base).days
            key = next(k for lim, k in buckets if days <= lim)
            r = res.setdefault(it["partner"], dict(partner=it["partner"], partner_show=it["partner_show"], total=D0,
                                                   d30=D0, d60=D0, d90=D0, d180=D0, over=D0))
            r[key] += it["remain"]
            r["total"] += it["remain"]
        return sorted((r for r in res.values() if r["total"]), key=lambda r: r["partner"])

    def statement(self, pk, partner, start, end):
        """對帳單：期初餘額、期間每筆單據與收付款、逐筆餘額。"""
        self.need("AR" if pk == "C" else "AP", 1)
        start, end = date(start), date(end)
        kind = "R" if pk == "C" else "P"
        types = AR_TYPES[pk]
        tlist = ",".join("'%s'" % t for t in types)
        before = self.db.rows("SELECT doc_type, SUM(total) s FROM docs WHERE status=1 AND partner_kind=%%s AND partner=%%s "
                              "AND doc_date<%%s AND doc_type IN (%s) GROUP BY doc_type" % tlist, (pk, partner, start))
        opening = sum((r["s"] * types[r["doc_type"]] for r in before), D0)
        opening -= self.db.value("SELECT SUM(applied) FROM receipts WHERE status=1 AND kind=%s AND partner=%s AND "
                                 "r_date<%s", (kind, partner, start)) or D0
        lines = []
        for d in self.db.rows("SELECT * FROM docs WHERE status=1 AND partner_kind=%%s AND partner=%%s AND doc_date "
                              "BETWEEN %%s AND %%s AND doc_type IN (%s) ORDER BY doc_date, doc_no" % tlist,
                              (pk, partner, start, end)):
            from .doctypes import DOC_TYPES
            lines.append(dict(date=d["doc_date"], no=d["doc_no"], kind=DOC_TYPES[d["doc_type"]]["short"],
                              memo=d["invoice_no"] and "發票 %s" % d["invoice_no"] or d["memo"],
                              add=d["total"] * types[d["doc_type"]], sub=D0, doc_id=d["id"]))
        for r in self.db.rows("SELECT * FROM receipts WHERE status=1 AND kind=%s AND partner=%s AND r_date BETWEEN "
                              "%s AND %s ORDER BY r_date, r_no", (kind, partner, start, end)):
            if r["applied"]:
                lines.append(dict(date=r["r_date"], no=r["r_no"], kind=R_NAME[kind][:2], memo=r["memo"], add=D0,
                                  sub=r["applied"], receipt_id=r["id"]))
        lines.sort(key=lambda x: (x["date"], x["no"]))
        bal = opening
        for x in lines:
            bal += x["add"] - x["sub"]
            x["balance"] = bal
        return dict(opening=opening, lines=lines, closing=bal,
                    total_add=sum((x["add"] for x in lines), D0), total_sub=sum((x["sub"] for x in lines), D0))

    # ================================================================ 收款／付款單
    def next_receipt_no(self, kind, d):
        prefix = ("RC" if kind == "R" else "PY") + rocdate.compact(d)
        last = self.db.value("SELECT MAX(r_no) FROM receipts WHERE r_no LIKE %s", (prefix + "%",))
        return "%s%03d" % (prefix, int(last[len(prefix):]) + 1 if last else 1)

    def receipt(self, rid):
        r = self.db.row("SELECT * FROM receipts WHERE id=%s", (rid,))
        if not r:
            raise BizError("收付款單不存在")
        r["applies"] = self.db.rows("SELECT a.*, d.doc_no, d.doc_type, d.doc_date, d.total FROM receipt_applies a "
                                    "JOIN docs d ON d.id=a.doc_id WHERE a.receipt_id=%s ORDER BY d.doc_date", (rid,))
        r["notes"] = self.db.rows("SELECT * FROM notes WHERE receipt_id=%s ORDER BY id", (rid,))
        r["endorsed"] = self.db.rows("SELECT * FROM notes WHERE endorse_receipt_id=%s ORDER BY id", (rid,))
        p = self.partner(R_KIND[r["kind"]], r["partner"]) or {}
        r["partner_name"] = p.get("name", "")
        return r

    def find_receipts(self, kind, start=None, end=None, partner="", status=1, limit=2000):
        self.need(R_FUNC[kind], 1)
        where, args = ["r.kind=%s"], [kind]
        if start:
            where.append("r.r_date>=%s")
            args.append(date(start))
        if end:
            where.append("r.r_date<=%s")
            args.append(date(end))
        if partner:
            where.append("r.partner=%s")
            args.append(partner)
        if status is not None:
            where.append("r.status=%s")
            args.append(status)
        rows = self.db.rows("SELECT r.*, COALESCE(p.short_name, p.name) partner_show FROM receipts r LEFT JOIN partners p "
                            "ON p.kind=%%s AND p.code=r.partner WHERE %s ORDER BY r.r_date DESC, r.r_no DESC LIMIT %%s"
                            % " AND ".join(where), (R_KIND[kind],) + tuple(args) + (limit,))
        for r in rows:
            r["total_in"] = r["cash"] + r["bank"] + r["notes_amt"] + r["endorsed_amt"]
        return rows

    def save_receipt(self, kind, header: dict, applies: list, notes: list = (), endorse: list = ()):
        """kind R 收款、P 付款。applies=[{doc_id, amount}]；notes=[{note_no, bank, account_no, amount, due_date}]；
        endorse＝轉付的應收票據 id（只限付款）。收付款單不能修改，錯了請作廢重開。"""
        if kind not in R_KIND:
            raise BizError("種類不正確")
        self.need(R_FUNC[kind])
        pk = R_KIND[kind]
        d = date(header.get("r_date") or rocdate.today())
        partner = (header.get("partner") or "").strip()
        if not partner or not self.partner(pk, partner):
            raise BizError("請選擇%s" % ("客戶" if pk == "C" else "廠商"))
        h = {k: money(header.get(k)) for k in ("cash", "bank", "fee", "discount", "use_advance", "to_advance")}
        for k, v in h.items():
            if v < 0:
                raise BizError("金額不能是負數")
        bank_account = (header.get("bank_account") or "").strip()
        if h["bank"] and not self.db.value("SELECT 1 FROM bank_accounts WHERE code=%s", (bank_account,)):
            raise BizError("有匯款／存款金額時，請選擇銀行帳戶")
        # 沖帳
        items = {it["id"]: it for it in self.open_items(pk, partner)}
        clean_ap = []
        for a in applies:
            amt = money(a.get("amount"))
            if not amt:
                continue
            it = items.get(int(a["doc_id"]))
            if not it:
                raise BizError("沖帳單據不存在、已沖清或不屬於此對象")
            if (amt > 0 > it["remain"]) or (amt < 0 < it["remain"]) or abs(amt) > abs(it["remain"]):
                raise BizError("%s 的沖帳金額 %s 超過未沖金額 %s" % (it["doc_no"], amt, it["remain"]))
            clean_ap.append((it["id"], amt))
        applied = sum((x[1] for x in clean_ap), D0)
        # 票據
        clean_notes = []
        for n in notes or ():
            amt = money(n.get("amount"))
            no = (n.get("note_no") or "").strip()
            if not no and not amt:
                continue
            if not no or amt <= 0:
                raise BizError("票據要有票號與金額")
            due = date(n.get("due_date"))
            clean_notes.append(dict(note_no=no, bank=(n.get("bank") or "").strip(),
                                    account_no=(n.get("account_no") or "").strip(), amount=amt, due_date=due,
                                    memo=(n.get("memo") or "").strip()))
        if kind == "P" and clean_notes and not bank_account:
            raise BizError("開立支票請選擇付款的銀行（甲存）帳戶")
        notes_amt = sum((n["amount"] for n in clean_notes), D0)
        endorsed, endorsed_amt = [], D0
        if endorse:
            if kind != "P":
                raise BizError("只有付款單可以轉付票據")
            for nid in endorse:
                n = self.db.row("SELECT * FROM notes WHERE id=%s", (nid,))
                if not n or n["kind"] != "R" or n["status"] != 1:
                    raise BizError("轉付的票據必須是「收票（在庫）」狀態的應收票據")
                endorsed.append(n)
                endorsed_amt += n["amount"]
        adv = self.advance_balance(kind, partner)
        if h["use_advance"] > adv:
            raise BizError("可用的%s只有 %s" % ("預收款" if kind == "R" else "預付款", adv))
        src = h["cash"] + h["bank"] + notes_amt + endorsed_amt + h["discount"] + h["use_advance"]
        use = applied + h["to_advance"]
        if kind == "R":
            src += h["fee"]
        else:
            use += h["fee"]
        if src != use:
            if kind == "R":
                raise BizError("金額不平衡：收到 %s（現金＋匯款＋票據＋手續費＋折讓＋使用預收）≠ 沖帳 %s＋轉預收 %s"
                               % (src, applied, h["to_advance"]))
            raise BizError("金額不平衡：付出 %s（現金＋匯款＋開票＋轉付＋折讓＋使用預付）≠ 沖帳 %s＋轉預付 %s＋手續費 %s"
                           % (src, applied, h["to_advance"], h["fee"]))
        if not src:
            raise BizError("請輸入收付款金額或沖帳明細")
        opening = bool(header.get("opening"))
        if opening:
            # 期初票據登錄：上線時手上已收（已開）未兌現的支票，會計系統已用開帳傳票記錄，所以不拋轉
            if h["cash"] or h["bank"] or h["fee"] or h["discount"] or h["use_advance"] or h["to_advance"] or endorsed:
                raise BizError("期初票據登錄只能用支票沖期初應收／應付")
            if any(items[i]["doc_type"] not in ("ARO", "APO") for i, _ in clean_ap):
                raise BizError("期初票據登錄只能沖「期初應收／期初應付」")
        with self.db.transaction():
            no = self.next_receipt_no(kind, d)
            rid = self.db.exec(
                "INSERT INTO receipts (r_no, kind, r_date, partner, cash, bank, bank_account, notes_amt, endorsed_amt, "
                "fee, discount, use_advance, to_advance, applied, memo, created_by, gl_batch_id) VALUES (%s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (no, kind, d, partner, h["cash"], h["bank"], bank_account, notes_amt, endorsed_amt, h["fee"],
                 h["discount"], h["use_advance"], h["to_advance"], applied, (header.get("memo") or "").strip()[:200],
                 self.uid, 0 if opening else None))
            self.db.exec_many("INSERT INTO receipt_applies (receipt_id, doc_id, amount) VALUES (%s, %s, %s)",
                              [(rid, i, a) for i, a in clean_ap])
            for n in clean_notes:
                self.db.exec("INSERT INTO notes (kind, note_no, bank, account_no, partner, amount, issue_date, due_date, "
                             "status, receipt_id, bank_account, memo) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                             "%s, %s)", (kind, n["note_no"], n["bank"], n["account_no"], partner, n["amount"], d,
                                         n["due_date"], 1 if kind == "R" else 11, rid,
                                         bank_account if kind == "P" else "", n["memo"]))
            for n in endorsed:
                self.db.exec("UPDATE notes SET status=5, endorse_receipt_id=%s WHERE id=%s", (rid, n["id"]))
                self.db.exec("INSERT INTO note_events (note_id, event, ev_date, prev_status, new_status, memo, created_by) "
                             "VALUES (%s, 'endorse', %s, 1, 5, %s, %s)", (n["id"], d, "轉付 %s %s" % (partner, no),
                                                                          self.uid))
        self.log("receipt_new", no, "%s %s" % (R_NAME[kind], applied))
        return rid

    def void_receipt(self, rid):
        r = self.db.row("SELECT * FROM receipts WHERE id=%s", (rid,))
        if not r:
            raise BizError("收付款單不存在")
        self.need(R_FUNC[r["kind"]])
        if r["status"] == 9:
            return
        if r["gl_batch_id"]:
            raise BizError("此單已拋轉會計，請先取消拋轉")
        notes = self.db.rows("SELECT * FROM notes WHERE receipt_id=%s", (rid,))
        _ = r["gl_batch_id"] == 0          # 期初票據登錄（不拋轉）也可以作廢
        for n in notes:
            if n["status"] not in (1, 11) or self.db.value("SELECT 1 FROM note_events WHERE note_id=%s LIMIT 1",
                                                            (n["id"],)):
                raise BizError("票據 %s 已有後續異動（%s），請先還原票據異動" % (n["note_no"], NOTE_STATUS[n["status"]]))
        if r["to_advance"] and self.advance_balance(r["kind"], r["partner"], exclude_receipt=rid) < 0:
            raise BizError("此單轉入的預收／預付款已被後續單據使用，請先作廢後續單據")
        with self.db.transaction():
            self.db.exec("UPDATE receipts SET status=9, voided_by=%s, voided_at=NOW() WHERE id=%s", (self.uid, rid))
            self.db.exec("DELETE FROM notes WHERE receipt_id=%s", (rid,))
            for n in self.db.rows("SELECT id FROM notes WHERE endorse_receipt_id=%s", (rid,)):
                self.db.exec("UPDATE notes SET status=1, endorse_receipt_id=NULL WHERE id=%s", (n["id"],))
                self.db.exec("DELETE FROM note_events WHERE note_id=%s AND event='endorse'", (n["id"],))
        self.log("receipt_void", r["r_no"])

    def auto_apply(self, pk, partner, amount):
        """自動沖帳：依日期先後沖到金額用完（銷退／進退負數先抵）。"""
        items = self.open_items(pk, partner)
        left = money(amount)
        out = []
        for it in sorted(items, key=lambda x: (x["remain"] > 0, x["doc_date"])):
            if it["remain"] < 0:
                out.append((it["id"], it["remain"]))
                left -= it["remain"]
        for it in sorted((x for x in items if x["remain"] > 0), key=lambda x: (x["doc_date"], x["doc_no"])):
            if left <= 0:
                break
            a = min(left, it["remain"])
            out.append((it["id"], a))
            left -= a
        return out

    # ================================================================ 票據
    def find_notes(self, kind, status=None, partner="", due_to=None, keyword=""):
        self.need("NOTE", 1)
        where, args = ["n.kind=%s"], [kind]
        if status:
            st = status if isinstance(status, (list, tuple)) else [status]
            where.append("n.status IN (%s)" % ",".join(str(int(s)) for s in st))
        if partner:
            where.append("n.partner=%s")
            args.append(partner)
        if due_to:
            where.append("n.due_date<=%s")
            args.append(date(due_to))
        if keyword:
            where.append("(n.note_no LIKE %s OR n.bank LIKE %s)")
            args += ["%" + keyword + "%"] * 2
        pk = R_KIND[kind]
        rows = self.db.rows("SELECT n.*, COALESCE(p.short_name, p.name) partner_show, r.r_no, e.r_no endorse_no FROM "
                            "notes n LEFT JOIN partners p ON p.kind=%%s AND p.code=n.partner LEFT JOIN receipts r ON "
                            "r.id=n.receipt_id LEFT JOIN receipts e ON e.id=n.endorse_receipt_id WHERE %s "
                            "ORDER BY n.due_date, n.id" % " AND ".join(where), (pk,) + tuple(args))
        for r in rows:
            r["status_name"] = NOTE_STATUS.get(r["status"], "")
        return rows

    def note_events(self, note_id):
        return self.db.rows("SELECT * FROM note_events WHERE note_id=%s ORDER BY id", (note_id,))

    def note_event(self, note_ids, event, ev_date, bank_account="", memo=""):
        """票據異動（可多張一起）。退票、撤票自動產生「退票轉應收」；應付票據作廢自動產生「票據作廢轉應付」。"""
        self.need("NOTE")
        if event not in NOTE_EVENTS:
            raise BizError("票據異動種類不正確")
        kind, allowed, new, title = NOTE_EVENTS[event]
        d = date(ev_date)
        if event == "collect" and not bank_account:
            raise BizError("請選擇%s的銀行帳戶" % title)
        if bank_account and not self.db.value("SELECT 1 FROM bank_accounts WHERE code=%s", (bank_account,)):
            raise BizError("銀行帳戶不存在")
        done, errs = [], []
        for nid in note_ids:
            n = self.db.row("SELECT * FROM notes WHERE id=%s", (nid,))
            try:
                if not n or n["kind"] != kind:
                    raise BizError("票據種類不符")
                if n["status"] not in allowed:
                    raise BizError("目前狀態是「%s」，不能%s" % (NOTE_STATUS[n["status"]], title))
                if d < n["issue_date"]:
                    raise BizError("異動日期不能早於收／開票日")
                acct = bank_account
                if event == "clear" and n["status"] == 2 and not acct:
                    acct = n["bank_account"]
                if event == "pay":
                    acct = n["bank_account"]
                if event == "clear" and not acct:
                    raise BizError("請選擇存入的銀行帳戶")
                with self.db.transaction():
                    self.db.exec("INSERT INTO note_events (note_id, event, ev_date, prev_status, new_status, "
                                 "bank_account, memo, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                                 (nid, event, d, n["status"], new, acct, memo[:100], self.uid))
                    if event in ("collect", "clear"):
                        self.db.exec("UPDATE notes SET status=%s, bank_account=%s WHERE id=%s", (new, acct, nid))
                    else:
                        self.db.exec("UPDATE notes SET status=%s WHERE id=%s", (new, nid))
                    if event in ("bounce", "withdraw", "cancel"):
                        self._note_reinstate(n, d, title)
                self.log("note_" + event, n["note_no"])
                done.append(n["note_no"])
            except BizError as e:
                errs.append("%s：%s" % (n["note_no"] if n else nid, e))
        return done, errs

    def _note_reinstate(self, n, d, title):
        t = "NTR" if n["kind"] == "R" else "NTP"
        pk = "C" if n["kind"] == "R" else "V"
        no = self.next_doc_no(t, d)
        self.db.exec("INSERT INTO docs (doc_type, doc_no, doc_date, partner_kind, partner, amount, total, memo, "
                     "ref_no, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                     (t, no, d, pk, n["partner"], n["amount"], n["amount"], "%s 票號 %s" % (title, n["note_no"]),
                      "NOTE:%d" % n["id"], self.uid))

    def undo_note_event(self, note_id):
        """還原票據最後一次異動（尚未拋轉會計時）。"""
        self.need("NOTE")
        ev = self.db.row("SELECT * FROM note_events WHERE note_id=%s ORDER BY id DESC LIMIT 1", (note_id,))
        if not ev:
            raise BizError("此票據沒有異動可以還原")
        if ev["event"] == "endorse":
            raise BizError("轉付是由付款單產生，請作廢該付款單")
        if ev["gl_batch_id"]:
            raise BizError("此異動已拋轉會計，請先取消拋轉")
        with self.db.transaction():
            if ev["event"] in ("bounce", "withdraw", "cancel"):
                doc = self.db.row("SELECT id, doc_no FROM docs WHERE ref_no=%s AND status=1 AND doc_type IN "
                                  "('NTR','NTP') ORDER BY id DESC LIMIT 1", ("NOTE:%d" % note_id,))
                if doc:
                    if self.db.value("SELECT 1 FROM receipt_applies a JOIN receipts r ON r.id=a.receipt_id WHERE "
                                     "a.doc_id=%s AND r.status=1 LIMIT 1", (doc["id"],)):
                        raise BizError("退票轉應收 %s 已被收款沖帳，請先作廢該收款單" % doc["doc_no"])
                    self.db.exec("UPDATE docs SET status=9, voided_by=%s, voided_at=NOW() WHERE id=%s",
                                 (self.uid, doc["id"]))
            self.db.exec("DELETE FROM note_events WHERE id=%s", (ev["id"],))
            self.db.exec("UPDATE notes SET status=%s WHERE id=%s", (ev["prev_status"], note_id))
        self.log("note_undo", note_id, ev["event"])

    def notes_due(self, days=14):
        to = rocdate.today() + dt.timedelta(days=days)
        r = self.db.rows("SELECT kind, COUNT(*) c, SUM(amount) s FROM notes WHERE status IN (1,2,11) AND due_date<=%s "
                         "GROUP BY kind", (to,))
        return {x["kind"]: (x["c"], x["s"] or Decimal(0)) for x in r}
