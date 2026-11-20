-- 室內軟裝資料庫 schema (SQLite)
-- ================================
-- 建立：sqlite3 softgoods.db < schema.sql
--
-- 為什麼是 SQLite 不是 CSV：
--   抓一個站 → CSV 夠用。抓 30 個站就不夠了，因為你會需要
--     1. 去重（同一張沙發在 5 個站有 5 個名字）
--     2. 價格歷史（今天 vs 上週，CSV 做不到）
--     3. 查詢（「預算 3 萬內、台灣有現貨的吊燈」）
--   SQLite 是單一個檔案，不用裝伺服器，複製就是備份。
--
-- 三層資料，不要混在一起：
--   raw（原始 HTML/JSON，檔案系統）
--     → normalized（這個 schema）
--       → published（給人看的 CSV / 網頁）

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;


-- ===========================================================
-- 1. 來源站台：你去哪裡抓的
-- ===========================================================
CREATE TABLE IF NOT EXISTS site (
  site_id         TEXT PRIMARY KEY,          -- 'luxurylife'
  name            TEXT NOT NULL,             -- '潤舍 Luxury Life'
  home_url        TEXT NOT NULL,
  country         TEXT DEFAULT 'TW',
  kind            TEXT,                      -- brand_official|dealer|marketplace|aggregator
  platform        TEXT,                      -- shopify|shopline|cyberbiz|woocommerce|custom
  -- 找到資料來源的捷徑，寫下來以後不用再找一次
  data_endpoint   TEXT,                      -- '/products.json?limit=250&page={n}'
  sitemap_url     TEXT,
  -- 禮貌設定：每個站自己一組
  robots_allowed  INTEGER,                   -- 1=robots.txt 放行
  crawl_delay_sec REAL NOT NULL DEFAULT 1.5,
  blocks_bots     INTEGER DEFAULT 0,         -- check_site.py 判定紅燈就設 1
  needs_browser   INTEGER DEFAULT 0,         -- 1=要 Playwright 才抓得到
  last_crawled_at TEXT,
  notes           TEXT
);


-- ===========================================================
-- 2. 品牌：aliases 是重點，同一個品牌會有五種寫法
-- ===========================================================
CREATE TABLE IF NOT EXISTS brand (
  brand_id  TEXT PRIMARY KEY,                -- 'flos'
  name      TEXT NOT NULL,                   -- 'Flos'
  country   TEXT,
  website   TEXT,
  tier      TEXT,                            -- luxury|mid|mass
  aliases   TEXT                             -- JSON: ["FLOS","Flos Italia","弗洛斯"]
);


