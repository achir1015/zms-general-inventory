"""會計拋轉：把進銷存的交易依「會計科目對照」產生傳票，送到「資料助秘之一般公司會計」。

送法有兩種：
1. 拋轉檔（.zmsgl，JSON）：在會計系統「傳票作業 → 進銷存拋轉」匯入。
2. 直接傳送：會計系統開著「手機連線服務」時，用會計系統的帳號密碼直接送過去（會計端同樣做檢查）。

會計端匯入後產生「未審核」傳票（會計系統若設定即時過帳則直接過帳），由會計人員審核過帳；
同一批次（batch_uid）不會被重複匯入。拋轉過的單據會被鎖住，要修改須先取消拋轉。

分錄規則（永續盤存制 P；定期盤存制 D 的差異註明）：
* 銷貨：借 應收帳款／貸 銷貨收入、銷項稅額
* 銷退：借 銷貨退回（折讓：銷貨折讓）、銷項稅額／貸 應收帳款
* 進貨：借 存貨（D：進貨）、進項稅額／貸 應付帳款；不計庫存的品項借 其他費用
* 進退：借 應付帳款／貸 存貨（D：進貨退出；折讓 D：進貨折讓）、進項稅額
* 收款：借 現金、銀行存款、應收票據、手續費、銷貨折讓、預收貨款／貸 應收帳款、預收貨款
* 付款：借 應付帳款、預付貨款、手續費／貸 現金、銀行存款、應付票據、應收票據（轉付）、進貨折讓、預付貨款
* 票據：應收兌現 借 銀行／貸 應收票據；退票、撤票 借 應收帳款／貸 應收票據；
        應付兌現 借 應付票據／貸 銀行；應付作廢 借 應付票據／貸 應付帳款
* 庫存月結（每月一張，需先完成成本月結）：
  P：借 銷貨成本／貸 存貨；報廢 借 存貨報廢損失；領用 借 其他費用（或單據指定科目）；
     盤盈虧與數量修正 借貸 存貨盤盈虧；其他入庫 借 存貨／貸 其他收入（或單據指定科目）
  D：借 銷貨成本（＝進貨－進退－折讓－存貨增加）、進貨退出、進貨折讓／貸 進貨；存貨增減 借貸 存貨
* 呆料跌價提列：借 存貨跌價及呆滯損失／貸 備抵存貨跌價損失（迴轉相反）
"""
import datetime as dt
import json
import time
import urllib.error
import urllib.request
import uuid
from decimal import Decimal

from . import APP_NAME, APP_VERSION, rocdate
from .core import D0, BizError, date, money
from .costing import ym_add, ym_range
from .doctypes import DOC_TYPES
from .seed import GL_DEFAULT, GL_MAP

SCOPES = {"sales": "銷貨／銷退", "purchase": "進貨／進退", "receipt": "收款", "payment": "付款", "note": "票據異動",
          "stock": "庫存月結成本", "wd": "呆料跌價提列"}
EV_TITLE = {"clear": "應收票據兌現", "bounce": "退票", "withdraw": "撤票", "pay": "應付票據兌現", "cancel": "應付票據作廢"}
FORMAT = "zms-gl"


