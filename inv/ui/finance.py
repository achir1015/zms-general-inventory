"""帳款與票據：應收／應付帳款（餘額、帳齡、對帳單、未沖明細）、收款／付款沖帳、收付款查詢、應收／應付票據。"""
import datetime as dt
from decimal import Decimal

import flet as ft

from .. import printing, rocdate
from ..doctypes import DOC_TYPES
from ..finance import NOTE_EVENTS, NOTE_STATUS, R_NAME
from . import theme as T
from .docs import num

PKN = {"C": "客戶", "V": "廠商"}


# ====================================================================== 應收／應付帳款
class Balances(ft.Column):
    def __init__(self, ctx, pk, tab="bal", partner=None):
        self.ctx, self.pk = ctx, pk
        self.tab = ft.SegmentedButton(segments=[ft.Segment(value="bal", label="餘額總表"),
                                                ft.Segment(value="aging", label="帳齡分析"),
                                                ft.Segment(value="items", label="未沖明細"),
                                                ft.Segment(value="stmt", label="對帳單")],
                                      selected=[tab], show_selected_icon=False, on_change=lambda e: self.render())
        self.partner_pick = partner
        self.body = ft.Column(spacing=12, expand=True)
        name = "應收帳款" if pk == "C" else "應付帳款"
        kind = "R" if pk == "C" else "P"
        acts = [self.tab]
        if ctx.app.find("receipt_" + kind):
            acts.append(T.btn("收款沖帳" if pk == "C" else "付款沖帳", ft.Icons.ADD_CARD,
                              lambda e: ctx.app.go("receipt_" + kind)))
        super().__init__([T.page_header(ft.Icons.REQUEST_QUOTE if pk == "C" else ft.Icons.PAYMENTS, name,
                                        "銷貨立帳、收款沖帳後的餘額" if pk == "C" else "進貨立帳、付款沖帳後的餘額",
                                        "green" if pk == "C" else "orange", acts), self.body], spacing=12, expand=True)
        self.render(refresh=False)

    def render(self, refresh=True):
        t = (self.tab.selected or ["bal"])[0]
        getattr(self, "r_" + t)()
        if refresh:
            self.update()

    def r_bal(self):
        b = self.ctx.books
        rows = b.balances(self.pk)
        g = T.Grid([("code", "代號", "s", 90), ("partner_show", PKN[self.pk], "s", 180), ("contact", "聯絡人", "s", 90),
                    ("phone", "電話", "s", 120), ("balance", "未沖帳款", "n", 120),
                    ("advance", "預收款" if self.pk == "C" else "預付款", "n", 110),
                    ("notes", "在途票據", "n", 110), ("net", "淨額", "n", 120)],
                   on_pick=lambda r: self.show_stmt(r["code"]), totals=("balance", "advance", "notes", "net"))
        g.set_rows(rows)
        self.body.controls = [ft.Row([T.muted("點選%s可看對帳單" % PKN[self.pk], 12), ft.Container(expand=True),
                                      self.ctx.export_button(g, "帳款餘額")]), g]

    def r_aging(self):
        self.as_of = T.date_field("基準日", width=160)
        self.by_due = T.switch("依預計收付日計算（否則依單據日期）", False)
        self.ag_grid = T.Grid([("partner", "代號", "s", 90), ("partner_show", PKN[self.pk], "s", 170),
                               ("d30", "30 天內", "n", 100), ("d60", "31～60 天", "n", 100), ("d90", "61～90 天", "n", 100),
                               ("d180", "91～180 天", "n", 100), ("over", "180 天以上", "n", 110),
                               ("total", "合計", "n", 120)], totals=("d30", "d60", "d90", "d180", "over", "total"),
                              on_pick=lambda r: self.show_stmt(r["partner"]))

        def go(e=None):
            rows = self.ctx.guard(self.ctx.books.aging, self.pk, self.as_of.value, self.by_due.value) or []
            self.ag_grid.set_rows(rows if isinstance(rows, list) else [])
            if e:
                self.update()
        go()
        self.body.controls = [T.card(ft.Row([self.as_of, self.by_due, T.btn("計算", ft.Icons.CALCULATE, go),
                                             ft.Container(expand=True), self.ctx.export_button(self.ag_grid, "帳齡分析")],
                                            wrap=True, spacing=10), padding=14), self.ag_grid]

    def r_items(self):
        rows = self.ctx.books.open_items(self.pk, "")
        for r in rows:
            r["type_name"] = DOC_TYPES[r["doc_type"]]["short"]
        g = T.Grid([("doc_date", "日期", "d", 90), ("doc_no", "單號", "s", 130), ("type_name", "種類", "s", 80),
                    ("partner_show", PKN[self.pk], "s", 150), ("invoice_no", "發票", "s", 100),
                    ("due_date", "預計收付日", "d", 100), ("amount", "金額", "n", 110), ("applied", "已沖", "n", 110),
                    ("remain", "未沖", "n", 110)], totals=("remain",),
                   on_pick=lambda r: self.ctx.app.go("doc_" + r["doc_type"], doc_id=r["id"])
                   if not DOC_TYPES[r["doc_type"]].get("auto") else None)
        g.set_rows(rows)
        self.body.controls = [ft.Row([ft.Container(expand=True), self.ctx.export_button(g, "未沖帳款明細")]), g]

    def show_stmt(self, code):
        self.partner_pick = code
        self.tab.selected = ["stmt"]
        self.render()

    def r_stmt(self):
        b = self.ctx.books
        today = rocdate.today()
        self.st_partner = T.dropdown(PKN[self.pk], b.options(self.pk), self.partner_pick, width=260)
        self.st_start = T.date_field("起", today.replace(day=1), width=150)
        self.st_end = T.date_field("迄", today, width=150)
        self.st_info = ft.Row([], spacing=10)
        self.st_grid = T.Grid([("date", "日期", "d", 90), ("no", "單號", "s", 130), ("kind", "種類", "s", 70),
                               ("memo", "說明", "s", 220), ("add", "本期增加", "nz", 110), ("sub", "收付沖帳", "nz", 110),
                               ("balance", "餘額", "n", 120)])

        def go(e=None):
            if not self.st_partner.value:
                if e:
                    self.ctx.toast("請選擇%s" % PKN[self.pk], True)
                return
            r = self.ctx.guard(b.statement, self.pk, self.st_partner.value, self.st_start.value, self.st_end.value)
            if not r:
                return
            self.stmt = r
            self.st_info.controls = [T.chip("期初 %s" % T.amt(r["opening"]), "slate"),
                                     T.chip("本期增加 %s" % T.amt(r["total_add"]), "sky"),
                                     T.chip("收付沖帳 %s" % T.amt(r["total_sub"]), "green"),
                                     T.chip("期末 %s" % T.amt(r["closing"]), "rose")]
            self.st_grid.set_rows(r["lines"])
            if e:
                self.update()
        go()
        self.body.controls = [T.card(ft.Row([self.st_partner, self.st_start, self.st_end,
                                             T.btn("查詢", ft.Icons.SEARCH, go),
                                             T.btn("列印對帳單", ft.Icons.PRINT, lambda e: self.print_stmt(),
                                                   kind="outline")], wrap=True, spacing=10), padding=14),
                              self.st_info, self.st_grid]

    def print_stmt(self):
        r = getattr(self, "stmt", None)
        if not r or not self.st_partner.value:
            self.ctx.toast("請先查詢對帳單", True)
            return
        b = self.ctx.books
        p = b.partner(self.pk, self.st_partner.value)
        comp = b.company()
        rows = [dict(date=rocdate.show(x["date"]), no=x["no"], kind=x["kind"], memo=x["memo"] or "",
                     add=T.amt(x["add"], blank_zero=True), sub=T.amt(x["sub"], blank_zero=True),
                     bal=T.amt(x["balance"])) for x in r["lines"]]
        body = ("<div class='meta'><span>%s：%s %s</span><span>期間：%s～%s</span></div>"
                % (PKN[self.pk], p["code"], printing.esc(p["name"]), self.st_start.value, self.st_end.value))
        body += "<p>期初餘額：%s</p>" % T.amt(r["opening"])
        body += printing.table([("date", "日期", False), ("no", "單號", False), ("kind", "種類", False),
                                ("memo", "說明", False), ("add", "本期增加", True), ("sub", "收付沖帳", True),
                                ("bal", "餘額", True)], rows)
        body += "<p style='font-size:15px;font-weight:700'>期末應%s餘額：%s 元</p>" % (
            "收" if self.pk == "C" else "付", T.amt(r["closing"]))
        if comp.get("doc_footer"):
            body += "<p>%s</p>" % printing.esc(comp["doc_footer"])
        body += "<div class='sign'><div>製表</div><div>主管</div><div>%s確認</div></div>" % PKN[self.pk]
        printing.write_and_open(printing.page(comp.get("name") or "", "對帳單", comp.get("address") or "", body),
                                "對帳單_%s" % p["code"])