-- ===========================================================
-- 3. 商品：正規化後的「同一個東西」
--    不管在幾個站看到，同一款燈只有一列
-- ===========================================================
CREATE TABLE IF NOT EXISTS product (
  product_id    TEXT PRIMARY KEY,            -- 'flos__bellhop'
  brand_id      TEXT REFERENCES brand(brand_id),
  model         TEXT NOT NULL,               -- 'Bellhop'
  series        TEXT,
  -- 分類，對應 taxonomy.yaml
  cat1          TEXT NOT NULL,               -- 'lighting'
  cat2          TEXT,                        -- 'table'
  cat3          TEXT,                        -- '無線桌燈'
  designer      TEXT,
  design_year   INTEGER,
  origin_country TEXT,
  description   TEXT,
  -- 類別專屬欄位放這裡。燈具的電壓/色溫、窗簾的遮光率、沙發的座高
  -- 全部塞同一張表會變成 200 個欄位、其中 190 個是空的，所以用 JSON。
  -- SQLite 有 JSON 函數，一樣查得動：
  --   SELECT * FROM product WHERE json_extract(attrs,'$.voltage') LIKE '%110%';
  attrs         TEXT DEFAULT '{}',
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_product_cat   ON product(cat1, cat2);
CREATE INDEX IF NOT EXISTS ix_product_brand ON product(brand_id, model);


-- ===========================================================
-- 4. 規格：同一款商品的不同尺寸 / 顏色 / 材質
--    尺寸一律存 mm，顏色一律歸到色系。原始文字另外留。
-- ===========================================================
CREATE TABLE IF NOT EXISTS variant (
  variant_id   TEXT PRIMARY KEY,
  product_id   TEXT NOT NULL REFERENCES product(product_id) ON DELETE CASCADE,
  name         TEXT,                         -- 'Ø12.5 x H21 cm / 紅銅'
  color        TEXT,                         -- '紅銅'
  color_family TEXT,                         -- 'metallic'（給篩選用）
  material_main TEXT,
  finish       TEXT,
  -- 尺寸全部 mm 整數。來源會給 "Ø12.5 x 高 21 cm"、"W180×D90"、"5x8 ft"，
  -- 進資料庫前一定要換算，不然永遠沒辦法排序或比較。
  width_mm     INTEGER,
  depth_mm     INTEGER,
  height_mm    INTEGER,
  diameter_mm  INTEGER,
  weight_g     INTEGER,
  size_raw     TEXT,                         -- 原始尺寸字串，換算錯了要能回溯
  -- 幾盞／幾件一組。單品是 1。
  -- 這是正式欄位不是塞在 attrs，因為它要進 UNIQUE：
  -- Lee Broom Mini Crescent 的單盞和五盞組，規格字串一模一樣
  -- （都是「吊燈 · Ø20 x H22 cm」），但 31,100 和 167,000 不是同一個東西。
  pack         INTEGER NOT NULL DEFAULT 1,
  attrs        TEXT DEFAULT '{}',
  -- 尺寸也在身分裡：同一個品名下，規格名一樣（「白色」）但尺寸不同的是不同東西
  -- （潤舍的 Nebra 立燈和 Nebra 桌燈）。2026-11-20 前建的資料庫是舊的限制，要重建
  UNIQUE(product_id, name, pack, width_mm, depth_mm, height_mm, diameter_mm)
);
CREATE INDEX IF NOT EXISTS ix_variant_product ON variant(product_id);


-- ===========================================================
-- 5. 通路上架：一個規格在一個站的一筆販售
--    這是爬蟲真正寫入的地方
-- ===========================================================
CREATE TABLE IF NOT EXISTS listing (
  listing_id     TEXT PRIMARY KEY,
  variant_id     TEXT REFERENCES variant(variant_id) ON DELETE SET NULL,
  site_id        TEXT NOT NULL REFERENCES site(site_id),
  url            TEXT NOT NULL,
  -- 原始標題一定要留。你的正規化邏輯以後會改，改了要能重跑。
  title_raw      TEXT NOT NULL,
  sku            TEXT,
  price          INTEGER,                    -- 存整數（元），不要用 float 算錢
  currency       TEXT NOT NULL DEFAULT 'TWD',
  price_original INTEGER,                    -- 原價，用來判斷有沒有打折
  in_stock       INTEGER,
  stock_text     TEXT,                       -- '預購 6-8 個月'（原文）
  lead_time_days INTEGER,                    -- 從上面那句解析出來的天數
  is_official    INTEGER DEFAULT 0,          -- 是否品牌正式授權通路
  first_seen_at  TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
  gone_at        TEXT,                       -- 下架日（不要刪資料，標記就好）
  UNIQUE(site_id, url)
);
CREATE INDEX IF NOT EXISTS ix_listing_variant ON listing(variant_id);
CREATE INDEX IF NOT EXISTS ix_listing_site    ON listing(site_id, last_seen_at);


-- ===========================================================
-- 6. 價格歷史：一天一列，價格沒變就不要寫
-- ===========================================================
CREATE TABLE IF NOT EXISTS price_point (
  listing_id TEXT NOT NULL REFERENCES listing(listing_id) ON DELETE CASCADE,
  seen_date  TEXT NOT NULL,                  -- 'YYYY-MM-DD'
  price      INTEGER,
  in_stock   INTEGER,
  PRIMARY KEY (listing_id, seen_date)
);


-- ===========================================================
-- 7. 圖片：不要一開始就下載。先存網址 + 雜湊。
--    perceptual hash 之後可以用來比對「兩個站是不是同一個商品」
-- ===========================================================
CREATE TABLE IF NOT EXISTS image (
  image_id    TEXT PRIMARY KEY,
  product_id  TEXT REFERENCES product(product_id) ON DELETE CASCADE,
  variant_id  TEXT REFERENCES variant(variant_id) ON DELETE CASCADE,
  src_url     TEXT NOT NULL,
  local_path  TEXT,                          -- 真的下載了才填
  position    INTEGER DEFAULT 0,
  width       INTEGER,
  height      INTEGER,
  phash       TEXT,                          -- 比對同商品用
  credit      TEXT,                          -- 圖片來源，一定要記
  license     TEXT,                          -- 能不能公開用
  UNIQUE(src_url)
);


-- ===========================================================
-- 8. 商品比對：最難的一步，不要全自動
--    把「可能是同一個商品」丟進來，人工確認後才合併
-- ===========================================================
CREATE TABLE IF NOT EXISTS match_candidate (
  left_listing  TEXT NOT NULL REFERENCES listing(listing_id) ON DELETE CASCADE,
  right_listing TEXT NOT NULL REFERENCES listing(listing_id) ON DELETE CASCADE,
  score         REAL NOT NULL,               -- 0~1 相似度
  method        TEXT,                        -- 'brand+model' | 'phash' | 'sku' | 'title_fuzzy'
  decision      TEXT DEFAULT 'pending',      -- pending|same|different
  decided_by    TEXT,
  decided_at    TEXT,
  PRIMARY KEY (left_listing, right_listing)
);


-- ===========================================================
-- 9. 抓取紀錄：出事才查得到原因
-- ===========================================================
CREATE TABLE IF NOT EXISTS crawl_log (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id      TEXT REFERENCES site(site_id),
  url          TEXT NOT NULL,
  fetched_at   TEXT NOT NULL DEFAULT (datetime('now')),
  status_code  INTEGER,
  from_cache   INTEGER DEFAULT 0,
  body_path    TEXT,                          -- 原始檔存哪
  content_hash TEXT,                          -- 內容沒變就不用重新解析
  parse_ok     INTEGER,
  error        TEXT
);
CREATE INDEX IF NOT EXISTS ix_crawl_url ON crawl_log(url, fetched_at);


-- ===========================================================
-- 常用查詢：做成 view，不用每次重寫
-- ===========================================================

-- 每個商品現在的最低價、在幾個通路買得到
CREATE VIEW IF NOT EXISTS v_product_price AS
SELECT
  p.product_id, b.name AS brand, p.model, p.cat1, p.cat2,
  MIN(l.price)                     AS price_min,
  MAX(l.price)                     AS price_max,
  COUNT(DISTINCT l.site_id)        AS site_count,
  COUNT(l.listing_id)              AS listing_count,
  SUM(COALESCE(l.in_stock, 0)) > 0 AS any_in_stock
FROM product p
LEFT JOIN brand   b ON b.brand_id = p.brand_id
LEFT JOIN variant v ON v.product_id = p.product_id
LEFT JOIN listing l ON l.variant_id = v.variant_id AND l.gone_at IS NULL
GROUP BY p.product_id;

-- 最近降價的：拿來做「降價通知」
CREATE VIEW IF NOT EXISTS v_price_drop AS
SELECT
  l.listing_id, s.name AS site, l.title_raw,
  old.price AS price_before, new.price AS price_now,
  new.price - old.price AS diff,
  ROUND(100.0 * (new.price - old.price) / old.price, 1) AS pct,
  old.seen_date AS date_before, new.seen_date AS date_now
FROM price_point new
JOIN price_point old
  ON old.listing_id = new.listing_id AND old.seen_date < new.seen_date
JOIN listing l ON l.listing_id = new.listing_id
JOIN site    s ON s.site_id    = l.site_id
WHERE new.price < old.price
  AND old.seen_date = (
    SELECT MAX(seen_date) FROM price_point
    WHERE listing_id = new.listing_id AND seen_date < new.seen_date
  );

-- 哪些站該重抓了（超過各自的設定天數沒抓）
CREATE VIEW IF NOT EXISTS v_stale_site AS
SELECT site_id, name, last_crawled_at,
       CAST(julianday('now') - julianday(last_crawled_at) AS INTEGER) AS days_ago
FROM site
WHERE last_crawled_at IS NULL OR julianday('now') - julianday(last_crawled_at) > 7
ORDER BY days_ago DESC;

-- 真正可以拿來比價的：同一款、同一種型式、同一個尺寸，但在不同通路。
--
-- 為什麼需要這個？v_product_price 的 price_min..price_max 是「整個系列」的範圍。
-- Artemide Tolomeo 底下有夾燈、Micro 桌燈、Mega 立燈、XXL 戶外立燈 ——
-- 12,600 到 786,400 不是價差，是不同的產品。
--
-- 尺寸是最客觀的比對依據，所以這裡要求尺寸解析得出來才納入。
-- 寧可少比，不要比錯。
CREATE VIEW IF NOT EXISTS v_same_spec_price AS
SELECT
  p.product_id,
  b.name AS brand,
  p.model,
  json_extract(v.attrs, '$.kind')       AS kind,
  -- 組數一定要分開。多盞組的尺寸標示跟單盞一樣（都寫 Ø20 x H22），
  -- 不分的話 167,000 的五盞組會跟 31,100 的單盞被當成同一個東西比價。
  v.pack,
  v.width_mm, v.depth_mm, v.height_mm, v.diameter_mm,
  MIN(l.price)                          AS price_min,
  MAX(l.price)                          AS price_max,
  MAX(l.price) - MIN(l.price)           AS price_gap,
  COUNT(DISTINCT l.site_id)             AS site_count
FROM listing l
JOIN variant v ON v.variant_id = l.variant_id
JOIN product p ON p.product_id = v.product_id
LEFT JOIN brand b ON b.brand_id = p.brand_id
WHERE l.gone_at IS NULL
  AND l.price > 0
  AND COALESCE(v.width_mm, v.height_mm, v.diameter_mm) IS NOT NULL
GROUP BY p.product_id, kind, v.pack, v.width_mm, v.depth_mm, v.height_mm, v.diameter_mm
HAVING COUNT(DISTINCT l.site_id) > 1;
