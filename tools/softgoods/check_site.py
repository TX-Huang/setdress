"""
檢查一個網站擋不擋爬蟲
======================

跑法:
    python check_site.py https://lampclub.tw/
    python check_site.py lampclub.tw books.toscrape.com    # 可以一次好幾個

它只打 3 個請求（robots.txt + 首頁兩次），比你用瀏覽器開一次還輕。
純診斷，不抓資料。

看六件事:
    1. robots.txt 怎麼寫
    2. 誠實的爬蟲 UA 會不會被擋（很多網站只看 User-Agent 就擋）
    3. 前面有沒有 CDN / 防火牆（Cloudflare 之類）
    4. 回傳的頁面是不是「你被擋了」的頁（驗證碼、Just a moment）
    5. 資料在 HTML 裡，還是要跑 JavaScript 才出來
    6. 有沒有 sitemap（有的話等於歡迎你抓）
"""

import re
import sys
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

TIMEOUT = 15
PAUSE = 1.0  # 每個請求之間等一下

# 一個誠實的爬蟲 UA：明講自己是機器人
BOT_UA = "check-site-bot/1.0 (crawler-politeness-check)"
# 一個正常瀏覽器的 UA
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 出現這些字 = 你拿到的一定是攔截頁。正常的內容頁不會寫這些。
BLOCK_WORDS_HARD = [
    "just a moment",
    "checking your browser",
    "enable javascript and cookies",
    "access denied",
    "unusual traffic",
    "are you a robot",
    "請確認您不是機器人",
    "您的操作過於頻繁",
]

# 這些字「正常頁面也會有」，所以只在頁面幾乎沒內容的時候才算攔截。
# 真實案例：Shopify 店每一頁都有 captcha-bootstrap script 保護聯絡表單，
# 我第一版因此把潤舍（676 KB 真實內容）誤判成攔截頁。
BLOCK_WORDS_SOFT = ["captcha", "recaptcha", "hcaptcha", "turnstile"]
SOFT_NEEDS_TEXT_UNDER = 2000  # 可見文字少於這個字數，soft 才算數

# header 裡出現這些，代表前面有一層 CDN / 防火牆
WAF_HINTS = {
    "cf-ray": "Cloudflare",
    "cf-mitigated": "Cloudflare（有在過濾）",
    "x-amz-cf-id": "AWS CloudFront",
    "x-akamai-transformed": "Akamai",
    "x-sucuri-id": "Sucuri WAF",
    "x-iinfo": "Imperva / Incapsula WAF",
    "x-fastly-request-id": "Fastly",
    "x-vercel-id": "Vercel",
}

# 使用條款常見的網址。條款不像 robots.txt 有固定位置，只能一個個試。
TOS_PATHS = [
    "/terms/", "/terms", "/terms-of-service/", "/terms-and-conditions/",
    "/tos/", "/legal/terms/", "/policies/terms-of-service", "/使用條款/",
]

# 條款裡出現這些字，代表站方「用文字」禁止爬蟲。
# 這跟 robots.txt 不一樣：robots.txt 是請求，條款是合約。
TOS_RED_FLAGS = [
    "大量擷取", "大量抓取", "大量下載", "大量複製", "程式擷取", "系統性擷取",
    "爬蟲", "網路爬蟲", "自動化程式", "機器人程式", "自動擷取", "資料探勘",
    "禁止轉載", "不得重製", "不得轉載",
    "scrape", "scraping", "crawler", "crawling", "spider",
    "automated means", "automated program", "data mining", "harvest",
]


# 這些 AI 爬蟲名字出現在 robots.txt，代表站方在意「資料被拿去訓練」
AI_BOTS = [
    "GPTBot",
    "ClaudeBot",
    "anthropic-ai",
    "CCBot",
    "Google-Extended",
    "PerplexityBot",
    "Bytespider",
    "Applebot-Extended",
    "meta-externalagent",
]


# ------------------------------------------------------------ 小工具


