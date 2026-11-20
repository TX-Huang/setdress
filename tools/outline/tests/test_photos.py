"""批次用的照片下載（photos.py）：只抓一次、看 robots、同一個主機不要抓太快。

docs/outline.md「批次」第 4 到 7 句。

不連網路：transport 換成假的，記下每一次請求。
"""

import io
import itertools

import pytest
from PIL import Image

import photos

ROBOTS_OK = b"User-agent: *\nAllow: /\n"


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, "PNG")
    return buf.getvalue()


class FakeWeb:
    """假的網路：pages[url] = (狀態碼, 內容) 或 (狀態碼, 內容, 轉址的 Location)。

    沒寫的 robots.txt 回 404（等於都可以抓），沒寫的照片回一張小 PNG。
    """

    def __init__(self, pages=None, clock=None):
        self.pages = pages or {}
        self.clock = clock
        self.asked: list[str] = []
        self.times: list[tuple[str, float]] = []  # (主機, 請求的時間)

    def __call__(self, url, headers, timeout):
        self.asked.append(url)
        if self.clock:
            self.times.append((url.split("/")[2], self.clock.now))
        assert headers["User-Agent"] == photos.USER_AGENT
        if url not in self.pages:
            return (404, b"", None) if url.endswith("/robots.txt") else (200, png(), None)
        status, body, *location = self.pages[url]
        if isinstance(body, Exception):
            raise body
        return status, body, (location or [None])[0]


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


def make(tmp_path, web, clock=None):
    clock = clock or FakeClock()
    web.clock = web.clock or clock
    return photos.PhotoCache(tmp_path / "photos", transport=web, clock=clock, sleep=clock.sleep)


A = "https://img.example.com/a.jpg"
B = "https://img.example.com/b.jpg"


class TestPhotoCache:
    def test_downloads_once_then_reads_from_disk(self, tmp_path):
        web = FakeWeb()
        cache = make(tmp_path, web)
        first = cache.get(A)
        assert Image.open(first).size == (4, 4)
        again = make(tmp_path, web).get(A)  # 新的一輪（重開程式）也不會再抓
        assert again == first
        assert web.asked.count(A) == 1

    def test_robots_disallow_means_no_download(self, tmp_path):
        web = FakeWeb(
            {"https://img.example.com/robots.txt": (200, b"User-agent: *\nDisallow: /\n")}
        )
        with pytest.raises(photos.BlockedError):
            make(tmp_path, web).get(A)
        assert A not in web.asked

    def test_robots_is_read_once_per_host(self, tmp_path):
        web = FakeWeb({"https://img.example.com/robots.txt": (200, ROBOTS_OK)})
        cache = make(tmp_path, web)
        cache.get(A)
        cache.get(B)
        assert web.asked.count("https://img.example.com/robots.txt") == 1

    def test_robots_server_error_means_do_not_crawl(self, tmp_path):
        # 標準（RFC 9309）：robots.txt 回 5xx 要當成全部不讓抓
        web = FakeWeb({"https://img.example.com/robots.txt": (503, b"")})
        with pytest.raises(photos.BlockedError):
            make(tmp_path, web).get(A)

    @staticmethod
    def gaps(web, host):
        times = [t for h, t in web.times if h == host]
        return [b - a for a, b in itertools.pairwise(times)]

    def test_same_host_waits_at_least_one_second(self, tmp_path):
        # robots.txt 也是一次請求：robots、A、B 三次，每兩次之間至少 1 秒
        web = FakeWeb()
        cache = make(tmp_path, web)
        cache.get(A)
        cache.get(B)
        gaps = self.gaps(web, "img.example.com")
        assert len(gaps) == 2 and min(gaps) == pytest.approx(1.0, abs=0.001)

    def test_different_hosts_do_not_wait_for_each_other(self, tmp_path):
        web = FakeWeb()
        cache = make(tmp_path, web)
        cache.get(A)
        cache.get("https://other.example.com/c.jpg")
        last_a = [t for h, t in web.times if h == "img.example.com"][-1]
        first_other = next(t for h, t in web.times if h == "other.example.com")
        assert first_other == last_a, "換一個主機不用等"

    def test_robots_crawl_delay_is_followed(self, tmp_path):
        robots = b"User-agent: *\nCrawl-delay: 3\n"
        web = FakeWeb({"https://img.example.com/robots.txt": (200, robots)})
        cache = make(tmp_path, web)
        cache.get(A)
        cache.get(B)
        assert self.gaps(web, "img.example.com") == pytest.approx([3.0, 3.0], abs=0.001)

    def test_a_failure_is_an_error_and_is_tried_again_next_time(self, tmp_path):
        web = FakeWeb({A: (500, b"")})
        with pytest.raises(photos.DownloadError):
            make(tmp_path, web).get(A)
        web.pages[A] = (200, png())
        assert make(tmp_path, web).get(A).exists()
        assert web.asked.count(A) == 2

    def test_a_network_error_is_a_download_error(self, tmp_path):
        web = FakeWeb({A: (0, OSError("連不上"))})
        with pytest.raises(photos.DownloadError):
            make(tmp_path, web).get(A)

    def test_too_big_is_refused(self, tmp_path):
        body = png()  # 是真的圖片，只是比上限大
        web = FakeWeb({A: (200, body)})
        cache = photos.PhotoCache(
            tmp_path,
            transport=web,
            clock=FakeClock(),
            sleep=lambda s: None,
            max_bytes=len(body) - 1,
        )
        with pytest.raises(photos.DownloadError, match="太大"):
            cache.get(A)
        assert not cache.path_for(A).exists()

    def test_not_an_image_is_refused_and_not_kept(self, tmp_path):
        web = FakeWeb({A: (200, b"<html>not found</html>")})
        cache = make(tmp_path, web)
        with pytest.raises(photos.DownloadError):
            cache.get(A)
        assert not cache.path_for(A).exists()


