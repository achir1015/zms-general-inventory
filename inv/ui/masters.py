"""基本資料：商品、客戶、廠商、類別、倉庫、員工、部門、銀行帳戶、異動原因、備註片語（清單＋右側編輯）。"""
from decimal import Decimal

import flet as ft

from ..core import MASTERS
from . import theme as T

MASTER_STYLE = {"products": (ft.Icons.CATEGORY, "teal"), "customers": (ft.Icons.STOREFRONT, "green"),
                "vendors": (ft.Icons.LOCAL_SHIPPING, "orange"), "categories": (ft.Icons.LABEL, "violet"),
                "warehouses": (ft.Icons.WAREHOUSE, "blue"), "employees": (ft.Icons.BADGE, "violet"),
                "departments": (ft.Icons.APARTMENT, "sky"), "bank_accounts": (ft.Icons.ACCOUNT_BALANCE, "amber"),
                "reasons": (ft.Icons.RULE, "rose"), "phrases": (ft.Icons.SHORT_TEXT, "pink")}
SUBTITLE = {"products": "售價、成本、安全存量與主要供應商；可用 Excel 整理後匯入",
            "customers": "結帳日、收款天數、價格等級與信用額度", "vendors": "結帳日與付款天數",
            "bank_accounts": "收付款、票據託收兌現用；「會計科目」對應會計系統的銀行存款科目",
            "reasons": "庫存調整、報廢、領用、其他入庫時可選的原因",
            "warehouses": "可設定多個倉庫；預設倉會自動帶入單據"}
LIST_COLS = {"products": ["code", "name", "spec", "category", "unit", "price", "avg_cost", "safety_qty", "active"],
             "customers": ["code", "name", "short_name", "tax_id", "contact", "phone", "closing_day", "active"],
             "vendors": ["code", "name", "short_name", "tax_id", "contact", "phone", "closing_day", "active"]}
REF_OPTS = {"cat": "categories", "vendor": "vendors", "dept": "departments", "emp": "employees", "wh": "warehouses"}


def form_header(icon, tone, title, sub=""):
    return ft.Row([T.icon_tile(icon, tone, 40), ft.Column([ft.Text(title, size=17, weight=ft.FontWeight.W_700),
                                                          T.muted(sub, 12)] if sub else
                                                         [ft.Text(title, size=17, weight=ft.FontWeight.W_700)],
                                                         spacing=0, expand=True)], spacing=12)


def sel_options(typ):
    return [tuple(x.split("=")) for x in typ[4:].split(",")]


