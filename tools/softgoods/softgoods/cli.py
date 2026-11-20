"""命令列入口。

    python -m softgoods sites                   列出站台
    python -m softgoods crawl lampclub          抓一個站
    python -m softgoods crawl all --limit 20    全部站，每站最多 20 筆（試跑用）
    python -m softgoods crawl all --mark-gone   更新全部：各店同時跑，跑完的店標記下架
    python -m softgoods report                  看資料庫現在有什麼
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import sys
import time

from .adapters.base import default_brand_aliases
from .fetcher import Fetcher
from .models import SiteConfig
from .registry import PROJECT_ROOT, SCHEMA, build_adapter, load_sites
from .store import Store
from .update import crawl_records, update_all  # noqa: F401 —— crawl_records 舊的匯入路徑還有人用

DEFAULT_DB = PROJECT_ROOT / "softgoods.db"
DEFAULT_CACHE = PROJECT_ROOT / "cache_multi"


def cmd_sites(args) -> int:
    sites = load_sites(args.sites)
    print(f"{'site_id':<14}{'adapter':<10}{'delay':>6}  名稱")
    for s in sites.values():
        print(f"{s.site_id:<14}{s.adapter:<10}{s.crawl_delay_sec:>6}  {s.name}")
    print(f"\n共 {len(sites)} 個站")
    return 0


def pick_sites(sites: dict[str, SiteConfig], names: list[str]) -> list[SiteConfig]:
    """「all」是全部通路，不含只拿來對照的站（lampclub）；不然照名字挑。"""
    if names == ["all"]:
        return [s for s in sites.values() if not s.baseline]
    return [sites[n] for n in dict.fromkeys(names)]  # 同一家只跑一個工人，不然會超過它的速度限制


def cmd_crawl(args) -> int:
    """抓幾家或全部（all）。各店同時跑，各照各的速度（update.py）。"""
    sites = load_sites(args.sites)
    targets = pick_sites(sites, args.site)
    seen_date = args.date or datetime.date.today().isoformat()
    store = Store(args.db, SCHEMA, brand_aliases=default_brand_aliases())
    # --fresh：這次開始之前存的快取不算數（定期更新要拿到新價格）；這次跑的時候存的照樣用
    fresh_since = time.time() if args.fresh else None

    results = update_all(
        targets, store, seen_date,
        make_fetch=lambda site: Fetcher(site, cache_dir=args.cache, fresh_since=fresh_since),
        make_adapter=build_adapter,
        mark_gone=args.mark_gone,
        limit=args.limit,
        progress=lambda msg: print(f"    {msg}", flush=True),
    )
    for r in results:
        _print_result(sites[r.site_id].name, r)
    _print_counts(store, args.db)
    store.close()
    return 0 if all(r.complete or args.limit for r in results) else 1


def _print_result(name: str, r) -> None:
    s = r.stats
    print()
    print(f"=== {name} ({r.site_id}) ===")
    print(
        f"  {r.records} 筆 | 下載 {s.get('downloaded', 0)} / 快取 {s.get('cached', 0)}"
        f" / 失敗 {s.get('failed', 0)} / robots 擋 {s.get('blocked', 0)}",
        flush=True,
    )
    if r.error:
        print(f"  沒跑完：{r.error}")
    if r.gone:
        print(f"  標記下架 {r.gone} 筆")


def _print_counts(store: Store, db) -> None:
    print()
    print(f"資料庫: {db}")
    for table in ("site", "brand", "product", "variant", "listing", "price_point"):
        print(f"  {table:<12}{store.count(table):>7}")


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
    c.add_argument("site", nargs="+", help="一個或幾個 site_id，或 all（不含 lampclub）")
    c.add_argument("--limit", type=int, default=None, help="最多抓幾筆（試跑用）")
    c.add_argument("--date", default=None, help="這一輪的日期，預設今天")
    c.add_argument("--mark-gone", action="store_true", help="這輪沒看到的標記下架（只有完整跑完的店）")
    c.add_argument("--fresh", action="store_true", help="不用以前的快取，重新抓（定期更新用）")
    c.set_defaults(func=cmd_crawl)

    r = sub.add_parser("report", help="看資料庫內容")
    r.add_argument("--top", type=int, default=15)
    r.set_defaults(func=cmd_report)
    return p


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)
