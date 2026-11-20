"""批次自動描用的照片下載：只抓一次、看 robots、同一個主機不要抓太快。

照片是店家的，只存在本機（tools/outline/out/photos/，.gitignore 擋著），不進 repo、不上網站。
資料庫只存連結（softgoods 的政策）；要描輪廓才需要照片本身，所以在這裡下載。

規則（docs/outline.md「批次」第 4 到 7 句）：
- 同一個網址只下載一次（檔名是網址的 SHA-1），再跑一次直接讀檔
- 每個主機先讀 robots.txt：不讓抓就不抓。robots.txt 回 4xx 等於沒有限制；5xx 或連不上，
  照標準（RFC 9309）當成全部不讓抓。http 和 https 各讀各的
- robots 用我們自己的名字（softgoods-crawler）比對：User-Agent 開頭的 Mozilla/5.0 不算（Codex 審查）
- 同一個主機（不分大小寫）兩次請求至少隔 1 秒；robots 寫了 Crawl-delay 就照它
- 轉址不自動跟：每一跳都先看那個主機的 robots、照它的間隔（Codex 審查），最多 3 跳
- 失敗、太大、不是圖片、網址壞掉：丟 DownloadError，不存檔，下次會再試
"""

from __future__ import annotations

import hashlib
import io
import pathlib
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import SplitResult, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from PIL import Image

# 跟爬蟲（tools/softgoods 的 DEFAULT_UA）同一個名字，店家看得出是同一隻
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) softgoods-crawler/1.0 (+polite: 1 req/1.5s, cached)"
)
ROBOTS_NAME = "softgoods-crawler"  # robots.txt 的 User-agent 比對用這個
MIN_DELAY = 1.0  # 同一個主機兩次請求至少隔幾秒
MAX_BYTES = 20 * 1024 * 1024
MAX_HOPS = 3
TIMEOUT = 30.0
SHOPIFY_WIDTH = "1000"  # 描輪廓只用到 600 px，跟 Shopify 要小一點的版本
REDIRECTS = (301, 302, 303, 307, 308)

# (網址, 標頭, 逾時) → (狀態碼, 內容, 轉址的 Location 或 None)。不可以自己跟轉址
Transport = Callable[[str, dict, float], tuple[int, bytes, str | None]]


class BlockedError(Exception):
    """robots.txt 不讓抓。"""


class DownloadError(Exception):
    """下載失敗、太大、不是圖片、或網址壞掉。下次會再試。"""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # 不自動跟：3xx 會變成 HTTPError，交給 PhotoCache 一跳一跳看 robots


_OPENER = urllib.request.build_opener(_NoRedirect)


def _urllib_transport(url: str, headers: dict, timeout: float) -> tuple[int, bytes, str | None]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(MAX_BYTES + 1), None
    except urllib.error.HTTPError as e:
        return e.code, b"", e.headers.get("Location")


def _split(url: str) -> SplitResult:
    try:
        parts = urlsplit(url)
        _ = parts.port  # 讀一次才會檢查埠號；壞掉的埠號在這裡丟 ValueError
    except ValueError as e:
        raise DownloadError(f"網址壞掉：{url[:80]}") from e
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise DownloadError(f"網址壞掉：{url[:80]}")
    return parts


def smaller_url(url: str) -> str:
    """Shopify 的照片網址加上 width=1000（cdn.shopify.com，或店家網域底下的 /cdn/shop/）。"""
    parts = _split(url)
    if parts.netloc != "cdn.shopify.com" and not parts.path.startswith("/cdn/shop/"):
        return url
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["width"] = SHOPIFY_WIDTH  # 本來就有 width 的留在原位、換掉值；沒有的加在最後
    return urlunsplit(parts._replace(query=urlencode(query)))


class PhotoCache:
    def __init__(
        self,
        folder: pathlib.Path | str,
        *,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        min_delay: float = MIN_DELAY,
        max_bytes: int = MAX_BYTES,
    ):
        self.folder = pathlib.Path(folder)
        self.transport = transport or _urllib_transport
        self.clock, self.sleep = clock, sleep
        self.min_delay, self.max_bytes = min_delay, max_bytes
        # (scheme, 主機) → robots；None = 全部不讓抓
        self._robots: dict[tuple[str, str], RobotFileParser | None] = {}
        self._last: dict[str, float] = {}  # 主機 → 上次請求的時間

    def path_for(self, url: str) -> pathlib.Path:
        return self.folder / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".img")

    def get(self, url: str) -> pathlib.Path:
        """照片在本機的位置；沒有的話先下載。robots 不讓抓丟 BlockedError，失敗丟 DownloadError。"""
        path = self.path_for(url)
        if path.exists():
            return path
        body = self._follow(smaller_url(url))
        _check_image(body)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def _follow(self, url: str) -> bytes:
        """一跳一跳下載：每一跳都先看那個主機的 robots。"""
        for _ in range(MAX_HOPS + 1):
            parts = _split(url)
            if not self._allowed(parts, url):
                raise BlockedError(f"robots.txt 不讓抓 {parts.hostname}")
            status, body, location = self._request(parts, url)
            if status not in REDIRECTS or not location:
                return self._accept(status, body)
            url = urljoin(url, location)
        raise DownloadError(f"轉址超過 {MAX_HOPS} 次")

    def _accept(self, status: int, body: bytes) -> bytes:
        if status != 200:
            raise DownloadError(f"HTTP {status}")
        if len(body) > self.max_bytes:
            raise DownloadError(f"太大（超過 {self.max_bytes // (1024 * 1024)} MB）")
        return body

    # ---------------------------------------------------------------- 主機
    def _request(self, parts: SplitResult, url: str) -> tuple[int, bytes, str | None]:
        """同一個主機至少隔 min_delay 秒（robots 的 Crawl-delay 比較長就照它）。"""
        host = parts.hostname
        wait = self._last.get(host, -1e9) + self._delay(parts) - self.clock()
        if wait > 0:
            self.sleep(wait)
        try:
            return self.transport(url, {"User-Agent": USER_AGENT}, TIMEOUT)
        except OSError as e:
            raise DownloadError(f"連不上：{e}") from e
        finally:
            self._last[host] = self.clock()

    def _delay(self, parts: SplitResult) -> float:
        robots = self._robots.get((parts.scheme, parts.hostname))
        asked = robots.crawl_delay(ROBOTS_NAME) if robots else None
        return max(self.min_delay, float(asked or 0))

    def _allowed(self, parts: SplitResult, url: str) -> bool:
        key = (parts.scheme, parts.hostname)  # hostname 已經是小寫
        if key not in self._robots:
            self._robots[key] = self._read_robots(parts)
        robots = self._robots[key]
        return robots is not None and robots.can_fetch(ROBOTS_NAME, url)

    def _read_robots(self, parts: SplitResult) -> RobotFileParser | None:
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            status, body, _ = self._request(parts, robots_url)
        except DownloadError:
            return None
        if status >= 500 or status == 0:
            return None
        parser = RobotFileParser(robots_url)
        parser.parse(body.decode("utf-8", "replace").splitlines() if status < 400 else [])
        parser.modified()  # 不設的話 can_fetch() 會當成還沒讀過、一律說不行
        return parser


def _check_image(body: bytes) -> None:
    try:
        with Image.open(io.BytesIO(body)) as img:
            img.verify()
    except Exception as e:  # Pillow 對壞檔丟的例外種類很多，全部都是「不是圖片」
        raise DownloadError(f"不是圖片：{e}") from e