class TestDownloadsTheSmallerShopifyPhoto:
    def test_get_asks_shopify_for_1000_px_but_caches_under_the_original_url(self, tmp_path):
        url = "https://cdn.shopify.com/s/files/lamp.jpg?v=1"
        web = FakeWeb()
        cache = make(tmp_path, web)
        path = cache.get(url)
        assert url + "&width=1000" in web.asked and url not in web.asked
        assert path == cache.path_for(url)


class TestSmallerUrl:
    def test_shopify_cdn_asks_for_1000_px(self):
        url = "https://cdn.shopify.com/s/files/1/0/files/lamp.jpg?v=123"
        assert photos.smaller_url(url) == url + "&width=1000"

    def test_shopify_store_domain_cdn_path_too(self):
        url = "https://shop.example.com/cdn/shop/files/lamp.jpg"
        assert photos.smaller_url(url) == url + "?width=1000"

    def test_an_existing_width_is_replaced(self):
        url = "https://cdn.shopify.com/s/files/lamp.jpg?width=3000&v=1"
        assert photos.smaller_url(url) == "https://cdn.shopify.com/s/files/lamp.jpg?width=1000&v=1"

    def test_other_hosts_are_left_alone(self):
        url = "https://img.shoplineapp.com/media/image_clips/abc/original.jpg?1=&owner_id=2"
        assert photos.smaller_url(url) == url


class TestCodexReview:
    """Codex 審查找到的（2026-11-21）。"""

    def test_rules_for_our_own_name_are_followed(self, tmp_path):
        # User-Agent 開頭是 Mozilla/5.0：robots 比對時要用我們自己的名字，不然只會套到 *
        robots = b"User-agent: softgoods-crawler\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
        web = FakeWeb({"https://img.example.com/robots.txt": (200, robots)})
        with pytest.raises(photos.BlockedError):
            make(tmp_path, web).get(A)

    def test_crawl_delay_for_our_own_name_is_followed(self, tmp_path):
        robots = b"User-agent: softgoods-crawler\nCrawl-delay: 4\n\nUser-agent: *\nAllow: /\n"
        web = FakeWeb({"https://img.example.com/robots.txt": (200, robots)})
        cache = make(tmp_path, web)
        cache.get(A)
        cache.get(B)
        assert TestPhotoCache.gaps(web, "img.example.com") == pytest.approx([4.0, 4.0], abs=0.001)

    def test_a_redirect_to_a_host_that_forbids_us_is_not_followed(self, tmp_path):
        moved = "https://cdn.other.com/a.jpg"
        web = FakeWeb(
            {
                A: (301, b"", moved),
                "https://cdn.other.com/robots.txt": (200, b"User-agent: *\nDisallow: /\n"),
            }
        )
        with pytest.raises(photos.BlockedError):
            make(tmp_path, web).get(A)
        assert moved not in web.asked

    def test_a_redirect_is_followed_politely_and_cached_under_the_first_url(self, tmp_path):
        moved = "https://cdn.other.com/a.jpg"
        web = FakeWeb({A: (302, b"", moved)})
        cache = make(tmp_path, web)
        path = cache.get(A)
        assert path == cache.path_for(A) and moved in web.asked
        assert "https://cdn.other.com/robots.txt" in web.asked, "轉過去的主機也要先看 robots"

    def test_a_relative_redirect_stays_on_the_same_host(self, tmp_path):
        web = FakeWeb({A: (301, b"", "/new/a.jpg")})
        make(tmp_path, web).get(A)
        assert "https://img.example.com/new/a.jpg" in web.asked

    def test_endless_redirects_give_up(self, tmp_path):
        web = FakeWeb({A: (301, b"", B), B: (301, b"", A)})
        with pytest.raises(photos.DownloadError, match="轉址"):
            make(tmp_path, web).get(A)

    def test_http_and_https_have_their_own_robots(self, tmp_path):
        web = FakeWeb({"http://img.example.com/robots.txt": (200, b"User-agent: *\nDisallow: /\n")})
        cache = make(tmp_path, web)
        cache.get(A)  # https：沒有 robots，可以
        with pytest.raises(photos.BlockedError):
            cache.get("http://img.example.com/b.jpg")

    def test_the_same_host_in_capitals_still_waits(self, tmp_path):
        web = FakeWeb()
        cache = make(tmp_path, web)
        cache.get(A)
        cache.get("https://IMG.example.com/b.jpg")
        times = [t for _, t in web.times]
        assert all(b - a >= 1.0 - 1e-9 for a, b in itertools.pairwise(times)), (
            "大小寫不同還是同一個主機"
        )

    def test_a_broken_url_is_a_download_error_not_a_crash(self, tmp_path):
        with pytest.raises(photos.DownloadError):
            make(tmp_path, FakeWeb()).get("https://[broken/a.jpg")
