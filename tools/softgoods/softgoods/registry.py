"""站台清單 + adapter 查表。

要加一個網站：
  · 如果它是 Shopify/Shopline → 只要在 sites.yaml 加三行，不用寫程式
  · 如果要自己解析 HTML      → 寫一個 adapter，在 ADAPTERS 註冊一行
"""

from __future__ import annotations

import pathlib

import yaml

from .adapters.base import Adapter
from .adapters.lampclub import LampclubAdapter
from .adapters.schemaorg import SchemaOrgAdapter
from .adapters.shopify import ShopifyAdapter
from .adapters.shopline import ShoplineAdapter
from .models import SiteConfig

ADAPTERS: dict[str, type[Adapter]] = {
    "shopify": ShopifyAdapter,  # 通用，一支打所有 Shopify 店
    "shopline": ShoplineAdapter,  # 通用，一支打所有 Shopline 店（要一頁一頁開，見檔頭）
    "schemaorg": SchemaOrgAdapter,  # 通用：sitemap ＋ 商品頁的 schema.org Product（自架網站）
    "lampclub": LampclubAdapter,
}

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_SITES = PROJECT_ROOT / "sites.yaml"
SCHEMA = PROJECT_ROOT / "schema.sql"


def load_sites(path: pathlib.Path | str | None = None) -> dict[str, SiteConfig]:
    raw = yaml.safe_load(pathlib.Path(path or DEFAULT_SITES).read_text(encoding="utf-8"))
    out = {}
    for entry in raw.get("sites", []):
        site = SiteConfig(**entry)
        out[site.site_id] = site
    return out


def build_adapter(site: SiteConfig) -> Adapter:
    if site.adapter not in ADAPTERS:
        raise KeyError(f"沒有這個 adapter: {site.adapter}（有的是 {', '.join(ADAPTERS)}）")
    return ADAPTERS[site.adapter](site)
