"""寫進 SQLite。

爬蟲會一直重跑，所以這一層只有一個目標：**重跑不能把資料弄亂**。
  · 同一筆上架抓一百次，listing 還是一列
  · 價格沒變，price_point 不新增（不然一年 365 列全一樣）
  · 商品下架不刪資料，標記 gone_at（歷史要留得住）

Record 進來，正規化在這裡發生（尺寸換 mm、品牌收斂、交期解析），
因為正規化規則會改，改了要能重跑整個資料庫而不用重抓網站。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
from collections.abc import Iterable, Sequence

from . import normalize as nz
from .models import Record


def _hid(*parts) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


class Store:
    def __init__(
        self,
        db_path: pathlib.Path | str,
        schema_path: pathlib.Path | str,
        brand_aliases: dict[str, list[str]] | None = None,
    ):
        self.path = pathlib.Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.executescript(pathlib.Path(schema_path).read_text(encoding="utf-8"))
        self.con.execute("PRAGMA foreign_keys = ON")
        self.brand_aliases = brand_aliases or {}

    # ------------------------------------------------------- 小工具

    def query(self, sql: str, params: Sequence = ()) -> list[tuple]:
        return self.con.execute(sql, params).fetchall()

    def count(self, table: str) -> int:
        return self.con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def close(self) -> None:
        self.con.commit()
        self.con.close()

    # ---------------------------------------------- 一層一層確保存在

    def _ensure_site(self, rec: Record) -> None:
        self.con.execute(
            """INSERT INTO site(site_id, name, home_url, kind)
               VALUES(?,?,?,?) ON CONFLICT(site_id) DO NOTHING""",
            (rec.site_id, rec.channel or rec.site_id, "", "dealer"),
        )

    def _ensure_brand(self, rec: Record) -> str:
        bid = nz.brand_id(rec.brand, self.brand_aliases)
        self.con.execute(
            "INSERT INTO brand(brand_id, name) VALUES(?,?) ON CONFLICT(brand_id) DO NOTHING",
            (bid, rec.brand or bid),
        )
        return bid

    def _ensure_product(self, rec: Record, brand_id: str) -> str:
        pid = f"{brand_id}__{nz.slug(rec.model)}"
        self.con.execute(
            """INSERT INTO product
                 (product_id, brand_id, model, series, cat1, cat2, cat3,
                  designer, design_year, origin_country, description, attrs)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(product_id) DO NOTHING""",
            (pid, brand_id, rec.model, rec.series, rec.cat1, rec.cat2, rec.cat3,
             rec.designer, rec.design_year, rec.origin_country, rec.description,
             json.dumps(rec.product_attrs, ensure_ascii=False)),
        )
        if rec.product_attrs:
            self._merge_attrs("product", "product_id", pid, rec.product_attrs)
        return pid

    def _merge_attrs(self, table: str, key_col: str, key: str, new: dict) -> None:
        """後來抓到的欄位補進去，不要覆蓋掉已經有的。"""
        row = self.con.execute(
            f"SELECT attrs FROM {table} WHERE {key_col} = ?", (key,)
        ).fetchone()
        merged = {**json.loads(row[0] or "{}"), **new} if row else new
        self.con.execute(
            f"UPDATE {table} SET attrs = ? WHERE {key_col} = ?",
            (json.dumps(merged, ensure_ascii=False), key),
        )

    def _ensure_variant(self, rec: Record, product_id: str) -> str:
        name = rec.variant_name or "標準"
        # 組數要算進規格的身分。真實案例：Lee Broom Mini Crescent 的單盞和
        # 五盞組，規格字串一模一樣（都是「吊燈 · Ø20 x H22 cm」），
        # 不分開的話 167,000 的五盞組會被當成 31,100 那盞的另一個報價。
        pack = rec.variant_attrs.get("pack", 1)
        size_raw = rec.size_raw or rec.variant_name
        dims = nz.parse_dimensions(size_raw)
        # 尺寸也算進規格的身分。真實案例（潤舍）：Nebra 立燈和 Nebra 桌燈，品名清理後
        # 都是「Nebra」、規格都叫「白色」—— 不分開的話兩筆共用一個規格，尺寸互相蓋掉。
        # 不同店賣同款同尺寸，還是同一個規格（比價靠這個）。
        size_key = [dims.get(k) for k in ("width_mm", "depth_mm", "height_mm", "diameter_mm")]
        vid = f"{product_id}__{_hid(name, pack, *size_key)}"
        self.con.execute(
            """INSERT INTO variant
                 (variant_id, product_id, name, color, color_family, material_main,
                  finish, width_mm, depth_mm, height_mm, diameter_mm, weight_g,
                  size_raw, pack, attrs)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(variant_id) DO NOTHING""",
            (vid, product_id, name, rec.color, nz.color_family(rec.color),
             rec.material_main, rec.finish,
             dims.get("width_mm"), dims.get("depth_mm"), dims.get("height_mm"),
             dims.get("diameter_mm"), rec.weight_g, size_raw, pack,
             json.dumps(rec.variant_attrs, ensure_ascii=False)),
        )
        return vid

    def _upsert_listing(self, rec: Record, variant_id: str, seen_date: str) -> str:
        lid = f"{rec.site_id}__{_hid(rec.url)}"
        stock = None if rec.in_stock is None else int(rec.in_stock)
        lead = rec.stock_text and nz.parse_lead_time(rec.stock_text)
        self.con.execute(
            """INSERT INTO listing
                 (listing_id, variant_id, site_id, url, title_raw, sku, price, currency,
                  price_original, in_stock, stock_text, lead_time_days, is_official,
                  first_seen_at, last_seen_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(listing_id) DO UPDATE SET
                 -- 指向這次看到的規格（尺寸解析變好了就換過去）；
                 -- 但這次沒抓到尺寸、上次有的話，留在上次那個，不要把尺寸弄丟
                 variant_id     = CASE
                   WHEN (SELECT COALESCE(width_mm, depth_mm, height_mm, diameter_mm)
                           FROM variant WHERE variant_id = excluded.variant_id) IS NOT NULL
                     OR (SELECT COALESCE(width_mm, depth_mm, height_mm, diameter_mm)
                           FROM variant WHERE variant_id = listing.variant_id) IS NULL
                   THEN excluded.variant_id ELSE listing.variant_id END,
                 price          = excluded.price,
                 price_original = excluded.price_original,
                 in_stock       = excluded.in_stock,
                 stock_text     = excluded.stock_text,
                 lead_time_days = excluded.lead_time_days,
                 last_seen_at   = excluded.last_seen_at,
                 gone_at        = NULL""",
            (lid, variant_id, rec.site_id, rec.url, rec.title_raw, rec.sku,
             rec.price, rec.currency, rec.price_original, stock, rec.stock_text,
             lead, int(rec.is_official), seen_date, seen_date),
        )
        return lid

    def _record_price(self, listing_id: str, price, stock, seen_date: str) -> bool:
        """只在價格或庫存變了才寫一列歷史。"""
        last = self.con.execute(
            """SELECT price, in_stock FROM price_point
               WHERE listing_id = ? ORDER BY seen_date DESC LIMIT 1""",
            (listing_id,),
        ).fetchone()
        if last is not None and (last[0], last[1]) == (price, stock):
            return False
        self.con.execute(
            """INSERT INTO price_point(listing_id, seen_date, price, in_stock)
               VALUES(?,?,?,?)
               ON CONFLICT(listing_id, seen_date) DO UPDATE SET
                 price = excluded.price, in_stock = excluded.in_stock""",
            (listing_id, seen_date, price, stock),
        )
        return True

    def _save_images(self, rec: Record, product_id: str) -> None:
        for i, src in enumerate(rec.images):
            self.con.execute(
                """INSERT INTO image(image_id, product_id, src_url, position, credit)
                   VALUES(?,?,?,?,?) ON CONFLICT(src_url) DO NOTHING""",
                (_hid(src), product_id, src, i, rec.channel or rec.site_id),
            )

    # ------------------------------------------------------------ 入口

    def upsert(self, records: Iterable[Record], seen_date: str) -> dict:
        stats = {"listings": 0, "price_points": 0}
        for rec in records:
            self._ensure_site(rec)
            bid = self._ensure_brand(rec)
            pid = self._ensure_product(rec, bid)
            vid = self._ensure_variant(rec, pid)
            lid = self._upsert_listing(rec, vid, seen_date)
            self._save_images(rec, pid)

            stock = None if rec.in_stock is None else int(rec.in_stock)
            if self._record_price(lid, rec.price, stock, seen_date):
                stats["price_points"] += 1
            stats["listings"] += 1
        self.con.commit()
        return stats

    def mark_gone(self, site_id: str, seen_date: str) -> int:
        """這一輪沒看到的，標記下架。不刪 —— 歷史要留得住。"""
        cur = self.con.execute(
            """UPDATE listing SET gone_at = ?
               WHERE site_id = ? AND gone_at IS NULL AND last_seen_at < ?""",
            (seen_date, site_id, seen_date),
        )
        self.con.commit()
        return cur.rowcount
