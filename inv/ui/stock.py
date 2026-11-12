"""庫存：庫存查詢（分倉）、商品異動明細、盤點作業、採購建議、成本月結、呆滯品與跌價。"""
import datetime as dt
from decimal import Decimal

import flet as ft

from .. import printing, rocdate
from ..costing import ym_add
from . import theme as T
from .docs import qshow


# ====================================================================== 庫存查詢
class StockQuery(ft.Column):
    def __init__(self, ctx):
        self.ctx = ctx
        b = ctx.books
        self.wh = T.dropdown("倉庫", b.options("wh"), "", width=170, blank="全部倉庫", filterable=False,
                             on_select=lambda e: self.load())
        self.cat = T.dropdown("類別", b.options("cat"), "", width=170, blank="全部類別", filterable=False,
                              on_select=lambda e: self.load())
        self.search = T.field("搜尋商品", "", width=200, prefix_icon=ft.Icons.SEARCH, on_submit=lambda e: self.load())
        self.zero = T.switch("含零庫存", False, on_change=lambda e: self.load())
        self.body = ft.Column(expand=True)
        self.summary = ft.Row([], spacing=14)
        super().__init__([T.page_header(ft.Icons.WAREHOUSE, "庫存查詢", "各倉庫即時庫存；紅字＝低於安全存量", "violet",
                                        [self.wh, self.cat, self.search, self.zero]),
                          self.summary, self.body], spacing=12, expand=True)
        self.load(refresh=False)

    def load(self, refresh=True):
        b = self.ctx.books
        rows, whs = b.stock_list(self.wh.value or "", self.cat.value or "", self.zero.value,
                                 (self.search.value or "").strip())
        cols = [("code", "商品編號", "s", 120), ("name", "品名", "s", 220), ("spec", "規格", "s", 110),
                ("unit", "單位", "s", 50)]
        if not self.wh.value and len(whs) > 1:
            names = dict(b.options("wh"))
            cols += [("wh_" + w, names.get(w, w).split(" ", 1)[-1], "n", 80) for w in whs]
        cols += [("qty", "庫存量", "n", 90), ("safety_qty", "安全存量", "n", 80)]
        if b.see_cost:
            cols += [("avg_cost", "平均成本", "n", 90), ("value", "庫存金額", "n", 120)]
        grid = T.Grid(cols, on_pick=lambda r: self.ctx.app.go("stock_card", product=r["code"]),
                      totals=("value",) if b.see_cost else (),
                      row_style=lambda r: {"color": T.DANGER, "weight": ft.FontWeight.W_700} if r["low"] else None)
        grid.set_rows(rows)
        self.body.controls = [grid]
        low = len([r for r in rows if r["low"]])
        self.summary.controls = [T.chip("%d 項商品" % len(rows), "violet", ft.Icons.CATEGORY),
                                 T.chip("低於安全存量 %d 項" % low, "rose" if low else "green", ft.Icons.WARNING_AMBER),
                                 self.ctx.export_button(grid, "庫存表")]
        if refresh:
            self.update()


