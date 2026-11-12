"""統計報表：銷貨明細與毛利、進貨明細、排行分析、月份統計、進銷存彙總表、成本月結表。"""
import flet as ft

from .. import printing, rocdate
from . import theme as T
from .dashboard import legend


def print_grid(ctx, grid, title, sub):
    """把畫面上的表格印成報表（HTML，可另存 PDF）。"""
    if not grid.data_rows:
        ctx.toast("沒有資料可以列印", True)
        return
    cols = [(c[0], c[1], c[2] in ("n", "nz")) for c in grid.cols]
    rows = [{c[0]: T.show(r.get(c[0]), c[2] if c[2] in ("n", "nz", "d", "b") else "") for c in grid.cols}
            for r in grid.data_rows]
    comp = ctx.books.company()
    printing.write_and_open(printing.page(comp.get("name") or "", title, sub, printing.table(cols, rows)), title)


def tools(ctx, grid, title, sub_fn):
    return [ctx.export_button(grid, title),
            T.btn("列印", ft.Icons.PRINT, lambda e: print_grid(ctx, grid, title, sub_fn()), kind="outline")]


class Detail(ft.Column):
    """銷貨（S）或進貨（P）明細，退回為負數。"""

    def __init__(self, ctx, side):
        self.ctx, self.side = ctx, side
        b = ctx.books
        today = rocdate.today()
        pk = "C" if side == "S" else "V"
        self.start = T.date_field("起", today.replace(day=1), width=150)
        self.end = T.date_field("迄", today, width=150)
        self.partner = T.dropdown("客戶" if side == "S" else "廠商", b.options(pk), None, width=200, blank="全部")
        prods = [(p["code"], "%s %s" % (p["code"], p["name"])) for p in
                 b.product_list(active_only=False)]
        self.product = T.dropdown("商品", prods, None, width=220, blank="全部")
        self.cat = T.dropdown("類別", b.options("cat"), "", width=150, blank="全部", filterable=False)
        cols = [("doc_date", "日期", "d", 90), ("doc_no", "單號", "s", 130), ("type_name", "種類", "s", 70),
                ("partner_show", "客戶" if side == "S" else "廠商", "s", 120), ("product", "商品", "s", 100),
                ("name", "品名", "s", 180), ("qty", "數量", "n", 80), ("price", "單價", "n", 90), ("net", "未稅金額", "n", 110)]
        tot = ["net"]
        if side == "S" and b.see_cost:
            cols += [("cost", "成本", "n", 100), ("margin", "毛利", "n", 100), ("margin_rate", "毛利率%", "s", 70)]
            tot += ["cost", "margin"]
        self.title = "銷貨明細與毛利" if side == "S" else "進貨明細"
        self.grid = T.Grid(cols, totals=tuple(tot),
                           on_pick=lambda r: ctx.app.go("doc_" + r["doc_type"], doc_id=self._doc_id(r)))
        super().__init__([T.page_header(ft.Icons.RECEIPT_LONG if side == "S" else ft.Icons.LIST_ALT, self.title,
                                        "退回、折讓以負數列示；毛利在月結前以平均成本估算" if side == "S" else
                                        "進貨與進貨退出／折讓", "orange",
                                        tools(ctx, self.grid, self.title, self.sub)),
                          T.card(ft.Row([self.start, self.end, self.partner, self.product, self.cat,
                                         T.btn("查詢", ft.Icons.SEARCH, lambda e: self.load())], wrap=True, spacing=10),
                                 padding=14), self.grid], spacing=12, expand=True)
        self.load(refresh=False)

    def _doc_id(self, r):
        return self.ctx.books.doc_id_by_no(r["doc_no"])

    def sub(self):
        return "%s～%s" % (self.start.value, self.end.value)

    def load(self, refresh=True):
        rows = self.ctx.guard(self.ctx.books.line_detail, self.side, self.start.value, self.end.value,
                              self.partner.value or "", self.product.value or "", self.cat.value or "") or []
        for r in rows if isinstance(rows, list) else []:
            r["margin_rate"] = "" if r.get("margin_rate") is None else "%s" % r["margin_rate"]
        self.grid.set_rows(rows if isinstance(rows, list) else [])
        if refresh:
            self.update()


