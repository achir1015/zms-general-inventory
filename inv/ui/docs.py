"""單據輸入（銷貨、進貨、退回、訂單、採購、報價、調撥、入出庫、報廢、調整、期初、跌價、期初帳款）、
單據查詢、訂單未出貨／採購未進貨追蹤。"""
from decimal import Decimal

import flet as ft

from .. import printing, rocdate
from ..core import BizError, money
from ..doctypes import DOC_TYPES, PK_NAMES, TAX_TYPES
from . import theme as T

H = 48
GROUPS = {"sales": ("銷售單據查詢", ["SI", "SR", "SO", "QT"], "C", "teal"),
          "purchase": ("採購單據查詢", ["PI", "PR", "PO"], "V", "amber"),
          "stock": ("庫存單據查詢", ["ADJ", "SCR", "TR", "OUT", "IN", "OPEN", "CNT", "WD"], "", "violet")}
NEXT_DOC = {"QT": ("SO", "轉成訂單"), "SO": ("SI", "轉成銷貨單"), "PO": ("PI", "轉成進貨單"),
            "SI": ("SR", "銷貨退回"), "PI": ("PR", "進貨退出")}


def num(s):
    try:
        return Decimal(str(s or "0").replace(",", "").strip() or "0")
    except Exception:
        return None


def qshow(v):
    if v in (None, ""):
        return ""
    v = Decimal(str(v))
    s = "{:,.3f}".format(v).rstrip("0").rstrip(".")
    return s


def icon_of(code):
    return getattr(ft.Icons, DOC_TYPES[code]["icon"])