# ====================================================================== 收款／付款沖帳
class ReceiptEntry(ft.Column):
    def __init__(self, ctx, kind, partner=None):
        self.ctx, self.kind = ctx, kind
        self.pk = "C" if kind == "R" else "V"
        b = ctx.books
        self.partner = T.dropdown(PKN[self.pk], b.options(self.pk), partner, width=280, on_select=self.load_items)
        self.date = T.date_field("日期", width=160)
        self.cash = T.money_field("現金", "", width=130, on_change=self.recalc)
        self.bank = T.money_field("匯款／存款" if kind == "R" else "匯款／轉帳", "", width=140, on_change=self.recalc)
        self.bank_acct = T.dropdown("銀行帳戶", b.options("bank"), b.options("bank")[0][0] if b.options("bank") else None,
                                    width=200, filterable=False)
        self.fee = T.money_field("手續費", "", width=110, on_change=self.recalc)
        self.discount = T.money_field("折讓／尾差", "", width=120, on_change=self.recalc)
        self.use_adv = T.money_field("使用預收" if kind == "R" else "使用預付", "", width=120, on_change=self.recalc)
        self.to_adv = T.money_field("轉為預收" if kind == "R" else "轉為預付", "", width=120, on_change=self.recalc)
        self.memo = T.field("備註", "", width=360)
        self.adv_info = T.muted("", 12)
        self.items_box = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
        self.item_inputs = []
        self.notes_box = ft.Column(spacing=4)
        self.note_rows = []
        self.endorsed = []
        self.endorse_box = ft.Row([], wrap=True, spacing=6)
        self.balance = ft.Row([], spacing=14)
        title = "收款沖帳" if kind == "R" else "付款沖帳"
        note_title = "收到的支票" if kind == "R" else "開立的支票"
        pay_tools = [T.btn("新增一張支票", ft.Icons.ADD, lambda e: self.add_note(), kind="outline")]
        if kind == "P":
            pay_tools.append(T.btn("轉付客戶支票", ft.Icons.SWAP_HORIZ, lambda e: self.pick_endorse(), kind="outline"))
        pay = T.card(ft.Column([
            ft.Row([ft.Text("收款方式" if kind == "R" else "付款方式", size=15, weight=ft.FontWeight.W_700),
                    ft.Container(expand=True), self.adv_info]),
            ft.Row([self.cash, self.bank, self.bank_acct, self.fee, self.discount, self.use_adv, self.to_adv],
                   wrap=True, spacing=10, run_spacing=10),
            ft.Row([ft.Text(note_title, size=14, weight=ft.FontWeight.W_600), ft.Container(expand=True), *pay_tools]),
            self.notes_box, self.endorse_box], spacing=10), padding=14)
        items = T.card(ft.Column([
            ft.Row([ft.Text("沖帳明細（未沖帳款）", size=15, weight=ft.FontWeight.W_700), ft.Container(expand=True),
                    T.btn("依金額自動沖帳", ft.Icons.AUTO_FIX_HIGH, lambda e: self.auto(), kind="outline"),
                    T.btn("全部沖清", ft.Icons.DONE_ALL, lambda e: self.all_items(), kind="outline"),
                    T.btn("清除", ft.Icons.CLEAR, lambda e: self.clear_items(), kind="ghost")]),
            ft.Row([ft.Text(x, width=w, size=12, color=T.MUTED, weight=ft.FontWeight.W_600) for x, w in
                    (("日期", 90), ("單號", 130), ("種類", 70), ("發票", 100), ("預計收付", 90), ("未沖金額", 110),
                     ("本次沖帳", 130))], spacing=10),
            self.items_box], spacing=8, expand=True), padding=14, expand=True)
        super().__init__([T.page_header(ft.Icons.ADD_CARD if kind == "R" else ft.Icons.CREDIT_CARD, title,
                                        "選擇對象 → 輸入收付金額與票據 → 勾沖帳款；左右金額相等才能存檔",
                                        "green" if kind == "R" else "orange",
                                        [T.btn("收付款查詢", ft.Icons.RECEIPT, lambda e: ctx.app.go("receipts"),
                                               kind="outline")]),
                          T.card(ft.Row([self.partner, self.date, self.memo], wrap=True, spacing=10), padding=14),
                          pay, items, ft.Row([self.balance, ft.Container(expand=True),
                                              T.btn("存檔", ft.Icons.SAVE, lambda e: self.save())])],
                         spacing=10, expand=True)
        if partner:
            self.load_items(refresh=False)
        self.recalc(refresh=False)

    # ---- 沖帳明細
    def load_items(self, e=None, refresh=True):
        b = self.ctx.books
        p = self.partner.value
        self.items_box.controls, self.item_inputs = [], []
        if not p:
            return
        items = b.open_items(self.pk, p)
        for it in items:
            f = T.money_field("", "", width=130, on_change=self.recalc, height=42)
            row = ft.Row([ft.Text(rocdate.show(it["doc_date"]), width=90, size=13),
                          ft.Text(it["doc_no"], width=130, size=13),
                          ft.Text(DOC_TYPES[it["doc_type"]]["short"], width=70, size=13),
                          ft.Text(it["invoice_no"] or "", width=100, size=13),
                          ft.Text(rocdate.show(it["due_date"]) if it["due_date"] else "", width=90, size=13),
                          ft.Text(T.amt(it["remain"]), width=110, size=13, text_align=ft.TextAlign.RIGHT,
                                  color=T.DANGER if it["remain"] < 0 else T.TEXT),
                          f, ft.IconButton(ft.Icons.DONE, icon_size=16, tooltip="沖清這筆",
                                           on_click=lambda e, f=f, it=it: self.fill(f, it["remain"]))], spacing=10)
            self.items_box.controls.append(ft.Container(row, padding=ft.Padding.symmetric(horizontal=4)))
            self.item_inputs.append((it, f))
        if not items:
            self.items_box.controls = [T.empty_state(ft.Icons.TASK_ALT, "這個%s目前沒有未沖帳款" % PKN[self.pk],
                                                     "收到的款項可以全部「轉為預收／預付」")]
        adv = b.advance_balance(self.kind, p)
        self.adv_info.value = ("可用%s %s" % ("預收" if self.kind == "R" else "預付", T.amt(adv))) if adv else ""
        self.recalc(refresh=False)
        if refresh:
            self.update()

    def fill(self, f, v):
        f.value = T.amt(v)
        self.recalc()

    def all_items(self):
        for it, f in self.item_inputs:
            f.value = T.amt(it["remain"])
        self.recalc()

    def clear_items(self):
        for it, f in self.item_inputs:
            f.value = ""
        self.recalc()

    def auto(self):
        if not self.partner.value:
            return
        src, _ = self.sums()
        amt = src - (num(self.to_adv.value) or 0) - ((num(self.fee.value) or 0) if self.kind == "P" else 0)
        plan = dict(self.ctx.books.auto_apply(self.pk, self.partner.value, amt))
        for it, f in self.item_inputs:
            f.value = T.amt(plan[it["id"]]) if it["id"] in plan else ""
        self.recalc()

    # ---- 票據
    def add_note(self, data=None):
        no = T.field("票號", "", width=120)
        bank = T.field("付款銀行" if self.kind == "R" else "（本公司甲存）", "", width=150, disabled=self.kind == "P")
        acc = T.field("帳號", "", width=130, visible=self.kind == "R")
        amt = T.money_field("金額", "", width=120, on_change=self.recalc)
        due = T.field("到期日", rocdate.show(rocdate.today() + dt.timedelta(days=30)), width=130,
                      hint_text="115/12/31")
        rowc = ft.Row([no, bank, acc, amt, due], spacing=8)
        rec = dict(no=no, bank=bank, acc=acc, amt=amt, due=due, row=rowc)
        rowc.controls.append(ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=18, icon_color="#E06666",
                                           on_click=lambda e: self.remove_note(rec)))
        self.note_rows.append(rec)
        self.notes_box.controls.append(rowc)
        self.update()

    def remove_note(self, rec):
        self.note_rows.remove(rec)
        self.notes_box.controls.remove(rec["row"])
        self.recalc()

    def pick_endorse(self):
        c = self.ctx
        rows = c.books.find_notes("R", status=1)
        if not rows:
            c.toast("目前沒有在庫（未託收）的客戶支票", True)
            return
        g = T.Grid([("note_no", "票號", "s", 110), ("partner_show", "客戶", "s", 130), ("bank", "付款銀行", "s", 120),
                    ("amount", "金額", "n", 110), ("due_date", "到期日", "d", 90)], selectable=True, height=320)
        g.set_rows(rows)

        def ok(e):
            self.endorsed = g.selected_rows()
            self.endorse_box.controls = [T.chip("轉付 %s %s" % (n["note_no"], T.amt(n["amount"])), "violet",
                                                ft.Icons.SWAP_HORIZ) for n in self.endorsed]
            c.close()
            self.recalc()
        c.dialog("選擇要轉付給廠商的客戶支票", g, [T.btn("取消", kind="ghost", on_click=lambda e: c.close()),
                                             T.btn("確定", ft.Icons.CHECK, ok)], icon=ft.Icons.SWAP_HORIZ, width=640)

    # ---- 平衡
    def sums(self):
        g = lambda f: num(f.value) or Decimal(0)  # noqa: E731
        notes = sum((g(r["amt"]) for r in self.note_rows), Decimal(0))
        endorsed = sum((n["amount"] for n in self.endorsed), Decimal(0))
        src = g(self.cash) + g(self.bank) + notes + endorsed + g(self.discount) + g(self.use_adv)
        applied = sum((g(f) for _, f in self.item_inputs), Decimal(0))
        use = applied + g(self.to_adv)
        if self.kind == "R":
            src += g(self.fee)
        else:
            use += g(self.fee)
        return src, use

    def recalc(self, e=None, refresh=True):
        src, use = self.sums()
        diff = src - use
        ok = diff == 0 and src != 0
        self.balance.controls = [
            T.chip("%s %s" % ("收到合計" if self.kind == "R" else "付出合計", T.amt(src)), "sky"),
            T.chip("沖帳＋轉預%s %s" % ("收" if self.kind == "R" else "付", T.amt(use)), "violet"),
            T.chip("平衡" if ok else "差額 %s" % T.amt(diff), "green" if ok else "rose",
                   ft.Icons.CHECK_CIRCLE if ok else ft.Icons.ERROR_OUTLINE)]
        if diff > 0 and not ok:
            self.balance.controls.append(T.btn("差額轉預%s" % ("收" if self.kind == "R" else "付"), ft.Icons.SAVINGS,
                                               lambda e, d=diff: self.diff_to_adv(d), kind="ghost"))
        if refresh:
            try:
                self.balance.update()
            except Exception:
                pass

    def diff_to_adv(self, d):
        self.to_adv.value = T.amt((num(self.to_adv.value) or 0) + d)
        self.recalc()
        self.update()

    def save(self):
        h = dict(r_date=self.date.value, partner=self.partner.value, cash=self.cash.value, bank=self.bank.value,
                 bank_account=self.bank_acct.value or "", fee=self.fee.value, discount=self.discount.value,
                 use_advance=self.use_adv.value, to_advance=self.to_adv.value, memo=self.memo.value)
        for k in ("cash", "bank", "fee", "discount", "use_advance", "to_advance"):
            h[k] = (h[k] or "").replace(",", "")
        applies = [dict(doc_id=it["id"], amount=(f.value or "").replace(",", "")) for it, f in self.item_inputs
                   if (f.value or "").strip()]
        notes = [dict(note_no=r["no"].value, bank=r["bank"].value, account_no=r["acc"].value,
                      amount=(r["amt"].value or "").replace(",", ""), due_date=r["due"].value) for r in self.note_rows]
        rid = self.ctx.guard(self.ctx.books.save_receipt, self.kind, h, applies, notes,
                             [n["id"] for n in self.endorsed])
        if rid:
            r = self.ctx.books.receipt(rid)
            self.ctx.toast("已存檔：%s　沖帳 %s" % (r["r_no"], T.amt(r["applied"])))
            self.ctx.app.go("receipts", focus=rid)