# ====================================================================== 商品異動明細
class StockCard(ft.Column):
    def __init__(self, ctx, product=None):
        self.ctx = ctx
        b = ctx.books
        today = rocdate.today()
        opts = [(p["code"], "%s %s" % (p["code"], p["name"])) for p in
                b.product_list(active_only=False, stock_only=True)]
        self.product = T.dropdown("商品", opts, product, width=300, on_select=lambda e: self.load())
        self.wh = T.dropdown("倉庫", b.options("wh"), "", width=160, blank="全部倉庫", filterable=False,
                             on_select=lambda e: self.load())
        self.start = T.date_field("起", today.replace(month=1, day=1), width=150)
        self.end = T.date_field("迄", today, width=150)
        self.info = ft.Row([], spacing=12)
        self.grid = T.Grid([("move_date", "日期", "d", 90), ("doc_no", "單號", "s", 130), ("type_name", "種類", "s", 70),
                            ("warehouse", "倉", "s", 50), ("who", "對象／原因", "s", 180), ("in_qty", "入庫", "n", 80),
                            ("out_qty", "出庫", "n", 80), ("balance", "結存", "n", 90), ("price", "單價", "n", 90)],
                           on_pick=lambda r: self.ctx.app.go("doc_" + r["doc_type"], doc_id=r["doc_id"])
                           if r["doc_type"] != "CNT" else None)
        super().__init__([T.page_header(ft.Icons.TIMELINE, "商品異動明細", "庫存卡：期初、每筆進出與結存", "violet",
                                        [self.ctx.export_button(self.grid, "商品異動明細")]),
                          T.card(ft.Row([self.product, self.wh, self.start, self.end,
                                         T.btn("查詢", ft.Icons.SEARCH, lambda e: self.load())], wrap=True,
                                        spacing=10), padding=14),
                          self.info, self.grid], spacing=12, expand=True)
        if product:
            self.load(refresh=False)

    def load(self, refresh=True):
        if not self.product.value:
            self.ctx.toast("請選擇商品", True)
            return
        r = self.ctx.guard(self.ctx.books.stock_card, self.product.value, self.start.value, self.end.value,
                           self.wh.value or "")
        if not r:
            return
        self.info.controls = [T.chip("期初 %s" % qshow(r["opening"]), "slate"),
                              T.chip("結存 %s" % qshow(r["closing"]), "violet")]
        self.grid.set_rows(r["rows"])
        if refresh:
            self.update()


