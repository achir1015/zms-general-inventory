-- 資料助秘之一般公司進銷存：資料表（MariaDB，utf8mb4）
-- 每次開啟程式都會執行（IF NOT EXISTS），新增欄位請寫在 database.py 的 UPGRADES。

CREATE TABLE IF NOT EXISTS meta (
  k VARCHAR(40) PRIMARY KEY,
  v VARCHAR(200) NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS company (
  id TINYINT PRIMARY KEY,
  name VARCHAR(80) NOT NULL DEFAULT '',
  short_name VARCHAR(30) NOT NULL DEFAULT '',
  tax_id VARCHAR(10) NOT NULL DEFAULT '',
  owner VARCHAR(30) NOT NULL DEFAULT '',
  phone VARCHAR(30) NOT NULL DEFAULT '',
  fax VARCHAR(30) NOT NULL DEFAULT '',
  email VARCHAR(80) NOT NULL DEFAULT '',
  address VARCHAR(200) NOT NULL DEFAULT '',
  tax_rate DECIMAL(5,2) NOT NULL DEFAULT 5,
  default_tax_type TINYINT NOT NULL DEFAULT 1,      -- 1 應稅外加、2 應稅內含、3 零稅率、4 免稅
  inventory_system CHAR(1) NOT NULL DEFAULT 'P',    -- P 永續盤存制、D 定期盤存制（影響拋轉分錄）
  allow_negative TINYINT NOT NULL DEFAULT 0,        -- 允許負庫存
  qty_decimals TINYINT NOT NULL DEFAULT 0,
  price_decimals TINYINT NOT NULL DEFAULT 2,
  stock_closed_ym CHAR(6) NOT NULL DEFAULT '',      -- 已完成成本月結（關帳）的最後年月
  gl_mode VARCHAR(4) NOT NULL DEFAULT 'doc',        -- 拋轉：doc 每張單據一張傳票、day 每日彙總
  doc_footer VARCHAR(200) NOT NULL DEFAULT '',
  dead_days INT NOT NULL DEFAULT 180                -- 呆滯品：超過幾天沒有出貨
);

CREATE TABLE IF NOT EXISTS users (
  uid VARCHAR(20) PRIMARY KEY,
  name VARCHAR(30) NOT NULL,
  pw_hash VARCHAR(200) NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT '',
  is_admin TINYINT NOT NULL DEFAULT 0,
  active TINYINT NOT NULL DEFAULT 1,
  last_login DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_perms (
  uid VARCHAR(20) NOT NULL,
  func VARCHAR(8) NOT NULL,
  lvl TINYINT NOT NULL DEFAULT 0,                   -- 0 無、1 查詢、2 維護
  PRIMARY KEY (uid, func)
);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  uid VARCHAR(20) NOT NULL DEFAULT '',
  action VARCHAR(30) NOT NULL,
  target VARCHAR(60) NOT NULL DEFAULT '',
  detail VARCHAR(500) NOT NULL DEFAULT '',
  INDEX idx_at (at)
);

-- ---------------------------------------------------------------- 基本資料
CREATE TABLE IF NOT EXISTS categories (
  code VARCHAR(12) PRIMARY KEY,
  name VARCHAR(40) NOT NULL,
  active TINYINT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS warehouses (
  code VARCHAR(12) PRIMARY KEY,
  name VARCHAR(40) NOT NULL,
  address VARCHAR(200) NOT NULL DEFAULT '',
  keeper VARCHAR(30) NOT NULL DEFAULT '',
  is_default TINYINT NOT NULL DEFAULT 0,
  active TINYINT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS products (
  code VARCHAR(30) PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  spec VARCHAR(80) NOT NULL DEFAULT '',
  category VARCHAR(12) NOT NULL DEFAULT '',
  unit VARCHAR(10) NOT NULL DEFAULT '個',
  barcode VARCHAR(40) NOT NULL DEFAULT '',
  price DECIMAL(14,4) NOT NULL DEFAULT 0,           -- 標準售價（零售）
  price2 DECIMAL(14,4) NOT NULL DEFAULT 0,          -- 批發價
  std_cost DECIMAL(14,4) NOT NULL DEFAULT 0,        -- 標準進價
  last_cost DECIMAL(14,4) NOT NULL DEFAULT 0,       -- 最近進價
  avg_cost DECIMAL(14,4) NOT NULL DEFAULT 0,        -- 平均成本（月結後為月加權平均；月中為移動估計）
  safety_qty DECIMAL(14,3) NOT NULL DEFAULT 0,
  vendor VARCHAR(12) NOT NULL DEFAULT '',           -- 主要供應商
  is_stock TINYINT NOT NULL DEFAULT 1,              -- 0＝勞務／費用類，不計庫存
  memo VARCHAR(200) NOT NULL DEFAULT '',
  active TINYINT NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_barcode (barcode),
  INDEX idx_category (category)
);

CREATE TABLE IF NOT EXISTS partners (
  kind CHAR(1) NOT NULL,                            -- C 客戶、V 廠商
  code VARCHAR(12) NOT NULL,
  name VARCHAR(80) NOT NULL,
  short_name VARCHAR(20) NOT NULL DEFAULT '',
  tax_id VARCHAR(10) NOT NULL DEFAULT '',
  contact VARCHAR(30) NOT NULL DEFAULT '',
  phone VARCHAR(30) NOT NULL DEFAULT '',
  fax VARCHAR(30) NOT NULL DEFAULT '',
  mobile VARCHAR(30) NOT NULL DEFAULT '',
  email VARCHAR(80) NOT NULL DEFAULT '',
  address VARCHAR(200) NOT NULL DEFAULT '',
  ship_address VARCHAR(200) NOT NULL DEFAULT '',
  closing_day TINYINT NOT NULL DEFAULT 0,           -- 每月結帳日（0＝月底）
  pay_days INT NOT NULL DEFAULT 30,                 -- 結帳後幾天收／付款
  price_level TINYINT NOT NULL DEFAULT 1,           -- 1 售價、2 批發價、3 上次成交價
  credit_limit DECIMAL(14,2) NOT NULL DEFAULT 0,
  salesman VARCHAR(12) NOT NULL DEFAULT '',
  memo VARCHAR(200) NOT NULL DEFAULT '',
  active TINYINT NOT NULL DEFAULT 1,
  PRIMARY KEY (kind, code)
);

CREATE TABLE IF NOT EXISTS departments (
  code VARCHAR(12) PRIMARY KEY,
  name VARCHAR(40) NOT NULL,
  active TINYINT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS employees (
  code VARCHAR(12) PRIMARY KEY,
  name VARCHAR(30) NOT NULL,
  dept VARCHAR(12) NOT NULL DEFAULT '',
  title VARCHAR(30) NOT NULL DEFAULT '',
  phone VARCHAR(30) NOT NULL DEFAULT '',
  active TINYINT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bank_accounts (
  code VARCHAR(12) PRIMARY KEY,
  name VARCHAR(40) NOT NULL,
  bank_name VARCHAR(40) NOT NULL DEFAULT '',
  account_no VARCHAR(30) NOT NULL DEFAULT '',
  gl_account VARCHAR(12) NOT NULL DEFAULT '1113',   -- 對應會計科目
  active TINYINT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS phrases (
  id INT AUTO_INCREMENT PRIMARY KEY,
  text VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS reasons (
  id INT AUTO_INCREMENT PRIMARY KEY,
  kind VARCHAR(4) NOT NULL,                         -- ADJ 調整、SCR 報廢、OUT 出庫、IN 入庫
  text VARCHAR(60) NOT NULL
);

-- ---------------------------------------------------------------- 單據
CREATE TABLE IF NOT EXISTS docs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  doc_type VARCHAR(4) NOT NULL,
  doc_no VARCHAR(20) NOT NULL,
  doc_date DATE NOT NULL,
  partner_kind CHAR(1) NOT NULL DEFAULT '',
  partner VARCHAR(12) NOT NULL DEFAULT '',
  warehouse VARCHAR(12) NOT NULL DEFAULT '',
  warehouse2 VARCHAR(12) NOT NULL DEFAULT '',       -- 調撥：撥入倉
  dept VARCHAR(12) NOT NULL DEFAULT '',
  employee VARCHAR(12) NOT NULL DEFAULT '',         -- 業務／經手人
  ref_no VARCHAR(30) NOT NULL DEFAULT '',           -- 客戶訂單號、廠商出貨單號
  invoice_no VARCHAR(20) NOT NULL DEFAULT '',       -- 發票號碼
  tax_type TINYINT NOT NULL DEFAULT 1,
  tax_rate DECIMAL(5,2) NOT NULL DEFAULT 5,
  amount DECIMAL(14,2) NOT NULL DEFAULT 0,          -- 未稅金額
  tax DECIMAL(14,2) NOT NULL DEFAULT 0,
  total DECIMAL(14,2) NOT NULL DEFAULT 0,           -- 含稅合計（應收付金額）
  discount_only TINYINT NOT NULL DEFAULT 0,         -- 退回單：只折讓、不退貨
  gl_account VARCHAR(12) NOT NULL DEFAULT '',       -- 其他入出庫的對方科目（空白＝用科目設定）
  reason VARCHAR(60) NOT NULL DEFAULT '',
  memo VARCHAR(200) NOT NULL DEFAULT '',
  due_date DATE NULL,                               -- 預交日／預計收付款日
  status TINYINT NOT NULL DEFAULT 1,                -- 1 有效、9 作廢
  closed TINYINT NOT NULL DEFAULT 0,                -- 訂單／採購單手動結案、盤點已轉調整
  src_doc_id INT NULL,
  gl_batch_id INT NULL,
  created_by VARCHAR(20) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_by VARCHAR(20) NOT NULL DEFAULT '',
  updated_at DATETIME NULL,
  voided_by VARCHAR(20) NOT NULL DEFAULT '',
  voided_at DATETIME NULL,
  UNIQUE KEY uq_doc_no (doc_no),
  INDEX idx_type_date (doc_type, doc_date),
  INDEX idx_partner (partner_kind, partner),
  INDEX idx_gl (gl_batch_id)
);

CREATE TABLE IF NOT EXISTS doc_lines (
  id INT AUTO_INCREMENT PRIMARY KEY,
  doc_id INT NOT NULL,
  line_no SMALLINT NOT NULL,
  product VARCHAR(30) NOT NULL,
  name VARCHAR(80) NOT NULL DEFAULT '',
  unit VARCHAR(10) NOT NULL DEFAULT '',
  qty DECIMAL(14,3) NOT NULL DEFAULT 0,
  price DECIMAL(14,4) NOT NULL DEFAULT 0,
  amount DECIMAL(14,2) NOT NULL DEFAULT 0,          -- 數量×單價（依單據稅別，可能含稅）
  net DECIMAL(14,2) NOT NULL DEFAULT 0,             -- 未稅金額（分攤後）
  cost DECIMAL(14,2) NOT NULL DEFAULT 0,            -- 成本金額（出庫類；月結後為實際）
  book_qty DECIMAL(14,3) NOT NULL DEFAULT 0,        -- 盤點：帳面數量
  count_qty DECIMAL(14,3) NULL,                     -- 盤點：實盤數量（NULL＝尚未盤）
  src_line_id INT NULL,
  memo VARCHAR(100) NOT NULL DEFAULT '',
  INDEX idx_doc (doc_id),
  INDEX idx_product (product),
  INDEX idx_src (src_line_id)
);

CREATE TABLE IF NOT EXISTS stock_moves (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  doc_id INT NOT NULL,
  line_id INT NOT NULL,
  doc_type VARCHAR(4) NOT NULL,
  move_date DATE NOT NULL,
  product VARCHAR(30) NOT NULL,
  warehouse VARCHAR(12) NOT NULL,
  qty DECIMAL(14,3) NOT NULL,                       -- 入＋、出－
  INDEX idx_pd (product, move_date),
  INDEX idx_doc (doc_id)
);

CREATE TABLE IF NOT EXISTS stock (
  product VARCHAR(30) NOT NULL,
  warehouse VARCHAR(12) NOT NULL,
  qty DECIMAL(14,3) NOT NULL DEFAULT 0,
  PRIMARY KEY (product, warehouse)
);

-- ---------------------------------------------------------------- 成本月結
CREATE TABLE IF NOT EXISTS cost_closes (
  ym CHAR(6) PRIMARY KEY,
  closed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  closed_by VARCHAR(20) NOT NULL DEFAULT '',
  gl_batch_id INT NULL
);

CREATE TABLE IF NOT EXISTS cost_months (
  ym CHAR(6) NOT NULL,
  product VARCHAR(30) NOT NULL,
  open_qty DECIMAL(14,3) NOT NULL DEFAULT 0,
  open_amt DECIMAL(16,2) NOT NULL DEFAULT 0,
  in_qty DECIMAL(14,3) NOT NULL DEFAULT 0,          -- 進貨（扣進退）、期初、其他入庫
  in_amt DECIMAL(16,2) NOT NULL DEFAULT 0,
  sale_qty DECIMAL(14,3) NOT NULL DEFAULT 0,        -- 銷貨（扣銷退）
  sale_amt DECIMAL(16,2) NOT NULL DEFAULT 0,
  other_qty DECIMAL(14,3) NOT NULL DEFAULT 0,       -- 出庫、報廢、調整、盤盈虧（出為正）
  other_amt DECIMAL(16,2) NOT NULL DEFAULT 0,
  close_qty DECIMAL(14,3) NOT NULL DEFAULT 0,
  close_amt DECIMAL(16,2) NOT NULL DEFAULT 0,
  unit_cost DECIMAL(14,4) NOT NULL DEFAULT 0,
  PRIMARY KEY (ym, product)
);

-- ---------------------------------------------------------------- 收付款、票據
CREATE TABLE IF NOT EXISTS receipts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  r_no VARCHAR(20) NOT NULL,
  kind CHAR(1) NOT NULL,                            -- R 收款、P 付款
  r_date DATE NOT NULL,
  partner VARCHAR(12) NOT NULL,
  cash DECIMAL(14,2) NOT NULL DEFAULT 0,
  bank DECIMAL(14,2) NOT NULL DEFAULT 0,
  bank_account VARCHAR(12) NOT NULL DEFAULT '',
  notes_amt DECIMAL(14,2) NOT NULL DEFAULT 0,       -- 收到／開立的票據
  endorsed_amt DECIMAL(14,2) NOT NULL DEFAULT 0,    -- 付款：轉付客戶票據
  fee DECIMAL(14,2) NOT NULL DEFAULT 0,             -- 手續費（匯費）
  discount DECIMAL(14,2) NOT NULL DEFAULT 0,        -- 折讓（尾差）
  use_advance DECIMAL(14,2) NOT NULL DEFAULT 0,     -- 使用預收／預付
  to_advance DECIMAL(14,2) NOT NULL DEFAULT 0,      -- 轉為預收／預付
  applied DECIMAL(14,2) NOT NULL DEFAULT 0,         -- 沖帳合計
  memo VARCHAR(200) NOT NULL DEFAULT '',
  status TINYINT NOT NULL DEFAULT 1,
  gl_batch_id INT NULL,
  created_by VARCHAR(20) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  voided_by VARCHAR(20) NOT NULL DEFAULT '',
  voided_at DATETIME NULL,
  UNIQUE KEY uq_r_no (r_no),
  INDEX idx_partner (kind, partner)
);

CREATE TABLE IF NOT EXISTS receipt_applies (
  receipt_id INT NOT NULL,
  doc_id INT NOT NULL,
  amount DECIMAL(14,2) NOT NULL,
  PRIMARY KEY (receipt_id, doc_id),
  INDEX idx_doc (doc_id)
);

CREATE TABLE IF NOT EXISTS notes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  kind CHAR(1) NOT NULL,                            -- R 應收票據、P 應付票據
  note_no VARCHAR(20) NOT NULL,
  bank VARCHAR(40) NOT NULL DEFAULT '',             -- 付款銀行
  account_no VARCHAR(30) NOT NULL DEFAULT '',
  partner VARCHAR(12) NOT NULL,                     -- 應收：客戶；應付：廠商
  amount DECIMAL(14,2) NOT NULL,
  issue_date DATE NOT NULL,                         -- 收票日／開票日
  due_date DATE NOT NULL,
  status TINYINT NOT NULL DEFAULT 1,
  receipt_id INT NULL,                              -- 來源收款單／付款單
  bank_account VARCHAR(12) NOT NULL DEFAULT '',     -- 託收或付款帳戶
  endorse_receipt_id INT NULL,                      -- 轉付：用在哪張付款單
  memo VARCHAR(100) NOT NULL DEFAULT '',
  INDEX idx_kind_status (kind, status),
  INDEX idx_due (due_date)
);

CREATE TABLE IF NOT EXISTS note_events (
  id INT AUTO_INCREMENT PRIMARY KEY,
  note_id INT NOT NULL,
  event VARCHAR(10) NOT NULL,
  ev_date DATE NOT NULL,
  prev_status TINYINT NOT NULL,
  new_status TINYINT NOT NULL,
  bank_account VARCHAR(12) NOT NULL DEFAULT '',
  memo VARCHAR(100) NOT NULL DEFAULT '',
  gl_batch_id INT NULL,
  created_by VARCHAR(20) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_note (note_id)
);

-- ---------------------------------------------------------------- 會計拋轉
CREATE TABLE IF NOT EXISTS gl_map (
  k VARCHAR(16) PRIMARY KEY,
  account VARCHAR(12) NOT NULL,
  name VARCHAR(40) NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS gl_batches (
  id INT AUTO_INCREMENT PRIMARY KEY,
  batch_no VARCHAR(20) NOT NULL,
  batch_uid VARCHAR(64) NOT NULL,                   -- 全域唯一代碼（會計系統用來防止重複匯入）
  date_from DATE NOT NULL,
  date_to DATE NOT NULL,
  scope VARCHAR(60) NOT NULL DEFAULT '',
  method VARCHAR(8) NOT NULL DEFAULT 'file',        -- file 拋轉檔、api 直接傳送
  status TINYINT NOT NULL DEFAULT 1,                -- 1 已產生、2 已送達會計、9 已取消
  voucher_count INT NOT NULL DEFAULT 0,
  total DECIMAL(16,2) NOT NULL DEFAULT 0,
  payload LONGTEXT NULL,
  result VARCHAR(500) NOT NULL DEFAULT '',
  created_by VARCHAR(20) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_batch_no (batch_no)
);