# ====================================================================== 收付款查詢
class ReceiptList(ft.Column):
    def __init__(self, ctx, focus=None):
        self.ctx = ctx
        b = ctx.books
        kinds = [(k, R_NAME[k]) for k in ("R", "P") if b.can("AR" if k == "R" else "AP", 1)]
        today = rocdate.today()
        self.kind = T.dropdown("種類", kinds, kinds[0][0] if kinds else "R", width=140, filterable=False,
                               on_select=lambda e: self.load())
        self.start = T.date_field("起", today.replace(day=1), width=150)
        self.end = T.date_field("迄", today, width=150)
        self.void = T.switch("含作廢", False, on_change=lambda e: self.load())
        self.grid = T.Grid([("r_date", "日期", "d", 90), ("r_no", "單號", "s", 130), ("partner_show", "對象", "s", 140),
                            ("cash", "現金", "nz", 90), ("bank", "匯款", "nz", 100), ("notes_amt", "票據", "nz", 100),
                            ("endorsed_amt", "轉付", "nz", 90), ("fee", "手續費", "nz", 70), ("discount", "折讓", "nz", 70),
                            ("applied", "沖帳", "n", 110), ("to_advance", "轉預收付", "nz", 90),
                            ("st", "狀態", "s", 80)], on_pick=self.detail, totals=("applied",))
        super().__init__([T.page_header(ft.Icons.RECEIPT, "收付款查詢", "點選可看沖帳明細、列印或作廢", "green",
                                        [ctx.export_button(self.grid, "收付款")]),
                          T.card(ft.Row([self.kind, self.start, self.end, self.void,
                                         T.btn("查詢", ft.Icons.SEARCH, lambda e: self.load())], wrap=True,
                                        spacing=10), padding=14), self.grid], spacing=12, expand=True)
        if focus:
            r = b.receipt(focus)
            self.kind.value = r["kind"]
            self.start.value = rocdate.show(min(r["r_date"], rocdate.today().replace(day=1)))
        self.load(refresh=False)

    def load(self, refresh=True):
        rows = self.ctx.guard(self.ctx.books.find_receipts, self.kind.value or "R", self.start.value, self.end.value,
                              "", None if self.void.value else 1) or []
        for r in rows if isinstance(rows, list) else []:
            r["st"] = "作廢" if r["status"] == 9 else ("已拋轉" if r["gl_batch_id"] else "")
        self.grid.set_rows(rows if isinstance(rows, list) else [])
        if refresh:
            self.update()

    def detail(self, row):
        c = self.ctx
        r = c.books.receipt(row["id"])
        lines = [T.muted("%s　%s %s　%s" % (r["r_no"], r["partner"], r["partner_name"], rocdate.show(r["r_date"])), 14)]
        parts = [("現金", r["cash"]), ("匯款", r["bank"]), ("票據", r["notes_amt"]), ("轉付票據", r["endorsed_amt"]),
                 ("手續費", r["fee"]), ("折讓", r["discount"]), ("使用預收付", r["use_advance"]),
                 ("轉預收付", r["to_advance"])]
        lines.append(ft.Row([T.chip("%s %s" % (k, T.amt(v)), "sky") for k, v in parts if v], wrap=True))
        g = T.Grid([("doc_no", "沖帳單據", "s", 130), ("doc_date", "日期", "d", 90), ("total", "單據金額", "n", 110),
                    ("amount", "本次沖帳", "n", 110)], height=200)
        g.set_rows(r["applies"])
        lines.append(g)
        for n in r["notes"] + r["endorsed"]:
            lines.append(T.muted("支票 %s　%s　%s　到期 %s　%s" % (n["note_no"], n["bank"], T.amt(n["amount"]),
                                                            rocdate.show(n["due_date"]), NOTE_STATUS[n["status"]]), 13))
        if r["memo"]:
            lines.append(T.muted("備註：" + r["memo"], 13))
        acts = [T.btn("關閉", kind="ghost", on_click=lambda e: c.close()),
                T.btn("列印", ft.Icons.PRINT, lambda e: self.print_r(r), kind="outline")]
        if r["status"] == 1 and not r["gl_batch_id"] and c.books.can("AR" if r["kind"] == "R" else "AP", 2):
            def void():
                if c.guard(c.books.void_receipt, r["id"], ok="已作廢 %s" % r["r_no"]):
                    self.load()
            acts.insert(1, T.btn("作廢", ft.Icons.BLOCK, lambda e: (c.close(), c.confirm(
                "作廢收付款單", "確定作廢 %s？沖帳會取消，收到或開立的支票一併刪除。" % r["r_no"], void, yes="作廢")),
                kind="danger"))
        c.dialog(R_NAME[r["kind"]], ft.Column(lines, tight=True, spacing=8), acts, icon=ft.Icons.RECEIPT, width=640)

    def print_r(self, r):
        b = self.ctx.books
        comp = b.company()
        body = "<div class='meta'><span>%s：%s %s</span><span>日期：%s</span></div>" % (
            "客戶" if r["kind"] == "R" else "廠商", r["partner"], printing.esc(r["partner_name"]),
            rocdate.show(r["r_date"]))
        body += printing.table([("doc_no", "沖帳單據", False), ("date", "日期", False), ("total", "單據金額", True),
                                ("amount", "本次沖帳", True)],
                               [dict(doc_no=a["doc_no"], date=rocdate.show(a["doc_date"]), total=T.amt(a["total"]),
                                     amount=T.amt(a["amount"])) for a in r["applies"]])
        parts = [("現金", r["cash"]), ("匯款", r["bank"]), ("支票", r["notes_amt"]), ("轉付支票", r["endorsed_amt"]),
                 ("手續費", r["fee"]), ("折讓", r["discount"]), ("使用預收付", r["use_advance"]),
                 ("轉預收付", r["to_advance"])]
        body += "<p>%s</p>" % "　".join("%s %s" % (k, T.amt(v)) for k, v in parts if v)
        for n in r["notes"] + r["endorsed"]:
            body += "<p>支票 %s　%s　%s 元　到期 %s</p>" % (n["note_no"], printing.esc(n["bank"]), T.amt(n["amount"]),
                                                     rocdate.show(n["due_date"]))
        body += "<p style='font-size:15px;font-weight:700'>沖帳合計：%s 元</p>" % T.amt(r["applied"])
        body += "<div class='sign'><div>核准</div><div>會計</div><div>出納</div><div>經手</div></div>"
        printing.write_and_open(printing.page(comp.get("name") or "", R_NAME[r["kind"]], r["r_no"], body), r["r_no"])


