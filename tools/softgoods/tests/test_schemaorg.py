"""通用讀取程式：sitemap ＋ schema.org Product（JSON-LD）。

很多自架網站（北歐櫥窗、Loft29）在商品頁放了給搜尋引擎看的標準商品資料：
  <script type="application/ld+json">{"@type": "Product", "offers": {...}}</script>
讀這個就不用為每家寫 HTML 解析。頁面結構照 2026-11-20 看過的兩家做，文字是自己寫的。

  - 北歐櫥窗：Product 直接放；offers 一個；availability 寫 "PreOrder"（不是網址）
  - Loft29：放在 @graph 裡；availability 寫 "https://schema.org/InStock"；
    沒有價格的商品（「歡迎來電洽詢」）沒有 offers
"""

import json

import pytest

from softgoods.adapters.schemaorg import SchemaOrgAdapter, slim_jsonld_page
from softgoods.fetcher import FetchError
from softgoods.models import SiteConfig

BASE = "https://www.shop.test"
URL = f"{BASE}/product/6"


def ld(data: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(data, ensure_ascii=False)}</script>'


def crumbs(*names: str) -> dict:
    return {
        "@context": "http://schema.org/", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "item": {"@id": BASE, "name": n}}
            for i, n in enumerate(names)
        ],
    }


def product(name="Coffee Table 咖啡桌（胡桃木）", offers=None, **kw) -> dict:
    data = {
        "@context": "https://schema.org/", "@type": "Product", "name": name,
        "sku": "VIT001", "brand": {"@type": "Thing", "name": "Vitra"},
        "description": "店家的介紹文字，有著作權，不能存。", "image": "https://img.test/a.jpg",
    }
    if offers is not None:
        data["offers"] = offers
    data.update(kw)
    return data


def offer(price="146400", availability="PreOrder", **kw) -> dict:
    return {"@type": "Offer", "url": URL, "priceCurrency": "TWD", "price": price,
            "availability": availability, **kw}


def page(*blocks: dict, body: str = "<p>尺寸：寬 128 x 深 93 x 高 40（公分）</p>") -> str:
    scripts = "".join(ld(b) for b in blocks)
    return (
        f"<html><head>{scripts}<script>var x = '尺寸：寬 999 cm';</script></head>"
        f"<body><nav>首頁 家具 燈具</nav><div class='spec'>{body}</div></body></html>"
    )


@pytest.fixture
def adapter():
    site = SiteConfig(site_id="nordic", name="北歐櫥窗", base_url=BASE, adapter="schemaorg",
                      product_url_pattern=r"/product/\d+$")
    return SchemaOrgAdapter(site, brand_names=["Vitra", "Tom Dixon"])


