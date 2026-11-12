"""共用基礎：錯誤類別、金額數量格式、登入與權限、使用者、公司設定、基本資料維護。

所有規則都在服務層檢查（畫面只負責顯示），日後手機版透過 API 也共用同一套。
"""
import datetime as dt
import json
from decimal import ROUND_HALF_UP, Decimal

from . import passwords, rocdate
from .seed import FUNC_NAMES, FUNCS, ROLES

CENT = Decimal("0.01")
MILLI = Decimal("0.001")
D0 = Decimal(0)


class BizError(Exception):
    """可以直接顯示給使用者看的錯誤。"""


def dec(v, q=CENT) -> Decimal:
    if v in (None, ""):
        return D0
    if isinstance(v, str):
        v = v.replace(",", "").strip() or "0"
    try:
        return Decimal(str(v)).quantize(q, ROUND_HALF_UP)
    except Exception:
        raise BizError("數字格式不正確：%s" % v)


def money(v) -> Decimal:
    return dec(v, CENT)


def qty(v) -> Decimal:
    return dec(v, MILLI)


def price(v) -> Decimal:
    return dec(v, Decimal("0.0001"))


def date(v) -> dt.date:
    try:
        return rocdate.read(v)
    except ValueError as e:
        raise BizError(str(e))


# 基本資料定義：(欄位, 標題, 型別, 寬度)；型別 s 文字、n 數字、i 整數、b 是否、
# cat 類別、wh 倉庫、vendor 廠商、dept 部門、emp 員工、acct 會計科目、sel:選項
MASTERS = {
    "products": dict(title="商品資料", table="products", key="code", fields=[
        ("code", "商品編號", "s", 130), ("name", "品名", "s", 220), ("spec", "規格", "s", 150),
        ("category", "類別", "cat", 140), ("unit", "單位", "s", 70), ("barcode", "條碼", "s", 140),
        ("price", "售價", "n", 100), ("price2", "批發價", "n", 100), ("std_cost", "標準進價", "n", 100),
        ("last_cost", "最近進價", "n", 100), ("avg_cost", "平均成本", "n", 100),
        ("safety_qty", "安全存量", "n", 90), ("vendor", "主要供應商", "vendor", 170),
        ("is_stock", "計庫存", "b", 70), ("memo", "備註", "s", 200), ("active", "使用中", "b", 70)],
        readonly=("last_cost", "avg_cost"), cost_fields=("std_cost", "last_cost", "avg_cost")),
    "categories": dict(title="商品類別", table="categories", key="code", fields=[
        ("code", "類別代號", "s", 100), ("name", "類別名稱", "s", 200), ("active", "使用中", "b", 70)]),
    "warehouses": dict(title="倉庫", table="warehouses", key="code", fields=[
        ("code", "倉庫代號", "s", 100), ("name", "倉庫名稱", "s", 180), ("address", "地址", "s", 260),
        ("keeper", "保管人", "s", 110), ("is_default", "預設倉", "b", 70), ("active", "使用中", "b", 70)]),
    "customers": dict(title="客戶資料", table="partners", key="code", kind="C", fields=[
        ("code", "客戶代號", "s", 110), ("name", "客戶名稱", "s", 230), ("short_name", "簡稱", "s", 110),
        ("tax_id", "統一編號", "s", 100), ("contact", "聯絡人", "s", 100), ("phone", "電話", "s", 120),
        ("fax", "傳真", "s", 120), ("mobile", "手機", "s", 120), ("email", "電子郵件", "s", 180),
        ("address", "地址", "s", 260), ("ship_address", "送貨地址", "s", 260),
        ("closing_day", "結帳日（0＝月底）", "i", 90), ("pay_days", "收款天數", "i", 80),
        ("price_level", "價格", "sel:1=售價,2=批發價,3=上次成交價", 110), ("credit_limit", "信用額度", "n", 110),
        ("salesman", "業務員", "emp", 120), ("memo", "備註", "s", 200), ("active", "使用中", "b", 70)]),
    "vendors": dict(title="廠商資料", table="partners", key="code", kind="V", fields=[
        ("code", "廠商代號", "s", 110), ("name", "廠商名稱", "s", 230), ("short_name", "簡稱", "s", 110),
        ("tax_id", "統一編號", "s", 100), ("contact", "聯絡人", "s", 100), ("phone", "電話", "s", 120),
        ("fax", "傳真", "s", 120), ("mobile", "手機", "s", 120), ("email", "電子郵件", "s", 180),
        ("address", "地址", "s", 260), ("closing_day", "結帳日（0＝月底）", "i", 90), ("pay_days", "付款天數", "i", 80),
        ("memo", "備註", "s", 200), ("active", "使用中", "b", 70)]),
    "departments": dict(title="部門", table="departments", key="code", fields=[
        ("code", "部門代號", "s", 100), ("name", "部門名稱", "s", 200), ("active", "使用中", "b", 70)]),
    "employees": dict(title="員工／業務員", table="employees", key="code", fields=[
        ("code", "員工編號", "s", 100), ("name", "姓名", "s", 130), ("dept", "部門", "dept", 150),
        ("title", "職稱", "s", 110), ("phone", "電話", "s", 130), ("active", "在職", "b", 70)]),
    "bank_accounts": dict(title="銀行帳戶", table="bank_accounts", key="code", fields=[
        ("code", "帳戶代號", "s", 100), ("name", "帳戶名稱", "s", 180), ("bank_name", "銀行／分行", "s", 180),
        ("account_no", "帳號", "s", 160), ("gl_account", "會計科目", "s", 100), ("active", "使用中", "b", 70)]),
    "phrases": dict(title="備註片語", table="phrases", key="id", fields=[("text", "片語內容", "s", 360)]),
    "reasons": dict(title="異動原因", table="reasons", key="id", fields=[
        ("kind", "用於", "sel:ADJ=庫存調整,SCR=報廢,OUT=領用出庫,IN=其他入庫", 140), ("text", "原因", "s", 260)]),
}
NUMERIC = ("n", "i")