class MasterList(ft.Row):
    def __init__(self, ctx, name):
        self.ctx, self.name = ctx, name
        self.m = MASTERS[name]
        b = ctx.books
        self.editable = b.can("BAS", 2)
        icon, tone = MASTER_STYLE.get(name, (ft.Icons.FOLDER, "blue"))
        self.icon, self.tone = icon, tone
        self.search = T.field("搜尋", "", width=220, prefix_icon=ft.Icons.SEARCH, on_change=lambda e: self.filter())
        fields = {f[0]: f for f in self.m["fields"]}
        show = LIST_COLS.get(name) or [f[0] for f in self.m["fields"]]
        cols = []
        for k in show:
            _, t, typ, w = fields[k]
            if k in self.m.get("cost_fields", ()) and not b.see_cost:
                continue
            cols.append((k + "_show" if typ.startswith("sel:") or typ in REF_OPTS else k, t,
                         "n" if typ == "n" else "b" if typ == "b" else "s", min(w, 230)))
        self.grid = T.Grid(cols, on_pick=self.edit)
        self.rows = []
        self.current = None
        self.inputs = {}
        self.form = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)
        tools = [self.search, ctx.export_button(self.grid, self.m["title"])]
        if self.editable and name in ("products", "customers", "vendors", "categories", "warehouses", "employees"):
            tools.append(ft.PopupMenuButton(
                content=ft.Container(ft.Row([ft.Icon(ft.Icons.UPLOAD_FILE, size=18, color=T.PRIMARY),
                                             ft.Text("匯入 Excel", color=T.PRIMARY, size=14,
                                                     weight=ft.FontWeight.W_500)], spacing=8, tight=True),
                                     border=ft.Border.all(1, "#C7D4E8"), border_radius=10,
                                     padding=ft.Padding.symmetric(horizontal=16, vertical=10)),
                tooltip="下載範本或匯入名冊",
                items=[ft.PopupMenuItem("下載範本（CSV）", icon=ft.Icons.DOWNLOAD, on_click=self.template),
                       ft.PopupMenuItem("選擇檔案匯入", icon=ft.Icons.UPLOAD_FILE, on_click=self.do_import)]))
        left = ft.Column([T.page_header(icon, self.m["title"], SUBTITLE.get(name, ""), tone, tools), self.grid],
                         expand=True, spacing=12)
        super().__init__([left, T.card(self.form, width=420, padding=18)], expand=True, spacing=14, data="split",
                         vertical_alignment=ft.CrossAxisAlignment.START)
        self.opts = {}
        self.reload()
        self.edit(None, refresh=False)

    def options(self, typ):
        if typ not in self.opts:
            self.opts[typ] = self.ctx.books.options(REF_OPTS[typ])
        return self.opts[typ]

    def reload(self):
        self.rows = self.ctx.books.master_rows(self.name)
        for k, t, typ, w in self.m["fields"]:
            if typ.startswith("sel:"):
                o = dict(sel_options(typ))
                for r in self.rows:
                    r[k + "_show"] = o.get(str(r.get(k)), r.get(k))
            elif typ in REF_OPTS:
                o = dict(self.options(typ))
                for r in self.rows:
                    r[k + "_show"] = o.get(r.get(k), r.get(k) or "")
        self.filter(refresh=False)

    def filter(self, refresh=True):
        q = (self.search.value or "").strip().lower()
        rows = [r for r in self.rows if not q or any(q in str(v).lower() for v in r.values())]
        self.grid.set_rows(rows)
        if refresh:
            self.update()

    async def template(self, e):
        from .. import csvio
        await self.ctx.save_generated("%s範本.csv" % self.m["title"], lambda p: csvio.master_template(self.name, p))

    async def do_import(self, e):
        from .. import csvio
        path = await self.ctx.pick_csv("選擇%s名冊（CSV）" % self.m["title"])
        if not path:
            return
        r = self.ctx.guard(csvio.import_masters, self.ctx.books, self.name, path)
        if not r:
            return
        ok, errs = r
        self.reload()
        self.update()
        msg = ft.Column([ft.Text("成功匯入（新增或更新）%d 筆。" % ok, size=15, color=T.SUCCESS,
                                 weight=ft.FontWeight.W_600)] +
                        ([ft.Text("以下 %d 列未匯入：" % len(errs), color=T.DANGER)] +
                         [ft.Text(x, size=12, selectable=True) for x in errs[:30]] if errs else []),
                        tight=True, scroll=ft.ScrollMode.AUTO, height=None if len(errs) < 10 else 360)
        self.ctx.dialog("匯入結果", msg, [T.btn("確定", on_click=lambda e: self.ctx.close())],
                        icon=ft.Icons.UPLOAD_FILE, tone="green" if not errs else "amber", width=520)

    def edit(self, r, refresh=True):
        self.current = r
        self.inputs = {}
        b = self.ctx.books
        ctrls = []
        pair = []
        for key, title, typ, w in self.m["fields"]:
            if key in self.m.get("cost_fields", ()) and not b.see_cost:
                continue
            v = (r or {}).get(key)
            ro = key in self.m.get("readonly", ())
            if typ == "b":
                c = T.switch(title, (True if key in ("active", "is_stock") else False) if r is None else v)
            elif typ.startswith("sel:"):
                c = T.dropdown(title, sel_options(typ), str(v) if v not in (None, "") else sel_options(typ)[0][0],
                               filterable=False)
            elif typ in REF_OPTS:
                c = T.dropdown(title, self.options(typ), v or "", blank="（無）")
            elif typ in ("n", "i"):
                c = T.field(title, "" if v is None else (T.amt(v) if typ == "n" else str(v)),
                            text_align=ft.TextAlign.RIGHT, read_only=ro)
            else:
                c = T.field(title, v or "", read_only=(bool(r) and key == self.m["key"] and key != "id") or ro,
                            multiline=key == "memo")
            c.disabled = not self.editable or ro
            self.inputs[key] = c
            if typ in ("n", "i") and self.name in ("products", "customers", "vendors"):
                c.expand = True
                pair.append(c)
                if len(pair) == 2:
                    ctrls.append(ft.Row(pair, spacing=10))
                    pair = []
                continue
            if pair:
                ctrls.append(ft.Row(pair, spacing=10))
                pair = []
            ctrls.append(c)
        if pair:
            ctrls.append(ft.Row(pair, spacing=10))
        acts = []
        if self.editable:
            acts = [T.btn("儲存", ft.Icons.SAVE, lambda e: self.save()),
                    T.btn("新增", ft.Icons.ADD, lambda e: self.edit(None), kind="outline")]
            if r:
                acts.append(T.btn("刪除", ft.Icons.DELETE_OUTLINE, lambda e: self.delete(), kind="danger"))
        extra = []
        if r and self.name == "products":
            st = b.stock_qty(r["code"])
            extra = [ft.Row([T.chip("目前庫存 %s %s" % (T.amt(st), r["unit"]), "violet", ft.Icons.WAREHOUSE),
                             T.btn("異動明細", ft.Icons.TIMELINE, lambda e: self.ctx.app.go("stock_card",
                                                                                         product=r["code"]),
                                   kind="ghost")], wrap=True)]
        self.form.controls = [form_header(self.icon, self.tone, "修改%s" % self.m["title"] if r else
                                          "新增%s" % self.m["title"], "" if self.editable else "您只有查詢權限"),
                              *extra, *ctrls, ft.Row(acts, wrap=True, spacing=8)]
        if refresh:
            self.update()

    def save(self):
        row = {k: c.value for k, c in self.inputs.items()}
        if self.current and self.m["key"] == "id":
            row["id"] = self.current["id"]
        for k, t, typ, _ in self.m["fields"]:
            if typ == "n" and k in row:
                row[k] = str(row[k] or "0").replace(",", "")
        if self.ctx.guard(self.ctx.books.save_master, self.name, row, self.current is None, ok="已儲存"):
            self.reload()
            self.edit(None)

    def delete(self):
        key = self.current[self.m["key"]]
        label = self.current.get("name") or self.current.get("text") or key

        def go():
            if self.ctx.guard(self.ctx.books.delete_master, self.name, key, ok="已刪除"):
                self.reload()
                self.edit(None)
        self.ctx.confirm("刪除%s" % self.m["title"], "確定要刪除「%s」嗎？" % label, go, yes="刪除")


_ = Decimal
