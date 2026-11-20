"""一個指令更新全部（update.update_all）。

目標：不靠 lampclub，自己定期把所有通路更新一遍（2026-11-20 Isaac：「我們還是要自己能更新最好」）。

  - 每家店各跑各的，同時進行：Shopline 每頁要等 5 秒，一家一家跑要 13 小時
  - 每家店照自己的速度（fetcher 管），同時跑的是「不同的網站」
  - 只有一個人寫資料庫（SQLite 不適合多人同時寫）
  - 一家出錯，其他家照跑
  - 只有「完整跑完」的店才標記下架：跑到一半斷掉的，沒看到的商品不代表下架了
"""

import pathlib
import threading

import pytest

from softgoods.fetcher import FetchError
from softgoods.models import Record, SiteConfig
from softgoods.store import Store
from softgoods.update import update_all

SCHEMA = pathlib.Path(__file__).parent.parent / "schema.sql"


def rec(site_id: str, n: int) -> Record:
    return Record(
        site_id=site_id, url=f"https://{site_id}.test/p/{n}", title_raw=f"Lamp {n}",
        brand="Flos", model=f"M{n}", cat1="lighting", variant_name="Ø20 x 高 30 cm", price=1000 + n,
    )


class FakeAdapter:
    def __init__(self, site, items, *, fail_after=None, barrier=None):
        self.site, self.items, self.fail_after, self.barrier = site, items, fail_after, barrier

    def crawl(self, fetch):
        if self.barrier:
            self.barrier.wait(timeout=5)  # 兩家店要「同時」走到這裡，不然會等到逾時
        for i in range(self.items):
            if self.fail_after is not None and i == self.fail_after:
                raise FetchError("連線斷了")
            yield rec(self.site.site_id, i)


def site(sid: str) -> SiteConfig:
    return SiteConfig(site_id=sid, name=sid, base_url=f"https://{sid}.test")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db", SCHEMA)
    yield s
    s.close()


def listings(store, site_id):
    return store.query(
        "SELECT COUNT(*), SUM(gone_at IS NOT NULL) FROM listing WHERE site_id = ?", (site_id,)
    )[0]


def run(store, adapters: dict, date="2026-11-20", **kw):
    return update_all(
        [site(s) for s in adapters], store, date,
        make_fetch=lambda s: (lambda url, trim=None: ""),
        make_adapter=lambda s: adapters[s.site_id](s),
        **kw,
    )


def test_every_store_lands_in_the_database(store):
    results = run(store, {"a": lambda s: FakeAdapter(s, 3), "b": lambda s: FakeAdapter(s, 2)})
    assert [(r.site_id, r.records, r.complete) for r in results] == [("a", 3, True), ("b", 2, True)]
    assert listings(store, "a")[0] == 3
    assert listings(store, "b")[0] == 2


def test_stores_run_at_the_same_time(store):
    together = threading.Barrier(2)
    results = run(store, {
        "a": lambda s: FakeAdapter(s, 1, barrier=together),
        "b": lambda s: FakeAdapter(s, 1, barrier=together),
    })
    assert all(r.complete for r in results), [r.error for r in results]


def test_one_store_failing_does_not_stop_the_others(store):
    results = run(store, {"a": lambda s: FakeAdapter(s, 5, fail_after=2), "b": lambda s: FakeAdapter(s, 2)})
    a, b = results
    assert (a.complete, a.records) == (False, 2)
    assert "連線斷了" in a.error
    assert b.complete


def test_only_a_complete_run_marks_things_as_gone(store):
    run(store, {"a": lambda s: FakeAdapter(s, 4), "b": lambda s: FakeAdapter(s, 4)}, date="2026-11-20")
    # 第二輪：a 只剩 2 件（真的下架了 2 件）；b 跑到一半斷線
    run(store, {"a": lambda s: FakeAdapter(s, 2), "b": lambda s: FakeAdapter(s, 4, fail_after=1)},
        date="2026-11-27")
    assert listings(store, "a") == (4, 2), "完整跑完：沒看到的 2 件標記下架"
    assert listings(store, "b") == (4, 0), "斷線的那家：不能把沒看到的當成下架"


def test_a_bug_in_one_adapter_is_reported_not_raised(store):
    class Broken(FakeAdapter):
        def crawl(self, fetch):
            raise KeyError("程式寫錯了")
            yield  # pragma: no cover

    results = run(store, {"a": lambda s: Broken(s, 0), "b": lambda s: FakeAdapter(s, 1)})
    assert results[0].complete is False and "程式寫錯了" in results[0].error
    assert results[1].complete