# ====================================================================== 明細列
class LineRow(ft.Container):
    def __init__(self, entry, data=None):
        self.entry = entry
        t = entry.t
        data = data or {}
        self.src_line_id = data.get("src_line_id")
        self.no = ft.Text("", width=26, size=13, color=T.MUTED, text_align=ft.TextAlign.CENTER)
        self.product = T.dropdown("", entry.prod_opts, data.get("product") or None, width=300,
                                  on_select=self.on_product, hint_text="商品編號、品名或條碼")
        self.qty = T.field("", qshow(data.get("qty")) if data.get("qty") not in (None, 0, "") else "", width=96,
                           hint_text="數量", text_align=ft.TextAlign.RIGHT, on_change=self.changed,
                           on_submit=self.submit, height=H)
        pv = data.get("price")
        self.price = T.field("", "" if pv in (None, "") else T.amt(pv) if Decimal(str(pv)) else "", width=110,
                             hint_text=t.get("price_label", "單價"), text_align=ft.TextAlign.RIGHT,
                             on_change=self.changed, on_submit=self.submit, height=H)
        self.amount = T.field("", T.amt(data.get("amount")) if data.get("amount") else "", width=120,
                              hint_text="金額", text_align=ft.TextAlign.RIGHT, on_change=self.changed,
                              on_submit=self.submit, height=H)
        self.amount_text = ft.Text("", width=110, size=13, text_align=ft.TextAlign.RIGHT, color=T.TEXT,
                                   weight=ft.FontWeight.W_600)
        self.memo = T.field("", data.get("memo", ""), width=150, hint_text="備註", height=H)
        self.hint = ft.Text("", width=150, size=11, color=T.MUTED, max_lines=2)
        for tf in (self.qty, self.price, self.amount, self.memo):
            tf.content_padding = ft.Padding.symmetric(horizontal=12, vertical=14)
        self.remove = ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=18, icon_color="#E06666", tooltip="刪除這一行",
                                    on_click=lambda e: entry.remove_line(self))
        self.src_chip = ft.Container(T.chip("帶單", "sky", size=10), visible=bool(self.src_line_id),
                                     tooltip="來源單據明細")
        if T.MOBILE:
            # 手機：每一行明細是一張小卡片（寬度按比例，字體放大也不會超出）
            for c in (self.product, self.qty, self.price, self.amount, self.memo):
                c.width = None
                c.expand = True
            self.qty.label, self.price.label = ("調整量（±）" if entry.code == "ADJ" else "數量"),                 t.get("price_label", "單價")
            self.amount.label, self.memo.label = "金額", "備註"
            self.hint.width = None
            nums = [self.amount] if entry.amount_mode else [self.qty] + ([self.price] if t["price"] else [])
            layout = ft.Column([
                ft.Row([self.no, self.product], spacing=6),
                ft.Row(nums, spacing=8),
                ft.Row([self.hint, ft.Container(expand=True), self.src_chip, self.amount_text], spacing=6),
                ft.Row([self.memo, self.remove], spacing=4)], spacing=8)
            super().__init__(layout, padding=12, border_radius=14, border=ft.Border.all(1, T.LINE),
                             bgcolor=T.CARD, data=T.READY, margin=ft.Margin.only(bottom=8))
        else:
            cells = [self.no, self.product]
            if entry.amount_mode:
                cells += [self.amount]
            else:
                cells += [self.qty]
                if t["price"]:
                    cells += [self.price, self.amount_text]
            cells += [self.memo, self.src_chip, self.hint, self.remove]
            super().__init__(ft.Row(cells, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                             padding=ft.Padding.symmetric(vertical=3, horizontal=6), border_radius=10)
        if data.get("product"):
            self.show_hint()
        self.calc()

    def on_product(self, e=None):
        e_ = self.entry
        code = self.product.value
        if code and e_.t["price"] and not num(self.price.value):
            p = e_.ctx.books.suggest_price(code, e_.t["pk"], e_.partner_value())
            if e_.code in ("IN", "OPEN"):
                prod = e_.ctx.books.product(code) or {}
                p = prod.get("avg_cost") or prod.get("std_cost") or 0
            self.price.value = T.amt(p) if p else ""
        if code and not self.qty.value and not e_.amount_mode:
            self.qty.value = "1"
        self.show_hint()
        self.calc()
        e_.recalc()
        self.update()

    def show_hint(self):
        e_ = self.entry
        code = self.product.value
        if not code:
            self.hint.value = ""
            return
        b = e_.ctx.books
        wh = e_.wh.value if e_.wh else ""
        st = b.stock_qty(code, wh) if wh else b.stock_qty(code)
        unit = e_.prod_unit.get(code, "")
        txt = "庫存 %s%s" % (qshow(st), unit)
        if e_.t["pk"] and e_.partner_value():
            last = b.last_deals(code, e_.t["pk"], e_.partner_value(), 1)
            if last:
                txt += "｜上次 %s" % T.amt(last[0]["price"])
        self.hint.value = txt
        self.hint.color = T.DANGER if st <= 0 and e_.t["stock"] in (-1, "T") else T.MUTED

    def calc(self):
        if self.entry.amount_mode or not self.entry.t["price"]:
            return
        q, p = num(self.qty.value), num(self.price.value)
        self.amount_text.value = T.amt(money(q * p)) if q is not None and p is not None and q and p else ""

    def changed(self, e=None):
        self.calc()
        self.entry.recalc()
        try:
            self.amount_text.update()
        except Exception:
            pass

    def submit(self, e):
        if self is self.entry.rows[-1]:
            self.entry.add_line()

    def line_amount(self):
        if self.entry.amount_mode:
            return num(self.amount.value) or Decimal(0)
        q, p = num(self.qty.value) or Decimal(0), num(self.price.value) or Decimal(0)
        return money(q * p)

    def values(self):
        return dict(product=self.product.value or "", qty=(self.qty.value or "0").replace(",", ""),
                    price=(self.price.value or "0").replace(",", ""), amount=(self.amount.value or "0").replace(",", ""),
                    memo=self.memo.value or "", src_line_id=self.src_line_id)


# ====================================================================== 單據輸入
class DocEntry(ft.Column):
    def __init__(self, ctx, code, doc_id=None, from_doc=None, partner=None):
        self.ctx, self.code = ctx, code
        self.t = t = DOC_TYPES[code]
        b = ctx.books
        self.editable = b.can(t["func"], 2)
        self.amount_mode = bool(t.get("amount_only"))
        self.doc = None
        self.rows = []
        comp = b.company()
        self.comp = comp
        prods = b.product_list()
        if t["stock"] not in (0,) and code not in ("SI", "SR", "PI", "PR"):
            prods = [p for p in prods if p["is_stock"]]
        self.prod_opts = [(p["code"], "%s %s%s" % (p["code"], p["name"], " " + p["spec"] if p["spec"] else ""))
                          for p in prods]
        self.prod_unit = {p["code"]: p["unit"] for p in prods}
        # ---- 表頭
        self.no_text = ft.Text("（存檔後自動編號）", size=14, color=T.MUTED, weight=ft.FontWeight.W_600)
        self.status = ft.Row([], spacing=6)
        self.date = T.date_field("日期", width=160)
        self.partner = None
        if t["pk"]:
            self.partner = T.dropdown(PK_NAMES[t["pk"]], b.options(t["pk"]), partner, width=260,
                                      on_select=self.on_partner)
        self.wh = self.wh2 = None
        if t["stock"] and not t.get("header_only"):
            whs = b.options("wh")
            self.wh = T.dropdown("倉庫" if t["stock"] != "T" else "撥出倉", whs, b.default_warehouse(), width=170,
                                 filterable=False, on_select=lambda e: self.refresh_hints())
            if t["stock"] == "T":
                self.wh2 = T.dropdown("撥入倉", whs, None, width=170, filterable=False)
        self.tax = None
        if t["tax"]:
            self.tax = T.dropdown("稅別", list(TAX_TYPES.items()), comp.get("default_tax_type") or 1,
                                  width=180 if T.MOBILE else 140,
                                  filterable=False, on_select=lambda e: self.recalc())
        self.invoice = T.field("發票號碼", "", width=150) if code in ("SI", "SR", "PI", "PR") else None
        self.ref = T.field("客戶單號" if t["pk"] == "C" else "廠商單號", "", width=150) if t["pk"] and not t.get(
            "header_only") else None
        self.emp = T.dropdown("業務／經手人", b.options("emp"), None, width=170, blank="（無）") \
            if t["pk"] and not t.get("header_only") else None
        self.dept = T.dropdown("部門", b.options("dept"), None, width=150, blank="（無）", filterable=False) \
            if code in ("SI", "SR", "PI", "PR", "OUT") else None
        self.due = T.field("預交日" if code in ("SO", "PO") else "預計收付日", "", width=150, hint_text="115/12/31") \
            if code in ("SO", "PO", "SI", "PI", "ARO", "APO") else None
        self.reason = T.dropdown("原因", b.options("reasons:" + t["reasons"]), None, width=170, blank="（無）") \
            if t.get("reasons") else None
        self.gl_acct = T.field("對方會計科目（空白＝預設）", "", width=220, hint_text="例 6213") \
            if code in ("OUT", "IN") else None
        self.discount = T.switch("只折讓（不退貨）", False, on_change=self.on_discount) if t.get("allow_discount") \
            else None
        self.total_field = T.money_field("金額", "", width=170) if t.get("header_only") else None
        self.memo = T.field("備註", "", width=420)
        phr = ft.PopupMenuButton(icon=ft.Icons.SHORT_TEXT, icon_size=18, tooltip="備註片語", icon_color="#94A3B8",
                                 items=[ft.PopupMenuItem(p, on_click=lambda e, p=p: self.set_memo(p))
                                        for _, p in b.options("phrases")])
        head_items = [x for x in (self.date, self.partner, self.wh, self.wh2, self.tax, self.invoice, self.ref,
                                  self.emp, self.dept, self.due, self.reason, self.gl_acct, self.total_field) if x]
        self.head = T.card(ft.Column([
            ft.Row([ft.Text("單號", size=13, color=T.MUTED), self.no_text, self.status, ft.Container(expand=True),
                    *([self.discount] if self.discount else [])], spacing=10),
            ft.Row(head_items, wrap=True, spacing=10, run_spacing=10),
            ft.Row([self.memo, phr], spacing=4)], spacing=12), padding=16)
        # ---- 明細
        self.lines = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
        self.line_head = ft.Container()
        self.totals = ft.Row([], spacing=18)
        tools = []
        if self.editable:
            tools.append(T.btn("新增一行", ft.Icons.ADD, lambda e: self.add_line(), kind="outline"))
            if t["src"]:
                tools.append(T.btn("帶單（%s）" % "、".join(DOC_TYPES[s]["short"] for s in t["src"]),
                                   ft.Icons.PLAYLIST_ADD, lambda e: self.pick_source(), kind="outline"))
        from .finance import items_head
        self.line_box = T.card(ft.Column([items_head(ft.Text("明細", size=15, weight=ft.FontWeight.W_700), tools),
                                          self.line_head, self.lines,
                                          ft.Divider(height=1), self.totals], spacing=8, expand=True),
                               padding=14, expand=True, visible=not t.get("header_only"))
        # ---- 動作
        self.actions = ft.Row([], spacing=8, wrap=True)
        sub = {"SI": "出貨給客戶：扣庫存、立應收帳款", "SR": "客戶退貨（加回庫存）或只給折讓",
               "PI": "向廠商進貨：加庫存、立應付帳款", "PR": "退貨給廠商（扣庫存）或只拿折讓",
               "SO": "客戶下單，之後轉成銷貨單", "PO": "向廠商下單，之後轉成進貨單", "QT": "給客戶的報價",
               "TR": "倉庫之間移轉", "IN": "非進貨的入庫（贈品、樣品、歸還）", "OUT": "內部領用、樣品贈送等出庫",
               "SCR": "過期、損壞品報廢出庫", "ADJ": "直接修正庫存數量（增加為正、減少為負）",
               "OPEN": "系統啟用時的期初庫存與單位成本", "WD": "呆料提列跌價損失（迴轉輸入負數）",
               "ARO": "系統啟用前尚未收回的帳款", "APO": "系統啟用前尚未支付的帳款"}.get(code, "")
        super().__init__([T.page_header(icon_of(code), t["name"], sub, t["tone"], [
            T.btn("新單", ft.Icons.NOTE_ADD, lambda e: self.ctx.app.go("doc_" + code), kind="outline"),
            T.btn("單據查詢", ft.Icons.MANAGE_SEARCH, lambda e: self.open_list(), kind="outline")]),
            self.head, self.line_box, self.actions], spacing=12, expand=True)
        self.render_line_head()
        if doc_id:
            self.load(doc_id)
        else:
            self.add_line(refresh=False)
            self.add_line(refresh=False)
            self.add_line(refresh=False)
            if from_doc:
                self.prefill_from(from_doc)
        self.render_actions()
        self.recalc(refresh=False)

    # ---------------------------------------------------------------- 版面
    def render_line_head(self):
        t = self.t
        cols = [("#", 26), ("商品", 300)]
        if self.amount_mode:
            cols += [("金額", 120)]
        else:
            cols += [("數量" if self.code != "ADJ" else "調整量（±）", 96)]
            if t["price"]:
                cols += [(t.get("price_label", "單價"), 110), ("金額", 110)]
        cols += [("備註", 150)]
        self.line_head.content = ft.Row([ft.Text(n, width=w, size=12, color=T.MUTED, weight=ft.FontWeight.W_600)
                                         for n, w in cols], spacing=8)
        self.line_head.visible = not T.MOBILE
        self.line_head.padding = ft.Padding.only(left=6)

    def set_memo(self, p):
        self.memo.value = p
        self.memo.update()

    def partner_value(self):
        return self.partner.value if self.partner else ""

    def on_partner(self, e=None):
        if self.code in ("SI", "PI") and self.due and self.partner.value:
            p = self.ctx.books.partner(self.t["pk"], self.partner.value) or {}
            self.due.value = rocdate.show(_due_date(rocdate.read(self.date.value or rocdate.show(rocdate.today())), p))
        self.refresh_hints()
        self.update()

    def refresh_hints(self):
        for r in self.rows:
            r.show_hint()
        try:
            self.update()
        except Exception:
            pass

    def on_discount(self, e=None):
        self.amount_mode = bool(self.discount.value)
        old = [r.values() for r in self.rows]
        self.lines.controls = []
        self.rows = []
        self.render_line_head()
        for v in old:
            if v["product"]:
                self.add_line(dict(product=v["product"], memo=v["memo"], src_line_id=v["src_line_id"]), refresh=False)
        if not self.rows:
            self.add_line(refresh=False)
        self.recalc(refresh=False)
        self.update()

    def add_line(self, data=None, refresh=True):
        r = LineRow(self, data)
        self.rows.append(r)
        self.lines.controls.append(r)
        self.renumber()
        if refresh:
            self.update()
        return r

    def remove_line(self, r):
        if r in self.rows:
            self.rows.remove(r)
            self.lines.controls.remove(r)
        if not self.rows:
            self.add_line(refresh=False)
        self.renumber()
        self.recalc()

    def renumber(self):
        for i, r in enumerate(self.rows, 1):
            r.no.value = str(i)

    def recalc(self, refresh=True):
        t = self.t
        if t.get("header_only"):
            return
        s = sum((r.line_amount() for r in self.rows if r.product.value), Decimal(0))
        items = [T.muted("共 %d 項" % len([r for r in self.rows if r.product.value]), 13)]
        if not self.amount_mode and not t["price"]:
            q = sum((num(r.qty.value) or Decimal(0) for r in self.rows if r.product.value), Decimal(0))
            items.append(ft.Text("數量合計 %s" % qshow(q), size=14, weight=ft.FontWeight.W_700, color=T.PRIMARY))
        elif t["tax"]:
            tt = int(self.tax.value or 1)
            rate = Decimal(str(self.comp.get("tax_rate") or 5)) / 100 if tt in (1, 2) else Decimal(0)
            if tt == 2:
                tax = money(s * rate / (1 + rate))
                amount = s - tax
            else:
                amount, tax = s, money(s * rate)
            items += [ft.Text("未稅 %s" % T.amt(amount), size=14), ft.Text("稅額 %s" % T.amt(tax), size=14),
                      ft.Text("合計 %s" % T.amt(amount + tax), size=17, weight=ft.FontWeight.W_800,
                              color=T.PRIMARY)]
        else:
            items.append(ft.Text("金額合計 %s" % T.amt(s), size=16, weight=ft.FontWeight.W_800, color=T.PRIMARY))
        self.totals.controls = items
        if refresh:
            try:
                self.totals.update()
            except Exception:
                pass

    def render_actions(self):
        d = self.doc
        t = self.t
        acts = []
        locked = d and (d["status"] == 9 or d["gl_batch_id"])
        if self.editable and not locked:
            acts.append(T.btn("存檔", ft.Icons.SAVE, lambda e: self.save()))
        if d:
            acts.append(T.btn("列印", ft.Icons.PRINT, lambda e: self.print_doc(), kind="outline"))
            if d["status"] == 1:
                nxt = NEXT_DOC.get(self.code)
                if nxt and self.ctx.app.find("doc_" + nxt[0]):
                    acts.append(T.btn(nxt[1], icon_of(nxt[0]), lambda e: self.ctx.app.go(
                        "doc_" + nxt[0], from_doc=d["id"]), kind="accent"))
                if t.get("track") and self.editable:
                    acts.append(T.btn("取消結案" if d["closed"] else "結案", ft.Icons.DONE_ALL,
                                      lambda e: self.toggle_close(), kind="outline"))
                if self.editable and not d["gl_batch_id"] and not t.get("auto"):
                    acts.append(T.btn("作廢", ft.Icons.BLOCK, lambda e: self.void(), kind="danger"))
        self.actions.controls = acts

    # ---------------------------------------------------------------- 載入、帶單
    def load(self, doc_id):
        b = self.ctx.books
        d = b.doc(doc_id)
        self.doc = d
        self.no_text.value = d["doc_no"]
        self.no_text.color = T.TEXT
        chips = []
        if d["status"] == 9:
            chips.append(T.chip("已作廢", "slate", ft.Icons.BLOCK))
        if d["gl_batch_id"]:
            chips.append(T.chip("已拋轉會計", "violet", ft.Icons.SYNC_ALT))
        if d["closed"]:
            chips.append(T.chip("已結案", "green", ft.Icons.DONE_ALL))
        if d.get("src_doc_no"):
            chips.append(T.chip("來源 %s" % d["src_doc_no"], "sky"))
        if self.t.get("track"):
            rem = sum((ln["qty"] - ln.get("done_qty", 0) for ln in d["lines"]), Decimal(0))
            chips.append(T.chip("未%s %s" % ("出貨" if self.code == "SO" else "進貨", qshow(rem)),
                                "amber" if rem > 0 else "green"))
        self.status.controls = chips
        self.date.value = rocdate.show(d["doc_date"])
        if self.partner:
            self.partner.value = d["partner"]
        if self.wh:
            self.wh.value = d["warehouse"] or None
        if self.wh2:
            self.wh2.value = d["warehouse2"] or None
        if self.tax:
            self.tax.value = str(d["tax_type"])
        for f, k in ((self.invoice, "invoice_no"), (self.ref, "ref_no"), (self.memo, "memo"),
                     (self.gl_acct, "gl_account")):
            if f:
                f.value = d[k] or ""
        for f, k in ((self.emp, "employee"), (self.dept, "dept"), (self.reason, "reason")):
            if f:
                f.value = d[k] or None
        if self.due:
            self.due.value = rocdate.show(d["due_date"]) if d["due_date"] else ""
        if self.total_field:
            self.total_field.value = T.amt(d["total"])
        if self.discount:
            self.discount.value = bool(d["discount_only"])
            self.amount_mode = bool(d["discount_only"])
            self.render_line_head()
        self.lines.controls, self.rows = [], []
        for ln in d["lines"]:
            self.add_line(dict(product=ln["product"], qty=ln["qty"], price=ln["price"], amount=ln["amount"],
                               memo=ln["memo"], src_line_id=ln["src_line_id"]), refresh=False)
        if not self.rows:
            self.add_line(refresh=False)
        locked = d["status"] == 9 or d["gl_batch_id"] or not self.editable
        if locked:
            self.head.disabled = True
            self.line_box.disabled = True

    def prefill_from(self, src_id):
        """從訂單／採購單／報價單／銷貨單／進貨單轉入。"""
        b = self.ctx.books
        src = b.doc(src_id)
        if self.partner:
            self.partner.value = src["partner"]
        if self.tax and src.get("tax_type"):
            self.tax.value = str(src["tax_type"])
        if self.wh and src.get("warehouse"):
            self.wh.value = src["warehouse"]
        if self.emp and src.get("employee"):
            self.emp.value = src["employee"]
        self.memo.value = "%s %s" % (DOC_TYPES[src["doc_type"]]["short"], src["doc_no"])
        if self.ref is not None and src.get("ref_no"):
            self.ref.value = src["ref_no"]
        lines = [x for x in b.open_source_lines(self.code, src["partner"]) if x["doc_id"] == src_id] \
            if self.t["src"] and src["doc_type"] in self.t["src"] else []
        if not lines and self.code == "SO":      # 報價 → 訂單：整張帶入
            lines = [dict(product=ln["product"], remain=ln["qty"], price=ln["price"], id=None) for ln in src["lines"]]
        if lines:
            self.lines.controls, self.rows = [], []
            for x in lines:
                self.add_line(dict(product=x["product"], qty=x["remain"], price=x["price"], src_line_id=x.get("id")),
                              refresh=False)
        self.on_partner_silent()

    def on_partner_silent(self):
        if self.code in ("SI", "PI") and self.due and self.partner and self.partner.value:
            p = self.ctx.books.partner(self.t["pk"], self.partner.value) or {}
            self.due.value = rocdate.show(_due_date(rocdate.today(), p))

    def pick_source(self):
        c = self.ctx
        if not self.partner_value():
            c.toast("請先選擇%s" % PK_NAMES[self.t["pk"]], True)
            return
        rows = c.books.open_source_lines(self.code, self.partner_value())
        if not rows:
            c.toast("這個%s沒有可帶入的%s" % (PK_NAMES[self.t["pk"]], "、".join(DOC_TYPES[s]["name"]
                                                                       for s in self.t["src"])), True)
            return
        for r in rows:
            r["type_name"] = DOC_TYPES[r["doc_type"]]["short"]
        g = T.Grid([("doc_no", "單號", "s", 130), ("doc_date", "日期", "d", 90), ("product", "商品", "s", 110),
                    ("name", "品名", "s", 200), ("qty", "原數量", "n", 80), ("remain", "可帶數量", "n", 80),
                    ("price", "單價", "n", 90)], selectable=True, height=360)
        g.set_rows(rows)

        def ok(e):
            picked = g.selected_rows()
            if not picked:
                c.toast("請勾選要帶入的明細", True)
                return
            self.rows = [r for r in self.rows if r.product.value]
            self.lines.controls = list(self.rows)
            for x in picked:
                self.add_line(dict(product=x["product"], qty=x["remain"], price=x["price"], src_line_id=x["id"]),
                              refresh=False)
                if self.tax and x.get("tax_type"):
                    self.tax.value = str(x["tax_type"])
            if not self.memo.value:
                self.memo.value = "、".join(sorted({x["doc_no"] for x in picked}))[:200]
            c.close()
            self.recalc(refresh=False)
            self.update()
        c.dialog("帶入來源單據", g, [T.btn("取消", kind="ghost", on_click=lambda e: c.close()),
                                   T.btn("帶入勾選的明細", ft.Icons.PLAYLIST_ADD, ok)],
                 icon=ft.Icons.PLAYLIST_ADD, tone="sky", width=860)

    # ---------------------------------------------------------------- 存檔、作廢、列印
    def header(self):
        h = dict(doc_type=self.code, doc_date=self.date.value, partner=self.partner_value(),
                 warehouse=self.wh.value if self.wh else "", warehouse2=self.wh2.value if self.wh2 else "",
                 tax_type=int(self.tax.value) if self.tax and self.tax.value else None,
                 invoice_no=self.invoice.value if self.invoice else "", ref_no=self.ref.value if self.ref else "",
                 employee=self.emp.value if self.emp else "", dept=self.dept.value if self.dept else "",
                 due_date=self.due.value if self.due else None, reason=self.reason.value if self.reason else "",
                 gl_account=self.gl_acct.value if self.gl_acct else "",
                 discount_only=bool(self.discount.value) if self.discount else False, memo=self.memo.value,
                 total=(self.total_field.value or "").replace(",", "") if self.total_field else None)
        if self.doc and self.doc.get("src_doc_id"):
            h["src_doc_id"] = self.doc["src_doc_id"]
        return h

    def save(self):
        lines = [r.values() for r in self.rows if r.product.value]
        did = self.ctx.guard(self.ctx.books.save_doc, self.doc["id"] if self.doc else None, self.header(), lines)
        if did:
            d = self.ctx.books.doc(did)
            self.ctx.toast("已存檔：%s　合計 %s" % (d["doc_no"], T.amt(d["total"])))
            self.ctx.app.go("doc_" + self.code, doc_id=did)

    def void(self):
        d = self.doc

        def go():
            if self.ctx.guard(self.ctx.books.void_doc, d["id"], ok="已作廢 %s" % d["doc_no"]):
                self.ctx.app.go("doc_" + self.code, doc_id=d["id"])
        self.ctx.confirm("作廢單據", "確定作廢 %s？庫存與帳款會一併取消，作廢後無法恢復（可重新開單）。" % d["doc_no"],
                         go, yes="作廢")

    def toggle_close(self):
        d = self.doc
        if self.ctx.guard(self.ctx.books.close_order, d["id"], not d["closed"],
                          ok="已取消結案" if d["closed"] else "已結案（剩餘數量不再追蹤）"):
            self.ctx.app.go("doc_" + self.code, doc_id=d["id"])

    def print_doc(self):
        b = self.ctx.books
        printing.write_and_open(doc_html(b, b.doc(self.doc["id"])), self.doc["doc_no"])

    def open_list(self):
        g = next((k for k, v in GROUPS.items() if self.code in v[1]), "")
        if g and self.ctx.app.find("list_" + g):
            self.ctx.app.go("list_" + g, doc_type=self.code)
        elif self.code in ("ARO", "APO"):
            self.ctx.app.go("receivable" if self.code == "ARO" else "payable")


def _due_date(d, p):
    """依結帳日與收付款天數推算預計收付款日。"""
    import datetime as dt
    cd, days = int(p.get("closing_day") or 0), int(p.get("pay_days") or 0)
    if cd and d.day > cd:
        base = rocdate.month_last(d) + dt.timedelta(days=1)
        close = base.replace(day=min(cd, rocdate.month_last(base).day))
    elif cd:
        close = d.replace(day=min(cd, rocdate.month_last(d).day))
    else:
        close = rocdate.month_last(d)
    return close + dt.timedelta(days=days)


# ====================================================================== 單據查詢
class DocList(ft.Column):
    def __init__(self, ctx, group, doc_type=None):
        self.ctx, self.group = ctx, group
        title, types, pk, tone = GROUPS[group]
        b = ctx.books
        self.types = [x for x in types if ctx.app.find("doc_" + x) or x == "CNT"]
        today = rocdate.today()
        self.type = T.dropdown("單據種類", [(x, DOC_TYPES[x]["name"]) for x in self.types], doc_type or "",
                               width=170, blank="全部", filterable=False, on_select=lambda e: self.load())
        self.start = T.date_field("起", today.replace(day=1), width=150)
        self.end = T.date_field("迄", today, width=150)
        self.partner = T.dropdown(PK_NAMES[pk], b.options(pk), None, width=220, blank="全部") if pk else None
        self.kw = T.field("單號／備註／發票", "", width=180, on_submit=lambda e: self.load())
        self.void = T.switch("含作廢", False, on_change=lambda e: self.load())
        cols = [("doc_date", "日期", "d", 90), ("doc_no", "單號", "s", 130), ("type_name", "種類", "s", 70)]
        if pk:
            cols.append(("partner_show", PK_NAMES[pk], "s", 140))
        cols += [("wh_name", "倉庫", "s", 80), ("amount", "未稅", "n", 100), ("tax", "稅額", "n", 80),
                 ("total", "合計", "n", 110), ("memo", "備註", "s", 220), ("st", "狀態", "s", 90)]
        self.grid = T.Grid(cols, on_pick=self.open, totals=("total",))
        filt = [x for x in (self.type, self.start, self.end, self.partner, self.kw, self.void) if x]
        super().__init__([T.page_header(ft.Icons.MANAGE_SEARCH, title, "點選單據可開啟、列印、作廢或轉單", tone,
                                        [ctx.export_button(self.grid, title)]),
                          T.card(ft.Row(filt + [T.btn("查詢", ft.Icons.SEARCH, lambda e: self.load())], wrap=True,
                                        spacing=10, run_spacing=10), padding=14),
                          self.grid], spacing=12, expand=True)
        self.load(refresh=False)

    def load(self, refresh=True):
        types = [self.type.value] if self.type.value else self.types
        rows = self.ctx.guard(self.ctx.books.find_docs, types, self.start.value, self.end.value,
                              self.partner.value if self.partner else "", self.kw.value.strip(),
                              None if self.void.value else 1) or []
        for r in rows:
            st = []
            if r["status"] == 9:
                st.append("作廢")
            if r["gl_batch_id"]:
                st.append("已拋轉")
            if r["closed"]:
                st.append("結案")
            r["st"] = "、".join(st)
        self.grid.set_rows(rows if isinstance(rows, list) else [])
        if refresh:
            self.update()

    def open(self, r):
        if r["doc_type"] == "CNT":
            self.ctx.app.go("count", doc_id=r["id"])
        else:
            self.ctx.app.go("doc_" + r["doc_type"], doc_id=r["id"])


# ====================================================================== 未出貨／未進貨
class Tracking(ft.Column):
    def __init__(self, ctx, code):
        self.ctx, self.code = ctx, code
        pk = DOC_TYPES[code]["pk"]
        self.partner = T.dropdown(PK_NAMES[pk], ctx.books.options(pk), None, width=240, blank="全部",
                                  on_select=lambda e: self.load())
        self.grid = T.Grid([("doc_no", "單號", "s", 130), ("doc_date", "日期", "d", 90), ("due_date", "預交日", "d", 90),
                            ("partner_show", PK_NAMES[pk], "s", 130), ("product", "商品", "s", 110),
                            ("name", "品名", "s", 200), ("qty", "訂購量", "n", 80), ("done", "已%s" % (
                                "出貨" if code == "SO" else "進貨"), "n", 80), ("remain", "未交量", "n", 80),
                            ("remain_amt", "未交金額", "n", 110)], on_pick=self.pick, totals=("remain_amt",))
        title = "訂單未出貨" if code == "SO" else "採購未進貨"
        super().__init__([T.page_header(ft.Icons.PENDING_ACTIONS, title, "點選明細可轉單或結案（剩餘不再追蹤）",
                                        "blue" if code == "SO" else "amber",
                                        [self.partner, ctx.export_button(self.grid, title)]),
                          self.grid], spacing=12, expand=True)
        self.load(refresh=False)

    def load(self, refresh=True):
        self.grid.set_rows(self.ctx.books.tracking(self.code, self.partner.value or ""))
        if refresh:
            self.update()

    def pick(self, r):
        c = self.ctx
        nxt = NEXT_DOC[self.code]
        c.dialog(r["doc_no"], T.muted("%s %s：未交 %s" % (r["product"], r["name"], qshow(r["remain"])), 14), [
            T.btn("關閉", kind="ghost", on_click=lambda e: c.close()),
            T.btn("開啟%s" % DOC_TYPES[self.code]["name"], ft.Icons.OPEN_IN_NEW,
                  lambda e: (c.close(), c.app.go("doc_" + self.code, doc_id=r["doc_id"])), kind="outline"),
            T.btn(nxt[1], icon_of(nxt[0]), lambda e: (c.close(), c.app.go("doc_" + nxt[0], from_doc=r["doc_id"])))],
            icon=ft.Icons.PENDING_ACTIONS, width=460)


# ====================================================================== 列印
def doc_html(b, d):
    t = DOC_TYPES[d["doc_type"]]
    comp = b.company()
    p = b.partner(d["partner_kind"], d["partner"]) if d["partner"] else None
    esc = printing.esc
    meta = [("單號", d["doc_no"]), ("日期", rocdate.show(d["doc_date"]))]
    if p:
        meta += [(PK_NAMES[d["partner_kind"]], "%s %s" % (p["code"], p["name"])), ("統一編號", p["tax_id"]),
                 ("電話", p["phone"]), ("地址", p.get("ship_address") or p["address"])]
    if d["warehouse"]:
        meta.append(("倉庫", d["warehouse"] + (" → " + d["warehouse2"] if d["warehouse2"] else "")))
    if t["tax"]:
        meta.append(("稅別", TAX_TYPES.get(d["tax_type"], "")))
    for k, title in (("invoice_no", "發票號碼"), ("ref_no", "對方單號"), ("reason", "原因")):
        if d.get(k):
            meta.append((title, d[k]))
    if d.get("due_date"):
        meta.append(("預交／收付日", rocdate.show(d["due_date"])))
    box = "<table class='m'>" + "".join("<tr><th style='width:16%%'>%s</th><td>%s</td></tr>" % (esc(k), esc(v))
                                        for k, v in meta if v) + "</table>"
    show_cost = d["doc_type"] not in ("IN", "OPEN") or b.see_cost
    cols = [("line_no", "項", False), ("product", "商品編號", False), ("name", "品名", False), ("unit", "單位", False)]
    if t.get("amount_only") or d["discount_only"]:
        cols += [("amount_s", "金額", True)]
    else:
        cols += [("qty_s", "數量", True)]
        if t["price"] and show_cost:
            cols += [("price_s", t.get("price_label", "單價"), True), ("amount_s", "金額", True)]
    cols.append(("memo", "備註", False))
    rows = []
    for ln in d["lines"]:
        rows.append(dict(ln, qty_s=qshow(ln["qty"]), price_s=T.amt(ln["price"]) if ln["price"] is not None else "",
                         amount_s=T.amt(ln["amount"]) if ln["amount"] is not None else ""))
    body = box + (printing.table(cols, rows) if rows else "")
    if t["tax"] or t.get("header_only"):
        body += ("<table style='width:40%%;margin-left:60%%'><tr><th>未稅金額</th><td class='n'>%s</td></tr>"
                 "<tr><th>營業稅</th><td class='n'>%s</td></tr><tr class='total'><td>合計</td><td class='n'>%s</td>"
                 "</tr></table>" % (T.amt(d["amount"]), T.amt(d["tax"]), T.amt(d["total"])))
    if d["memo"]:
        body += "<p>備註：%s</p>" % esc(d["memo"])
    if comp.get("doc_footer"):
        body += "<p style='color:#475569'>%s</p>" % esc(comp["doc_footer"])
    body += "<div class='sign'><div>核准</div><div>主管</div><div>經手</div><div>%s</div></div>" % (
        "客戶簽收" if d["partner_kind"] == "C" else "倉管" if not d["partner_kind"] else "廠商")
    sub = "　".join(x for x in (comp.get("address"), "電話 " + comp["phone"] if comp.get("phone") else "",
                                "統編 " + comp["tax_id"] if comp.get("tax_id") else "") if x)
    if d["status"] == 9:
        sub += "　【已作廢】"
    return printing.page(comp.get("name") or "", t["name"], sub, body)


_ = BizError
