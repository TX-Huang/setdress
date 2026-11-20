"""抓取層的測試。

這些測試完全不碰網路：真正的網路呼叫是注入進去的，測試傳一個假的。
所以 (a) 跑得很快 (b) 沒網路也能跑 (c) 可以驗證「它到底打了幾次請求」—
而「有沒有多打請求」正是爬蟲最該測的一件事。
"""

import pytest

from softgoods.fetcher import Blocked, Fetcher, FetchError
from softgoods.models import SiteConfig

ROBOTS_OPEN = "User-agent: *\nAllow: /\n"
ROBOTS_CLOSED = "User-agent: *\nDisallow: /private/\n"


class FakeTransport:
    """假的網路層。記錄每一次呼叫，照排好的腳本回應。"""

    def __init__(self, script: dict):
        # {url: [(status, body), ...]} — 依序消耗，用完就一直回最後一個
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict, timeout: float):
        self.calls.append(url)
        queue = self.script.get(url)
        if not queue:
            return 404, ""
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def hits(self, url: str) -> int:
        return self.calls.count(url)


@pytest.fixture
def site():
    return SiteConfig(site_id="demo", name="Demo", base_url="https://demo.test", crawl_delay_sec=1.5)


@pytest.fixture
def slept():
    return []


def make(site, tmp_path, script, slept, **kw):
    return Fetcher(
        site=site,
        cache_dir=tmp_path / "cache",
        transport=FakeTransport(script),
        sleeper=slept.append,
        **kw,
    )


# ------------------------------------------------- 快取（最重要的一條）


class TestCache:
    def test_second_fetch_does_not_touch_network(self, site, tmp_path, slept):
        url = "https://demo.test/p/1"
        f = make(site, tmp_path, {
            "https://demo.test/robots.txt": [(200, ROBOTS_OPEN)],
            url: [(200, "<h1>hello</h1>")],
        }, slept)

        first = f(url)
        second = f(url)

        assert first == second == "<h1>hello</h1>"
        assert f.transport.hits(url) == 1, "第二次應該走快取，不該再打網路"
        assert f.stats["downloaded"] == 1
        assert f.stats["cached"] == 1

    def test_cache_survives_a_brand_new_fetcher(self, site, tmp_path, slept):
        """重跑程式還是要讀得到快取 —— 不然改一行 parse 就重抓一次全站。"""
        url = "https://demo.test/p/1"
        script = {
            "https://demo.test/robots.txt": [(200, ROBOTS_OPEN)],
            url: [(200, "body")],
        }
        make(site, tmp_path, script, slept)(url)

        f2 = make(site, tmp_path, script, slept)
        assert f2(url) == "body"
        assert f2.transport.hits(url) == 0

    def test_two_sites_do_not_share_cache_entries(self, tmp_path, slept):
        """不同站可能有一樣的路徑，快取不能撞在一起。"""
        a = SiteConfig(site_id="a", name="A", base_url="https://a.test")
        b = SiteConfig(site_id="b", name="B", base_url="https://b.test")
        fa = make(a, tmp_path, {
            "https://a.test/robots.txt": [(200, ROBOTS_OPEN)],
            "https://a.test/p/1": [(200, "A 的內容")],
        }, slept)
        fb = make(b, tmp_path, {
            "https://b.test/robots.txt": [(200, ROBOTS_OPEN)],
            "https://b.test/p/1": [(200, "B 的內容")],
        }, slept)

        assert fa("https://a.test/p/1") == "A 的內容"
        assert fb("https://b.test/p/1") == "B 的內容"


# ------------------------------------------------------------- robots


class TestRobots:
    def test_disallowed_url_is_refused_before_any_request(self, site, tmp_path, slept):
        f = make(site, tmp_path, {
            "https://demo.test/robots.txt": [(200, ROBOTS_CLOSED)],
            "https://demo.test/private/x": [(200, "secret")],
        }, slept)

        with pytest.raises(Blocked):
            f("https://demo.test/private/x")

        assert f.transport.hits("https://demo.test/private/x") == 0, "不該抓了才檢查"

    def test_allowed_url_still_works_on_the_same_site(self, site, tmp_path, slept):
        f = make(site, tmp_path, {
            "https://demo.test/robots.txt": [(200, ROBOTS_CLOSED)],
            "https://demo.test/public/x": [(200, "ok")],
        }, slept)
        assert f("https://demo.test/public/x") == "ok"

    def test_robots_is_fetched_only_once(self, site, tmp_path, slept):
        f = make(site, tmp_path, {
            "https://demo.test/robots.txt": [(200, ROBOTS_OPEN)],
            "https://demo.test/a": [(200, "a")],
            "https://demo.test/b": [(200, "b")],
        }, slept)
        f("https://demo.test/a")
        f("https://demo.test/b")
        assert f.transport.hits("https://demo.test/robots.txt") == 1

    def test_missing_robots_means_allowed(self, site, tmp_path, slept):
        f = make(site, tmp_path, {"https://demo.test/p": [(200, "ok")]}, slept)
        assert f("https://demo.test/p") == "ok"

    def test_can_be_turned_off_for_a_site_you_own(self, tmp_path, slept):
        s = SiteConfig(site_id="mine", name="Mine", base_url="https://demo.test", obey_robots=False)
        f = make(s, tmp_path, {
            "https://demo.test/robots.txt": [(200, ROBOTS_CLOSED)],
            "https://demo.test/private/x": [(200, "ok")],
        }, slept)
        assert f("https://demo.test/private/x") == "ok"


