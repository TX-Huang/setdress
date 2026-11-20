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
