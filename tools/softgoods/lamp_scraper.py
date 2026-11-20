"""
lampclub.tw 爬蟲練習（已被 softgoods/ 取代，留著當參考）
=========================================================

⚠ 不要在這支上面開發。它是最早的單站練習腳本，功能已經全部移進
  softgoods/ 這個多站框架（有測試、有正規化、會寫資料庫）。
  留著的理由：它產生了 cache/ 裡那 2143 個 HTML，而且讀起來比框架簡單，
  適合當「爬蟲最小可行版本」的教材。

  它的 parse_lamp 複雜度 C (15)，沒有拆 —— 刻意不整理，因為整理它
  等於維護兩份做同一件事的程式。要刪掉它請問 Isaac。

⚠ 陷阱（我自己踩過）：這支每次跑完都會「整個覆蓋」out/*.csv。
  所以 `python lamp_scraper.py 5` 會把完整的 2142 列 CSV 蓋成 5 列。
  想試跑請先備份 out/，或直接用 `python lamp_scraper.py all`（走快取、零下載）。

正式的用法看 README.md：
    python -m softgoods crawl lampclub

抓「燈迷俱樂部」的燈具資料，存成 CSV。

跑法:
    python lamp_scraper.py          # 抓 15 頁（預設）
    python lamp_scraper.py 30       # 抓 30 頁

重要: 抓下來的 HTML 會存在 cache/ 資料夾。
      第二次跑會直接讀 cache，不會再連網站。
      所以你改 parse 的程式碼可以改一百次，網站只被抓一次。
"""

import csv
import pathlib
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------- 設定

BASE = "https://lampclub.tw"
HERE = pathlib.Path(__file__).parent
CACHE = HERE / "cache"  # 抓回來的原始 HTML 放這
OUT = HERE / "out"  # CSV 放這

DELAY = 1.5  # 每抓一頁等幾秒。不要改小。
TIMEOUT = 20
MAX_RETRY = 3  # 一頁失敗重試幾次（抓幾千頁一定會遇到幾次連線失敗）

HEADERS = {
    # 說清楚自己是誰、速度很慢，是爬蟲的基本禮貌
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) lamp-scraper-practice/1.0",
    "Accept-Language": "zh-TW,zh;q=0.9",
}


# ---------------------------------------------- 第 1 步：下載（含快取）


def download(url: str) -> str:
    """真的去連網站。失敗就等久一點再試，最多 MAX_RETRY 次。"""
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except requests.RequestException as e:
            last_error = e
            wait = DELAY * attempt * 2  # 每次失敗等更久（退讓）
            print(f"    (第 {attempt}/{MAX_RETRY} 次失敗: {e}；等 {wait:.0f} 秒)")
            time.sleep(wait)
    raise RuntimeError(f"試 {MAX_RETRY} 次都失敗: {url}") from last_error


def cache_path(url: str) -> pathlib.Path:
    """網址 -> 本地檔名。https://lampclub.tw/lamps/flos-bellhop/ -> lamps_flos-bellhop.html"""
    key = re.sub(r"[^a-zA-Z0-9._-]+", "_", url.replace(BASE, "").strip("/"))
    return CACHE / f"{key or 'index'}.html"


def fetch(url: str) -> str:
    """抓一個網址的 HTML。抓過的就讀本地檔，不重抓。"""
    CACHE.mkdir(exist_ok=True)
    path = cache_path(url)

    if path.exists():
        print(f"  [快取] {url}", flush=True)
        return path.read_text(encoding="utf-8")

    print(f"  [下載] {url}", flush=True)
    html = download(url)
    path.write_text(html, encoding="utf-8")

    time.sleep(DELAY)  # 禮貌：下載後才等，讀快取不用等
    return html


def lamp_urls() -> list[str]:
    """從 sitemap 拿出所有燈具頁的網址。"""
    xml = fetch(f"{BASE}/sitemap.xml")
    locs = re.findall(r"<loc>(.*?)</loc>", xml)
    # 只要 /lamps/<名字>/ 這種，不要 /lamps/ 列表頁本身
    return [u for u in locs if re.fullmatch(rf"{BASE}/lamps/[^/]+/", u)]


# ------------------------------------------------------- 第 2 步：解析


def txt(node) -> str:
    """把一個 HTML 標籤裡的文字挖出來，前後空白清掉。"""
    return node.get_text(" ", strip=True) if node else ""


def money(s: str) -> list[int]:
    """'NT$7,600 起，最高 NT$35,900' -> [7600, 35900]"""
    return [int(m.replace(",", "")) for m in re.findall(r"NT\$([\d,]+)", s)]


