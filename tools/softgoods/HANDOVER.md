# 交接：室內軟裝資料爬蟲

交接日：2026-11-20（從另一個 Claude session 交接）

原本是獨立的 softgoods repo，2026-11-20 併進 Setdress：現在在 `tools/softgoods/`，下面的指令都在這個資料夾裡跑。

---

## 授權狀態（先看這個）

lampclub.tw 的使用條款寫「請勿以程式大量擷取本站資料」（條款頁最後更新
2026-11-15）。**Isaac 在 2026-11-20 來信詢問，對方回覆同意。**

所以這批資料是在站方同意下取得的，不是違反條款抓的。

**公開發布**：Isaac 說資料可以公開；但 lampclub 同意的是「抓取」，「公開發布那份資料」還沒跟對方確認，所以資料先放私人 repo，公開前先問 lampclub（lampclub 的聯絡信箱在它的條款頁）。

加其他新站時不要重複我的錯：`check_site.py` 第 7 項會查使用條款，
一定要跑，不要只看 robots.txt。robots.txt 是請求，條款是合約。

---

## 東西現在在哪（2026-11-20 交接完成）

| 東西 | 位置 | 公開嗎 |
|---|---|---|
| **程式**（框架、測試、工具、文件、通路清單 `CHANNELS.md`） | [TX-Huang/setdress](https://github.com/TX-Huang/setdress) 的 `tools/softgoods/` | 公開 |
| **資料**（`out/*.csv`、lampclub 那份 `softgoods.db`） | [TX-Huang/softgoods](https://github.com/TX-Huang/softgoods)（說明見它的 `DATA.md`）；本機改名成 `tools/softgoods/lampclub_baseline.db`，被 `.gitignore` 擋著 | **私人** |
| **直接從通路抓的資料**（`softgoods.db`，目前 4 家 Shopify） | 只在本機 `tools/softgoods/`，被 `.gitignore` 擋著 | 沒上傳 |
| **原始網頁快取**（59 MB） | 只在 Isaac 的另一台電腦 | 沒上傳 |

**改程式推到 setdress 的 `tools/softgoods/`**，softgoods repo 只放資料。

資料是「抓齊了沒」的基準：改成直接抓各家通路之後，拿它對照有沒有漏。

---

## 還沒解決的問題

**1. lampclub 的授權範圍** ← 最重要

對方同意「抓取」，「公開發布那份資料」沒問到。要公開之前先問清楚。

**2. `tests/fixtures/shopify_products.json` 在公開 repo 裡**

那是潤舍（luxurylife）的 3 個商品（標題、價格、SKU），當測試素材用。
潤舍的條款沒有禁止爬取，3 個商品算極少量，所以判斷可以留。
要更保守的話換成自己編的假資料，代價是測不到真實世界的髒資料。

**3. `lamp_scraper.py` 要不要刪**

已被 `softgoods/` 完全取代，留著的理由寫在它的檔頭（**它每次跑完都會整個覆蓋
`out/*.csv`**，不要在有資料的資料夾裡跑）。問 Isaac 決定。

---

## 這是什麼

抓台灣買得到的**室內軟裝**商品（家具、燈飾、布藝、擺飾、畫作、綠植），
把幾十個網站的資料合進同一個資料庫，算出「同一款在哪裡買、各賣多少」。

目前只有「燈飾」這一類有真實資料，但框架和分類表涵蓋全部六大類。

---

## 做完了什麼（都跑過、驗證過）

### 1. 資料：2142 盞燈

| 檔案 | 內容 |
|---|---|
| `out/lamps.csv` | 2142 盞：品牌、型號、設計師、年份、類型、電壓、價格範圍 |
| `out/listings.csv` | 5645 筆：哪家店、什麼規格、多少錢、現貨或預購、連結 |
| `softgoods.db` | 同一批資料的 SQLite（149 品牌 / 26 通路 / 4044 規格） |
| `cache/`、`cache_multi/` | 2143 個原始 HTML。**有這個就不用重抓** |

抓了 88 分鐘，零失敗。**零解析損失**，逐欄比對原始 HTML 驗證過：

| 欄位 | HTML 真的有寫 | CSV 抓到 |
|---|---|---|
| 設計師 | 833 | 833 |
| 設計年份 | 525 | 525 |
| 電壓 | 575 | 575 |

空的欄位是來源真的沒寫，不是漏抓。`listings.csv` 完全沒有空值。

### 2. 多站框架（`softgoods/`）

1285 行、12 個檔、**167 個測試全綠**（沒有 lampclub 網頁副本的電腦上：159 過、8 個自動跳過）、ruff 乾淨。

複雜度（`python -m radon cc . -s -n C`）：

| 範圍 | C 級以上的函式 |
|---|---|
| `softgoods/`（框架本體） | **0 個**，平均 A (3.2) |
| `check_site.py` | 0 個 |
| `lamp_scraper.py` | `parse_lamp` C (15) ← 見下方說明 |

`lamp_scraper.py` 是最早的單站練習腳本，已經被 `softgoods/` 完全取代，
留著只是當參考（而且它產生了 `cache/` 裡的那批 HTML）。**不要在它上面
開發**，也不用為它清複雜度。要刪掉它也可以，問 Isaac 一聲就好。

```
softgoods/
  fetcher.py     抓取層（快取/robots/限速/重試）—— 所有站共用一份
  normalize.py   正規化（尺寸→mm、品牌收斂、分類對應、標題清理、組數）
  store.py       寫 SQLite（重跑不弄亂、價格變了才記歷史）
  models.py      SiteConfig 和 Record
  registry.py    站台清單 + adapter 查表
  cli.py         命令列
  adapters/
    shopify.py   通用，一支打所有 Shopify 店
    lampclub.py  HTML 的站（而且是聚合站）
  data/
    category_map.yaml  網站分類名 → 我們的分類
    brands.yaml        品牌別名（FLOS / Flos Italia → flos）
```

`Record` 是整個框架的腰：所有 adapter 的輸出都是 Record，store 的輸入
也只有 Record。所以**加一個新網站不會動到任何其他地方**。

### 3. 分類表和資料結構

| 檔案 | 內容 |
|---|---|
| `taxonomy.yaml` | 軟裝 6 大類 / 39 子類 / 184 品項 / 65 個類別專屬欄位 |
| `schema.sql` | 9 張表 + 4 個 view |
| `sites.yaml` | 站台清單（目前 2 個站） |
| `README.md` | 怎麼跑、怎麼加新站 |
| `check_site.py` | 丟網址進去，判斷那個網站擋不擋爬蟲（紅/黃/綠燈） |

---

## 怎麼跑

```powershell
python -m softgoods sites                  # 列出站台
python -m softgoods crawl lampclub         # 抓一個站
python -m softgoods crawl all --limit 40   # 全部站，試跑
python -m softgoods report                 # 看資料庫內容
python -m pytest tests/ -q                 # 167 個測試，1.2 秒，不碰網路
ruff check softgoods/ tests/               # 交出去前跑
```

需要 `requests bs4 lxml pyyaml pandas pytest ruff radon`。

---

## 加一個新網站

1. **先檢查**：`python check_site.py <網址>`。🔴 紅燈不要加，🟡 黃燈把 delay 調大。
2. **是 Shopify / Shopline**（很多台灣通路都是）→ **不用寫程式**，
   `sites.yaml` 加五行就好。怎麼確認：開 `網址/products.json?limit=3`，
   有 JSON 就是。
3. **要自己解析 HTML** → 寫一個 adapter，只要 `discover()` 和 `parse()`
   兩個方法，在 `registry.py` 註冊一行。快取、限速、robots、重試、
   寫資料庫、正規化都已經有了。

---

## 我踩過的坑（這段最值得看）

全部都是**跑真實資料才踩到**的，測試編不出來。每個都補了測試才修。

### 1. 「電線長 200 cm」被當成商品寬度 2000mm
因為「長」也是寬度的標籤之一。
→ `normalize._ACCESSORY_LEN` 先把配件長度剔掉。

### 2. `擺飾 / 雕塑 / 壁飾` 這種分類對不到
Shopify 店常把 `product_type` 寫成斜線分隔的多重分類。
→ `map_category` 整串先試，再拆斜線一段一段試。

### 3. 系列價格範圍被誤當成價差 ★ 最重要
`Artemide Tolomeo` 底下其實有 **30 個不同產品** —— 夾燈、Micro 桌燈、
Mega 立燈、XXL 戶外立燈。`v_product_price` 會說它 12,600～786,400，
那不是價差。

**比價一定要用 `v_same_spec_price`**（同款+同型式+同尺寸+同組數，
2 家以上有賣）。`v_product_price` 只能當「系列價格範圍」看。

### 4. 多盞組跟單盞混在一起比
`Mini Crescent 五盞吊燈組` 167,000 和單盞 31,100，**尺寸標示一模一樣**
（都寫 Ø20 x H22），因為組合的尺寸是標單盞的。
→ `normalize.pack_size()` 從商品名判斷組數，`variant.pack` 是正式欄位
並且進 `UNIQUE(product_id, name, pack)`。

注意「三節閱讀立燈」是三節燈臂、「雙頭款吊燈」是一盞兩頭，都是 1 盞。
所以 `pack_size` 只認 盞/件/入/顆/支，不認 節/頭。

### 5. HTTP 200 不代表拿到東西
Amazon 回 `202` 加一個**完全空白**的頁面。狀態碼看起來成功，裡面什麼
都沒有。`check_site.py` 第一版因此把 Amazon 判成綠燈 —— 那是錯的。
→ 現在頁面不到 1000 字元就直接警告。

---

## 一個對產品決策有用的發現

```
可比價組合 128 組
  其中 49 組各店同價 (38%)
  平均價差 4,144 元
```

**這個品類很多是代理商定價，不同店賣一樣的錢。** 查過的大價差幾乎都是
來源資料錯誤 —— 例如北歐先生把 `Mini Crescent` 標成 Ø38（那是全尺寸的
規格，Mini 應該是 Ø20）。

所以做比價功能的話：**大價差要當成資料品質警訊，不是省錢機會。**

---

## 建議的下一步（我沒做的）

按我的建議順序：

1. **把檔案搬到正式資料夾 / 進 git**（最優先，見最上面）
2. **加幾家軟裝站** —— 家具、布藝、擺飾，不只燈。框架現在最便宜，
   Shopify 的站加五行就好
3. **商品比對（跨站去重）** —— 目前只做到「同品牌同型號」。
   `schema.sql` 有 `match_candidate` 表（機器算分、人工確認），但還沒寫
   填它的程式。這是整個專案最難的一步，**不要做全自動**
4. **排程 + 變更偵測** —— `crawl_log.content_hash` 欄位已經有了，
   邏輯還沒寫。商品清單每週、價格每天或每週
5. **圖片** —— 現在預設不存（連網址都不存，見下面「只存事實」）。`image.phash` 欄位留著，等站方同意、在 sites.yaml 打開 `keep_content` 才用得到
6. **從介紹文字抽尺寸** —— 直接抓 4 家 Shopify 後發現尺寸大多寫在介紹文字裡（見 CHANNELS.md）。抓的時候只抽出尺寸，文字本身丟掉

---

## 禮貌規則（請照做）

- 每頁等 1.5 秒以上；站方自己寫了更慢的 `Crawl-delay` 就聽它的
- 抓過的存快取，絕不重抓。**改 parse 程式碼不該重抓網站**
- robots.txt 禁止的，**打之前**就拒絕，不是抓了才檢查
- 404 不重試
- 商品下架不刪資料，標記 `gone_at`
- **只存事實**：品名、品牌、價格、尺寸、庫存、SKU、連結。介紹文字和圖片有著作權，預設不存（`softgoods/policy.py`）；站方同意才在 sites.yaml 那一站加 `keep_content: true`

**lampclub.tw 是紅燈**（使用條款禁止程式大量擷取）。技術上它是開放的
（robots `Allow: /`、有 sitemap、純 HTML），但那不等於條款允許 ——
我們能抓是因為 Isaac 2026-11-20 來信取得同意，不是因為它是綠燈。

加新站前一定要跑 `check_site.py`，第 7 項會查使用條款。