class GLMixin:
    # ================================================================ 科目對照
    def gl_map(self):
        rows = {r["k"]: r for r in self.db.rows("SELECT * FROM gl_map")}
        out = []
        for k, a, n, desc in GL_MAP:
            r = rows.get(k) or {}
            out.append(dict(k=k, account=r.get("account") or a, name=r.get("name") or n, desc=desc, default=a))
        return out

    def save_gl_map(self, items):
        self.need("GL")
        for it in items:
            k = it["k"]
            if k not in GL_DEFAULT:
                continue
            a = (it.get("account") or "").strip()
            n = (it.get("name") or "").strip()
            if not (a.isdigit() and len(a) == 4):
                raise BizError("%s 的科目代號要是四碼明細科目" % GL_DEFAULT[k][1])
            self.db.exec("REPLACE INTO gl_map (k, account, name) VALUES (%s, %s, %s)", (k, a, n or GL_DEFAULT[k][1]))
        self.log("gl_map")

    def _acct(self):
        return {r["k"]: (r["account"], r["name"]) for r in self.gl_map()}

    # ================================================================ 待拋轉清單
    def gl_pending(self, date_from, date_to):
        """各類別尚未拋轉的筆數（首頁與拋轉畫面用）。"""
        f, t = date(date_from), date(date_to)
        cnt = {}
        doc_scope = {"SI": "sales", "SR": "sales", "PI": "purchase", "PR": "purchase", "WD": "wd"}
        for r in self.db.rows("SELECT doc_type, COUNT(*) c FROM docs WHERE status=1 AND gl_batch_id IS NULL AND "
                              "doc_date BETWEEN %s AND %s AND doc_type IN ('SI','SR','PI','PR','WD') GROUP BY doc_type",
                              (f, t)):
            k = doc_scope[r["doc_type"]]
            cnt[k] = cnt.get(k, 0) + r["c"]
        for r in self.db.rows("SELECT kind, COUNT(*) c FROM receipts WHERE status=1 AND gl_batch_id IS NULL AND "
                              "r_date BETWEEN %s AND %s GROUP BY kind", (f, t)):
            cnt["receipt" if r["kind"] == "R" else "payment"] = r["c"]
        cnt["note"] = self.db.value("SELECT COUNT(*) FROM note_events WHERE gl_batch_id IS NULL AND event IN "
                                    "('clear','bounce','withdraw','pay','cancel') AND ev_date BETWEEN %s AND %s",
                                    (f, t)) or 0
        cnt["stock"] = len(self._stock_months(f, t))
        return cnt

    def gl_first_pending(self):
        """最早一筆尚未拋轉的交易日期（拋轉畫面預設的起始日）。"""
        ds = [self.db.value("SELECT MIN(doc_date) FROM docs WHERE status=1 AND gl_batch_id IS NULL AND doc_type IN "
                            "('SI','SR','PI','PR','WD')"),
              self.db.value("SELECT MIN(r_date) FROM receipts WHERE status=1 AND gl_batch_id IS NULL"),
              self.db.value("SELECT MIN(ev_date) FROM note_events WHERE gl_batch_id IS NULL AND event IN "
                            "('clear','bounce','withdraw','pay','cancel')")]
        ym = self.db.value("SELECT MIN(ym) FROM cost_closes WHERE gl_batch_id IS NULL")
        if ym:
            ds.append(ym_range(ym)[0])
        ds = [d for d in ds if d]
        return min(ds) if ds else None

    def _stock_months(self, f, t):
        out = []
        for r in self.db.rows("SELECT ym FROM cost_closes WHERE gl_batch_id IS NULL ORDER BY ym"):
            first, last = ym_range(r["ym"])
            if f <= last <= t:
                out.append(r["ym"])
        return out

    # ================================================================ 產生分錄
    def gl_preview(self, date_from, date_to, scopes=None, mode=None):
        """回傳 (傳票清單, 來源清單)；不寫入資料庫。"""
        self.need("GL", 1)
        f, t = date(date_from), date(date_to)
        if f > t:
            raise BizError("起始日不能晚於結束日")
        scopes = set(scopes or SCOPES)
        A = self._acct()
        comp = self.company()
        periodic = comp.get("inventory_system") == "D"
        mode = mode or comp.get("gl_mode") or "doc"
        names = {(p["kind"], p["code"]): p["short_name"] or p["name"] for p in
                 self.db.rows("SELECT kind, code, name, short_name FROM partners")}
        banks = {b["code"]: b for b in self.db.rows("SELECT * FROM bank_accounts")}
        vouchers, sources = [], []

        def V(ref, d, memo, cat, lines, src):
            lines = [ln for ln in lines if ln["debit"] or ln["credit"]]
            if not lines:
                return
            vouchers.append(dict(ref=ref, date=d, memo=memo[:100], cat=cat, lines=lines))
            sources.append(src)

        def L(key_or_acct, summary, amt, side, pk="", partner="", dept=""):
            acct = A[key_or_acct][0] if key_or_acct in A else key_or_acct
            amt = money(amt)
            if amt < 0:
                amt, side = -amt, ("C" if side == "D" else "D")
            return dict(account=acct, summary=summary[:100], debit=amt if side == "D" else D0,
                        credit=amt if side == "C" else D0, partner_kind=pk if partner else "", partner=partner,
                        dept=dept)

        # ---- 銷貨、銷退、進貨、進退、跌價提列
        types = []
        if "sales" in scopes:
            types += ["SI", "SR"]
        if "purchase" in scopes:
            types += ["PI", "PR"]
        if "wd" in scopes:
            types += ["WD"]
        if types:
            docs = self.db.rows("SELECT * FROM docs WHERE status=1 AND gl_batch_id IS NULL AND doc_date BETWEEN %%s AND "
                                "%%s AND doc_type IN (%s) ORDER BY doc_date, doc_no"
                                % ",".join("'%s'" % x for x in types), (f, t))
            nonstock = {}
            if docs:
                for r in self.db.rows("SELECT l.doc_id, SUM(l.net) s FROM doc_lines l JOIN products p ON "
                                      "p.code=l.product WHERE p.is_stock=0 AND l.doc_id IN (%s) GROUP BY l.doc_id"
                                      % ",".join(str(d["id"]) for d in docs)):
                    nonstock[r["doc_id"]] = r["s"] or D0
            for d in docs:
                code, pn = d["doc_type"], names.get((d["partner_kind"], d["partner"]), d["partner"])
                s = "%s %s %s" % (DOC_TYPES[code]["short"], d["doc_no"], pn)
                if d["invoice_no"]:
                    s += " 發票" + d["invoice_no"]
                p, dp = d["partner"], d["dept"]
                if code == "SI":
                    ls = [L("AR", s, d["total"], "D", "C", p, dp), L("SALES", s, d["amount"], "C", dept=dp),
                          L("OUT_TAX", s, d["tax"], "C", dept=dp)]
                elif code == "SR":
                    ls = [L("SALES_ALLOW" if d["discount_only"] else "SALES_RET", s, d["amount"], "D", dept=dp),
                          L("OUT_TAX", s, d["tax"], "D", dept=dp), L("AR", s, d["total"], "C", "C", p, dp)]
                elif code == "PI":
                    ns = nonstock.get(d["id"], D0)
                    ls = [L("PURCHASE" if periodic else "INV", s, d["amount"] - ns, "D", dept=dp),
                          L("USE_OUT", s + "（費用品項）", ns, "D", dept=dp),
                          L("IN_TAX", s, d["tax"], "D", dept=dp), L("AP", s, d["total"], "C", "V", p, dp)]
                elif code == "PR":
                    ns = nonstock.get(d["id"], D0)
                    k = ("PUR_ALLOW" if d["discount_only"] else "PUR_RET") if periodic else "INV"
                    ls = [L("AP", s, d["total"], "D", "V", p, dp), L(k, s, d["amount"] - ns, "C", dept=dp),
                          L("USE_OUT", s + "（費用品項）", ns, "C", dept=dp), L("IN_TAX", s, d["tax"], "C", dept=dp)]
                else:   # WD
                    tot = self.db.value("SELECT SUM(amount) FROM doc_lines WHERE doc_id=%s", (d["id"],)) or D0
                    s = "呆料跌價%s %s" % ("提列" if tot >= 0 else "迴轉", d["doc_no"])
                    ls = [L("WRITE_DOWN", s, tot, "D"), L("INV_ALLOW", s, tot, "C")]
                cat = {"SI": "sales", "SR": "sales", "PI": "purchase", "PR": "purchase", "WD": "wd"}[code]
                V(d["doc_no"], d["doc_date"], s, cat, ls, ("doc", d["id"]))
        # ---- 收款、付款
        kinds = [k for k, sc in (("R", "receipt"), ("P", "payment")) if sc in scopes]
        for kind in kinds:
            for r in self.db.rows("SELECT * FROM receipts WHERE status=1 AND gl_batch_id IS NULL AND kind=%s AND "
                                  "r_date BETWEEN %s AND %s ORDER BY r_date, r_no", (kind, f, t)):
                pk = "C" if kind == "R" else "V"
                p = r["partner"]
                s = "%s %s %s" % ("收款" if kind == "R" else "付款", r["r_no"], names.get((pk, p), p))
                bank = banks.get(r["bank_account"], {}).get("gl_account") or "1113"
                if kind == "R":
                    ls = [L("CASH", s, r["cash"], "D"), L(bank, s, r["bank"], "D"),
                          L("AR_NOTE", s, r["notes_amt"], "D", "C", p), L("BANK_FEE", s, r["fee"], "D"),
                          L("SALES_ALLOW", s + " 折讓", r["discount"], "D"),
                          L("ADVANCE", s + " 使用預收", r["use_advance"], "D", "C", p),
                          L("AR", s, r["applied"], "C", "C", p), L("ADVANCE", s + " 轉預收", r["to_advance"], "C", "C", p)]
                else:
                    ls = [L("AP", s, r["applied"], "D", "V", p), L("PREPAY", s + " 轉預付", r["to_advance"], "D", "V", p),
                          L("BANK_FEE", s, r["fee"], "D"), L("CASH", s, r["cash"], "C"), L(bank, s, r["bank"], "C"),
                          L("AP_NOTE", s, r["notes_amt"], "C", "V", p),
                          L("PUR_ALLOW", s + " 折讓", r["discount"], "C"),
                          L("PREPAY", s + " 使用預付", r["use_advance"], "C", "V", p)]
                    for n in self.db.rows("SELECT * FROM notes WHERE endorse_receipt_id=%s", (r["id"],)):
                        ls.append(L("AR_NOTE", "%s 轉付票據 %s" % (s, n["note_no"]), n["amount"], "C", "C", n["partner"]))
                V(r["r_no"], r["r_date"], s, "receipt" if kind == "R" else "payment", ls, ("receipt", r["id"]))
        # ---- 票據異動
        if "note" in scopes:
            for e in self.db.rows("SELECT e.*, n.note_no, n.partner, n.amount, n.kind, n.bank_account nbank FROM "
                                  "note_events e JOIN notes n ON n.id=e.note_id WHERE e.gl_batch_id IS NULL AND e.event "
                                  "IN ('clear','bounce','withdraw','pay','cancel') AND e.ev_date BETWEEN %s AND %s "
                                  "ORDER BY e.ev_date, e.id", (f, t)):
                p = e["partner"]
                pk = "C" if e["kind"] == "R" else "V"
                s = "%s 票號 %s %s" % (EV_TITLE[e["event"]], e["note_no"], names.get((pk, p), p))
                bank = banks.get(e["bank_account"] or e["nbank"], {}).get("gl_account") or "1113"
                ev = e["event"]
                if ev == "clear":
                    ls = [L(bank, s, e["amount"], "D"), L("AR_NOTE", s, e["amount"], "C", "C", p)]
                elif ev in ("bounce", "withdraw"):
                    ls = [L("AR", s, e["amount"], "D", "C", p), L("AR_NOTE", s, e["amount"], "C", "C", p)]
                elif ev == "pay":
                    ls = [L("AP_NOTE", s, e["amount"], "D", "V", p), L(bank, s, e["amount"], "C")]
                else:
                    ls = [L("AP_NOTE", s, e["amount"], "D", "V", p), L("AP", s, e["amount"], "C", "V", p)]
                V("NOTE%d" % e["id"], e["ev_date"], s, "note", ls, ("note", e["id"]))
        # ---- 庫存月結
        if "stock" in scopes:
            for ym in self._stock_months(f, t):
                ls = self._stock_lines(ym, periodic, L)
                first, last = ym_range(ym)
                V("COST" + ym, last, "%s 庫存月結成本" % rocdate.ym_show(ym), "stock", ls, ("cost", ym))
        if mode == "day":
            vouchers, sources = _merge_daily(vouchers, sources)
        for v in vouchers:
            td = sum((x["debit"] for x in v["lines"]), D0)
            tc = sum((x["credit"] for x in v["lines"]), D0)
            if td != tc:
                raise BizError("%s 借貸不平衡（借 %s、貸 %s），請檢查單據金額" % (v["ref"], td, tc))
            v["total"] = td
            v["type"] = "轉"
        return vouchers, sources

    def _stock_lines(self, ym, periodic, L):
        first, last = ym_range(ym)
        s = "%s 庫存月結" % rocdate.ym_show(ym)
        if periodic:
            r = self.db.row("SELECT SUM(close_amt) c, SUM(open_amt) o FROM cost_months WHERE ym=%s", (ym,))
            # 期初庫存單（OPEN）是開帳資料，不算本月存貨增加
            opening = self.db.value("SELECT SUM(l.amount) FROM doc_lines l JOIN docs d ON d.id=l.doc_id JOIN products p "
                                    "ON p.code=l.product WHERE d.status=1 AND p.is_stock=1 AND d.doc_type='OPEN' AND "
                                    "d.doc_date BETWEEN %s AND %s", (first, last)) or D0
            delta = (r["c"] or D0) - (r["o"] or D0) - opening
            pur = self.db.row(
                "SELECT SUM(CASE WHEN d.doc_type='PI' THEN l.net ELSE 0 END) p, SUM(CASE WHEN d.doc_type='PR' AND "
                "d.discount_only=0 THEN l.net ELSE 0 END) r, SUM(CASE WHEN d.doc_type='PR' AND d.discount_only=1 THEN "
                "l.net ELSE 0 END) a FROM doc_lines l JOIN docs d ON d.id=l.doc_id JOIN products p ON p.code=l.product "
                "WHERE d.status=1 AND p.is_stock=1 AND d.doc_type IN ('PI','PR') AND d.doc_date BETWEEN %s AND %s",
                (first, last))
            P, R, A_ = pur["p"] or D0, pur["r"] or D0, pur["a"] or D0
            cogs = P - R - A_ - delta
            return [L("COGS", s + " 銷貨成本", cogs, "D"), L("PUR_RET", s + " 結轉進貨退出", R, "D"),
                    L("PUR_ALLOW", s + " 結轉進貨折讓", A_, "D"), L("PURCHASE", s + " 結轉進貨", P, "C"),
                    L("INV", s + " 存貨增減", delta, "D")]
        rows = self.db.rows("SELECT d.doc_type, d.gl_account, l.cost, l.amount FROM doc_lines l JOIN docs d ON "
                            "d.id=l.doc_id JOIN products p ON p.code=l.product WHERE d.status=1 AND p.is_stock=1 AND "
                            "d.discount_only=0 AND d.doc_type IN ('SI','SR','OUT','SCR','ADJ','IN') AND d.doc_date "
                            "BETWEEN %s AND %s", (first, last))
        cogs = scrap = diff = D0
        use, other_in = {}, {}
        for r in rows:
            t = r["doc_type"]
            if t == "SI":
                cogs += r["cost"]
            elif t == "SR":
                cogs -= r["cost"]
            elif t == "SCR":
                scrap += r["cost"]
            elif t == "ADJ":
                diff += r["cost"]                     # 增加為正（盤盈）
            elif t == "OUT":
                k = r["gl_account"] or "USE_OUT"
                use[k] = use.get(k, D0) + r["cost"]
            elif t == "IN":
                k = r["gl_account"] or "OTHER_IN"
                other_in[k] = other_in.get(k, D0) + r["amount"]
        ls = [L("COGS", s + " 銷貨成本", cogs, "D"), L("INV", s + " 銷貨成本", cogs, "C"),
              L("SCRAP", s + " 報廢", scrap, "D"), L("INV", s + " 報廢", scrap, "C"),
              L("INV", s + " 盤盈虧／數量修正", diff, "D"), L("COUNT_DIFF", s + " 盤盈虧／數量修正", diff, "C")]
        for k, v in use.items():
            ls += [L(k, s + " 領用出庫", v, "D"), L("INV", s + " 領用出庫", v, "C")]
        for k, v in other_in.items():
            ls += [L("INV", s + " 其他入庫", v, "D"), L(k, s + " 其他入庫", v, "C")]
        return ls

    def _stock_month_empty(self, ym):
        """該月月結沒有任何成本分錄（例如只有期初庫存）。"""
        periodic = self.company().get("inventory_system") == "D"
        amounts = self._stock_lines(ym, periodic, lambda k, s, amt, side, *a, **kw: money(amt))
        return not any(amounts)

    # ================================================================ 批次
    def next_batch_no(self):
        prefix = "GL" + rocdate.compact(rocdate.today())
        last = self.db.value("SELECT MAX(batch_no) FROM gl_batches WHERE batch_no LIKE %s", (prefix + "%",))
        return "%s%03d" % (prefix, int(last[len(prefix):]) + 1 if last else 1)

    def create_gl_batch(self, date_from, date_to, scopes=None, mode=None):
        self.need("GL")
        vouchers, sources = self.gl_preview(date_from, date_to, scopes, mode)
        if "stock" in set(scopes or SCOPES):
            # 沒有任何成本分錄的月份（例如只有期初庫存的月份）標記為「不需拋轉」（gl_batch_id=0）
            refs = {v["ref"] for v in vouchers}
            for ym in self._stock_months(date(date_from), date(date_to)):
                if "COST" + ym not in refs:
                    self.db.exec("UPDATE cost_closes SET gl_batch_id=0 WHERE ym=%s AND gl_batch_id IS NULL", (ym,))
        if not vouchers:
            raise BizError("這段期間沒有尚未拋轉的交易")
        comp = self.company()
        A = self._acct()
        no = self.next_batch_no()
        uid = "%s-%s" % (comp.get("tax_id") or "ZMS", uuid.uuid4().hex)
        used = {x["account"] for v in vouchers for x in v["lines"]}
        acct_names = {a: n for a, n in A.values()}
        for b in self.db.rows("SELECT gl_account, name FROM bank_accounts"):
            acct_names.setdefault(b["gl_account"], b["name"])
        partners = sorted({(x["partner_kind"], x["partner"]) for v in vouchers for x in v["lines"] if x["partner"]})
        pinfo = []
        for k, c in partners:
            p = self.partner(k, c) or {}
            pinfo.append({key: str(p.get(key) or "") for key in ("name", "short_name", "tax_id", "contact", "phone",
                                                                 "address")} | dict(kind=k, code=c))
        depts = sorted({x["dept"] for v in vouchers for x in v["lines"] if x["dept"]})
        dinfo = [dict(code=d, name=self.db.value("SELECT name FROM departments WHERE code=%s", (d,)) or d) for d in depts]
        payload = dict(
            format=FORMAT, version=1, batch_uid=uid, batch_no=no, source=APP_NAME, source_version=APP_VERSION,
            company=dict(name=comp.get("name", ""), tax_id=comp.get("tax_id", "")),
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"), created_by=self.user["name"] if self.user else "",
            date_from=date(date_from).isoformat(), date_to=date(date_to).isoformat(),
            accounts=[dict(code=a, name=acct_names.get(a, "")) for a in sorted(used)],
            partners=pinfo, departments=dinfo,
            vouchers=[dict(ref=v["ref"], date=v["date"].isoformat(), type=v["type"], memo=v["memo"],
                           lines=[dict(account=x["account"], summary=x["summary"], debit=str(x["debit"]),
                                       credit=str(x["credit"]), partner_kind=x["partner_kind"], partner=x["partner"],
                                       dept=x["dept"]) for x in v["lines"]]) for v in vouchers])
        total = sum((v["total"] for v in vouchers), D0)
        sc = ",".join(sorted(set(scopes or SCOPES)))
        with self.db.transaction():
            bid = self.db.exec("INSERT INTO gl_batches (batch_no, batch_uid, date_from, date_to, scope, voucher_count, "
                               "total, payload, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                               (no, uid, date(date_from), date(date_to), sc, len(vouchers), total,
                                json.dumps(payload, ensure_ascii=False), self.uid))
            self._mark_sources(sources, bid)
        self.log("gl_batch", no, "%d 張傳票 %s" % (len(vouchers), total))
        return bid

    def _mark_sources(self, sources, bid):
        for src in sources:
            for kind, key in (src if isinstance(src, list) else [src]):
                if kind == "doc":
                    self.db.exec("UPDATE docs SET gl_batch_id=%s WHERE id=%s", (bid, key))
                elif kind == "receipt":
                    self.db.exec("UPDATE receipts SET gl_batch_id=%s WHERE id=%s", (bid, key))
                elif kind == "note":
                    self.db.exec("UPDATE note_events SET gl_batch_id=%s WHERE id=%s", (bid, key))
                elif kind == "cost":
                    self.db.exec("UPDATE cost_closes SET gl_batch_id=%s WHERE ym=%s", (bid, key))

    def gl_batches(self, limit=200):
        self.need("GL", 1)
        return self.db.rows("SELECT id, batch_no, batch_uid, date_from, date_to, scope, method, status, voucher_count, "
                            "total, result, created_by, created_at FROM gl_batches ORDER BY id DESC LIMIT %s", (limit,))

    def gl_batch(self, bid):
        b = self.db.row("SELECT * FROM gl_batches WHERE id=%s", (bid,))
        if not b:
            raise BizError("拋轉批次不存在")
        b["data"] = json.loads(b["payload"] or "{}")
        return b

    def export_gl_batch(self, bid, path):
        self.need("GL")
        b = self.gl_batch(bid)
        if b["status"] == 9:
            raise BizError("此批次已取消")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(b["data"], f, ensure_ascii=False, indent=1)
        self.db.exec("UPDATE gl_batches SET method='file', result=%s WHERE id=%s",
                     ("已匯出拋轉檔 %s" % time.strftime("%Y-%m-%d %H:%M"), bid))
        self.log("gl_export", b["batch_no"], path)

    def cancel_gl_batch(self, bid, remote=None):
        """取消拋轉：解除單據鎖定。已直接送到會計系統的批次，會先請會計系統刪除（傳票須仍未審核）。"""
        self.need("GL")
        b = self.gl_batch(bid)
        if b["status"] == 9:
            return
        if b["status"] == 2 and remote:
            remote.call("cancel_gl_import", b["batch_uid"])
        with self.db.transaction():
            for table in ("docs", "receipts", "note_events", "cost_closes"):
                self.db.exec("UPDATE %s SET gl_batch_id=NULL WHERE gl_batch_id=%%s" % table, (bid,))
            self.db.exec("UPDATE gl_batches SET status=9, result=CONCAT(result, ' ／已取消') WHERE id=%s", (bid,))
        self.log("gl_cancel", b["batch_no"])

    def send_gl_batch(self, bid, remote):
        """直接傳送到會計系統（remote＝AcctClient）。"""
        self.need("GL")
        b = self.gl_batch(bid)
        if b["status"] == 9:
            raise BizError("此批次已取消")
        res = remote.call("import_gl_batch", b["data"])
        nos = res.get("voucher_nos") or []
        text = "已送達會計系統：%d 張傳票 %s" % (len(nos), ("%s～%s" % (nos[0], nos[-1])) if nos else "")
        self.db.exec("UPDATE gl_batches SET status=2, method='api', result=%s WHERE id=%s", (text[:500], bid))
        self.log("gl_send", b["batch_no"], text)
        return res


