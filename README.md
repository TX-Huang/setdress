# Setdress

把燈和地毯放進你家照片，邊看邊算總價。（原型）

**網站：** https://tx-huang.github.io/setdress/

上傳一張房間照片 → AI 在瀏覽器裡算出鏡頭多高、往哪看、天花板多高 → 把 lampclub.tw 上 14 盞真燈照真實尺寸放進照片、調燈光 → 列出哪家最便宜。照片不會上傳。

## 資料夾

| | |
|---|---|
| `prototype/` | 網頁：`index.html`（Three.js）、`lamps.js`（燈具目錄）、`catalog.js`（爬到的燈，`tools/outline/export_catalog.py` 產生）、`erase.js`（擦掉照片裡的東西）、`webalign.js`（網頁版 AI 對齊、量尺）、`models/`（AI 模型：MoGe-2 小版、MobileSAM、MI-GAN，ONNX） |
| `tools/autoalign/` | Python：本機 AI 對齊服務 `server.py`、找地板天花板 `geometry.py`、遮擋 `occlusion.py`、轉模型 `export_onnx.py` |
| `tools/outline/` | 沒有原廠 3D 時：從商品照片描側面輪廓，轉成 3D；`batch.py` 對爬到的全部圓形燈批次跑（照片只在本機，見 `docs/outline.md`） |
| `tools/softgoods/` | 軟裝商品爬蟲：把台灣各家通路的商品和價格抓進同一個資料庫、算比價（先讀 `HANDOVER.md`） |
| `tools/web/` | `build_site.py`：只把網站要的檔案放進 `_site`（白名單） |
| `docs/` | 規格和結果：[MVP 規格](docs/mvp-spec.md)、[AI 自動對齊](docs/auto-align.md)、[網頁版](docs/web-align.md)、[燈具目錄](docs/lamps.md)、[爬到的燈放進模擬器](docs/catalog.md)、[擦掉照片裡的東西](docs/erase.md)、[自動描輪廓](docs/outline.md)、[量尺](docs/ruler.md) |

## 測試

推到 `main` 時，GitHub Actions 會先跑全部測試，過了才更新網站（`.github/workflows/pages.yml`）。

自己跑：

- `prototype/` 底下：`node --test`（Node 22 以上）
- `tools/autoalign/` 底下：`pip install numpy pillow pytest`，然後 `python -m pytest -q`
- `tools/web/` 底下：`python -m pytest -q`
- `tools/outline/` 底下：`python -m pytest -q`（要 numpy、pillow）
- `tools/softgoods/` 底下：`pip install requests beautifulsoup4 lxml pyyaml pandas pytest`，然後 `python -m pytest -q`（不連網路）

## 照片

- 網站上：AI 在瀏覽器裡跑，照片不會送出去
- 本機對齊服務（`tools/autoalign/server.py`）只聽 127.0.0.1，照片只在記憶體裡處理
- `tools/autoalign/photos/` 放測試用的實拍照片，不進 git

## 用到的東西

| | 授權 |
|---|---|
| [MoGe-2](https://github.com/microsoft/MoGe) 小版（`prototype/models/`，轉成 ONNX 半精度） | MIT（含 DINOv2 的部分是 Apache 2.0），見 `prototype/models/LICENSE-MoGe.txt` |
| [Three.js](https://threejs.org/) 0.170.0、[onnxruntime-web](https://onnxruntime.ai/) 1.22.0（從 jsDelivr 載入） | MIT |
| 燈的尺寸和價格：[lampclub.tw](https://lampclub.tw/)（2026-11-20 人工抄錄，每盞都連回 lampclub） | |