def parse_lamp(html: str, url: str) -> tuple[dict, list[dict]]:
    """一張燈具頁 -> (這盞燈的資料, 這盞燈在各通路的售價清單)"""
    soup = BeautifulSoup(html, "lxml")

    # 型號：<h1>Bellhop</h1>
    model = txt(soup.select_one("h1"))

    # 麵包屑第二個連結是品牌：找燈 › Flos › Bellhop
    crumb_links = soup.select("div.crumb a")
    brand = txt(crumb_links[1]) if len(crumb_links) > 1 else ""

    # 價格：<div class="price">NT$7,600<small> 起，最高 NT$35,900</small></div>
    prices = money(txt(soup.select_one("div.price")))
    price_min = prices[0] if prices else None
    price_max = prices[-1] if prices else None

    # 規格表：<dl class="facts"><dt>設計師</dt><dd>...</dd>...</dl>
    facts = {}
    for dt in soup.select("dl.facts dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            # dd 裡面可能夾一顆 <span class="tag">原廠官網</span> 的小標籤，拔掉
            for tag in dd.select("span.tag"):
                tag.extract()
        facts[txt(dt)] = txt(dd)

    # 主圖
    img = soup.select_one("section.mhead img")
    image = img.get("src", "") if img else ""

    # 「哪裡買」表格：一列一個通路的一個規格
    listings = []
    for tr in soup.select("table.ls tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue

        # 商品欄裡面有個 <span class="sub"> 裝規格，先切出來再拿名稱
        item_cell = tds[1]
        sub = item_cell.select_one("span.sub")
        spec = txt(sub)
        if sub:
            sub.extract()  # 拔掉，剩下的才是純商品名

        go = tr.select_one("td.go a")
        listings.append(
            {
                "品牌": brand,
                "型號": model,
                "通路": txt(tds[0].select_one("b")) or txt(tds[0]),
                "商品名": txt(item_cell),
                "規格": spec,
                "價格": (money(txt(tr.select_one("td.pr"))) or [None])[0],
                "供貨": txt(tds[3]),
                "通路連結": go.get("href", "") if go else "",
            }
        )

    lamp = {
        "品牌": brand,
        "型號": model,
        "設計師": facts.get("設計師", ""),
        "設計年份": facts.get("設計年份", ""),
        "類型": facts.get("類型", ""),
        "電壓": facts.get("電壓（通路標示）", ""),
        "最低價": price_min,
        "最高價": price_max,
        "通路數": len({x["通路"] for x in listings}),
        "規格數": len(listings),
        "圖片": image,
        "網址": url,
    }
    return lamp, listings


# ----------------------------------------------------- 第 3 步：存 CSV


def save_csv(rows: list[dict], path: pathlib.Path) -> None:
    """存成 CSV。utf-8-sig 是為了 Excel 打開不會變亂碼。"""
    if not rows:
        print(f"沒資料，跳過 {path.name}")
        return
    OUT.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"寫好 {path}  ({len(rows)} 列)")


# ------------------------------------------------------------- 主程式


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "15"

    print("讀 sitemap...", flush=True)
    urls = lamp_urls()
    limit = len(urls) if arg == "all" else min(int(arg), len(urls))
    print(f"sitemap 裡有 {len(urls)} 盞燈，這次抓 {limit} 盞", flush=True)

    todo = urls[:limit]
    new = sum(1 for u in todo if not cache_path(u).exists())
    print(f"其中 {new} 盞還沒抓過，預估要 {new * DELAY / 60:.0f} 分鐘\n", flush=True)

    started = time.time()
    lamps, listings, failed = [], [], []

    for i, url in enumerate(todo, 1):
        if i % 50 == 0 or i == limit:
            done = time.time() - started
            print(f"  --- 進度 {i}/{limit}，已跑 {done / 60:.1f} 分 ---", flush=True)
        print(f"[{i}/{limit}]", end=" ", flush=True)
        try:
            lamp, rows = parse_lamp(fetch(url), url)
        # 故意吞掉所有錯誤（BLE001 關掉）：第 7 頁的 HTML 壞掉不該
        # 害剩下 2000 頁都沒抓到，而且重跑會走快取、不會再打網站一次。
        except Exception as e:  # noqa: BLE001
            print(f"  !! 失敗: {e}", flush=True)
            failed.append(url)
            continue
        lamps.append(lamp)
        listings.extend(rows)

    print(f"\n跑完，共 {(time.time() - started) / 60:.1f} 分鐘")
    save_csv(lamps, OUT / "lamps.csv")
    save_csv(listings, OUT / "listings.csv")

    if failed:
        (OUT / "failed.txt").write_text("\n".join(failed), encoding="utf-8")
        print(f"有 {len(failed)} 頁失敗，網址記在 out/failed.txt（再跑一次就會補抓）")
    else:
        print("沒有失敗的頁")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 印中文不要爆掉
    main()