def _merge_daily(vouchers, sources):
    """每日彙總：同一天同一類別合併成一張傳票，相同科目＋往來對象＋借貸方向的金額相加。"""
    groups = {}
    order = []
    cat_name = {"sales": "銷貨", "purchase": "進貨", "receipt": "收款", "payment": "付款", "note": "票據", "wd": "跌價",
                "stock": "庫存月結"}
    for v, s in zip(vouchers, sources):
        if v["cat"] == "stock":
            key = ("stock", v["ref"])
        else:
            key = (v["date"], v["cat"])
        if key not in groups:
            groups[key] = dict(ref="", date=v["date"], cat=v["cat"], refs=[], lines={}, srcs=[])
            order.append(key)
        g = groups[key]
        g["refs"].append(v["ref"])
        g["srcs"].append(s)
        for x in v["lines"]:
            side = "D" if x["debit"] else "C"
            k = (x["account"], x["partner_kind"], x["partner"], x["dept"], side)
            if k not in g["lines"]:
                g["lines"][k] = dict(x, summary="", debit=D0, credit=D0, n=0)
            g["lines"][k]["debit"] += x["debit"]
            g["lines"][k]["credit"] += x["credit"]
            g["lines"][k]["n"] += 1
    outv, outs = [], []
    for key in order:
        g = groups[key]
        name = cat_name.get(g["cat"], g["cat"])
        if g["cat"] == "stock":
            v = next(v for v in vouchers if v["ref"] == g["refs"][0])
            outv.append(v)
        else:
            memo = "%s %s 彙總 %d 筆（%s～%s）" % (rocdate.show(g["date"]), name, len(g["refs"]), g["refs"][0],
                                              g["refs"][-1])
            lines = []
            for x in g["lines"].values():
                x["summary"] = "%s %s 彙總 %d 筆" % (rocdate.show(g["date"]), name, x.pop("n"))
                lines.append(x)
            lines.sort(key=lambda x: (0 if x["debit"] else 1, x["account"]))
            outv.append(dict(ref="%s-%s" % (g["cat"].upper(), rocdate.compact(g["date"])), date=g["date"], memo=memo,
                             cat=g["cat"], lines=lines))
        outs.append(g["srcs"])
    return outv, outs


