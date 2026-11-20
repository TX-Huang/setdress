# 室內軟裝多站爬蟲

抓台灣買得到的軟裝商品（家具、燈飾、布藝、擺飾、畫作、綠植），
把幾十個網站的資料合進同一個資料庫，算出「同一款在哪裡買、各賣多少」。

## 跑法

```powershell
python -m softgoods sites                    # 列出站台
python -m softgoods crawl luxurylife         # 抓一個站
python -m softgoods crawl all --limit 40     # 全部站，每站最多 40 筆（試跑）
python -m softgoods report                   # 看資料庫內容
```

抓回來的東西都在 `cache_multi/`。**第二次跑是零下載。**
所以你改 parse 的程式碼可以改一百次，網站只被打一次。

## 加一個新網站

### 先檢查

```powershell
python check_site.py https://新網站.com.tw
```

🔴 紅燈就不要加。🟡 黃燈就把 `crawl_delay_sec` 調大。

### 如果它是 Shopify / Shopline（很多台灣通路都是）

**不用寫程式**，在 `sites.yaml` 加一塊就好：

```yaml
  - site_id: 某某家居
    name: 某某家居
    base_url: https://example.com.tw
    adapter: shopify
    platform: shopify
    kind: dealer
    crawl_delay_sec: 2.0
```

怎麼知道是不是 Shopify？開 `https://網站/products.json?limit=3`，
有 JSON 出來就是。

尺寸會從商品介紹文字裡只抽出「尺寸那一行」（`sizes.py`，規格在 `SIZES.md`），
介紹文字本身不存。有些店（潤舍）尺寸只寫在商品頁、JSON 裡沒有，
那一站加 `size_from_page: true`：分得出類別、清單裡沒尺寸的商品，一件多開一頁。

### 如果要自己解析 HTML

寫一個 adapter，只要兩個方法：

```python
class 新站Adapter(Adapter):
    def discover(self, fetch):
        """產生要抓的網址。可以自己 fetch（讀 sitemap、翻頁）。"""

    def parse(self, url, body):
        """內容 → list[Record]。純函式，不要在這裡連網路。"""
```

然後在 `registry.py` 的 `ADAPTERS` 註冊一行。

快取、限速、robots、重試、寫資料庫、正規化**都已經有了**，不用碰。

## 架構

```
softgoods/
  fetcher.py          抓取層（快取 / robots / 限速 / 重試）—— 所有站共用一份
  normalize.py        正規化（尺寸→mm、品牌收斂、分類對應、標題清理）
  sizes.py            從介紹文字只抽出尺寸那一行（SIZES.md）
  policy.py           只存事實：介紹文字和圖片預設不存
  store.py            寫 SQLite（重跑不會弄亂資料、價格變了才記歷史）
  models.py           SiteConfig 和 Record
  registry.py         站台清單 + adapter 查表
  cli.py              命令列
  adapters/
    shopify.py        通用，一支打所有 Shopify 店
    lampclub.py       HTML 的站（而且是聚合站）
  data/
    category_map.yaml 網站分類名 → 我們的分類
    brands.yaml       品牌別名（FLOS / Flos Italia → flos）
sites.yaml            站台清單
schema.sql            資料庫結構（9 表 + 4 view）
taxonomy.yaml         軟裝分類表（6 大類 / 39 子類 / 184 品項）
```

`Record` 是整個框架的腰：所有 adapter 的輸出都是 Record，store 的輸入也只有
Record。所以加一個新網站不會動到任何其他地方。

## 比價要用哪個 view（很重要）

| view | 是什麼 | 能不能當價差看 |
|---|---|---|
| `v_product_price` | **整個系列**的價格範圍 | **不行** |
| `v_same_spec_price` | 同款+同型式+同尺寸+同組數，2 家以上有賣 | 可以 |

為什麼要分開：`Artemide Tolomeo` 底下有 30 個東西 —— 夾燈、Micro 桌燈、
Mega 立燈、XXL 戶外立燈。`v_product_price` 會說它 12,600～786,400，
那不是價差，是不同的產品。

`v_same_spec_price` 要求尺寸解析得出來才納入（尺寸是最客觀的比對依據），
而且組數要一樣 —— 多盞組的尺寸標示跟單盞一模一樣，不分開就會把
167,000 的五盞組當成 31,100 那盞的另一個報價。

**寧可少比，不要比錯。**

## 分類對不到的時候

`report` 會提醒你。原始分類名存在 `product.attrs.source_category`，查得出來：

```sql
SELECT DISTINCT json_extract(attrs,'$.source_category')
FROM product WHERE cat1 = 'unknown' OR cat2 IS NULL;
```

把缺的補進 `data/category_map.yaml` 就好，不用改程式。

不用另外加的：「吊燈 Pendant」「Light燈飾」這種中英黏在一起的、「吧檯椅(高)」這種帶括號的，
程式會拆開各試一次。網站分類太粗（NOSA 的燈全寫「燈具」）時，小分類從標題找。

**改了分類對應，要重建資料庫**：商品的分類只在第一次寫入時決定（好幾家店共用同一個商品）。
把 `softgoods.db` 移走、重跑 `crawl`，會全部從本機快取讀，不會再打網站。
尺寸不用：重跑時解析得出尺寸，就會更新舊的；這次沒抓到尺寸，不會蓋掉舊的。

## 測試

```powershell
python -m pytest tests/ -q
```

296 個測試（8 個要 lampclub 頁面副本，沒有就跳過），完全不碰網路（網路層是注入的）。
測試素材是真的抓回來的頁面，放在 `tests/fixtures/`。

交出去前跑：

```powershell
ruff check softgoods/ tests/
```

## 授權

`lampclub.tw` 的使用條款寫「請勿以程式大量擷取本站資料」。
Isaac 在 2026-11-20 來信詢問，**對方回覆同意**，整站資料才抓的；Isaac 說資料可以公開；但 lampclub 同意的是「抓取」，「公開發布那份資料」還沒跟對方確認，所以資料先放私人 repo，公開前先問 lampclub。

加新站一定要跑 `check_site.py`，它的第 7 項會查使用條款。robots.txt 是請求，條款是合約。

## 禮貌規則

- 每頁等 1.5 秒以上（站方自己寫了更慢的 `Crawl-delay` 就聽它的）
- 抓過的存快取，絕不重抓
- robots.txt 禁止的，**打之前**就拒絕
- 404 不重試
- 商品下架不刪資料，標記 `gone_at`
