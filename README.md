# 資料助秘之一般公司進銷存
<img width="1919" height="1079" alt="image" src="https://github.com/user-attachments/assets/42359c96-1489-42fb-b283-674b193cdcb5" />

示範






這是單一公司用的進貨、銷貨、庫存、帳款與票據管理系統。它可以和[資料助秘之一般公司會計](https://github.com/achir1015/zms-accounting)搭配：進銷存的交易會轉成會計傳票，直接送到會計系統。

- 介面用 Python＋Flet，資料庫用 MariaDB。
- Windows 版內建資料庫，打開程式就自動啟動，關掉程式就自動停止。
- 平台：Windows 11、macOS 版已完成；Android、iPhone、iPad 版規劃中。
- 開發者：吳玉柱 先生 與 Claude AI Opus 5.5

## 功能

| 類別 | 功能 |
|---|---|
| 銷售 | 報價單 → 客戶訂單 → 銷貨單（可分批出貨）→ 銷貨退回或只給折讓；追蹤未出貨訂單 |
| 採購 | 採購單 → 進貨單 → 進貨退出或只拿折讓；追蹤未進貨採購；依安全存量提出採購建議 |
| 庫存 | 多倉庫即時庫存、商品異動明細（庫存卡）、調撥、領用出庫、其他入庫、報廢、庫存數量修正、期初庫存 |
| 盤點 | 建立盤點單並帶出帳面量 → 列印盤點表 → 輸入實盤量 → 盤差自動轉成調整單 |
| 成本 | 每月依月加權平均計算成本，同時關帳；銷貨、報廢、盤差都以實際成本計算 |
| 呆料 | 列出多久沒出貨的呆滯品，可提列跌價損失（也可迴轉），或直接轉成報廢單 |
| 帳款 | 應收、應付餘額，帳齡分析，未沖明細，對帳單（可列印）；期初應收與期初應付 |
| 收付款 | 現金、匯款、支票、手續費、折讓、預收預付；可自動沖帳；付款時可轉付客戶開的支票 |
| 票據 | 應收票據：託收、兌現、退票、撤票（退票或撤票後會重新列為應收）<br>應付票據：兌現、作廢退回（作廢後會重新列為應付）<br>每一步都可以還原 |
| 會計拋轉 | 依科目對照把交易轉成傳票。可以匯出 .zmsgl 拋轉檔，也可以直接傳送到會計系統。已拋轉的單據會鎖住，取消拋轉後才能修改 |
| 報表 | 銷貨明細與毛利、進貨明細、排行分析、月份統計、進銷存彙總表、成本月結表；都可以匯出 Excel 或列印 |
| 權限 | 共 12 個功能，每個可設「無」、「查詢」或「維護」，並提供 7 種角色範本。「成本毛利」是獨立權限，可以讓業務人員看不到成本 |
| 其他 | 使用說明有前言（導入程序）和每個畫面的語音朗讀。另有：備份與還原、操作紀錄、版本自動更新、桌面捷徑、Excel 匯入基本資料 |

## 和會計系統的拋轉

| 交易 | 分錄（永續盤存制） |
|---|---|
| 銷貨／銷退 | 借 應收帳款／貸 銷貨收入、銷項稅額（銷退相反；只折讓時記銷貨折讓） |
| 進貨／進退 | 借 存貨、進項稅額／貸 應付帳款（不計庫存的品項記其他費用） |
| 收款 | 借 現金、銀行存款、應收票據、手續費、銷貨折讓、預收貨款／貸 應收帳款、預收貨款 |
| 付款 | 借 應付帳款、預付貨款、手續費／貸 現金、銀行存款、應付票據、應收票據（轉付）、進貨折讓 |
| 票據異動 | 兌現：借 銀行存款／貸 應收票據<br>退票、撤票：借 應收帳款／貸 應收票據<br>應付兌現：借 應付票據／貸 銀行存款<br>應付作廢：借 應付票據／貸 應付帳款 |
| 庫存月結 | 每月一張。借 銷貨成本、存貨報廢損失、領用費用，借或貸 存貨盤盈虧／貸 存貨（其他入庫相反） |
| 呆料提列 | 借 存貨跌價及呆滯損失／貸 備抵存貨跌價損失 |

- 如果選定期盤存制：進貨記「進貨」，進退和折讓記「進貨退出」、「進貨折讓」。月結時再用「期初＋進貨－期末」把這些結轉成銷貨成本。
- 會計系統需要 v1.4.0 以上，在「傳票作業 → 進銷存拋轉」匯入或接收。
- 會計系統匯入後產生「未審核」傳票。同一個批次不會被重複匯入。
- 會計系統缺少的科目（1219、5115～5117）、客戶、廠商、部門，匯入時會自動建立。
- 期初庫存、期初應收、期初應付，以及勾選「期初票據登錄」的收付款都不會拋轉，請在會計系統用開帳傳票輸入。
- 使用說明的前言以範例公司「祥和貿易」說明從人工作業到上線、日常作業、月結與拋轉會計的完整程序（含 1 月份 14 張傳票與兩系統核對表），範例數字由 `inv/example.py` 實際跑出並由 `tests/test_adoption.py` 驗證。

## 安裝（Windows 11）

1. 到 [Releases](https://github.com/achir1015/zms-general-inventory/releases) 下載 `ZMSGeneralInventory-Setup-<版本>.exe` 並執行。
2. 安裝完成後，桌面會出現「資料助秘之一般公司進銷存」的捷徑。
3. 第一次開啟時，先建立系統管理員帳號。

- 資料存放在 `%LOCALAPPDATA%\ZMSGeneralInventory`，程式更新或解除安裝都不會刪除。
- 程式開啟時會自動檢查新版本，按一下就能更新。

## 安裝（macOS）

1. 到 [Releases](https://github.com/achir1015/zms-general-inventory/releases) 下載 `ZMSGeneralInventory-<版本>-mac.dmg`。
2. 開啟 DMG，把「資料助秘之一般公司進銷存」拖到「應用程式」資料夾。

- App 已用 Apple Developer ID 簽章，並通過 Apple 公證，可以直接開啟。
- 內附 MariaDB 10.11.18，開啟 App 時自動啟動，結束 App（含 ⌘Q）時自動停止。Apple 晶片的 Mac 會透過 Rosetta 2 執行。
- 資料存在 `~/Library/Application Support/ZMSGeneralInventory`。
- 程式內的「版本更新」會下載新版、自動取代舊的 App，再重新開啟。

## 開發

```bash
python -m venv .venv
.venv\Scripts\pip install flet==1.1.2 flet-audio==1.1.2 flet-desktop==1.1.2 flet-web==1.1.2 flet-cli==1.1.2 pymysql edge-tts qrcode pillow pytest pyinstaller==6.22.3 playwright
.venv\Scripts\python main.py                 # 桌面版（開發資料在 data\）
.venv\Scripts\python run_web.py              # 網頁預覽 http://127.0.0.1:8570（自動用 admin 登入）
.venv\Scripts\python tools\demo_data.py      # 建立示範資料（祥和貿易；會清空開發資料庫）
.venv\Scripts\python -m pytest -q tests      # 測試（含與會計系統的拋轉整合測試）
.venv\Scripts\python tools\build_windows.py  # 建置安裝檔 → dist-installer\
bash tools/mac_in_terminal.sh                # （在 Mac 上）建置簽章公證 DMG → dist-mac/，結果在 build-mac.log
```

- 內建 MariaDB 預設連接埠：正式版 3358、測試 3368（被佔用時會自動往上找）。
- 程式結構：
  - `inv/biz.py` 組合各服務模組：`core`（權限、基本資料）、`docs`（單據與庫存）、`costing`（月結、呆料）、`finance`（帳款、票據）、`gl`（拋轉）、`reports`。
  - `inv/ui/` 是各個畫面。
- 版本號在 `inv/__init__.py` 的 `APP_VERSION`。更新時，在 GitHub Release 附上同名安裝檔即可。
