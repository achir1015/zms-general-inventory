"""首頁：關鍵數字、十二個月銷貨與進貨、快捷功能、待辦提醒、熱銷商品。"""
import datetime as dt
from decimal import Decimal

import flet as ft

from .. import rocdate
from . import theme as T


class Dashboard(ft.Column):
    def __init__(self, ctx):
        self.ctx = ctx
        b, app = ctx.books, ctx.app
        d = b.dashboard()
        comp = b.company()
        hour = dt.datetime.now().hour
        hello = "早安" if hour < 11 else "午安" if hour < 18 else "晚安"

        chips = [hero_chip(ft.Icons.CALENDAR_MONTH, rocdate.ym_show(rocdate.ym(rocdate.today()))),
                 hero_chip(ft.Icons.LOCK_CLOCK, "已月結至 %s" % rocdate.ym_show(d["closed_ym"]) if d["closed_ym"]
                           else "尚未月結")]
        if d["gl_pending"]:
            chips.append(hero_chip(ft.Icons.SYNC_ALT, "待拋轉會計 %d 筆" % d["gl_pending"]))
        hero = ft.Container(ft.Row([
            ft.Column([
                ft.Text("%s，%s" % (hello, b.user["name"]), size=26, weight=ft.FontWeight.W_800,
                        color=ft.Colors.WHITE),
                ft.Text(comp.get("name") or "請先到「系統管理 → 公司設定」輸入公司名稱", size=15, color="#CFE0F7"),
                ft.Container(height=6), ft.Row(chips, spacing=10, wrap=True)], spacing=2, expand=True),
            ft.Image(src="icon.png", width=96, height=96, opacity=0.95)]),
            padding=26, border_radius=20,
            gradient=ft.LinearGradient(begin=ft.Alignment.CENTER_LEFT, end=ft.Alignment.CENTER_RIGHT,
                                       colors=[T.PRIMARY_DARK, T.PRIMARY, "#178A8F"]),
            shadow=ft.BoxShadow(blur_radius=24, spread_radius=-8, color="#551E4D8C", offset=ft.Offset(0, 10)))

        cards = [T.kpi("本月銷貨（未稅）", r0(d["month_sales"]), ft.Icons.POINT_OF_SALE, "teal",
                       sub="今日 %s" % T.amt(d["today_sales"]), on_click=lambda e: app.go("rpt_sales"))]
        if "month_margin" in d:
            rate = (d["month_margin"] / d["month_sales"] * 100) if d["month_sales"] else Decimal(0)
            cards.append(T.kpi("本月毛利", r0(d["month_margin"]), ft.Icons.TRENDING_UP, "green",
                               sub="毛利率 %.1f%%" % rate, on_click=lambda e: app.go("rpt_sales")))
            cards.append(T.kpi("庫存金額", r0(d["stock_value"]), ft.Icons.WAREHOUSE, "violet",
                               sub="低於安全存量 %d 項" % d["low_stock"], on_click=lambda e: app.go("stock")))
        else:
            cards.append(T.kpi("低於安全存量", "%d 項" % d["low_stock"], ft.Icons.WARNING_AMBER, "amber",
                               on_click=lambda e: app.go("low_stock")))
        cards += [T.kpi("應收帳款", r0(d["ar"]), ft.Icons.CALL_RECEIVED, "sky",
                        on_click=lambda e: app.go("receivable")),
                  T.kpi("應付帳款", r0(d["ap"]), ft.Icons.CALL_MADE, "amber",
                        on_click=lambda e: app.go("payable"))]
        kpis = T.kpis(cards)

        quick = [("doc_SI", "銷貨單", ft.Icons.LOCAL_SHIPPING, "teal"), ("doc_PI", "進貨單", ft.Icons.INVENTORY, "green"),
                 ("doc_SO", "客戶訂單", ft.Icons.ASSIGNMENT, "blue"), ("doc_PO", "採購單", ft.Icons.SHOPPING_CART, "amber"),
                 ("receipt_R", "收款沖帳", ft.Icons.ADD_CARD, "sky"), ("receipt_P", "付款沖帳", ft.Icons.CREDIT_CARD, "orange"),
                 ("stock", "庫存查詢", ft.Icons.WAREHOUSE, "violet"), ("count", "盤點作業", ft.Icons.FACT_CHECK, "pink"),
                 ("gl_transfer", "會計拋轉", ft.Icons.SYNC_ALT, "rose"), ("help", "使用說明", ft.Icons.RECORD_VOICE_OVER,
                                                                      "green")]
        quick_tiles = ft.Row([quick_tile(t, ic, tone, lambda e, s=sid: app.go(s)) for sid, t, ic, tone in quick
                              if app.find(sid)], wrap=True, spacing=12, run_spacing=12)

        chart = T.card(ft.Column([
            ft.Row([T.icon_tile(ft.Icons.AUTO_GRAPH, "violet", 36), ft.Text("近 12 個月銷貨與進貨（未稅）", size=17,
                                                                          weight=ft.FontWeight.W_700),
                    ft.Container(expand=True), legend("銷貨", "#14B8A6"), legend("進貨", "#F59E0B")], spacing=10),
            bars(d["months"])], spacing=14), expand=3)

        todo_items = []
        if d["open_so"]:
            todo_items.append(todo_row(ft.Icons.ASSIGNMENT, "blue", "訂單未出貨", "%d 張" % d["open_so"],
                                       lambda e: app.go("track_SO")))
        if d["open_po"]:
            todo_items.append(todo_row(ft.Icons.SHOPPING_CART, "amber", "採購未進貨", "%d 張" % d["open_po"],
                                       lambda e: app.go("track_PO")))
        if d["low_stock"]:
            todo_items.append(todo_row(ft.Icons.WARNING_AMBER, "rose", "低於安全存量", "%d 項" % d["low_stock"],
                                       lambda e: app.go("low_stock")))
        nd = d["notes_due"]
        if nd.get("R"):
            todo_items.append(todo_row(ft.Icons.RECEIPT_LONG, "green", "兩週內到期應收票據",
                                       "%d 張 %s" % (nd["R"][0], T.amt(nd["R"][1])), lambda e: app.go("notes_R")))
        if nd.get("P"):
            todo_items.append(todo_row(ft.Icons.EDIT_DOCUMENT, "orange", "兩週內到期應付票據",
                                       "%d 張 %s" % (nd["P"][0], T.amt(nd["P"][1])), lambda e: app.go("notes_P")))
        if d["gl_pending"]:
            todo_items.append(todo_row(ft.Icons.SYNC_ALT, "violet", "尚未拋轉會計", "%d 筆" % d["gl_pending"],
                                       lambda e: app.go("gl_transfer")))
        top = d.get("top_products") or []
        if top:
            todo_items.append(ft.Container(height=4))
            todo_items.append(ft.Text("本月熱銷商品", size=14, weight=ft.FontWeight.W_700, color=T.TEXT))
            for r in top:
                todo_items.append(ft.Row([T.chip(str(r["rank"]), "teal"), ft.Text(r["name"], size=13, expand=True,
                                                                                  max_lines=1),
                                          T.muted(T.amt(r["net"]), 12)], spacing=8))
        todo = T.card(ft.Column([
            ft.Row([T.icon_tile(ft.Icons.PENDING_ACTIONS, "amber", 36),
                    ft.Text("待辦提醒", size=17, weight=ft.FontWeight.W_700)], spacing=10),
            ft.Column(todo_items or [T.empty_state(ft.Icons.TASK_ALT, "目前沒有待辦事項")], spacing=6,
                      scroll=ft.ScrollMode.AUTO, expand=True)], spacing=12), expand=2, height=330)

        super().__init__([
            hero, kpis,
            ft.Row([ft.Text("快捷功能", size=17, weight=ft.FontWeight.W_700, color=T.TEXT)]), quick_tiles,
            T.split(chart, todo, spacing=16)],
            spacing=18, scroll=ft.ScrollMode.AUTO, expand=True)


