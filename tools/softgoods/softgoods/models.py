"""標準資料結構。

這裡只有兩個東西：
  SiteConfig —— 一個站台的設定（網址、延遲、用哪個 adapter）
  Record     —— 「某個通路的某個規格賣多少錢」

Record 是整個框架的腰。所有 adapter 的輸出都是 Record，
store 的輸入也只有 Record。所以加一個新網站，不會動到任何其他地方。
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "softgoods-crawler/1.0 (+polite: 1 req/1.5s, cached)"
)


@dataclass(slots=True)
class SiteConfig:
    """一個站台。全部設定寫在 sites.yaml，不要散在程式裡。"""

    site_id: str
    name: str
    base_url: str

    adapter: str = "shopify"  # 用哪個 adapter（registry 裡的名字）
    kind: str = "dealer"  # brand_official | dealer | marketplace | aggregator
    platform: str | None = None  # shopify | shopline | cyberbiz | woocommerce | custom
    country: str = "TW"
    currency: str = "TWD"

    # 禮貌設定：每個站自己一組
    crawl_delay_sec: float = 1.5
    obey_robots: bool = True
    user_agent: str = DEFAULT_UA
    max_pages: int = 100

    # 存不存商品說明文字和圖片（有著作權）。預設不存，只存事實；站方同意才打開（policy.py）
    keep_content: bool = False
    # 尺寸只寫在商品頁、商品清單 JSON 拿不到的店（潤舍）才打開：一件多開一頁（SIZES.md）
    size_from_page: bool = False
    # 只賣自己牌子的店（柒木、HAY TAIPEI）：標題不會寫品牌，就用這個
    house_brand: str = ""
    # schemaorg adapter：sitemap 裡哪些網址是商品頁（正規表示式，比對網址的路徑）
    product_url_pattern: str = ""
    # 只拿來對照「抓齊了沒」的站（lampclub）：crawl all 不抓它，要抓得指名
    baseline: bool = False

    # check_site.py 的判定結果記在這
    blocks_bots: bool = False
    needs_browser: bool = False
    notes: str = ""


@dataclass(slots=True)
class Record:
    """一筆上架資料。

    欄位分三層，對應資料庫的三張表：
      product 層：brand / model / cat / designer …  （不管幾個站，同一款就一列）
      variant 層：variant_name / color / 尺寸        （同一款的不同尺寸顏色）
      listing 層：url / price / in_stock             （某個通路的某一筆）
    """

    # --- 必填
    site_id: str  # 這筆是「誰在賣」
    url: str
    title_raw: str  # 原始標題，永遠要留
    brand: str
    model: str
    cat1: str

    # --- product 層
    cat2: str | None = None
    cat3: str | None = None
    series: str | None = None
    designer: str | None = None
    design_year: int | None = None
    origin_country: str | None = None
    description: str | None = None
    product_attrs: dict = field(default_factory=dict)  # 類別專屬欄位

    # --- variant 層
    variant_name: str | None = None
    color: str | None = None
    material_main: str | None = None
    finish: str | None = None
    size_raw: str | None = None  # 原始尺寸字串
    weight_g: int | None = None
    variant_attrs: dict = field(default_factory=dict)

    # --- listing 層
    price: int | None = None
    currency: str = "TWD"
    price_original: int | None = None
    sku: str | None = None
    in_stock: bool | None = None
    stock_text: str | None = None
    is_official: bool = False
    images: list[str] = field(default_factory=list)

    # --- 出處（聚合站用：資料是在 A 站看到的，但東西在 B 站賣）
    channel: str | None = None  # 賣家的顯示名稱
    source_site_id: str | None = None  # 我們是從哪個站讀到的
    source_url: str | None = None
