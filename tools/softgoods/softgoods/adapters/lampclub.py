"""lampclub.tw adapter —— HTML 的站，而且是「聚合站」。

跟 Shopify 那種直營店不一樣的地方：
這個站自己不賣東西，它列出「這盞燈在台灣哪幾家買得到、各賣多少」。
所以一列資料的賣家（channel）不是 lampclub，是潤舍、北歐櫥窗那些。

Record 裡分得很清楚：
    site_id / channel  = 真正在賣的人
    source_site_id     = 我們是從哪裡讀到這件事（lampclub）
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from bs4 import BeautifulSoup

from .. import normalize as nz
from ..models import Record
from .base import Adapter, Fetch

VOLTAGE_KEY = "電壓（通路標示）"


def _txt(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


class LampclubAdapter(Adapter):
    def discover(self, fetch: Fetch) -> Iterator[str]:
        """sitemap 裡 2000 多個網址，只要燈具頁。"""
        xml = fetch(f"{self.site.base_url}/sitemap.xml")
        pattern = re.compile(rf"{re.escape(self.site.base_url)}/lamps/[^/]+/$")
        for loc in re.findall(r"<loc>(.*?)</loc>", xml):
            if pattern.match(loc):
                yield loc

    # ------------------------------------------------- 頁面層級的資料

    def _page_facts(self, soup) -> dict[str, str]:
        """<dl class="facts"> 的 dt/dd 配對。"""
        facts: dict[str, str] = {}
        for dt in soup.select("dl.facts dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                for tag in dd.select("span.tag"):
                    tag.extract()  # 「原廠官網」那顆小標籤不是值
            facts[_txt(dt)] = _txt(dd)
        return facts

    def _page_header(self, soup) -> dict:
        crumb = soup.select("div.crumb a")
        facts = self._page_facts(soup)
        year = re.search(r"\d{4}", facts.get("設計年份", ""))
        img = soup.select_one("section.mhead img")

        attrs = {}
        if facts.get(VOLTAGE_KEY):
            attrs["voltage"] = facts[VOLTAGE_KEY]
        if facts.get("類型"):
            attrs["types"] = facts["類型"]

        return {
            "model": _txt(soup.select_one("h1")),
            "brand": _txt(crumb[1]) if len(crumb) > 1 else "",
            "designer": facts.get("設計師") or None,
            "design_year": int(year.group()) if year else None,
            "attrs": attrs,
            "images": [img["src"]] if img and img.get("src") else [],
        }

    # ------------------------------------------------ 每一列通路報價

    @staticmethod
    def _split_item_cell(item_cell) -> tuple[str, str]:
        """商品欄裡夾一個 <span class="sub"> 裝規格。切開成 (商品名, 規格)。"""
        sub = item_cell.select_one("span.sub")
        spec = _txt(sub)
        if sub:
            sub.extract()  # 拔掉，剩下的才是純商品名
        return _txt(item_cell), spec

    @staticmethod
    def _row_target(row, cells) -> str | None:
        """這一列指向的通路網址。沒有就不是一列有效的報價。"""
        link = row.select_one("td.go a")
        if len(cells) < 4 or not link:
            return None
        return link.get("href")

    def _row_category(self, spec: str | None) -> tuple[str | None, str | None]:
        """規格字串的第一段是燈的型式：「無線桌燈 · Ø12.5 x 高 21 cm · 全電壓」"""
        kind = (spec.split("·")[0].strip() if spec else "") or None
        _, cat2 = nz.map_category(kind, self.category_map)
        return kind, cat2

    def _row_record(self, row, head: dict, source_url: str) -> Record | None:
        cells = row.find_all("td")
        target = self._row_target(row, cells)
        if not target:
            return None

        # 先把欄位全部算好，建 Record 的時候就只是填空
        title, spec = self._split_item_cell(cells[1])
        spec = spec or None
        seller_cell = _txt(cells[0])
        channel = _txt(cells[0].select_one("b")) or seller_cell
        stock_text = _txt(cells[3]) or None
        official = "Monobrand" in seller_cell or "✓" in seller_cell
        kind, cat2 = self._row_category(spec)

        return Record(
            site_id=nz.slug(channel),
            channel=channel,
            url=target,
            title_raw=title,
            brand=head["brand"],
            model=head["model"],
            cat1="lighting",
            cat2=cat2,
            cat3=kind,
            designer=head["designer"],
            design_year=head["design_year"],
            product_attrs=head["attrs"],
            # 型式和組數要存在 variant 不是 product：同一個系列底下
            # 桌燈、壁燈、立燈是不同的東西，單盞和五盞組也是。
            # 組數要從商品名看（規格欄的尺寸是單盞的，看不出組數）。
            variant_attrs={"kind": kind, "pack": nz.pack_size(title)},
            variant_name=spec or title,
            size_raw=spec,
            price=nz.parse_price(_txt(row.select_one("td.pr"))),
            currency=self.site.currency,
            in_stock=nz.in_stock(stock_text),
            stock_text=stock_text,
            is_official=official,
            images=head["images"],
            source_site_id=self.site.site_id,
            source_url=source_url,
        )

    def parse(self, url: str, body: str) -> list[Record]:
        soup = BeautifulSoup(body, "lxml")
        head = self._page_header(soup)
        if not head["model"]:
            return []

        out = []
        for row in soup.select("table.ls tbody tr"):
            rec = self._row_record(row, head, url)
            if rec:
                out.append(rec)
        return out