# ====================================================================== 盤點作業
class Counting(ft.Column):
    """盤點：建立盤點單（載入帳面量）→ 列印盤點表 → 輸入實盤量 → 盤差轉庫存調整單。"""

    def __init__(self, ctx, doc_id=None):
        self.ctx = ctx
        b = ctx.books
        self.doc = None
        self.inputs = {}
        self.body = ft.Column(spacing=12, expand=True)
        super().__init__([T.page_header(ft.Icons.FACT_CHECK, "盤點作業",
                                        "建立盤點單 → 列印盤點表 → 輸入實盤量 → 盤差轉成庫存數量修正單", "teal",
                                        [T.btn("新的盤點", ft.Icons.ADD, lambda e: self.ctx.app.go("count"),
                                               kind="outline")]),
                          self.body], spacing=12, expand=True)
        if doc_id:
            self.show(doc_id, refresh=False)
        else:
            self.start_page(refresh=False)
        _ = b

    def start_page(self, refresh=True):
        b = self.ctx.books
        self.f_wh = T.dropdown("盤點倉庫", b.options("wh"), b.default_warehouse(), width=200, filterable=False)
        self.f_cat = T.dropdown("類別（可只盤一類）", b.options("cat"), "", width=220, blank="全部類別",
                                filterable=False)
        self.f_date = T.date_field("盤點日", width=160)
        self.f_zero = T.switch("包含零庫存商品", False)
        recent = b.find_docs(["CNT"], limit=30)
        g = T.Grid([("doc_date", "盤點日", "d", 90), ("doc_no", "盤點單號", "s", 130), ("wh_name", "倉庫", "s", 90),
                    ("memo", "說明", "s", 220), ("st", "狀態", "s", 110)],
                   on_pick=lambda r: self.show(r["id"]))
        for r in recent:
            r["st"] = "已轉調整" if r["closed"] else "盤點中"
        g.set_rows(recent)
        steps = ft.Row([step(1, "建立盤點單", "依倉庫載入商品與盤點日帳面量"), step(2, "列印盤點表", "到現場點數，寫上實盤量"),
                        step(3, "輸入實盤量", "可分次輸入，隨時存檔"), step(4, "盤差轉調整", "自動產生庫存數量修正單")],
                       spacing=12, data="split")
        self.body.controls = [
            steps,
            T.card(ft.Column([ft.Text("建立盤點單", size=16, weight=ft.FontWeight.W_700),
                              ft.Row([self.f_wh, self.f_cat, self.f_date, self.f_zero,
                                      T.btn("建立並載入帳面量", ft.Icons.PLAYLIST_ADD_CHECK, lambda e: self.create())],
                                     wrap=True, spacing=10)], spacing=12), padding=16),
            ft.Text("最近的盤點單", size=15, weight=ft.FontWeight.W_700), g]
        if refresh:
            self.update()

    def create(self):
        did = self.ctx.guard(self.ctx.books.create_count, self.f_wh.value, self.f_date.value, self.f_cat.value or "",
                             self.f_zero.value)
        if did:
            self.ctx.toast("盤點單已建立")
            self.show(did)

    def show(self, doc_id, refresh=True):
        b = self.ctx.books
        d = b.doc(doc_id)
        self.doc = d
        done = bool(d["closed"]) or d["status"] == 9
        editable = b.can("STK", 2) and not done
        self.inputs = {}
        self.diffs = []
        rows = []
        prods = {p["code"]: p for p in b.product_list(active_only=False)}
        for ln in d["lines"]:
            f = T.field("", "" if ln["count_qty"] is None else qshow(ln["count_qty"]), width=110,
                        text_align=ft.TextAlign.RIGHT, hint_text="實盤", height=44, disabled=not editable,
                        on_change=lambda e: self.refresh_diff())
            self.inputs[ln["id"]] = (ln, f)
            diff = ft.Text("", width=90, size=13, text_align=ft.TextAlign.RIGHT)
            self.diffs.append(diff)
            unit = prods.get(ln["product"], {}).get("unit", "")
            if T.MOBILE:
                f.width, f.expand, f.label = None, True, "實盤量"
                diff.width = 80
                rows.append(ft.Container(ft.Column([
                    ft.Row([ft.Text(ln["product"], size=13, weight=ft.FontWeight.W_600),
                            ft.Text(ln["name"], size=13, expand=True, max_lines=2)], spacing=8),
                    ft.Row([T.muted("帳面 %s %s" % (qshow(ln["book_qty"]), unit), 13), f, diff], spacing=8)],
                    spacing=6), padding=10, border_radius=12, border=ft.Border.all(1, T.LINE), bgcolor=T.CARD,
                    data=T.READY, margin=ft.Margin.only(bottom=6)))
            else:
                rows.append(ft.Container(ft.Row([
                    ft.Text(ln["product"], width=120, size=13), ft.Text(ln["name"], width=240, size=13, max_lines=1),
                    ft.Text(unit, width=50, size=13),
                    ft.Text(qshow(ln["book_qty"]), width=90, size=13, text_align=ft.TextAlign.RIGHT), f, diff],
                    spacing=10), padding=ft.Padding.symmetric(vertical=2, horizontal=8)))
        self.row_ctrls = rows
        head = ft.Row([ft.Text(x, width=w, size=12, color=T.MUTED, weight=ft.FontWeight.W_600) for x, w in
                       (("商品編號", 120), ("品名", 240), ("單位", 50), ("帳面量", 90), ("實盤量", 110),
                        ("盤差", 90))], spacing=10, visible=not T.MOBILE)
        self.stat = ft.Row([], spacing=10)
        acts = [T.btn("列印盤點表", ft.Icons.PRINT, lambda e: self.print_sheet(), kind="outline")]
        if editable:
            acts = [T.btn("存檔", ft.Icons.SAVE, lambda e: self.save()),
                    T.btn("未輸入的＝帳面量", ft.Icons.DONE_ALL, lambda e: self.fill_book(), kind="outline"),
                    T.btn("重新抓帳面量", ft.Icons.REFRESH, lambda e: self.refresh_book(), kind="outline")] + acts + [
                T.btn("盤差轉調整單", ft.Icons.TUNE, lambda e: self.to_adjust(), kind="accent"),
                T.btn("作廢盤點單", ft.Icons.BLOCK, lambda e: self.void(), kind="danger")]
        info = [T.chip(d["doc_no"], "teal"), T.chip("盤點日 %s" % rocdate.show(d["doc_date"]), "slate"),
                T.chip("倉庫 %s" % d["warehouse"], "violet")]
        if d["closed"]:
            adj = b.count_adjust_doc(d["id"])
            info.append(T.chip("已轉調整單 %s" % (adj["doc_no"] if adj else ""), "green", ft.Icons.DONE_ALL))
            if adj:
                info.append(T.btn("開啟調整單", ft.Icons.OPEN_IN_NEW,
                                  lambda e: self.ctx.app.go("doc_ADJ", doc_id=adj["id"]), kind="ghost"))
        if d["status"] == 9:
            info.append(T.chip("已作廢", "slate"))
        self.body.controls = [
            (ft.Row(info + [self.stat], wrap=True, spacing=8, run_spacing=8) if T.MOBILE else
             ft.Row(info + [ft.Container(expand=True), self.stat])),
            T.card(ft.Column([head, ft.Divider(height=1), ft.Column(rows, spacing=0, scroll=ft.ScrollMode.AUTO,
                                                                    expand=True)], spacing=6, expand=True),
                   padding=12, expand=True),
            ft.Row(acts, spacing=8, wrap=True)]
        self.refresh_diff(update=False)
        if refresh:
            self.update()

    def refresh_diff(self, update=True):
        n_done, n_diff = 0, 0
        for diff, (ln, f) in zip(self.diffs, self.inputs.values()):
            v = (f.value or "").replace(",", "").strip()
            if v:
                try:
                    q = Decimal(v) - ln["book_qty"]
                    n_done += 1
                    diff.value = qshow(q) if q else "0"
                    diff.color = T.DANGER if q < 0 else T.SUCCESS if q > 0 else T.MUTED
                    n_diff += bool(q)
                except Exception:
                    diff.value, diff.color = "？", T.DANGER
            else:
                diff.value = ""
        self.stat.controls = [T.chip("已盤 %d／%d" % (n_done, len(self.inputs)), "teal"),
                              T.chip("有差異 %d 項" % n_diff, "rose" if n_diff else "green")]
        if update:
            try:
                self.update()
            except Exception:
                pass

    def _lines(self):
        out = []
        for ln, f in self.inputs.values():
            v = (f.value or "").replace(",", "").strip()
            out.append(dict(product=ln["product"], book_qty=ln["book_qty"], count_qty=v if v != "" else None,
                            memo=ln["memo"]))
        return out

    def save(self, quiet=False):
        d = self.doc
        r = self.ctx.guard(self.ctx.books.save_doc, d["id"], dict(doc_type="CNT", doc_date=d["doc_date"],
                                                                   warehouse=d["warehouse"], memo=d["memo"]),
                           self._lines(), ok=None if quiet else "已存檔")
        return r

    def fill_book(self):
        for ln, f in self.inputs.values():
            if not (f.value or "").strip():
                f.value = qshow(ln["book_qty"]) or "0"
        self.refresh_diff()

    def refresh_book(self):
        if self.save(quiet=True) and self.ctx.guard(self.ctx.books.refresh_count_book, self.doc["id"],
                                                    ok="已重新抓取盤點日的帳面量"):
            self.show(self.doc["id"])

    def to_adjust(self):
        def go(zero=False):
            if not self.save(quiet=True):
                return
            adj = self.ctx.guard(self.ctx.books.count_to_adjust, self.doc["id"], zero)
            if adj is not None and adj is not False:
                self.ctx.toast("已產生庫存數量修正單" if adj is not True else "沒有盤差，盤點完成")
                self.show(self.doc["id"])
        missing = [ln for ln, f in self.inputs.values() if not (f.value or "").strip()]
        if missing:
            self.ctx.confirm("還有 %d 項沒有輸入" % len(missing), "沒輸入實盤量的商品要當作實盤 0（全部盤虧）嗎？"
                             "若是漏盤，請按取消後輸入，或用「未輸入的＝帳面量」。", lambda: go(True), yes="當作 0")
        else:
            self.ctx.confirm("盤差轉調整", "會依盤差產生庫存數量修正單（日期＝盤點日），盤點單之後不能再修改。", go,
                             yes="確定轉調整", danger=False)

    def void(self):
        def go():
            if self.ctx.guard(self.ctx.books.void_doc, self.doc["id"], ok="盤點單已作廢"):
                self.ctx.app.go("count")
        self.ctx.confirm("作廢盤點單", "確定作廢 %s？" % self.doc["doc_no"], go, yes="作廢")

    def print_sheet(self):
        b = self.ctx.books
        d = self.doc
        prods = {p["code"]: p for p in b.product_list(active_only=False)}
        rows = [dict(no=i, product=ln["product"], name=ln["name"], spec=prods.get(ln["product"], {}).get("spec", ""),
                     unit=prods.get(ln["product"], {}).get("unit", ""), book=qshow(ln["book_qty"]),
                     count="" if ln["count_qty"] is None else qshow(ln["count_qty"]), memo="")
                for i, (ln, f) in enumerate(self.inputs.values(), 1)]
        body = printing.table([("no", "項", False), ("product", "商品編號", False), ("name", "品名", False),
                               ("spec", "規格", False), ("unit", "單位", False), ("book", "帳面量", True),
                               ("count", "實盤量", True), ("memo", "備註", False)], rows)
        body += "<div class='sign'><div>盤點人</div><div>複盤人</div><div>倉管</div><div>主管</div></div>"
        comp = b.company()
        printing.write_and_open(printing.page(comp.get("name") or "", "盤點表",
                                              "%s　倉庫 %s　盤點日 %s" % (d["doc_no"], d["warehouse"],
                                                                     rocdate.show(d["doc_date"])), body), d["doc_no"])


