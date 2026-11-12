"""基本資料 CSV 匯入／範本（Excel 另存 CSV 即可；Big5 與 UTF-8 都能讀）。"""
import csv

from .core import MASTERS, BizError

SAMPLES = {
    "products": [dict(code="P001", name="不鏽鋼保溫杯 500ml", spec="銀色", category="01", unit="個", barcode="4710000000017",
                      price="450", price2="380", std_cost="250", safety_qty="20", vendor="V001", is_stock="是",
                      active="是")],
    "customers": [dict(code="C001", name="大華商行有限公司", short_name="大華", tax_id="12345675", contact="王小明",
                       phone="02-2345-6789", address="臺北市中正區重慶南路一段 1 號", closing_day="25", pay_days="30",
                       price_level="1", active="是")],
    "vendors": [dict(code="V001", name="永興實業股份有限公司", short_name="永興", tax_id="", contact="林經理",
                     phone="04-2222-3333", closing_day="0", pay_days="30", active="是")],
}


def master_template(name, path):
    m = MASTERS[name]
    fields = [f for f in m["fields"] if f[0] not in m.get("readonly", ())]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([t for _, t, _, _ in fields])
        for s in SAMPLES.get(name, []):
            w.writerow([s.get(k, "") for k, _, _, _ in fields])


def _read(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp950", "big5hkscs"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise BizError("檔案編碼無法辨識，請用 Excel「另存新檔 → CSV UTF-8」")


def import_masters(biz, name, path):
    """依標題列對應欄位；代號已存在就更新、不存在就新增。回傳 (成功筆數, 錯誤清單)。"""
    m = MASTERS[name]
    rows = list(csv.reader(_read(path).splitlines()))
    if len(rows) < 2:
        raise BizError("檔案沒有資料（第一列要是標題）")
    titles = {t: k for k, t, _, _ in m["fields"]}
    titles.update({k: k for k, _, _, _ in m["fields"]})
    cols = [titles.get(h.strip()) for h in rows[0]]
    if m["key"] != "id" and m["key"] not in cols:
        raise BizError("找不到「%s」欄，請用範本的標題列" % m["fields"][0][1])
    types = {k: t for k, _, t, _ in m["fields"]}
    ok, errs = 0, []
    existing = {str(r[m["key"]]) for r in biz.master_rows(name)} if m["key"] != "id" else set()
    for i, r in enumerate(rows[1:], 2):
        if not any(x.strip() for x in r):
            continue
        row = {}
        for k, v in zip(cols, r):
            if not k:
                continue
            v = v.strip()
            if types.get(k) == "b":
                v = v not in ("否", "0", "N", "n", "no", "False", "false", "")
            elif types.get(k, "").startswith("sel:") and v:
                opts = dict(x.split("=") for x in types[k][4:].split(","))
                v = next((a for a, b in opts.items() if v in (a, b)), v)
            row[k] = v
        for k, _, t, _ in m["fields"]:
            if t == "b" and k not in row:
                row[k] = True
        try:
            biz.save_master(name, row, str(row.get(m["key"], "")) not in existing)
            existing.add(str(row.get(m["key"], "")))
            ok += 1
        except BizError as e:
            errs.append("第 %d 列：%s" % (i, e))
    return ok, errs