# ================================================================ 會計系統連線（直接傳送）
class AcctClient:
    """連到「資料助秘之一般公司會計」的手機連線服務（http://電腦:8765）。"""

    def __init__(self, url, uid, pw, timeout=20):
        self.url = (url or "").strip().rstrip("/")
        if self.url and not self.url.startswith("http"):
            self.url = "http://" + self.url
        self.uid, self.pw, self.timeout = uid, pw, timeout
        self.token = None

    def _post(self, path, body, token=None):
        data = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        req = urllib.request.Request(self.url + path, data=data, method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error")
            except Exception:
                msg = str(e)
            raise BizError("會計系統回應錯誤：%s" % msg)
        except (urllib.error.URLError, OSError) as e:
            raise BizError("連不到會計系統（%s）：請確認會計系統已開啟，並在「系統管理 → 手機連線」打開連線服務。%s"
                           % (self.url, getattr(e, "reason", e)))

    def ping(self):
        req = urllib.request.Request(self.url + "/api/ping")
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            raise BizError("連不到會計系統（%s）：%s" % (self.url, e))

    def login(self):
        r = self._post("/api/login", dict(uid=self.uid, pw=self.pw))
        if "token" not in r:
            raise BizError("會計系統登入失敗：%s" % r.get("error", ""))
        self.token = r["token"]
        return r

    def call(self, method, *args, **kwargs):
        if not self.token:
            self.login()
        r = self._post("/api/call", dict(obj="books", method=method, args=list(args), kwargs=kwargs), self.token)
        if "biz" in r:
            raise BizError("會計系統：%s" % r["biz"])
        if "error" in r:
            raise BizError("會計系統：%s" % r["error"])
        return _plain(r.get("result"))


def _plain(o):
    """會計系統回傳的 {"$d": "1.00"} 之類還原成一般值。"""
    if isinstance(o, dict):
        if len(o) == 1 and next(iter(o)) in ("$d", "$date", "$dt"):
            k, v = next(iter(o.items()))
            return Decimal(v) if k == "$d" else v
        return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_plain(x) for x in o]
    return o


_ = (dt, ym_add)