def step(n, title, sub):
    return T.card(ft.Row([ft.Container(ft.Text(str(n), size=18, weight=ft.FontWeight.W_800, color=ft.Colors.WHITE),
                                       width=36, height=36, border_radius=18, bgcolor=T.ACCENT,
                                       alignment=ft.Alignment.CENTER),
                          ft.Column([ft.Text(title, size=14, weight=ft.FontWeight.W_700), T.muted(sub, 11)],
                                    spacing=0, expand=True)], spacing=10), padding=12, expand=True)


# ====================================================================== 採購建議
class LowStock(ft.Column):
    def __init__(self, ctx):
        self.ctx = ctx
        g = T.Grid([("code", "商品編號", "s", 120), ("name", "品名", "s", 220), ("unit", "單位", "s", 50),
                    ("qty", "現有庫存", "n", 90), ("safety_qty", "安全存量", "n", 90), ("on_order", "已採購未進", "n", 100),
                    ("suggest", "建議採購量", "n", 100), ("vendor", "主要供應商", "s", 120)], selectable=True)
        g.set_rows(ctx.books.low_stock())
        self.grid = g
        acts = [ctx.export_button(g, "採購建議")]
        if ctx.app.find("doc_PO"):
            acts.insert(0, T.btn("勾選的產生採購單", ft.Icons.SHOPPING_CART, lambda e: self.make_po()))
        super().__init__([T.page_header(ft.Icons.LIGHTBULB, "採購建議",
                                        "低於安全存量的商品；建議量＝安全存量×2－現有－已採購未進貨", "amber", acts),
                          g], spacing=12, expand=True)

    def make_po(self):
        rows = self.grid.selected_rows()
        if not rows:
            self.ctx.toast("請勾選商品", True)
            return
        vendors = {r["vendor"] for r in rows}
        if len(vendors) > 1 or not next(iter(vendors)):
            self.ctx.toast("請勾選同一個主要供應商的商品（商品資料可設定主要供應商）", True)
            return
        b = self.ctx.books
        v = next(iter(vendors))
        lines = [dict(product=r["code"], qty=r["suggest"] or r["safety_qty"], price=b.suggest_price(r["code"], "V", v))
                 for r in rows]
        did = self.ctx.guard(b.save_doc, None, dict(doc_type="PO", partner=v, memo="依採購建議產生"), lines)
        if did:
            self.ctx.toast("已產生採購單，請確認數量與單價")
            self.ctx.app.go("doc_PO", doc_id=did)


