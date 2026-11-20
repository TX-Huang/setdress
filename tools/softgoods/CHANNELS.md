# 26 家通路清單

從 lampclub 的 5645 筆上架資料反推出來的。**平台欄是推論，不是確認過的** ——
依據是商品圖片放在哪個 CDN：Shopify 店的圖在 cdn.shopify.com、
Shopline 店的圖在 img.shoplineapp.com。零新請求推出來的。

只有「潤舍」是我實際打過 /products.json 確認的。

| 通路 | 上架數 | 網域 | 平台（推論） | 依據 |
|---|---:|---|---|---|
| Loft29 | 1053 | `www.loft29.com.tw` | ? | 圖片自架在 www.loft29.com.tw |
| 潤舍 | 595 | `www.luxurylife.com.tw` | Shopify ✓已確認 | 圖片在 cdn.shopify.com |
| 瑪黑 | 542 | `www.storemarais.com` | ? | 圖片自架在 www.storemarais-image.com |
| 新采 | 445 | `www.mithus.co` | Shopline | 圖片在 img.shoplineapp.com |
| NOSA | 437 | `www.nosa.tw` | Shopify | 圖片在 cdn.shopify.com |
| 散步舖 | 415 | `www.classicandchairs.com` | Shopline | 圖片在 img.shoplineapp.com |
| viithe | 289 | `viithe.com` | ? | 圖片自架在 viithe.com |
| 北歐先生 | 284 | `www.mrnordic.com.tw` | Shopify | 圖片在 cdn.shopify.com |
| 居雅堂 | 249 | `www.jytdesign.com.tw` | Shopify | 圖片在 cdn.shopify.com |
| TH Company | 211 | `shop.thcompany.tw` | Shopify | 圖片在 cdn.shopify.com |
| Design Butik | 185 | `www.designbutik.com.tw` | Shopline | 圖片在 img.shoplineapp.com |
| WOW | 168 | `www.wowfactor.com.tw` | Shopline | 圖片在 img.shoplineapp.com |
| Motive | 167 | `www.motiveshowroom.com` | Shopline | 圖片在 img.shoplineapp.com |
| 北歐櫥窗 | 153 | `www.nordic.com.tw` | ? | 圖片自架在 www.nordic.com.tw |
| 喜的 | 120 | `shop.seeddesign.tw` | Shopline | 圖片在 img.shoplineapp.com |
| FUNHOUSE | 64 | `www.funhouse.biz` | Shopline | 圖片在 img.shoplineapp.com |
| 睦叁 | 60 | `www.moodsans.tw` | Shopline | 圖片在 img.shoplineapp.com |
| MOTTO | 49 | `motto-furniture.com` | ? | 圖片自架在 motto-furniture.com |
| 柒木 | 33 | `www.kimushoptw.com` | Shopline | 圖片在 img.shoplineapp.com |
| moonmist | 25 | `moonmist.tw` | Shopify | 圖片在 cdn.shopify.com |
| Sheeper | 25 | `www.sheeper.com.tw` | Shopify | 圖片在 cdn.shopify.com |
| 一嶼 | 23 | `www.is-land.tw` | Shopline | 圖片在 img.shoplineapp.com |
| HAY TAIPEI | 17 | `www.hay-taiwan.com` | Shopline | 圖片在 img.shoplineapp.com |
| Objects Ark | 14 | `www.objectsark.com` | Shopline | 圖片在 img.shoplineapp.com |
| OSTI | 11 | `www.osti-living.com` | ? | 圖片自架在 www.osti-living.com |
| 黑色雋永 | 11 | `lumamiling.com` | ? | 圖片自架在 lumamiling.com |

共 26 家、5645 筆上架。

## 平台分佈

- **Shopline**：12 家
- **?**：7 家
- **Shopify**：7 家

## 怎麼用

Shopify 和 Shopline 兩家平台都有公開的商品 JSON，所以那 19 家
理論上都不用寫 HTML parser：

- Shopify：`/products.json?limit=250&page=N`
- Shopline：開 F12 看 Network 的 XHR，它自己打的 API

**但每一家都要先跑 `python check_site.py <網域>`**，特別是第 7 項的
使用條款檢查。技術上開放不等於條款允許 —— lampclub 就是這樣：
robots.txt 寫 Allow: /、還附 sitemap，但條款禁止程式大量擷取。

## check_site.py 檢查結果（2026-11-20，每家只打幾個請求，沒抓商品）

| 結果 | 通路（上架數） | 合計 |
|---|---|---:|
| 🟢 條款找到了、沒禁止 | 潤舍 595、新采 445、NOSA 437、散步舖 415、居雅堂 249、Design Butik 185、WOW 168、Motive 167、柒木 33、Sheeper 25、一嶼 23、HAY TAIPEI 17 | 12 家 / 2759 |
| 🟢 沒擋，但**找不到條款頁**（要人工看） | Loft29 1053、瑪黑 542、北歐櫥窗 153、喜的 120、睦叁 60、moonmist 25、Objects Ark 14、OSTI 11、黑色雋永 11 | 9 家 / 1989 |
| 🟡 連線不穩（兩次結果不同） | viithe 289、MOTTO 49 | 2 家 / 338 |
| 🔴 Cloudflare 驗證頁 | 北歐先生 284、TH Company 211 | 2 家 / 495 |
| 🔴 **誤判**（要人工看） | FUNHOUSE 64：條款裡的「Harvest Grace」被當成禁止 harvest 的字眼，其實沒禁止 | 1 家 / 64 |