class TestParse:
    def test_reads_the_facts_from_the_product_box(self, adapter):
        r = adapter.parse(URL, page(product(offers=offer()), crumbs("首頁", "設計家具")))[0]
        assert (r.title_raw, r.brand, r.sku, r.price, r.currency) == (
            "Coffee Table 咖啡桌（胡桃木）", "Vitra", "VIT001", 146400, "TWD")
        assert r.url == URL

    def test_preorder_is_not_in_stock_but_orderable(self, adapter):
        r = adapter.parse(URL, page(product(offers=offer(availability="PreOrder"))))[0]
        assert (r.in_stock, r.stock_text) == (False, "可預購")

    @pytest.mark.parametrize("value, want", [
        ("https://schema.org/InStock", (True, None)),
        ("InStock", (True, None)),
        ("http://schema.org/OutOfStock", (False, "售完")),
        ("https://schema.org/SoldOut", (False, "售完")),
        (None, (None, None)),
    ])
    def test_availability(self, adapter, value, want):
        r = adapter.parse(URL, page(product(offers=offer(availability=value))))[0]
        assert (r.in_stock, r.stock_text) == want

    def test_the_graph_form(self, adapter):
        # Loft29：Product 放在 @graph 裡
        graph = {"@context": "https://schema.org", "@graph": [
            product("Bell Portable 行動桌燈", offers=offer("10600", "https://schema.org/InStock"),
                    brand={"@type": "Brand", "name": "Tom Dixon"}),
            crumbs("首頁", "燈具", "Bell Portable 行動桌燈"),
        ]}
        r = adapter.parse(URL, page(graph))[0]
        assert (r.brand, r.price, r.in_stock) == ("Tom Dixon", 10600, True)
        assert (r.cat1, r.cat2) == ("lighting", "table")

    def test_a_product_without_a_price_is_still_listed(self, adapter):
        # Loft29：「歡迎來電洽詢」的商品沒有 offers
        r = adapter.parse(URL, page(product("New York Air 床架組")))[0]
        assert r.price is None
        assert (r.cat1, r.cat2) == ("furniture", "bed")

    def test_several_offers_become_several_records_with_their_own_urls(self, adapter):
        offers = [offer("1000", "InStock", sku="A", name="白色"), offer("1200", "InStock", sku="B", name="黑色")]
        recs = adapter.parse(URL, page(product(offers=offers)))
        assert [(r.variant_name, r.sku, r.price) for r in recs] == [("白色", "A", 1000), ("黑色", "B", 1200)]
        assert len({r.url for r in recs}) == 2

    def test_a_price_range_is_not_a_price(self, adapter):
        # 系列價格範圍不是價差（HANDOVER「踩過的坑」第 3 點）
        agg = {"@type": "AggregateOffer", "lowPrice": "1000", "highPrice": "5000", "priceCurrency": "TWD"}
        assert adapter.parse(URL, page(product(offers=agg)))[0].price is None
        same = {"@type": "AggregateOffer", "lowPrice": "1000", "highPrice": "1000", "priceCurrency": "TWD"}
        assert adapter.parse(URL, page(product(offers=same)))[0].price == 1000

    def test_brand_written_as_plain_text_or_missing(self, adapter):
        assert adapter.parse(URL, page(product(brand="Vitra", offers=offer())))[0].brand == "Vitra"
        r = adapter.parse(URL, page(product("Tom Dixon Bell 桌燈", brand=None, offers=offer())))[0]
        assert r.brand == "Tom Dixon"

    def test_size_comes_from_the_page_text_not_from_scripts(self, adapter):
        r = adapter.parse(URL, page(product(offers=offer())))[0]
        assert r.size_raw == "寬 128 x 深 93 x 高 40"

    def test_no_text_but_image_links(self, adapter):
        r = adapter.parse(URL, page(product(offers=offer())))[0]
        assert (r.description, r.images) == (None, ["https://img.test/a.jpg"])

    @pytest.mark.parametrize("image, want", [
        (["https://img.test/1.jpg", "https://img.test/2.jpg"], ["https://img.test/1.jpg", "https://img.test/2.jpg"]),
        ({"@type": "ImageObject", "url": "https://img.test/o.jpg"}, ["https://img.test/o.jpg"]),
        ([{"@type": "ImageObject", "contentUrl": "https://img.test/c.jpg"}], ["https://img.test/c.jpg"]),
        (None, []),
        ("不是網址", []),
    ])
    def test_image_written_in_different_ways(self, adapter, image, want):
        assert adapter.parse(URL, page(product(offers=offer(), image=image)))[0].images == want

    @pytest.mark.parametrize("html", ["<html>沒有商品資料</html>", page(crumbs("首頁")),
                                      "<script type='application/ld+json'>{壞掉的 json</script>"])
    def test_pages_without_a_product_give_nothing(self, adapter, html):
        assert adapter.parse(URL, html) == []


class TestSlim:
    def test_keeps_the_product_box_and_text_drops_other_scripts(self, adapter):
        raw = page(product(offers=offer()), crumbs("首頁", "設計家具"))
        slim = slim_jsonld_page(raw)
        assert "application/ld+json" in slim
        assert "var x" not in slim
        assert adapter.parse(URL, slim) == adapter.parse(URL, raw)


SITEMAP = f"""<urlset>
<url><loc>{BASE}/product/6</loc></url>
<url><loc>{BASE}/product_category/11</loc></url>
<url><loc>{BASE}/product/7</loc></url>
<url><loc>{BASE}/product/6</loc></url>
<url><loc>https://elsewhere.test/product/8</loc></url>
</urlset>"""