def get(url: str, ua: str) -> requests.Response | None:
    """打一個請求。失敗回 None，不丟例外（我們要的是「結果」不是「成功」）。"""
    try:
        r = requests.get(
            url,
            headers={"User-Agent": ua, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        print(f"    連不上: {type(e).__name__}")
        return None
    finally:
        time.sleep(PAUSE)
    return r


def visible_text_len(html: str) -> int:
    """算頁面上「人看得到的字」有幾個。script/style 裡的不算。"""
    body = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    return len(re.sub(r"\s+", " ", body).strip())


# ------------------------------------------------------------ 六項檢查


def check_robots(base: str, report: list[str]) -> dict:
    """第 1 項：robots.txt 怎麼寫。"""
    print("1) robots.txt")
    r = get(f"{base}/robots.txt", BOT_UA)

    if r is None or r.status_code != 200:
        code = r.status_code if r else "連不上"
        print(f"   沒有 robots.txt（{code}）→ 沒規則，但也沒許可")
        return {"has": False, "allowed": True, "sitemap": None, "delay": None}

    text = r.text
    print(f"   有，{len(text)} 字")

    # 用 Python 內建的 parser 問：我這隻機器人可以抓首頁嗎？
    rp = RobotFileParser()
    rp.parse(text.splitlines())
    allowed = rp.can_fetch(BOT_UA, base + "/")
    print(f"   首頁可以抓嗎: {'可以' if allowed else '不行 ← 站方明講不要抓'}")
    if not allowed:
        report.append("robots.txt 明講不要抓首頁")

    # 是「擋所有機器人」還是只擋某幾隻？問一下 '*' 這個泛用名字
    if not rp.can_fetch("*", base + "/"):
        print("   ⚠ 連 'User-agent: *' 都不給抓首頁 → 全站不歡迎爬蟲")
        report.append("robots.txt 全站禁止")

    delay = _print_crawl_delay(text)
    sitemap = _print_sitemap(text)
    _print_ai_bots(text)
    _print_disallows(text)

    return {"has": True, "allowed": allowed, "sitemap": sitemap, "delay": delay}


def _print_crawl_delay(text: str) -> float | None:
    """Crawl-delay：站方指定的速度。"""
    m = re.search(r"(?im)^\s*crawl-delay:\s*([\d.]+)", text)
    if not m:
        return None
    delay = float(m.group(1))
    print(f"   Crawl-delay: {delay} 秒 ← 站方指定的速度，照這個跑")
    return delay


def _print_sitemap(text: str) -> str | None:
    sm = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", text)
    if not sm:
        print("   沒寫 Sitemap")
        return None
    print(f"   Sitemap: {sm[0]}  ← 好事，網址都列好了")
    return sm[0]


def _print_ai_bots(text: str) -> None:
    """有沒有特別點名擋 AI 爬蟲。"""
    named = [b for b in AI_BOTS if re.search(rf"(?i)user-agent:\s*{re.escape(b)}", text)]
    if named:
        print(f"   有點名擋 AI 爬蟲: {', '.join(named)}")
        print("     （代表站方在意資料被拿去訓練，但不一定擋一般爬蟲）")


def _print_disallows(text: str) -> None:
    dis = re.findall(r"(?im)^\s*disallow:\s*(\S+)", text)
    if dis:
        print(f"   不給抓的路徑（部分）: {', '.join(dict.fromkeys(dis))[:120]}")


def check_user_agent(base: str, report: list[str]) -> requests.Response | None:
    """第 2 項：換 UA 結果會不一樣嗎？這是最常見的擋法。"""
    print("\n2) User-Agent 測試（同一頁，打兩次）")

    as_bot = get(base + "/", BOT_UA)
    as_browser = get(base + "/", BROWSER_UA)

    bot_code = as_bot.status_code if as_bot else None
    br_code = as_browser.status_code if as_browser else None
    print(f"   說自己是機器人: {bot_code or '連不上'}")
    print(f"   裝成瀏覽器:     {br_code or '連不上'}")

    _judge_ua_difference(bot_code, br_code, report)

    if 429 in (bot_code, br_code):
        print("   ⚠ 429 = 你太快了，被限速")
        report.append("被限速（429）")

    # 後面幾項要用「真的有內容」的那個回應來看。
    # 有些網站（Amazon 就是）會回 200/202 但給你一個空白頁。
    got = [r for r in (as_browser, as_bot) if r is not None]
    return max(got, key=lambda r: len(r.text)) if got else None


def _judge_ua_difference(bot_code, br_code, report: list[str]) -> None:
    """兩個 UA 的狀態碼差異代表什麼。"""
    if bot_code in (403, 406, 429, 503) and br_code == 200:
        print("   → 只看 UA 就擋。站方不想要機器人，只是擋得很淺。")
        report.append(f"誠實的爬蟲 UA 被擋（{bot_code}）")
    elif br_code in (403, 429, 503):
        print(f"   → 連瀏覽器 UA 都被擋（{br_code}）。擋得很認真。")
        report.append(f"連瀏覽器 UA 都被擋（{br_code}）")
    elif bot_code == br_code == 200:
        print("   → 兩種都放行。沒在看 UA。")
    elif bot_code != br_code:
        print(f"   → 結果不一樣（{bot_code} vs {br_code}）：站方有在看 UA")
        report.append(f"兩種 UA 拿到不同結果（{bot_code} vs {br_code}）")
    elif br_code is not None and br_code != 200:
        print(f"   → 兩種都回 {br_code}，不是正常的 200")
        report.append(f"首頁回傳 {br_code}，不是 200")


def check_waf(resp: requests.Response, report: list[str]) -> None:
    """第 3 項：前面有沒有 CDN / 防火牆。"""
    print("\n3) 前面有沒有防火牆 / CDN")
    hits = [name for h, name in WAF_HINTS.items() if h in resp.headers]
    server = resp.headers.get("server", "")
    if server:
        print(f"   Server: {server}")
    if "cloudflare" in server.lower() and "Cloudflare" not in hits:
        hits.append("Cloudflare")

    if hits:
        print(f"   有: {', '.join(dict.fromkeys(hits))}")
        print("     （CDN 本身不等於擋你，但站方可以隨時一鍵開啟擋爬蟲）")
    else:
        print("   沒看到，應該是直接連到伺服器")

    # 限速相關的 header
    for h in ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining"):
        if h in resp.headers:
            print(f"   {h}: {resp.headers[h]} ← 有明講速度上限，照它的來")
            report.append("有限速 header")


def check_blocked_page(resp: requests.Response, report: list[str]) -> None:
    """第 4 項：拿到的是內容，還是「你被擋了」的頁？"""
    print("\n4) 拿到的是內容還是攔截頁")

    # 最陰的擋法：給你 200，但頁面是空的。狀態碼看起來很成功，其實什麼都沒拿到。
    size = len(resp.text.strip())
    if size < 1000:
        print(f"   ⚠ 整頁只有 {size} 個字元 — 幾乎是空的")
        print("   → 空白頁也是一種擋法。狀態碼騙你，內容才是真相。")
        report.append(f"首頁回傳幾乎空白的內容（{size} 字元）")
        return

    low = resp.text.lower()
    chars = visible_text_len(resp.text)

    hard = [w for w in BLOCK_WORDS_HARD if w in low]
    if hard:
        print(f"   ⚠ 頁面裡有: {', '.join(hard[:4])}")
        print("   → 這是攔截頁，不是真內容。HTTP 200 也可能是假的！")
        report.append(f"回傳攔截頁（{hard[0]}）")
        return

    soft = [w for w in BLOCK_WORDS_SOFT if w in low]
    if soft and chars < SOFT_NEEDS_TEXT_UNDER:
        print(f"   ⚠ 只有 {chars} 字可見文字，而且有 {soft[0]} → 應該是驗證頁")
        report.append(f"回傳攔截頁（{soft[0]}）")
        return

    if soft:
        # 正常頁面也會載 captcha script（保護聯絡/登入表單），不算被擋
        print(f"   正常內容（{chars} 字）。有 {soft[0]} script，但那是表單用的")
        return

    print(f"   看起來是正常內容（{chars} 字）")


def check_js(resp: requests.Response, report: list[str]) -> None:
    """第 5 項：資料在 HTML 裡，還是要跑 JS？"""
    print("\n5) 資料在 HTML 裡嗎")
    html = resp.text
    chars = visible_text_len(html)
    scripts = html.lower().count("<script")
    print(f"   HTML {len(html) // 1024} KB，人看得到的字 {chars} 個，{scripts} 個 <script>")

    spa = any(k in html for k in ("__NEXT_DATA__", "__NUXT__", "window.__INITIAL_STATE__"))
    if len(html.strip()) < 1000:
        print("   → 根本沒拿到頁面（被擋了），這項判斷不了")
    elif chars < 500 and len(html) > 20_000:
        print("   → 幾乎沒有文字，資料是 JS 跑出來的。requests 抓不到，要用瀏覽器自動化。")
        report.append("內容要跑 JavaScript 才出來")
    elif spa:
        print("   → 是前端框架，但資料有塞在 HTML 裡的 JSON，可以直接挖出來（比較好）")
    else:
        print("   → 資料就在 HTML 裡。requests + BeautifulSoup 就夠了。")


def _page_text(html: str) -> str:
    body = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    return re.sub(r"[ \t]+", " ", body)


def _sentence_with(text: str, word: str) -> str:
    """把含有關鍵字的那一句挖出來，讓人自己判斷。"""
    for part in re.split(r"[。\.\n！!？?；;]", text):
        if word.lower() in part.lower():
            return " ".join(part.split())[:120]
    return ""


def check_terms(base: str, report: list[str]) -> None:
    """第 7 項：使用條款。

    這是最容易漏掉、但後果最大的一項。
    robots.txt 是「請求」，條款是「合約」—— robots.txt 寫 Allow: / 不代表
    條款允許你抓。真實案例：lampclub.tw 的 robots.txt 是 Allow: /，
    還附 sitemap，但條款寫著不要用程式大量擷取。
    """
    print("\n7) 使用條款（robots.txt 放行 ≠ 條款允許）")

    for path in TOS_PATHS:
        resp = get(base + path, BROWSER_UA)
        if resp is None or resp.status_code != 200 or len(resp.text) < 500:
            continue

        text = _page_text(resp.text)
        hits = [w for w in TOS_RED_FLAGS if w.lower() in text.lower()]
        print(f"   找到條款: {base}{path}")
        if not hits:
            print("   沒看到禁止爬取的字眼（但還是建議自己讀一遍）")
            return

        print(f"   ⚠ 條款提到: {', '.join(dict.fromkeys(hits))[:60]}")
        for word in dict.fromkeys(hits):
            line = _sentence_with(text, word)
            if line:
                print(f'     「{line}」')
                break
        print("   → 條款禁止爬取。這是合約問題，不是禮貌問題。")
        report.append("使用條款禁止程式擷取")
        return

    print("   找不到條款頁。建議自己在網站上找一下再動手。")


def check_sitemap(base: str, robots: dict) -> None:
    """第 6 項：有 sitemap 就不用自己翻頁。"""
    print("\n6) sitemap")
    if robots["sitemap"]:
        print(f"   robots.txt 已經給了: {robots['sitemap']}")
        return
    r = get(f"{base}/sitemap.xml", BROWSER_UA)
    if r is not None and r.status_code == 200 and "<loc>" in r.text:
        print(f"   有 {base}/sitemap.xml（{r.text.count('<loc>')} 個網址）")
    else:
        print("   沒有。你得自己翻頁或找列表頁。")


# ------------------------------------------------------------- 總結


def verdict(base: str, report: list[str], robots: dict) -> None:
    print("\n" + "=" * 60)
    HARD_SIGNS = ("攔截頁", "全站禁止", "瀏覽器 UA 都被擋", "明講不要抓", "空白", "條款")
    hard = [r for r in report if any(s in r for s in HARD_SIGNS)]
    if hard:
        print("🔴 紅燈：這個網站在認真擋爬蟲")
        for r in report:
            print(f"   · {r}")
        print("\n   建議：先找有沒有官方 API。沒有就別硬上 —")
        print("   刻意繞過技術阻擋，性質就不只是沒禮貌了。")
    elif report:
        print("🟡 黃燈：可以抓，但它有在看")
        for r in report:
            print(f"   · {r}")
        print("\n   建議：慢慢抓、一定要做快取、UA 寫清楚。")
    else:
        print("🟢 綠燈：對爬蟲友善")
        print("   建議：還是每頁等 1～2 秒、抓過的存快取。禮貌是免費的。")

    if robots["delay"]:
        print(f"\n   ⏱ 站方指定 Crawl-delay {robots['delay']} 秒，照它的跑。")
    print("=" * 60)


def check(site: str) -> None:
    if not site.startswith("http"):
        site = "https://" + site
    base = f"{urlparse(site).scheme}://{urlparse(site).netloc}"

    print("\n" + "#" * 60)
    print(f"# {base}")
    print("#" * 60)

    report: list[str] = []
    robots = check_robots(base, report)
    resp = check_user_agent(base, report)

    if resp is None:
        print("\n首頁連不上，後面幾項沒辦法檢查")
        return

    check_waf(resp, report)
    check_blocked_page(resp, report)
    check_js(resp, report)
    check_sitemap(base, robots)
    check_terms(base, report)
    verdict(base, report, robots)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for site in sys.argv[1:]:
        check(site)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