- 很多 Shopline 店的 robots.txt 寫了 `Crawl-delay: 5`，要照它跑（每頁 5 秒）
- 「找不到條款頁」不等於「條款允許」：自動找的路徑沒找到而已，抓之前要到網站上找條款看一遍
- check_site.py 的條款關鍵字 `harvest` 太寬，會誤判品牌名稱，要修（先寫會紅的測試）

## 人工看條款（2026-11-20，用瀏覽器從首頁底部的連結找，像一般人那樣讀）

自動檢查「找不到條款頁」的 9 家，加上被誤判的 FUNHOUSE：

| 通路（上架數） | 找到什麼 | 結論 |
|---|---|---|
| Loft29（1053） | 只有隱私權政策（講個資）和版權宣告 | 沒有禁止 |
| 瑪黑（542） | 使用條款第十一條「智慧財產權」：網站所有內容（含「資訊、資料」）不得重製、散布，轉載要事先書面同意 | 🟡 沒提程式抓取，但限制寫得很廣 |
| 北歐櫥窗（153） | 會員權益暨隱私權條款第九條：跟瑪黑同一套智慧財產權條文 | 🟡 同上 |
| 喜的（120） | 只有隱私權政策、會員權益 | 沒有禁止 |
| 睦叁（60） | 只有退換貨、運送說明，沒有條款 | 沒有條款 |
| moonmist（25） | 只有 Privacy（講個資） | 沒有禁止 |
| Objects Ark（14） | 「條款與細則」頁是空的，只有地址電話 | 沒有條款 |
| OSTI（11） | 「服務條款」頁是空的 | 沒有條款 |
| 黑色雋永（11） | 整站沒有條款或隱私權連結，只有版權宣告 | 沒有條款 |
| FUNHOUSE（64） | 沒有服務條款，`/terms/` 其實會轉回首頁；隱私權政策只講個資 | 沒有禁止（自動檢查的紅燈是誤判） |

要注意：

- **沒有條款 ≠ 什麼都能拿。** 商品照片和介紹文字有著作權。價格、尺寸、品名、庫存、連結這種「事實」比較沒問題。所以只存事實，不存文案；圖片只存連結（2026-11-20 起，做 3D 要用），每筆都連回原店
- **「智慧財產權」這一套條文很常見**（瑪黑、北歐櫥窗一字不差）。自動檢查只找「爬蟲、擷取」這類字眼，所以前面標 🟢 的 12 家可能也有，但還沒逐條讀
- check_site.py 的三個誤判已修（2026-11-20，`tests/test_check_site.py`）：
  1. 單獨的 `harvest` 拿掉，英文字要整個字對到 —— 品牌「Harvest Grace」不再被當成禁止
  2. 條款網址轉回首頁的，不算找到條款
  3. 加了 Shopline 的 `/about/terms`、PHP 站的 `/terms.php`
  重跑 FUNHOUSE：在 `/about/terms` 找到條款、沒有禁止字眼，綠燈

## 直接抓 4 家 Shopify（2026-11-20）

只存事實（品名、品牌、價格、規格名、庫存、SKU、連結），不存介紹文字和圖片（`softgoods/policy.py`）。
每頁等 2 秒，robots 沒擋任何一頁，0 失敗。資料在本機 `softgoods.db`（不進 git）。

拿 lampclub 那份（`lampclub_baseline.db`、`out/listings.csv`）對照：

| 通路 | lampclub 列的 | 我們也抓到 | 價格一樣 | 我們多抓到的商品 |
|---|---:|---:|---:|---:|
| 潤舍 | 595 | 595 | 595 | 765 |
| NOSA | 437 | 437 | 437 | 3384 |
| 居雅堂 | 249 | 249 | 249 | 648 |
| Sheeper | 25 | 25 | 25 | 569 |

**清單和價格：一筆都沒漏。** 多抓到的大多是家具、家飾；跟燈有關的約 137 件 lampclub 沒列
（NOSA 122 件裡有不少是燈泡這類配件）。

**尺寸：已補（2026-11-20，規格和結果在 `SIZES.md`）。** 一開始只有 101 件有尺寸，因為各店把尺寸寫在介紹文字裡。
現在抓的時候從文字裡只抽出尺寸那一段（文字本身照樣不存）；潤舍的尺寸只在商品頁，`size_from_page` 打開、多開了 1052 頁。
lampclub 有尺寸的 1170 件，我們有 1154 件，98% 數字一致。

**分類表：已補。** NOSA 的「燈具」、居雅堂的「吊燈 Pendant」、Sheeper 的「Light燈飾」都對得到了；
只寫「燈具」的，小分類從標題找。燈 1165 款裡只剩 36 款分不出是吊燈、桌燈還是壁燈。

