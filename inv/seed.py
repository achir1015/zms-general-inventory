"""第一次使用的預設資料：權限功能與角色、會計科目對照、調整／報廢原因、倉庫與類別。

會計科目代號與「資料助秘之一般公司會計」預設科目表一致（四碼制）；
1219、5115～5117 是進銷存專用科目，會計系統匯入拋轉檔時若還沒有，會自動建立。
"""

# 權限功能：(代號, 名稱, 說明)
FUNCS = [
    ("BAS", "基本資料", "商品、類別、倉庫、客戶、廠商、部門、員工、銀行帳戶、片語與原因"),
    ("SAL", "銷售作業", "報價單、客戶訂單、銷貨單、銷貨退回／折讓"),
    ("PUR", "採購作業", "採購單、進貨單、進貨退出／折讓"),
    ("STK", "庫存作業", "調撥、其他入庫、領用出庫、報廢、庫存數量修正、盤點、期初庫存"),
    ("AR", "應收收款", "應收帳款、收款沖帳、預收、期初應收、客戶對帳單"),
    ("AP", "應付付款", "應付帳款、付款沖帳、預付、期初應付、廠商對帳單"),
    ("NOTE", "票據管理", "應收票據託收、兌現、退票；應付票據兌現、作廢"),
    ("CLS", "月結關帳", "成本月結（月加權平均）、庫存關帳、呆料跌價提列"),
    ("GL", "會計拋轉", "會計科目對照、產生傳票、拋轉到會計系統、取消拋轉"),
    ("RPT", "報表查詢", "進銷存各項明細、統計、排行、帳齡與庫存報表"),
    ("COST", "成本毛利", "可看到成本、平均成本、毛利（1＝可看）"),
    ("SYS", "系統管理", "使用者與權限、公司設定、備份還原、資料庫設定、版本更新、操作紀錄"),
]
FUNC_NAMES = {f[0]: f[1] for f in FUNCS}


def _r(**kw):
    return {f[0]: kw.get(f[0], 0) for f in FUNCS}


# 角色範本：功能 → 等級（0 無、1 查詢、2 維護）
ROLES = {
    "系統管理員": {f[0]: 2 for f in FUNCS},
    "主管": _r(BAS=2, SAL=2, PUR=2, STK=2, AR=2, AP=2, NOTE=2, CLS=2, GL=2, RPT=2, COST=1),
    "業務人員": _r(BAS=1, SAL=2, STK=1, AR=1, RPT=1),
    "採購人員": _r(BAS=1, PUR=2, STK=1, AP=1, RPT=1, COST=1),
    "倉管人員": _r(BAS=1, SAL=1, PUR=1, STK=2, RPT=1),
    "會計出納": _r(BAS=1, SAL=1, PUR=1, STK=1, AR=2, AP=2, NOTE=2, CLS=2, GL=2, RPT=2, COST=1),
    "查詢人員": _r(BAS=1, SAL=1, PUR=1, STK=1, AR=1, AP=1, NOTE=1, RPT=1),
}

# 會計科目對照：(代號, 預設科目, 科目名稱, 說明)
GL_MAP = [
    ("CASH", "1111", "庫存現金", "收付現金"),
    ("AR", "1141", "應收帳款", "銷貨立帳、收款沖帳（往來：客戶）"),
    ("AR_NOTE", "1131", "應收票據", "收到客戶支票（往來：客戶）"),
    ("ADVANCE", "2181", "預收貨款", "客戶多付或訂金（往來：客戶）"),
    ("AP", "2131", "應付帳款", "進貨立帳、付款沖帳（往來：廠商）"),
    ("AP_NOTE", "2121", "應付票據", "開給廠商的支票（往來：廠商）"),
    ("PREPAY", "1252", "預付貨款", "預先付給廠商（往來：廠商）"),
    ("INV", "1211", "商品存貨", "永續盤存制：進貨、出貨成本、盤盈虧"),
    ("INV_ALLOW", "1219", "備抵存貨跌價損失", "呆料跌價提列（資產減項）"),
    ("IN_TAX", "1161", "進項稅額", "進貨營業稅"),
    ("OUT_TAX", "2161", "銷項稅額", "銷貨營業稅"),
    ("SALES", "4111", "銷貨收入", "銷貨未稅金額"),
    ("SALES_RET", "4112", "銷貨退回", "銷退未稅金額"),
    ("SALES_ALLOW", "4113", "銷貨折讓", "銷貨折讓、收款折讓"),
    ("COGS", "5111", "銷貨成本", "出貨成本（月結後產生）"),
    ("PURCHASE", "5112", "進貨", "定期盤存制：進貨"),
    ("PUR_RET", "5113", "進貨退出", "定期盤存制：進貨退出"),
    ("PUR_ALLOW", "5114", "進貨折讓", "進貨折讓、付款折讓"),
    ("COUNT_DIFF", "5115", "存貨盤盈虧", "盤點差異、庫存數量修正"),
    ("SCRAP", "5116", "存貨報廢損失", "報廢單"),
    ("WRITE_DOWN", "5117", "存貨跌價及呆滯損失", "呆料跌價提列（回升為減項）"),
    ("USE_OUT", "6299", "其他費用", "領用出庫（單據可另指定科目）"),
    ("OTHER_IN", "7191", "其他收入", "其他入庫（贈品、樣品入庫；單據可另指定）"),
    ("BANK_FEE", "6233", "銀行手續費", "收付款手續費、匯費"),
]
GL_DEFAULT = {k: (a, n) for k, a, n, _ in GL_MAP}

REASONS = [
    ("ADJ", "盤點差異"), ("ADJ", "帳務更正"), ("ADJ", "包裝拆併"),
    ("SCR", "過期"), ("SCR", "損壞"), ("SCR", "品質不良"), ("SCR", "呆滯報廢"),
    ("OUT", "內部領用"), ("OUT", "樣品贈送"), ("OUT", "維修耗用"),
    ("IN", "贈品入庫"), ("IN", "樣品入庫"), ("IN", "借出歸還"),
]

PHRASES = ["請於收貨後七日內對帳", "貨到付款", "月結 30 天", "請開立發票", "急件，請優先處理"]


def seed_all(db):
    db.exec("INSERT IGNORE INTO company (id, name) VALUES (1, '')")
    db.exec_many("INSERT IGNORE INTO gl_map (k, account, name) VALUES (%s, %s, %s)",
                 [(k, a, n) for k, a, n, _ in GL_MAP])
    if not db.value("SELECT COUNT(*) FROM reasons"):
        db.exec_many("INSERT INTO reasons (kind, text) VALUES (%s, %s)", REASONS)
    if not db.value("SELECT COUNT(*) FROM phrases"):
        db.exec_many("INSERT INTO phrases (text) VALUES (%s)", [(p,) for p in PHRASES])
    db.exec("INSERT IGNORE INTO warehouses (code, name, is_default) VALUES ('A', '總倉', 1)")
    db.exec_many("INSERT IGNORE INTO categories (code, name) VALUES (%s, %s)",
                 [("01", "商品"), ("02", "原物料"), ("09", "勞務／費用")])
    db.exec("INSERT IGNORE INTO bank_accounts (code, name, gl_account) VALUES ('B01', '主要往來銀行', '1113')")