def r0(v):
    """首頁卡片金額：四捨五入到元，避免小數被截斷。"""
    return T.amt(Decimal(str(v or 0)).quantize(Decimal(1)))


def hero_chip(icon, text):
    return ft.Container(ft.Row([ft.Icon(icon, size=15, color=ft.Colors.WHITE), ft.Text(text, size=12,
                                                                                    color=ft.Colors.WHITE)],
                               spacing=6, tight=True), bgcolor="#33FFFFFF", border_radius=20,
                        padding=ft.Padding.symmetric(horizontal=12, vertical=5))


def quick_tile(title, icon, tone, on_click):
    return ft.Container(ft.Column([T.icon_tile(icon, tone, 48, radius=14),
                                   ft.Text(title, size=13, weight=ft.FontWeight.W_600, color=T.TEXT)],
                                  horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                        width=112, padding=ft.Padding.symmetric(vertical=16), bgcolor=T.CARD, border_radius=16,
                        border=ft.Border.all(1, T.LINE), on_click=on_click, ink=True,
                        shadow=ft.BoxShadow(blur_radius=14, spread_radius=-6, color="#1A1E3A5F",
                                            offset=ft.Offset(0, 4)))


def todo_row(icon, tone, title, value, on_click):
    return ft.Container(ft.Row([T.icon_tile(icon, tone, 30, radius=9), ft.Text(title, size=13, expand=True),
                                ft.Text(value, size=13, weight=ft.FontWeight.W_700, color=T.TEXT),
                                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16, color=T.MUTED)], spacing=10),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=6), border_radius=10, bgcolor="#F7F9FC",
                        on_click=on_click, ink=True)


def legend(text, color):
    return ft.Row([ft.Container(width=12, height=12, bgcolor=color, border_radius=3), T.muted(text, 12)],
                  spacing=5, tight=True)


def bars(months, h=190):
    top = max([Decimal(1)] + [abs(m["sales"]) for m in months] + [abs(m["purchase"]) for m in months])
    cols = []
    for m in months:
        s, p = max(m["sales"], 0), max(m["purchase"], 0)
        label = "%d月" % int(m["ym"][4:])
        cols.append(ft.Column([
            ft.Row([ft.Container(width=12, height=max(2, float(s / top) * h), bgcolor="#14B8A6",
                                 border_radius=ft.BorderRadius.only(top_left=4, top_right=4),
                                 tooltip="銷貨 %s" % T.amt(m["sales"])),
                    ft.Container(width=12, height=max(2, float(p / top) * h), bgcolor="#F59E0B",
                                 border_radius=ft.BorderRadius.only(top_left=4, top_right=4),
                                 tooltip="進貨 %s" % T.amt(m["purchase"]))],
                   spacing=3, vertical_alignment=ft.CrossAxisAlignment.END),
            T.muted(label, 11)], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4,
            alignment=ft.MainAxisAlignment.END))
    return ft.Container(ft.Row(cols, alignment=ft.MainAxisAlignment.SPACE_AROUND,
                               vertical_alignment=ft.CrossAxisAlignment.END), height=h + 26,
                        border=ft.Border.only(bottom=ft.BorderSide(1, T.LINE)))