class Ranking(ft.Column):
    def __init__(self, ctx):
        self.ctx = ctx
        today = rocdate.today()
        self.side = T.dropdown("對象", [("S", "銷貨"), ("P", "進貨")], "S", width=110, filterable=False)
        self.by = T.dropdown("排行依", [("product", "商品"), ("partner", "客戶／廠商"), ("employee", "業務員"),
                                     ("category", "商品類別")], "product", width=150, filterable=False)
        self.start = T.date_field("起", today.replace(month=1, day=1), width=150)
        self.end = T.date_field("迄", today, width=150)
        self.body = ft.Column(expand=True, spacing=10)
        self.grid = None
        super().__init__([T.page_header(ft.Icons.LEADERBOARD, "排行分析", "依淨額（扣除退回折讓）排名", "orange"),
                          T.card(ft.Row([self.side, self.by, self.start, self.end,
                                         T.btn("分析", ft.Icons.SEARCH, lambda e: self.load())], wrap=True, spacing=10),
                                 padding=14), self.body], spacing=12, expand=True)
        self.load(refresh=False)

    def load(self, refresh=True):
        b = self.ctx.books
        rows = self.ctx.guard(b.ranking, self.by.value, self.side.value, self.start.value, self.end.value) or []
        rows = rows if isinstance(rows, list) else []
        for r in rows:
            r["share_s"] = "" if r["share"] is None else "%s%%" % r["share"]
            r["margin_rate"] = "" if r.get("margin_rate") is None else "%s%%" % r["margin_rate"]
            r["rank_s"] = str(r["rank"])
        cols = [("rank_s", "名次", "s", 50), ("k", "代號", "s", 100), ("name", "名稱", "s", 220),
                ("qty", "數量", "n", 90), ("net", "淨額", "n", 120), ("share_s", "占比", "s", 70), ("docs", "單數", "s", 60)]
        if self.side.value == "S" and b.see_cost:
            cols += [("cost", "成本", "n", 110), ("margin", "毛利", "n", 110), ("margin_rate", "毛利率", "s", 70)]
        self.grid = T.Grid(cols, totals=("net",))
        for r in rows:
            r["docs"] = str(r["docs"])
        self.grid.set_rows(rows)
        top = rows[:10]
        mx = max([abs(r["net"] or 0) for r in top] + [1])
        bars = ft.Column([ft.Row([ft.Text(r["name"][:14], width=170, size=12, max_lines=1),
                                  ft.Container(width=max(2, float(abs(r["net"] or 0) / mx) * 420), height=16,
                                               bgcolor="#14B8A6" if self.side.value == "S" else "#F59E0B",
                                               border_radius=4),
                                  T.muted(T.amt(r["net"]), 12)], spacing=8) for r in top], spacing=6)
        self.body.controls = [ft.Row([T.card(ft.Column([ft.Text("前十名", size=15, weight=ft.FontWeight.W_700), bars],
                                                       spacing=10), padding=16),
                                      ft.Container(expand=True)] + tools(self.ctx, self.grid, "排行分析",
                                                                         lambda: "%s～%s" % (self.start.value,
                                                                                            self.end.value)),
                                     vertical_alignment=ft.CrossAxisAlignment.START), self.grid]
        if refresh:
            self.update()


class Monthly(ft.Column):
    def __init__(self, ctx):
        self.ctx = ctx
        y = rocdate.today().year
        self.year = T.dropdown("年度", [(str(x), "%d 年" % (x - 1911)) for x in range(y, y - 6, -1)], str(y), width=130,
                               filterable=False, on_select=lambda e: self.load())
        self.body = ft.Column(expand=True, spacing=10)
        super().__init__([T.page_header(ft.Icons.BAR_CHART, "月份統計", "各月銷貨、進貨與毛利（未稅）", "orange",
                                        [self.year]), self.body], spacing=12, expand=True, scroll=ft.ScrollMode.AUTO)
        self.load(refresh=False)

    def load(self, refresh=True):
        b = self.ctx.books
        rows = b.monthly(int(self.year.value))
        for r in rows:
            r["margin_rate"] = "" if r["margin_rate"] is None else "%s%%" % r["margin_rate"]
        cols = [("month", "月份", "s", 70), ("sales", "銷貨淨額", "n", 130), ("purchase", "進貨淨額", "n", 130)]
        if b.see_cost:
            cols += [("cost", "銷貨成本", "n", 130), ("margin", "毛利", "n", 130), ("margin_rate", "毛利率", "s", 80)]
        g = T.Grid(cols, totals=("sales", "purchase", "cost", "margin") if b.see_cost else ("sales", "purchase"),
                   height=470)
        g.set_rows(rows)
        mx = max([abs(r["sales"]) for r in rows] + [abs(r["purchase"]) for r in rows] + [1])
        h = 170
        chart = ft.Row([ft.Column([ft.Row([
            ft.Container(width=12, height=max(2, float(max(r["sales"], 0) / mx) * h), bgcolor="#14B8A6",
                         border_radius=ft.BorderRadius.only(top_left=4, top_right=4)),
            ft.Container(width=12, height=max(2, float(max(r["purchase"], 0) / mx) * h), bgcolor="#F59E0B",
                         border_radius=ft.BorderRadius.only(top_left=4, top_right=4))], spacing=3,
            vertical_alignment=ft.CrossAxisAlignment.END), T.muted(r["month"], 11)],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4, alignment=ft.MainAxisAlignment.END)
            for r in rows], alignment=ft.MainAxisAlignment.SPACE_AROUND, vertical_alignment=ft.CrossAxisAlignment.END)
        self.body.controls = [T.card(ft.Column([ft.Row([legend("銷貨", "#14B8A6"), legend("進貨", "#F59E0B"),
                                                        ft.Container(expand=True)] +
                                                       tools(self.ctx, g, "月份統計",
                                                             lambda: "%s 年" % (int(self.year.value) - 1911))),
                                                ft.Container(chart, height=h + 26)], spacing=10), padding=16), g]
        if refresh:
            self.update()


