"""只存事實：商品介紹文字有著作權，預設不存（docs：CHANNELS.md「人工看條款」）。

事實 = 品名、品牌、價格、尺寸、庫存、SKU、連結。
圖片只存「連結」（網址），不下載圖檔（2026-11-20 Isaac 同意）：做 3D 模型、並排檢查要用。
公開上線前要拿到授權（docs/mvp-spec.md「風險：版權」）。
站方同意時，sites.yaml 打開 keep_content 才存介紹文字。
"""

import json
import pathlib

from softgoods.adapters.shopify import ShopifyAdapter
from softgoods.cli import crawl_records
from softgoods.models import Record, SiteConfig
from softgoods.policy import facts_only
from softgoods.store import Store

FIX = pathlib.Path(__file__).parent / "fixtures"
SCHEMA = pathlib.Path(__file__).parent.parent / "schema.sql"


def _site(**kw) -> SiteConfig:
    return SiteConfig(site_id="luxurylife", name="潤舍", base_url="https://www.luxurylife.com.tw", **kw)


def _record() -> Record:
    return Record(
        site_id="luxurylife",
        url="https://www.luxurylife.com.tw/products/bell?variant=1",
        title_raw="Bell 無線桌燈",
        brand="Tom Dixon",
        model="Bell",
        cat1="lighting",
        description="<p>這段介紹文字有著作權</p>",
        images=["https://cdn.shopify.com/bell.jpg"],
        size_raw="Ø19 x H28 cm",
        price=10600,
        sku="TOD1",
        in_stock=True,
    )


def test_by_default_sites_do_not_keep_content():
    assert _site().keep_content is False


def test_drops_the_description_but_keeps_the_facts_and_image_links():
    r = facts_only(_record(), _site())
    assert r.description is None
    assert r.images == ["https://cdn.shopify.com/bell.jpg"], "圖片只存連結，3D 和並排檢查要用"
    assert (r.price, r.sku, r.url, r.brand, r.model, r.size_raw, r.in_stock) == (
        10600, "TOD1", "https://www.luxurylife.com.tw/products/bell?variant=1",
        "Tom Dixon", "Bell", "Ø19 x H28 cm", True,
    )


def test_keeps_the_description_only_when_the_site_allows_it():
    r = facts_only(_record(), _site(keep_content=True))
    assert r.description == "<p>這段介紹文字有著作權</p>"


def test_crawling_a_real_shopify_page_stores_image_links_but_no_description(tmp_path):
    page1 = (FIX / "shopify_products.json").read_text(encoding="utf-8")
    raw = json.loads(page1)["products"]
    assert any(p.get("body_html") for p in raw) and any(p.get("images") for p in raw)  # 素材真的有內容

    def fake_fetch(url: str) -> str:
        return page1 if "page=1" in url else json.dumps({"products": []})

    site = _site(platform="shopify")
    records = list(crawl_records(site, ShopifyAdapter(site), fake_fetch))
    assert records
    store = Store(tmp_path / "t.db", SCHEMA)
    store.upsert(records, "2026-11-20")
    assert store.query("SELECT COUNT(*) FROM product WHERE description IS NOT NULL")[0][0] == 0
    assert store.count("image") > 0
    assert store.query("SELECT COUNT(*) FROM image WHERE local_path IS NOT NULL")[0][0] == 0, "只存連結，不下載"
    assert store.query("SELECT COUNT(*) FROM image WHERE credit IS NULL")[0][0] == 0, "每張圖都要記來源"
    assert store.query("SELECT COUNT(*) FROM listing WHERE price IS NOT NULL")[0][0] > 0
    store.close()