## 目標：自己做出 lampclub 的全部資料，自己更新（2026-11-20）

Isaac：「為了以後著想，爬蟲要做到可以爬到 lampclub 裡面的所有資料，我們還是要自己能更新最好。」
lampclub 是聚合站，資料都來自這 26 家通路；直接抓通路，就不用靠它。

**通路（lampclub 列了 5645 筆）**

| 狀態 | 通路 | lampclub 筆數 |
|---|---|---:|
| ✅ 抓好了（Shopify） | 潤舍、NOSA、居雅堂、Sheeper | 1306 |
| ⏳ 在抓（Shopline，每頁 5 秒） | 新采、散步舖、Design Butik、WOW、Motive、柒木、一嶼、HAY TAIPEI | 1453 |
| 加進 sites.yaml 就好（Shopline，人工看過沒禁止） | 喜的、FUNHOUSE、睦叁、Objects Ark | 258 |
| 加進 sites.yaml 就好（Shopify，人工看過沒禁止） | moonmist | 25 |
| 要寫新的讀取程式（自架網站，沒禁止） | Loft29（1053）、viithe、MOTTO、OSTI、黑色雋永 | 1413 |
| ✅ **店家同意了**（條款有很廣的智慧財產權條文 🟡，Isaac 2026-11-20 問過） | 瑪黑、北歐櫥窗 | 695 |
| ✅ **店家同意了**（Cloudflare 擋機器人；我們不繞過，Isaac 2026-11-20 問過） | 北歐先生、TH Company | 495 |

2026-11-20 Isaac 寫信問了這 4 家，都同意。所以 26 家全部可以抓，剩下的是技術問題：
Cloudflare 那兩家要看我們的請求會不會被擋（被擋就請店家把我們放行，不繞過）。

**欄位（lampclub 的 lamps.csv：2142 盞）**

| lampclub 有的 | 我們 |
|---|---|
| 品牌、型號、類型、最低價、最高價、通路數、規格數 | ✅ 有（v_product_price、v_same_spec_price） |
| 尺寸、價格、供貨、連結（listings.csv） | ✅ 有（SIZES.md） |
| 設計師（833 盞有）、設計年份（525）、電壓（575） | ❌ 還沒抽。多半寫在介紹文字裡（「設計師：Vico Magistretti 設計年份：1970」），可以照抽尺寸的方式只抽那幾個事實 |
| 圖片 | 不存（著作權，policy.py）；Setdress 要的是 3D 模型 |
| 同一盞燈在不同店歸成一筆 | 部分：同品牌同型號才合得起來（HANDOVER「商品比對」） |

**自己更新**：`python -m softgoods crawl all --mark-gone` —— 各店同時跑、各照各的速度；只有完整跑完的店才標記下架（`update.py`）。

### 自架網站盤點（2026-11-20，每家只打 2～3 個請求）

| 通路 | lampclub 筆數 | 看到的 | 怎麼做 |
|---|---:|---|---|
| 北歐櫥窗 | 153 | Laravel；sitemap 有 4115 個 /product/ 頁；商品頁有 schema.org Product（含價格、供貨）；尺寸寫「尺寸：寬 128 x 深 93 x 高 40（公分）」 | ✅ 通用的 `schemaorg` 讀取程式（試跑 20 件：價格、分類、尺寸 20/20） |
| Loft29 | 1053 | sitemap 4280 個 /w/product/detail/ 頁；有價格的商品，schema.org Product 裡有價格；「歡迎來電洽詢」的沒有。尺寸、規格從 /api/ 來（robots 禁止），拿不到 | ✅ `schemaorg`（試跑 20 件：15 件有價格、0 件有尺寸） |
| 黑色雋永 | 11 | sitemap 有 24 個商品頁 | 還沒細看 |
| 瑪黑 | 542 | Play Framework；**沒有 robots.txt、沒有 sitemap** | 要從分類頁找商品 |
| viithe | 289 | sitemap 打得開但裡面沒有網址 | 還沒細看 |
| OSTI | 11 | 沒有 sitemap | 還沒細看 |
| MOTTO | 49 | robots.txt 和 sitemap 都回 **403（擋我們）** | 要請店家放行，我們不繞過 |

### Shopline 7 家抓完（2026-11-21）

| 通路 | 商品頁 | 上架筆數 | 不知道品牌 |
|---|---:|---:|---:|
| 新采 | 1217 | 9242 | 39% |
| 散步舖 | 1283 | 7118 | 89% |
| WOW | 3946 | 138054 | 0%（用商品資料的 brand 欄位；以前沒讀這欄是 98%） |
| Motive | 1057 | 7546 | 73% |
| 一嶼 | 390 | 548 | 94% |
| HAY TAIPEI | 544 | 2195 | 0% |
| Design Butik | 942 | 0 → 重抓中 | 商品資料寫法不一樣（直接寫成物件），已修 |

下載全部 0 失敗。品牌欄位空著的店（散步舖、Motive、一嶼、新采一部分），品牌多半寫在麵包屑或品牌分類，還沒讀。
