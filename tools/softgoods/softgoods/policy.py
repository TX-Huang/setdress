"""存什麼、不存什麼。

商品介紹文字有著作權，各店條款也常寫「網站內容不得重製、散布」。
所以預設只存事實：品名、品牌、價格、尺寸、庫存、SKU、連結。
站方同意時，在 sites.yaml 那一站加 keep_content: true 才存介紹文字。

圖片只存「連結」（網址），不下載圖檔、不轉貼（2026-11-20 Isaac 同意）。
Setdress 要把商品做成 3D 放進照片：沒有原廠 3D 時，要從商品照片描輪廓，
做好的 3D 也要跟照片並排檢查。image 表的 credit 記來源；license 空著 = 還沒拿到授權。
公開上線前，用到的照片要拿到授權（docs/mvp-spec.md「風險：版權」）。

本機快取（cache_multi/）是另一回事：它存的是抓回來的頁面（已瘦身），只在這台電腦、
被 .gitignore 擋著、不上傳也不發布。留著它是為了「改了解析程式不用再打網站」，
以後要抽設計師、年份、電壓這些事實，也是從快取重跑。資料庫和公開的東西才是「只存事實」。
（Codex 審查 2026-11-20 提過「快取裡有介紹文字」，這是刻意的取捨。）
"""

from __future__ import annotations

from dataclasses import replace

from .models import Record, SiteConfig


def facts_only(rec: Record, site: SiteConfig) -> Record:
    """拿掉介紹文字，其他欄位（包括圖片連結）原封不動。"""
    if site.keep_content:
        return rec
    return replace(rec, description=None)
