"""一個指令更新全部通路。

目標：不靠 lampclub，自己定期更新（2026-11-20）。

  - 每家店一個工人，同時跑。每家照自己的速度（fetcher 讀 robots.txt 的 Crawl-delay）；
    同時跑的是「不同的網站」，對每一家來說跟一家一家跑一樣禮貌。
    Shopline 每頁 5 秒，一家一家跑要 13 小時，同時跑看最大那家（約 5.5 小時）。
  - 只有一個人寫資料庫（主執行緒）：SQLite 不適合多人同時寫。
  - 一家出錯，其他家照跑，最後回報。
  - 只有「完整跑完」的店才標記下架：跑到一半斷掉的，沒看到的商品不代表下架。
"""

from __future__ import annotations

import queue
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from itertools import islice

from .fetcher import Blocked, FetchError
from .models import Record, SiteConfig
from .policy import facts_only
from .store import Store

BATCH = 500


@dataclass
class SiteResult:
    site_id: str
    records: int = 0
    complete: bool = False  # 有沒有完整跑完（斷掉的不標記下架）
    error: str | None = None
    gone: int = 0
    stats: dict = field(default_factory=dict)


def crawl_records(site: SiteConfig, adapter, fetch, limit: int | None = None) -> Iterator[Record]:
    """一筆一筆給出這個站的資料，已經套用「只存事實」（policy.py）。"""
    stream = (facts_only(rec, site) for rec in adapter.crawl(fetch))
    return islice(stream, limit) if limit else stream


def _stream(site, adapter, fetch, limit, out: queue.Queue, stop: threading.Event) -> None:
    """一筆一筆抓，一批一批交出去。斷掉的時候，手上那批也要交出去。"""
    batch: list[Record] = []
    try:
        for rec in crawl_records(site, adapter, fetch, limit):
            if stop.is_set():
                return
            batch.append(rec)
            if len(batch) >= BATCH:
                out.put(("records", site.site_id, batch))
                batch = []
    finally:
        if batch:
            out.put(("records", site.site_id, batch))


def _completeness(adapter, limit: int | None, stop: threading.Event) -> tuple[bool, str | None]:
    """跑完了，但算不算「完整」？不完整的不標記下架。"""
    if stop.is_set():
        return False, "中途停止"
    if limit is not None:
        return False, None  # 試跑（--limit）
    skipped = getattr(adapter, "skipped", 0)  # Shopline：有幾頁抓不到或讀不懂
    if skipped:
        return False, f"{skipped} 頁沒讀到（這輪沒看到的商品不標記下架）"
    return True, None


def _work(site: SiteConfig, make_fetch, make_adapter, out: queue.Queue, limit, stop) -> None:
    """一家店的工人：抓、整理，一批一批交給寫資料庫的人。不碰資料庫。"""
    fetch = make_fetch(site)
    result = SiteResult(site.site_id)
    try:
        adapter = make_adapter(site)
        _stream(site, adapter, fetch, limit, out, stop)
        result.complete, result.error = _completeness(adapter, limit, stop)
    except (Blocked, FetchError) as e:
        result.error = str(e)
    except Exception as e:  # noqa: BLE001 —— 一家店的程式出錯，不能讓其他店跟著停；錯誤會回報
        result.error = f"{type(e).__name__}: {e}"
    result.stats = dict(getattr(fetch, "stats", {}))
    out.put(("done", site.site_id, result))


def update_all(
    sites: list[SiteConfig],
    store: Store,
    seen_date: str,
    *,
    make_fetch: Callable,
    make_adapter: Callable,
    mark_gone: bool = True,
    limit: int | None = None,
    progress: Callable[[str], None] = lambda msg: None,
) -> list[SiteResult]:
    """所有店同時抓，主執行緒一個人寫資料庫。回傳每家店的結果（跟 sites 同順序）。

    寫資料庫出錯時：叫工人停下來再往外丟。佇列不設上限，工人不會卡在交貨那一步。
    """
    out: queue.Queue = queue.Queue()
    stop = threading.Event()
    with ThreadPoolExecutor(max_workers=max(1, len(sites))) as pool:
        for site in sites:
            pool.submit(_work, site, make_fetch, make_adapter, out, limit, stop)
        try:
            results = _consume(len(sites), store, seen_date, out, mark_gone, progress)
        except BaseException:
            stop.set()
            raise
    return [results[s.site_id] for s in sites]


def _consume(expected: int, store, seen_date, out: queue.Queue, mark_gone, progress) -> dict:
    """寫資料庫的人：收到一批寫一批，收到「跑完了」就收尾。"""
    counts: Counter = Counter()
    results: dict[str, SiteResult] = {}
    while len(results) < expected:
        kind, site_id, payload = out.get()
        if kind == "records":
            store.upsert(payload, seen_date)
            counts[site_id] += len(payload)
            progress(f"{site_id}: 已寫入 {counts[site_id]} 筆")
        else:
            results[site_id] = _finish(store, payload, counts[site_id], seen_date, mark_gone)
            progress(f"{site_id}: {'完成' if payload.complete else '沒跑完'}（{payload.records} 筆）")
    return results


def _finish(store: Store, result: SiteResult, records: int, seen_date: str, mark_gone: bool) -> SiteResult:
    """一家店跑完：記下筆數；完整跑完才標記下架。"""
    result.records = records
    if result.complete and mark_gone:
        result.gone = store.mark_gone(result.site_id, seen_date)
    return result