class TestDiscover:
    def test_only_product_pages_on_this_site_once_each(self, adapter):
        got = list(adapter.discover(lambda url, trim=None: SITEMAP))
        assert got == [f"{BASE}/product/6", f"{BASE}/product/7"]

    def test_a_sitemap_index_reads_every_part(self, adapter):
        pages = {
            f"{BASE}/sitemap.xml": f"<sitemapindex><sitemap><loc>{BASE}/s1.xml</loc></sitemap>"
                                   f"<sitemap><loc>{BASE}/s2.xml</loc></sitemap></sitemapindex>",
            f"{BASE}/s1.xml": f"<urlset><url><loc>{BASE}/product/1</loc></url></urlset>",
            f"{BASE}/s2.xml": f"<urlset><url><loc>{BASE}/product/2</loc></url></urlset>",
        }
        got = list(adapter.discover(lambda url, trim=None: pages[url]))
        assert got == [f"{BASE}/product/1", f"{BASE}/product/2"]

    def test_crawl_counts_pages_it_could_not_read(self, adapter):
        good = page(product(offers=offer()))

        def fetch(url, trim=None):
            if url.endswith("sitemap.xml"):
                return SITEMAP
            if url.endswith("/7"):
                raise FetchError("HTTP 503")
            return trim(good) if trim else good

        recs = list(adapter.crawl(fetch))
        assert len(recs) == 1
        assert adapter.skipped == 1


class TestCodexReview3:
    """Codex 審查（2026-11-20 第三次）抓到的。"""

    def test_offers_without_their_own_sku_still_get_their_own_urls(self, adapter):
        offers = [offer("1000", "InStock", name="白"), offer("1200", "InStock", name="黑")]
        recs = adapter.parse(URL, page(product(offers=offers, sku="P1")))
        assert len({r.url for r in recs}) == 2

    @pytest.mark.parametrize("agg", [
        {"@type": "AggregateOffer", "price": "1000", "lowPrice": "1000", "highPrice": "5000"},
        {"@type": "Offer", "lowPrice": "1000"},
    ])
    def test_a_range_or_half_a_range_is_not_a_price(self, adapter, agg):
        assert adapter.parse(URL, page(product(offers=agg)))[0].price is None

    def test_price_in_price_specification(self, adapter):
        o = {"@type": "Offer", "priceSpecification": {"@type": "PriceSpecification", "price": 3200,
                                                      "priceCurrency": "TWD"}}
        assert adapter.parse(URL, page(product(offers=o)))[0].price == 3200

    @pytest.mark.parametrize("price", ["0", 0, "", "NT$0"])
    def test_zero_means_no_price(self, adapter, price):
        assert adapter.parse(URL, page(product(offers=offer(price=price))))[0].price is None

    def test_the_product_matching_this_page_wins_over_a_related_one(self, adapter):
        related = product("別的商品 吊燈", offers=offer("999"), url=f"{BASE}/product/99")
        main = product("Coffee Table 咖啡桌", offers=offer("146400"), url=URL)
        assert adapter.parse(URL, page(related, main))[0].price == 146400

    def test_brand_written_as_a_list(self, adapter):
        r = adapter.parse(URL, page(product(brand=[{"@type": "Brand", "name": "Vitra"}], offers=offer())))[0]
        assert r.brand == "Vitra"

    def test_json_ld_wrapped_in_comments_or_cdata(self, adapter):
        data = json.dumps(product(offers=offer()), ensure_ascii=False)
        html = f'<script type="application/ld+json">//<![CDATA[\n{data}\n//]]></script>'
        assert adapter.parse(URL, html)[0].price == 146400
        html = f'<script type="application/ld+json"><!-- {data} --></script>'
        assert adapter.parse(URL, html)[0].price == 146400

    def test_the_whole_path_must_match_and_query_strings_do_not_make_duplicates(self, adapter):
        sm = f"""<urlset><url><loc>{BASE}/blog/product/6</loc></url>
<url><loc>{BASE}/product/6</loc></url><url><loc>{BASE}/product/6?utm_source=x</loc></url></urlset>"""
        assert list(adapter.discover(lambda url, trim=None: sm)) == [f"{BASE}/product/6"]

    def test_sitemap_parts_beyond_the_limit_make_the_run_incomplete(self):
        site = SiteConfig(site_id="s", name="s", base_url=BASE, adapter="schemaorg",
                          product_url_pattern=r"/product/\d+", max_pages=1)
        a = SchemaOrgAdapter(site, brand_names=[])
        pages = {
            f"{BASE}/sitemap.xml": f"<sitemapindex><sitemap><loc>{BASE}/s1.xml</loc></sitemap>"
                                   f"<sitemap><loc>{BASE}/s2.xml</loc></sitemap></sitemapindex>",
            f"{BASE}/s1.xml": f"<urlset><url><loc>{BASE}/product/1</loc></url></urlset>",
        }
        good = page(product(offers=offer()))
        list(a.crawl(lambda url, trim=None: pages.get(url, good)))
        assert a.skipped >= 1, "沒讀到的 sitemap 那一份，商品沒看到，不能當成下架"