class Base:
    def __init__(self, db):
        self.db = db
        self.user = None
        self.perms = {}

    # ================================================================ 登入、權限、紀錄
    @property
    def uid(self):
        return self.user["uid"] if self.user else ""

    def has_users(self) -> bool:
        return bool(self.db.value("SELECT COUNT(*) FROM users"))

    def login(self, uid, pw):
        u = self.db.row("SELECT * FROM users WHERE uid=%s", ((uid or "").strip(),))
        if not u or not passwords.verify(pw, u["pw_hash"]):
            self.db.exec("INSERT INTO audit_log (uid, action, detail) VALUES (%s, 'login_fail', '')", (uid or "",))
            raise BizError("帳號或密碼錯誤")
        if not u["active"]:
            raise BizError("此帳號已停用，請洽系統管理員")
        self.user = u
        self.perms = {r["func"]: r["lvl"] for r in self.db.rows("SELECT func, lvl FROM user_perms WHERE uid=%s",
                                                                 (u["uid"],))}
        self.db.exec("UPDATE users SET last_login=NOW() WHERE uid=%s", (u["uid"],))
        self.log("login", u["uid"])
        return u

    def logout(self):
        if self.user:
            self.log("logout", self.uid)
        self.user, self.perms = None, {}

    def level(self, func) -> int:
        if not self.user:
            return 0
        if self.user["is_admin"]:
            return 2
        return int(self.perms.get(func, 0))

    def can(self, func, lvl=1) -> bool:
        return self.level(func) >= lvl

    def need(self, func, lvl=2):
        if not self.can(func, lvl):
            raise BizError("您沒有「%s」的%s權限" % (FUNC_NAMES.get(func, func), "維護" if lvl >= 2 else "查詢"))

    @property
    def see_cost(self):
        return self.can("COST", 1)

    def log(self, action, target="", detail=""):
        try:
            self.db.exec("INSERT INTO audit_log (uid, action, target, detail) VALUES (%s, %s, %s, %s)",
                         (self.uid, action, str(target)[:60], str(detail)[:500]))
        except Exception:
            pass

    # ================================================================ 使用者
    def users(self):
        rows = self.db.rows("SELECT uid, name, role, is_admin, active, last_login FROM users ORDER BY uid")
        perms = self.db.rows("SELECT uid, func, lvl FROM user_perms")
        for u in rows:
            u["perms"] = {p["func"]: p["lvl"] for p in perms if p["uid"] == u["uid"]}
        return rows

    def create_first_admin(self, uid, name, pw):
        if self.has_users():
            raise BizError("系統已有使用者")
        self._check_new_password(pw)
        self._insert_user(uid, name, pw, "系統管理員", True)

    def save_user(self, uid, name, role, is_admin, active, perms, pw=None, is_new=False):
        self.need("SYS")
        uid = (uid or "").strip()
        if not uid or not (name or "").strip():
            raise BizError("帳號與姓名必填")
        if is_new:
            if self.db.value("SELECT 1 FROM users WHERE uid=%s", (uid,)):
                raise BizError("帳號 %s 已存在" % uid)
            self._check_new_password(pw)
            self._insert_user(uid, name, pw, role, is_admin, perms)
        else:
            if uid == self.uid and (not is_admin or not active) and self.user["is_admin"]:
                raise BizError("不能取消自己的管理員身分或停用自己")
            if (not is_admin or not active) and not self.db.value(
                    "SELECT COUNT(*) FROM users WHERE is_admin=1 AND active=1 AND uid<>%s", (uid,)):
                raise BizError("至少要保留一位啟用中的系統管理員")
            self.db.exec("UPDATE users SET name=%s, role=%s, is_admin=%s, active=%s WHERE uid=%s",
                         (name.strip(), role, int(bool(is_admin)), int(bool(active)), uid))
            self._write_perms(uid, perms)
            if pw:
                self._check_new_password(pw)
                self.db.exec("UPDATE users SET pw_hash=%s WHERE uid=%s", (passwords.make(pw), uid))
        self.log("user_save", uid, json.dumps({"role": role, "admin": bool(is_admin), "perms": perms},
                                               ensure_ascii=False))

    def _insert_user(self, uid, name, pw, role, is_admin, perms=None):
        uid = (uid or "").strip()
        if not uid:
            raise BizError("請輸入帳號")
        self.db.exec("INSERT INTO users (uid, name, pw_hash, role, is_admin) VALUES (%s, %s, %s, %s, %s)",
                     (uid, (name or uid).strip(), passwords.make(pw), role, int(bool(is_admin))))
        self._write_perms(uid, perms if perms is not None else ROLES.get(role, {}))

    def _write_perms(self, uid, perms):
        self.db.exec("DELETE FROM user_perms WHERE uid=%s", (uid,))
        self.db.exec_many("INSERT INTO user_perms (uid, func, lvl) VALUES (%s, %s, %s)",
                          [(uid, f, int(perms.get(f, 0))) for f, _, _ in FUNCS])

    @staticmethod
    def _check_new_password(pw):
        if len(pw or "") < 6:
            raise BizError("密碼至少 6 個字")

    def change_password(self, old, new):
        if not passwords.verify(old, self.db.value("SELECT pw_hash FROM users WHERE uid=%s", (self.uid,))):
            raise BizError("舊密碼不正確")
        self._check_new_password(new)
        self.db.exec("UPDATE users SET pw_hash=%s WHERE uid=%s", (passwords.make(new), self.uid))
        self.log("password", self.uid)

    def delete_user(self, uid):
        self.need("SYS")
        if uid == self.uid:
            raise BizError("不能刪除自己")
        if self.db.value("SELECT 1 FROM docs WHERE created_by=%s LIMIT 1", (uid,)) or \
                self.db.value("SELECT 1 FROM receipts WHERE created_by=%s LIMIT 1", (uid,)):
            raise BizError("此帳號已有單據紀錄，請改為「停用」以保留稽核軌跡")
        self.db.exec("DELETE FROM user_perms WHERE uid=%s", (uid,))
        self.db.exec("DELETE FROM users WHERE uid=%s", (uid,))
        self.log("user_delete", uid)

    def audit(self, limit=500, uid=""):
        sql = "SELECT * FROM audit_log" + (" WHERE uid=%s" if uid else "") + " ORDER BY id DESC LIMIT %s"
        return self.db.rows(sql, ((uid, limit) if uid else (limit,)))

    # ================================================================ 公司設定
    COMPANY_FIELDS = ("name", "short_name", "tax_id", "owner", "phone", "fax", "email", "address", "tax_rate",
                      "default_tax_type", "inventory_system", "allow_negative", "qty_decimals", "price_decimals",
                      "gl_mode", "doc_footer", "dead_days")

    def company(self):
        return self.db.row("SELECT * FROM company WHERE id=1") or {}

    def save_company(self, **kw):
        self.need("SYS")
        vals = {k: kw[k] for k in self.COMPANY_FIELDS if k in kw}
        if "tax_id" in vals and vals["tax_id"] and (not str(vals["tax_id"]).isdigit() or len(vals["tax_id"]) != 8):
            raise BizError("統一編號應為 8 位數字")
        if "inventory_system" in vals and vals["inventory_system"] not in ("P", "D"):
            raise BizError("存貨制度不正確")
        if vals:
            self.db.exec("UPDATE company SET %s WHERE id=1" % ", ".join("%s=%%s" % k for k in vals),
                         tuple(vals.values()))
        self.log("company", "", json.dumps({k: str(v) for k, v in vals.items()}, ensure_ascii=False))

    # ================================================================ 基本資料
    def master_rows(self, name, active_only=False, search=""):
        m = MASTERS[name]
        where, args = [], []
        if m.get("kind"):
            where.append("kind=%s")
            args.append(m["kind"])
        if active_only and any(f[0] == "active" for f in m["fields"]):
            where.append("active=1")
        if search:
            cols = [f[0] for f in m["fields"] if f[2] == "s"][:4]
            where.append("(" + " OR ".join("%s LIKE %%s" % c for c in cols) + ")")
            args += ["%" + search + "%"] * len(cols)
        sql = "SELECT * FROM %s%s ORDER BY %s" % (m["table"], (" WHERE " + " AND ".join(where)) if where else "",
                                                  m["key"])
        rows = self.db.rows(sql, tuple(args))
        if name == "products" and not self.see_cost:
            for r in rows:
                for k in m["cost_fields"]:
                    r[k] = None
        return rows

    def options(self, name):
        """下拉選單：(代號, 顯示文字)"""
        if name in ("cat", "categories"):
            return [(r["code"], "%s %s" % (r["code"], r["name"])) for r in
                    self.db.rows("SELECT code, name FROM categories WHERE active=1 ORDER BY code")]
        if name in ("wh", "warehouses"):
            return [(r["code"], "%s %s" % (r["code"], r["name"])) for r in
                    self.db.rows("SELECT code, name FROM warehouses WHERE active=1 ORDER BY is_default DESC, code")]
        if name in ("vendor", "vendors", "V"):
            return [(r["code"], "%s %s" % (r["code"], r["short_name"] or r["name"])) for r in
                    self.db.rows("SELECT code, name, short_name FROM partners WHERE kind='V' AND active=1 "
                                 "ORDER BY code")]
        if name in ("customers", "C"):
            return [(r["code"], "%s %s" % (r["code"], r["short_name"] or r["name"])) for r in
                    self.db.rows("SELECT code, name, short_name FROM partners WHERE kind='C' AND active=1 "
                                 "ORDER BY code")]
        if name in ("dept", "departments"):
            return [(r["code"], "%s %s" % (r["code"], r["name"])) for r in
                    self.db.rows("SELECT code, name FROM departments WHERE active=1 ORDER BY code")]
        if name in ("emp", "employees"):
            return [(r["code"], "%s %s" % (r["code"], r["name"])) for r in
                    self.db.rows("SELECT code, name FROM employees WHERE active=1 ORDER BY code")]
        if name in ("bank", "bank_accounts"):
            return [(r["code"], "%s %s" % (r["code"], r["name"])) for r in
                    self.db.rows("SELECT code, name FROM bank_accounts WHERE active=1 ORDER BY code")]
        if name.startswith("reasons:"):
            return [(r["text"], r["text"]) for r in
                    self.db.rows("SELECT text FROM reasons WHERE kind=%s ORDER BY id", (name[8:],))]
        if name == "phrases":
            return [(r["text"], r["text"]) for r in self.db.rows("SELECT text FROM phrases ORDER BY id")]
        return []

    def default_warehouse(self):
        return self.db.value("SELECT code FROM warehouses WHERE active=1 ORDER BY is_default DESC, code LIMIT 1") or ""

    def save_master(self, name, row: dict, is_new: bool):
        self.need("BAS")
        m = MASTERS[name]
        key = m["key"]
        data = {}
        for f, title, typ, _ in m["fields"]:
            if f not in row or f in m.get("readonly", ()):
                continue
            if f in m.get("cost_fields", ()) and not self.see_cost:
                continue
            v = row[f]
            if typ == "n":
                v = dec(v, Decimal("0.0001"))
            elif typ == "i":
                try:
                    v = int(str(v or 0).replace(",", ""))
                except ValueError:
                    raise BizError("「%s」要是整數" % title)
            elif typ == "b":
                v = int(bool(v))
            else:
                v = ("" if v is None else str(v)).strip()
            data[f] = v
        if key != "id":
            if not data.get(key):
                raise BizError("請輸入%s" % m["fields"][0][1])
            if any(ch in data[key] for ch in " ,'\"\\"):
                raise BizError("代號不能有空白、逗號或引號")
        name_field = next((f[0] for f in m["fields"] if f[0] in ("name", "text")), None)
        if name_field and not data.get(name_field, "x" if not is_new else ""):
            raise BizError("請輸入%s" % next(f[1] for f in m["fields"] if f[0] == name_field))
        if name in ("customers", "vendors"):
            data["kind"] = m["kind"]
            cd = data.get("closing_day", 0)
            if cd < 0 or cd > 31:
                raise BizError("結帳日要在 0～31 之間")
            if data.get("tax_id") and (not data["tax_id"].isdigit() or len(data["tax_id"]) != 8):
                raise BizError("統一編號應為 8 位數字")
        if name == "warehouses" and data.get("is_default"):
            self.db.exec("UPDATE warehouses SET is_default=0")
        if is_new:
            if key != "id":
                where = "%s=%%s" % key + (" AND kind=%s" if m.get("kind") else "")
                args = (data[key],) + ((m["kind"],) if m.get("kind") else ())
                if self.db.value("SELECT 1 FROM %s WHERE %s" % (m["table"], where), args):
                    raise BizError("代號 %s 已存在" % data[key])
            cols = list(data)
            self.db.exec("INSERT INTO %s (%s) VALUES (%s)" % (m["table"], ", ".join(cols), ", ".join(["%s"] * len(cols))),
                         tuple(data.values()))
        else:
            kv = row.get(key) if key == "id" else data[key]
            upd = {k: v for k, v in data.items() if k not in (key, "kind")}
            where = "%s=%%s" % key + (" AND kind=%s" if m.get("kind") else "")
            self.db.exec("UPDATE %s SET %s WHERE %s" % (m["table"], ", ".join("%s=%%s" % k for k in upd), where),
                         tuple(upd.values()) + (kv,) + ((m["kind"],) if m.get("kind") else ()))
        self.log("master_" + ("new" if is_new else "edit"), "%s:%s" % (name, data.get(key, row.get(key, ""))))

    def delete_master(self, name, keyval):
        self.need("BAS")
        m = MASTERS[name]
        used = {
            "products": [("doc_lines", "product")],
            "customers": [("docs", "partner")], "vendors": [("docs", "partner")],
            "warehouses": [("docs", "warehouse"), ("docs", "warehouse2")],
            "categories": [("products", "category")], "departments": [("docs", "dept")],
            "employees": [("docs", "employee")], "bank_accounts": [("receipts", "bank_account")],
        }.get(name, [])
        for table, col in used:
            extra = ""
            args = (keyval,)
            if name in ("customers", "vendors"):
                extra = " AND partner_kind=%s"
                args = (keyval, m["kind"])
            if self.db.value("SELECT 1 FROM %s WHERE %s=%%s%s LIMIT 1" % (table, col, extra), args):
                raise BizError("此資料已被使用，不能刪除（可改為停用）")
        where = "%s=%%s" % m["key"] + (" AND kind=%s" if m.get("kind") else "")
        self.db.exec("DELETE FROM %s WHERE %s" % (m["table"], where),
                     (keyval,) + ((m["kind"],) if m.get("kind") else ()))
        self.log("master_delete", "%s:%s" % (name, keyval))

    def partner(self, kind, code):
        return self.db.row("SELECT * FROM partners WHERE kind=%s AND code=%s", (kind, code))

    def product(self, code):
        p = self.db.row("SELECT * FROM products WHERE code=%s", (code,))
        if p is None:
            p = self.db.row("SELECT * FROM products WHERE barcode=%s AND barcode<>'' LIMIT 1", (code,))
        return p

    def find_products(self, text, limit=30):
        s = "%" + (text or "") + "%"
        return self.db.rows("SELECT code, name, spec, unit, price, price2, barcode FROM products WHERE active=1 AND "
                            "(code LIKE %s OR name LIKE %s OR barcode LIKE %s OR spec LIKE %s) ORDER BY code LIMIT %s",
                            (s, s, s, s, limit))
