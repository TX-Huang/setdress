"""存什麼、不存什麼。

商品說明文字和圖片有著作權，各店條款也常寫「網站內容不得重製、散布」。
所以預設只存事實：品名、品牌、價格、尺寸、庫存、SKU、連結。
站方同意時，在 sites.yaml 那一站加 keep_content: true 才存說明和圖片。

本機快取（cache_multi/）是另一回事：它存的是抓回來的頁面（已瘦身），只在這台電腦、
被 .gitignore 擋著、不上傳也不發布。留著它是為了「改了解析程式不用再打網站」，
以後要抽設計師、年份、電壓這些事實，也是從快取重跑。資料庫和公開的東西才是「只存事實」。
（Codex 審查 2026-11-20 提過「快取裡有介紹文字」，這是刻意的取捨。）
"""

from __future__ import annotations

from dataclasses import replace

from .models import Record, SiteConfig


def facts_only(rec: Record, site: SiteConfig) -> Record:
    """拿掉說明文字和圖片網址，其他欄位原封不動。"""
    if site.keep_content:
        return rec
    return replace(rec, description=None, images=[])