# ====================================================================== 成本月結
class CostClose(ft.Column):
    def __init__(self, ctx):
        self.ctx = ctx
        self.body = ft.Column(spacing=14)
        super().__init__([T.page_header(ft.Icons.CALCULATE, "成本月結", "月加權平均成本；月結後該月單據鎖住（關帳）",
                                        "rose"), self.body], spacing=12, expand=True, scroll=ft.ScrollMode.AUTO)
        self.render(refresh=False)

    def render(self, refresh=True):
        b = self.ctx.books
        st = b.cost_status()
        nxt = st["next"]
        hist = T.Grid([("ym_s", "月份", "s", 110), ("closed_at", "月結時間", "s", 150), ("closed_by", "執行人", "s", 90),
                       ("batch_no", "已拋轉批次", "s", 140)], height=260, empty="尚未月結")
        for r in st["history"]:
            r["ym_s"] = rocdate.ym_show(r["ym"])
            r["closed_at"] = T.show(r["closed_at"])
            if r["gl_batch_id"] == 0:
                r["batch_no"] = "（無成本分錄）"
        hist.set_rows(st["history"])
        can = b.can("CLS", 2)
        acts = []
        if can:
            acts.append(T.btn("執行 %s 月結" % rocdate.ym_show(nxt), ft.Icons.PLAY_ARROW, lambda e: self.close(nxt),
                              kind="accent"))
            if st["closed"]:
                acts.append(T.btn("取消 %s 月結" % rocdate.ym_show(st["closed"]), ft.Icons.UNDO,
                                  lambda e: self.reopen(st["closed"]), kind="danger"))
        self.body.controls = [
            T.card(ft.Column([
                ft.Row([T.icon_tile(ft.Icons.CALCULATE, "rose", 44), ft.Column([
                    ft.Text("下一個要月結的月份：%s" % rocdate.ym_show(nxt), size=17, weight=ft.FontWeight.W_700),
                    T.muted("已月結至 %s" % (rocdate.ym_show(st["closed"]) if st["closed"] else "（尚未月結）"), 13)],
                    spacing=2, expand=True)], spacing=12),
                T.muted("月結會：① 依月加權平均計算每項商品的單位成本；② 回寫該月銷貨、銷退、領用、報廢、調整的成本，"
                        "毛利報表改用實際成本；③ 鎖住該月所有影響庫存的單據（關帳）；④ 之後可到「會計拋轉」產生"
                        "庫存月結成本傳票（銷貨成本、報廢、盤盈虧、領用）。月結前請確認該月進貨與退貨都已輸入。", 12),
                ft.Row(acts, spacing=8)], spacing=12), padding=18),
            ft.Text("月結紀錄", size=15, weight=ft.FontWeight.W_700), hist]
        if refresh:
            self.update()

    def close(self, ym):
        def go():
            n = self.ctx.guard(self.ctx.books.close_month, ym)
            if n is not None and n is not False:
                self.ctx.toast("%s 月結完成：%s 項商品" % (rocdate.ym_show(ym), n))
                self.render()
        self.ctx.confirm("成本月結", "確定執行 %s 月結？月結後該月影響庫存的單據不能再新增、修改或作廢。"
                         % rocdate.ym_show(ym), go, yes="執行月結", danger=False)

    def reopen(self, ym):
        def go():
            if self.ctx.guard(self.ctx.books.reopen_month, ym, ok="已取消 %s 月結" % rocdate.ym_show(ym)):
                self.render()
        self.ctx.confirm("取消月結", "取消 %s 月結後，該月單據可以再修改，修改完要重新月結。" % rocdate.ym_show(ym), go,
                         yes="取消月結")