# ====================================================================== 票據
class Notes(ft.Column):
    def __init__(self, ctx, kind):
        self.ctx, self.kind = ctx, kind
        b = ctx.books
        sts = [(k, v) for k, v in NOTE_STATUS.items() if (k < 10) == (kind == "R")]
        default = "1,2" if kind == "R" else "11"
        self.status = T.dropdown("狀態", [(default, "未兌現（在庫／託收）" if kind == "R" else "未兌現")] +
                                 [(str(k), v) for k, v in sts], default, width=200, blank="全部", filterable=False,
                                 on_select=lambda e: self.load())
        self.due = T.field("到期日至", "", width=140, hint_text="115/12/31", on_submit=lambda e: self.load())
        self.grid = T.Grid([("due_date", "到期日", "d", 90), ("note_no", "票號", "s", 110), ("partner_show",
                                                                                     "客戶" if kind == "R" else "廠商",
                                                                                     "s", 130),
                            ("bank", "付款銀行", "s", 120), ("amount", "金額", "n", 110), ("issue_date", "收／開票日", "d", 90),
                            ("status_name", "狀態", "s", 100), ("bank_account", "帳戶", "s", 70),
                            ("r_no", "來源單號", "s", 130), ("endorse_no", "轉付單號", "s", 130)],
                           selectable=True, totals=("amount",))
        acts = []
        if b.can("NOTE", 2):
            evs = [k for k, v in NOTE_EVENTS.items() if v[0] == kind]
            for ev in evs:
                acts.append(T.btn(NOTE_EVENTS[ev][3].split("（")[0], ft.Icons.PLAY_ARROW,
                                  lambda e, ev=ev: self.event(ev),
                                  kind="accent" if ev in ("clear", "pay") else "danger" if ev in (
                                      "bounce", "cancel") else "outline"))
            acts.append(T.btn("還原上一步", ft.Icons.UNDO, lambda e: self.undo(), kind="ghost"))
        acts.append(T.btn("異動紀錄", ft.Icons.HISTORY, lambda e: self.history(), kind="ghost"))
        title = "應收票據" if kind == "R" else "應付票據"
        super().__init__([T.page_header(ft.Icons.RECEIPT_LONG if kind == "R" else ft.Icons.EDIT_DOCUMENT, title,
                                        "收款時收到的支票：託收 → 兌現；也可退票、撤回或轉付廠商" if kind == "R" else
                                        "付款時開立的支票：到期兌現扣款，或作廢退回（重新應付）",
                                        "pink" if kind == "R" else "orange",
                                        [self.status, self.due, ctx.export_button(self.grid, title)]),
                          ft.Row(acts, wrap=True, spacing=8), self.grid], spacing=12, expand=True)
        self.load(refresh=False)

    def load(self, refresh=True):
        st = [int(x) for x in (self.status.value or "").split(",") if x]
        rows = self.ctx.guard(self.ctx.books.find_notes, self.kind, st or None, "", self.due.value or None) or []
        self.grid.set_rows(rows if isinstance(rows, list) else [])
        if refresh:
            self.update()

    def event(self, ev):
        c = self.ctx
        rows = self.grid.selected_rows()
        if not rows:
            c.toast("請先勾選票據", True)
            return
        kind, allowed, new, title = NOTE_EVENTS[ev]
        d = T.date_field("%s日期" % title.split("（")[0], width=170)
        bank = T.dropdown("銀行帳戶", c.books.options("bank"), rows[0]["bank_account"] or None, width=220,
                          filterable=False) if ev in ("collect", "clear") else None
        memo = T.field("說明", "", width=300)
        tip = {"collect": "支票交給銀行託收，狀態改為託收中（不產生分錄）。",
               "clear": "支票兌現存入銀行：借 銀行存款、貸 應收票據。",
               "bounce": "退票：借 應收帳款、貸 應收票據，並自動產生「退票轉應收」讓客戶重新付款。",
               "withdraw": "撤票（把支票還給客戶）：同退票，客戶重新欠款。",
               "pay": "支票到期兌付：借 應付票據、貸 銀行存款。",
               "cancel": "支票作廢退回：借 應付票據、貸 應付帳款，並自動產生「票據作廢轉應付」。"}[ev]

        def go(e):
            r = c.guard(c.books.note_event, [x["id"] for x in rows], ev, d.value, bank.value if bank else "",
                        memo.value)
            if not r:
                return
            done, errs = r
            c.close()
            if errs:
                c.toast("完成 %d 張；%s" % (len(done), "；".join(errs[:3])), True)
            else:
                c.toast("已%s %d 張" % (title, len(done)))
            self.load()
        total = sum((x["amount"] for x in rows), Decimal(0))
        c.dialog("%s（%d 張，%s 元）" % (title, len(rows), T.amt(total)),
                 ft.Column([T.muted(tip, 13), ft.Row([d] + ([bank] if bank else [])), memo], tight=True, spacing=12),
                 [T.btn("取消", kind="ghost", on_click=lambda e: c.close()), T.btn("確定", ft.Icons.CHECK, go)],
                 icon=ft.Icons.RECEIPT_LONG, tone="pink", width=520)

    def undo(self):
        rows = self.grid.selected_rows()
        if len(rows) != 1:
            self.ctx.toast("請勾選一張票據", True)
            return

        def go():
            if self.ctx.guard(self.ctx.books.undo_note_event, rows[0]["id"], ok="已還原上一步"):
                self.load()
        self.ctx.confirm("還原票據異動", "還原票號 %s 最後一次異動？" % rows[0]["note_no"], go, yes="還原")

    def history(self):
        rows = self.grid.selected_rows()
        if len(rows) != 1:
            self.ctx.toast("請勾選一張票據", True)
            return
        ev = self.ctx.books.note_events(rows[0]["id"])
        names = {k: v[3] for k, v in NOTE_EVENTS.items()}
        names["endorse"] = "轉付"
        for e in ev:
            e["ev"] = names.get(e["event"], e["event"])
            e["from_to"] = "%s → %s" % (NOTE_STATUS.get(e["prev_status"], ""), NOTE_STATUS.get(e["new_status"], ""))
            e["gl"] = "已拋轉" if e["gl_batch_id"] else ""
        g = T.Grid([("ev_date", "日期", "d", 90), ("ev", "異動", "s", 110), ("from_to", "狀態", "s", 170),
                    ("bank_account", "帳戶", "s", 70), ("memo", "說明", "s", 160), ("gl", "會計", "s", 70)], height=260)
        g.set_rows(ev)
        self.ctx.dialog("票號 %s 異動紀錄" % rows[0]["note_no"], g,
                        [T.btn("關閉", kind="ghost", on_click=lambda e: self.ctx.close())], icon=ft.Icons.HISTORY,
                        width=720)