# -------------------------------------------------------------- 限速


class TestRateLimit:
    def test_sleeps_the_sites_own_delay_after_downloading(self, site, tmp_path, slept):
        f = make(site, tmp_path, {
            "https://demo.test/robots.txt": [(200, ROBOTS_OPEN)],
            "https://demo.test/p": [(200, "ok")],
        }, slept)
        f("https://demo.test/p")
        assert 1.5 in slept

    def test_cache_hit_does_not_sleep(self, site, tmp_path, slept):
        f = make(site, tmp_path, {
            "https://demo.test/robots.txt": [(200, ROBOTS_OPEN)],
            "https://demo.test/p": [(200, "ok")],
        }, slept)
        f("https://demo.test/p")
        slept.clear()
        f("https://demo.test/p")
        assert slept == [], "讀本地檔不用等"

    def test_each_site_uses_its_own_delay(self, tmp_path, slept):
        slow = SiteConfig(site_id="slow", name="S", base_url="https://s.test", crawl_delay_sec=5.0)
        f = make(slow, tmp_path, {
            "https://s.test/robots.txt": [(200, ROBOTS_OPEN)],
            "https://s.test/p": [(200, "ok")],
        }, slept)
        f("https://s.test/p")
        assert 5.0 in slept

    def test_robots_crawl_delay_wins_when_site_asks_for_slower(self, site, tmp_path, slept):
        """站方自己寫了 Crawl-delay 就聽它的 —— 但只在它比我們慢的時候。"""
        f = make(site, tmp_path, {
            "https://demo.test/robots.txt": [(200, "User-agent: *\nCrawl-delay: 10\n")],
            "https://demo.test/p": [(200, "ok")],
        }, slept)
        f("https://demo.test/p")
        assert 10.0 in slept


# -------------------------------------------------------------- 重試


class TestRetry:
    def test_retries_then_succeeds(self, site, tmp_path, slept):
        import requests

        url = "https://demo.test/p"
        f = make(site, tmp_path, {
            "https://demo.test/robots.txt": [(200, ROBOTS_OPEN)],
            url: [requests.ConnectionError("boom"), requests.ConnectionError("boom"), (200, "ok")],
        }, slept, max_retry=3)

        assert f(url) == "ok"
        assert f.transport.hits(url) == 3

    def test_gives_up_after_max_retry(self, site, tmp_path, slept):
        import requests

        url = "https://demo.test/p"
        f = make(site, tmp_path, {
            "https://demo.test/robots.txt": [(200, ROBOTS_OPEN)],
            url: [requests.ConnectionError("boom")],
        }, slept, max_retry=2)

        with pytest.raises(FetchError, match="失敗"):
            f(url)
        assert f.transport.hits(url) == 2
        assert f.stats["failed"] == 1

    def test_failed_download_is_not_cached(self, site, tmp_path, slept):
        """失敗不要寫進快取，否則下次重跑永遠拿到空的。"""
        import requests

        url = "https://demo.test/p"
        script = {
            "https://demo.test/robots.txt": [(200, ROBOTS_OPEN)],
            url: [requests.ConnectionError("boom")],
        }
        f = make(site, tmp_path, script, slept, max_retry=1)
        with pytest.raises(FetchError):
            f(url)

        f2 = make(site, tmp_path, {
            "https://demo.test/robots.txt": [(200, ROBOTS_OPEN)],
            url: [(200, "終於成功")],
        }, slept)
        assert f2(url) == "終於成功"

    def test_http_error_status_also_retries(self, site, tmp_path, slept):
        url = "https://demo.test/p"
        f = make(site, tmp_path, {
            "https://demo.test/robots.txt": [(200, ROBOTS_OPEN)],
            url: [(503, "down"), (200, "ok")],
        }, slept, max_retry=3)
        assert f(url) == "ok"
        assert f.transport.hits(url) == 2

    def test_404_does_not_retry(self, site, tmp_path, slept):
        """404 重試幾次都一樣，浪費別人的伺服器。"""
        url = "https://demo.test/gone"
        f = make(site, tmp_path, {
            "https://demo.test/robots.txt": [(200, ROBOTS_OPEN)],
            url: [(404, "")],
        }, slept, max_retry=3)
        with pytest.raises(FetchError):
            f(url)
        assert f.transport.hits(url) == 1
