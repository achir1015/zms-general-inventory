"""單據種類定義：所有單據共用 docs／doc_lines 兩個資料表，差別在這裡的設定。

stock：庫存影響　+1 入庫、-1 出庫、0 不影響、"T" 調撥（倉庫→撥入倉）、"A" 數量可正可負（調整）、
       "C" 盤點（本身不動庫存，轉成調整單才動）
price：明細要輸入單價（銷售／採購類＝售價／進價；入庫類＝單位成本）
tax：計算營業稅；ar：應收付影響（+1 增加應收或應付、-1 減少）
src：可以「帶單」的來源單據；func：權限功能
"""

D = dict

DOC_TYPES = {
    "QT": D(name="報價單", short="報價", pk="C", stock=0, price=True, tax=True, ar=0, src=[], func="SAL",
            icon="REQUEST_QUOTE", tone="sky"),
    "SO": D(name="客戶訂單", short="訂單", pk="C", stock=0, price=True, tax=True, ar=0, src=["QT"], func="SAL",
            icon="ASSIGNMENT", tone="blue", track=True),
    "SI": D(name="銷貨單", short="銷貨", pk="C", stock=-1, price=True, tax=True, ar=1, src=["SO"], func="SAL",
            icon="LOCAL_SHIPPING", tone="teal"),
    "SR": D(name="銷貨退回／折讓", short="銷退", pk="C", stock=1, price=True, tax=True, ar=-1, src=["SI"],
            func="SAL", icon="ASSIGNMENT_RETURN", tone="rose", allow_discount=True),
    "PO": D(name="採購單", short="採購", pk="V", stock=0, price=True, tax=True, ar=0, src=[], func="PUR",
            icon="SHOPPING_CART", tone="amber", track=True),
    "PI": D(name="進貨單", short="進貨", pk="V", stock=1, price=True, tax=True, ar=1, src=["PO"], func="PUR",
            icon="INVENTORY", tone="green"),
    "PR": D(name="進貨退出／折讓", short="進退", pk="V", stock=-1, price=True, tax=True, ar=-1, src=["PI"],
            func="PUR", icon="KEYBOARD_RETURN", tone="orange", allow_discount=True),
    "TR": D(name="調撥單", short="調撥", pk="", stock="T", price=False, tax=False, ar=0, src=[], func="STK",
            icon="SWAP_HORIZ", tone="violet"),
    "IN": D(name="其他入庫單", short="入庫", pk="", stock=1, price=True, tax=False, ar=0, src=[], func="STK",
            icon="MOVE_TO_INBOX", tone="green", price_label="單位成本", reasons="IN"),
    "OUT": D(name="領用出庫單", short="領用", pk="", stock=-1, price=False, tax=False, ar=0, src=[], func="STK",
             icon="OUTBOX", tone="orange", reasons="OUT"),
    "SCR": D(name="報廢單", short="報廢", pk="", stock=-1, price=False, tax=False, ar=0, src=[], func="STK",
             icon="DELETE_SWEEP", tone="rose", reasons="SCR"),
    "ADJ": D(name="庫存數量修正單", short="調整", pk="", stock="A", price=False, tax=False, ar=0, src=[],
             func="STK", icon="TUNE", tone="slate", reasons="ADJ"),
    "CNT": D(name="盤點單", short="盤點", pk="", stock="C", price=False, tax=False, ar=0, src=[], func="STK",
             icon="FACT_CHECK", tone="teal"),
    "OPEN": D(name="期初庫存", short="期初", pk="", stock=1, price=True, tax=False, ar=0, src=[], func="STK",
              icon="FLAG", tone="violet", price_label="單位成本"),
    "WD": D(name="呆料跌價提列", short="跌價", pk="", stock=0, price=False, tax=False, ar=0, src=[], func="CLS",
            icon="TRENDING_DOWN", tone="pink", amount_only=True),
    "ARO": D(name="期初應收", short="期初應收", pk="C", stock=0, price=False, tax=False, ar=1, src=[], func="AR",
             icon="FLAG", tone="sky", header_only=True),
    "APO": D(name="期初應付", short="期初應付", pk="V", stock=0, price=False, tax=False, ar=1, src=[], func="AP",
             icon="FLAG", tone="amber", header_only=True),
    # 由票據作業自動產生（退票、撤票 → 重新應收；應付票據作廢 → 重新應付），不另外拋轉（分錄在票據異動）
    "NTR": D(name="退票轉應收", short="退票應收", pk="C", stock=0, price=False, tax=False, ar=1, src=[],
             func="NOTE", icon="FLAG", tone="rose", header_only=True, auto=True),
    "NTP": D(name="票據作廢轉應付", short="作廢應付", pk="V", stock=0, price=False, tax=False, ar=1, src=[],
             func="NOTE", icon="FLAG", tone="orange", header_only=True, auto=True),
}
NO_GL = {"ARO", "APO", "NTR", "NTP", "QT", "SO", "PO", "CNT", "TR"}

TAX_TYPES = {1: "應稅外加", 2: "應稅內含", 3: "零稅率", 4: "免稅"}
PK_NAMES = {"C": "客戶", "V": "廠商"}

# 出庫成本以平均成本計算的單據
COST_OUT = {"SI", "OUT", "SCR"}
# 入庫且帶入成本（加權平均的分子）
COST_IN = {"PI", "OPEN", "IN"}


def T(code):
    return DOC_TYPES[code]


def ar_kind(code):
    """應收（C）或應付（V）單據；不影響帳款回傳空字串。"""
    t = DOC_TYPES[code]
    return t["pk"] if t["ar"] else ""
