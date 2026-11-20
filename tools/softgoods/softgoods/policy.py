"""存什麼、不存什麼。

商品說明文字和圖片有著作權，各店條款也常寫「網站內容不得重製、散布」。
所以預設只存事實：品名、品牌、價格、尺寸、庫存、SKU、連結。
站方同意時，在 sites.yaml 那一站加 keep_content: true 才存說明和圖片。
"""

from __future__ import annotations

from dataclasses import replace

from .models import Record, SiteConfig


def facts_only(rec: Record, site: SiteConfig) -> Record:
    """拿掉說明文字和圖片網址，其他欄位原封不動。"""
    if site.keep_content:
        return rec
    return replace(rec, description=None, images=[])
