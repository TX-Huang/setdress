"""check_site.py 第 7 項（使用條款）的測試。

這三種誤判是人工看條款時抓到的（CHANNELS.md「人工看條款」，2026-11-20）。
網路層用假的：check_terms 收一個 fetch 參數。
"""

from types import SimpleNamespace

import check_site

BASE = "https://shop.test"
LONG = "這是一段夠長的條款內容，講退換貨和隱私。" * 40  # 條款頁要夠長才算數（> 500 字元）


def page(text: str, url: str, redirected: bool = False):
    return SimpleNamespace(
        status_code=200,
        text=f"<html><body>{LONG}{text}</body></html>",
        url=url,
        history=[SimpleNamespace(status_code=301)] if redirected else [],
    )


def run(pages: dict):
    asked: list[str] = []

    def fake_get(url, ua):
        asked.append(url)
        return pages.get(url)

    report: list[str] = []
    check_site.check_terms(BASE, report, fetch=fake_get)
    return report, asked


def test_a_brand_called_harvest_is_not_a_ban():
    # FUNHOUSE：選單裡的品牌「Harvest Grace」被當成條款禁止 harvest
    report, _ = run({f"{BASE}/terms/": page("品牌：Harvest Grace", f"{BASE}/terms/")})
    assert report == []


def test_a_chinese_ban_is_still_caught():
    report, _ = run({f"{BASE}/terms/": page("請勿以程式大量擷取本站資料。", f"{BASE}/terms/")})
    assert report == ["使用條款禁止程式擷取"]


def test_an_english_ban_is_still_caught():
    text = "You may not use any automated means to scrape this site."
    report, _ = run({f"{BASE}/terms/": page(text, f"{BASE}/terms/")})
    assert report == ["使用條款禁止程式擷取"]


def test_a_redirect_to_the_home_page_is_not_a_terms_page(capsys):
    # FUNHOUSE：/terms/ 其實轉回首頁。首頁剛好有一篇講「爬蟲」的文章，也不能算條款禁止
    home = page("部落格：網路爬蟲是什麼？", f"{BASE}/", redirected=True)
    report, _ = run({f"{BASE}/terms/": home})
    out = capsys.readouterr().out
    assert report == []
    assert "找到條款" not in out
    assert "找不到條款頁" in out


def test_a_redirect_to_another_terms_page_still_counts(capsys):
    moved = page("一般條款。", f"{BASE}/pages/terms-of-service", redirected=True)
    run({f"{BASE}/terms/": moved})
    assert "找到條款" in capsys.readouterr().out


def test_tries_the_shopline_and_php_terms_paths():
    _, asked = run({})
    assert f"{BASE}/about/terms" in asked
    assert f"{BASE}/terms.php" in asked