# ====================================================================== 呆滯品與跌價
class DeadStock(ft.Column):
    def __init__(self, ctx):
        self.ctx = ctx
        b = ctx.books
        comp = b.company()
        self.days = T.field("幾天沒有出貨", str(comp.get("dead_days") or 180), width=140,
                            on_submit=lambda e: self.load())
        self.wh = T.dropdown("倉庫", b.options("wh"), "", width=160, blank="全部倉庫", filterable=False)
        cols = [("product", "商品編號", "s", 110), ("name", "品名", "s", 200), ("unit", "單位", "s", 50),
                ("qty", "庫存量", "n", 80), ("last_in", "最後進貨", "d", 90), ("last_out", "最後出貨", "d", 90),
                ("idle_days", "閒置天數", "s", 80)]
        if b.see_cost:
            cols += [("value", "庫存金額", "n", 110), ("provision", "已提跌價", "n", 100),
                     ("net_value", "帳面淨額", "n", 110)]
        self.grid = T.Grid(cols, selectable=True, totals=("value", "provision") if b.see_cost else ())
        acts = [ctx.export_button(self.grid, "呆滯品")]
        if b.can("CLS", 2):
            acts.insert(0, T.btn("勾選的提列跌價", ft.Icons.TRENDING_DOWN, lambda e: self.provision(), kind="accent"))
        if b.can("STK", 2):
            acts.insert(1, T.btn("勾選的轉報廢單", ft.Icons.DELETE_SWEEP, lambda e: self.scrap(), kind="danger"))
        bal = b.provision_balance() if b.see_cost else None
        super().__init__([T.page_header(ft.Icons.TRENDING_DOWN, "呆滯品與跌價",
                                        "超過指定天數沒有出貨的庫存；可提列跌價損失或轉報廢", "rose", acts),
                          T.card(ft.Row([self.days, self.wh, T.btn("查詢", ft.Icons.SEARCH, lambda e: self.load())] +
                                        ([T.chip("備抵跌價餘額 %s" % T.amt(bal), "pink")] if bal is not None else []),
                                        wrap=True, spacing=10), padding=14),
                          self.grid], spacing=12, expand=True)
        self.load(refresh=False)

    def load(self, refresh=True):
        rows = self.ctx.guard(self.ctx.books.dead_stock, self.days.value or 180, None, self.wh.value or "") or []
        for r in rows:
            r["idle_days"] = "%s 天" % r["idle_days"] if r["idle_days"] is not None else "從未進出"
        self.grid.set_rows(rows if isinstance(rows, list) else [])
        if refresh:
            self.update()

    def provision(self):
        rows = self.grid.selected_rows()
        if not rows:
            self.ctx.toast("請勾選商品", True)
            return
        pct = T.field("提列比例（%）", "50", width=140)
        c = self.ctx

        def go(e):
            try:
                p = Decimal(pct.value or "0") / 100
            except Exception:
                c.toast("比例要是數字", True)
                return
            lines = []
            for r in rows:
                amt = (r["value"] or 0) * p - (r["provision"] or 0)
                amt = amt.quantize(Decimal("1"))
                if amt:
                    lines.append(dict(product=r["product"], amount=amt, memo="閒置 %s" % r["idle_days"]))
            if not lines:
                c.toast("勾選的商品已提足，不需再提列", True)
                return
            did = c.guard(c.books.save_doc, None, dict(doc_type="WD", memo="呆滯品提列跌價 %s%%" % pct.value), lines)
            if did:
                c.close()
                c.toast("已產生呆料跌價提列單")
                c.app.go("doc_WD", doc_id=did)
        c.dialog("提列跌價損失", ft.Column([T.muted("提列金額＝庫存金額×比例－已提列；會產生「呆料跌價提列」單，"
                                                "拋轉會計後借：存貨跌價及呆滯損失、貸：備抵存貨跌價損失。", 13), pct],
                                        tight=True, spacing=12),
                 [T.btn("取消", kind="ghost", on_click=lambda e: c.close()), T.btn("產生提列單", ft.Icons.CHECK, go)],
                 icon=ft.Icons.TRENDING_DOWN, tone="rose", width=480)

    def scrap(self):
        rows = self.grid.selected_rows()
        if not rows:
            self.ctx.toast("請勾選商品", True)
            return
        b = self.ctx.books
        wh = self.wh.value or b.default_warehouse()
        lines = [dict(product=r["product"], qty=min(r["qty"], b.stock_qty(r["product"], wh)))
                 for r in rows if b.stock_qty(r["product"], wh) > 0]
        if not lines:
            self.ctx.toast("所選倉庫沒有這些商品的庫存，請先選擇倉庫", True)
            return
        did = self.ctx.guard(b.save_doc, None, dict(doc_type="SCR", warehouse=wh, reason="呆滯報廢",
                                                     memo="呆滯品報廢"), lines)
        if did:
            self.ctx.toast("已產生報廢單，請確認數量")
            self.ctx.app.go("doc_SCR", doc_id=did)


_ = (dt, ym_add)