class InOut(ft.Column):
    def __init__(self, ctx):
        self.ctx = ctx
        b = ctx.books
        today = rocdate.today()
        self.start = T.date_field("起", today.replace(day=1), width=150)
        self.end = T.date_field("迄", today, width=150)
        self.wh = T.dropdown("倉庫", b.options("wh"), "", width=160, blank="全部倉庫", filterable=False)
        self.cat = T.dropdown("類別", b.options("cat"), "", width=150, blank="全部", filterable=False)
        cols = [("product", "商品編號", "s", 110), ("name", "品名", "s", 200), ("unit", "單位", "s", 50),
                ("open", "期初", "n", 80), ("purchase", "進貨淨", "n", 80), ("sales", "銷貨淨", "n", 80),
                ("other_in", "其他入", "n", 80), ("other_out", "其他出", "n", 80), ("close", "結存", "n", 80)]
        if b.see_cost:
            cols.append(("value", "結存金額", "n", 110))
        self.grid = T.Grid(cols, totals=("value",) if b.see_cost else (),
                           on_pick=lambda r: ctx.app.go("stock_card", product=r["product"]))
        super().__init__([T.page_header(ft.Icons.TABLE_CHART, "進銷存彙總表",
                                        "期間各商品的期初、進、銷、其他異動與結存數量（其他＝調撥、入出庫、報廢、調整）",
                                        "orange", tools(ctx, self.grid, "進銷存彙總表",
                                                        lambda: "%s～%s" % (self.start.value, self.end.value))),
                          T.card(ft.Row([self.start, self.end, self.wh, self.cat,
                                         T.btn("查詢", ft.Icons.SEARCH, lambda e: self.load())], wrap=True, spacing=10),
                                 padding=14), self.grid], spacing=12, expand=True)
        self.load(refresh=False)

    def load(self, refresh=True):
        rows = self.ctx.guard(self.ctx.books.inout_summary, self.start.value, self.end.value, self.wh.value or "",
                              self.cat.value or "") or []
        self.grid.set_rows(rows if isinstance(rows, list) else [])
        if refresh:
            self.update()


class CostMonth(ft.Column):
    def __init__(self, ctx):
        self.ctx = ctx
        b = ctx.books
        months = b.cost_close_months()
        self.ym = T.dropdown("月份", [(m, rocdate.ym_show(m)) for m in months], months[0] if months else None,
                             width=170, filterable=False, on_select=lambda e: self.load())
        cols = [("product", "商品編號", "s", 110), ("name", "品名", "s", 180), ("open_qty", "期初量", "n", 75),
                ("open_amt", "期初金額", "n", 100), ("in_qty", "入庫量", "n", 75), ("in_amt", "入庫金額", "n", 100),
                ("unit_cost", "單位成本", "n", 90), ("sale_qty", "銷貨量", "n", 75), ("sale_amt", "銷貨成本", "n", 100),
                ("other_qty", "其他出", "n", 70), ("other_amt", "其他成本", "n", 90), ("close_qty", "結存量", "n", 75),
                ("close_amt", "結存金額", "n", 110)]
        if not b.see_cost:
            cols = [c for c in cols if not c[0].endswith("_amt") and c[0] != "unit_cost"]
        self.grid = T.Grid(cols, totals=("open_amt", "in_amt", "sale_amt", "other_amt", "close_amt")
                           if b.see_cost else (), empty="尚未月結（到「成本月結」執行）")
        super().__init__([T.page_header(ft.Icons.CALCULATE, "成本月結表", "月加權平均成本計算結果", "orange",
                                        [self.ym] + tools(ctx, self.grid, "成本月結表",
                                                          lambda: rocdate.ym_show(self.ym.value) if self.ym.value
                                                          else "")),
                          self.grid], spacing=12, expand=True)
        self.load(refresh=False)

    def load(self, refresh=True):
        rows = self.ctx.books.cost_month_rows(self.ym.value) if self.ym.value else []
        self.grid.set_rows(rows)
        if refresh:
            self.update()
