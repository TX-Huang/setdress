"""命令列入口。

    python -m softgoods sites                   列出站台
    python -m softgoods crawl lampclub          抓一個站
    python -m softgoods crawl all --limit 20    全部站，每站最多 20 頁（試跑用）
    python -m softgoods report                  看資料庫現在有什麼
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import sys
from itertools import islice

from .adapters.base import default_brand_aliases
from .fetcher import Blocked, Fetcher, FetchError
from .models import SiteConfig
from .registry import PROJECT_ROOT, SCHEMA, build_adapter, load_sites
from .store import Store

DEFAULT_DB = PROJECT_ROOT / "softgoods.db"
DEFAULT_CACHE = PROJECT_ROOT / "cache_multi"
BATCH = 500


def cmd_sites(args) -> int:
    sites = load_sites(args.sites)
    print(f"{'site_id':<14}{'adapter':<10}{'delay':>6}  名稱")
    for s in sites.values():
        print(f"{s.site_id:<14}{s.adapter:<10}{s.crawl_delay_sec:>6}  {s.name}")
    print(f"\n共 {len(sites)} 個站")
    return 0


def _crawl_one(site: SiteConfig, store: Store, args, seen_date: str) -> dict:
    fetch = Fetcher(site, cache_dir=args.cache)
    adapter = build_adapter(site)

    stream = adapter.crawl(fetch)
    if args.limit:
        stream = islice(stream, args.limit)

    total = 0
    batch = []
    try:
        for rec in stream:
            batch.append(rec)
            if len(batch) >= BATCH:
                store.upsert(batch, seen_date)
                total += len(batch)
                print(f"    ...已寫入 {total} 筆", flush=True)
                batch = []
    except (Blocked, FetchError) as e:
        print(f"    中斷: {e}", flush=True)

    if batch:
        store.upsert(batch, seen_date)
        total += len(batch)

    return {"records": total, **fetch.stats}


def cmd_crawl(args) -> int:
    sites = load_sites(args.sites)
    targets = list(sites.values()) if args.site == "all" else [sites[args.site]]
    seen_date = args.date or datetime.date.today().isoformat()
    store = Store(args.db, SCHEMA, brand_aliases=default_brand_aliases())

    for site in targets:
        print(f"\n=== {site.name} ({site.site_id}) ===", flush=True)
        stats = _crawl_one(site, store, args, seen_date)
        print(
            f"  {stats['records']} 筆 | 下載 {stats['downloaded']}"
            f" / 快取 {stats['cached']} / 失敗 {stats['failed']}"
            f" / robots 擋 {stats['blocked']}",
            flush=True,
        )
        if args.mark_gone:
            n = store.mark_gone(site.site_id, seen_date)
            print(f"  標記下架 {n} 筆")

    print(f"\n資料庫: {args.db}")
    for table in ("site", "brand", "product", "variant", "listing", "price_point"):
        print(f"  {table:<12}{store.count(table):>7}")
    store.close()
    return 0


def cmd_report(args) -> int:
    store = Store(args.db, SCHEMA)
    rows = store.query(
        """SELECT brand, model, cat2, price_min, price_max, site_count
           FROM v_product_price WHERE price_min IS NOT NULL
           ORDER BY price_min DESC LIMIT ?""",
        (args.top,),
    )
    print(f"{'品牌':<18}{'型號':<22}{'子類':<10}{'最低':>9}{'最高':>9}{'通路':>5}")
    for brand, model, cat2, lo, hi, sites in rows:
        print(f"{brand or '':<18}{model or '':<22}{cat2 or '':<10}{lo:>9}{hi:>9}{sites:>5}")

    missing = store.query(
        "SELECT COUNT(*) FROM product WHERE cat2 IS NULL OR cat1 = 'unknown'"
    )[0][0]
    if missing:
        print(f"\n⚠ 有 {missing} 款商品分類對不到 —— 去 category_map.yaml 補對應")
    store.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="softgoods", description="室內軟裝多站爬蟲")
    p.add_argument("--db", type=pathlib.Path, default=DEFAULT_DB)
    p.add_argument("--cache", type=pathlib.Path, default=DEFAULT_CACHE)
    p.add_argument("--sites", type=pathlib.Path, default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sites", help="列出站台").set_defaults(func=cmd_sites)

    c = sub.add_parser("crawl", help="抓一個站或全部")
    c.add_argument("site", help="site_id，或 all")
    c.add_argument("--limit", type=int, default=None, help="最多抓幾筆（試跑用）")
    c.add_argument("--date", default=None, help="這一輪的日期，預設今天")
    c.add_argument("--mark-gone", action="store_true", help="這輪沒看到的標記下架")
    c.set_defaults(func=cmd_crawl)

    r = sub.add_parser("report", help="看資料庫內容")
    r.add_argument("--top", type=int, default=15)
    r.set_defaults(func=cmd_report)
    return p


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)
