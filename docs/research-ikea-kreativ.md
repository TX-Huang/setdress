# IKEA Kreativ 是怎麼做的？給 Setdress 的技術調查

> 2026-11-19 · 只用公開資料：新聞稿、專利、論文、徵才、IKEA 說明頁、評測。沒有拆 App、沒有側錄流量。
> **已證實** = 來源直接寫了（附連結）。**推測** = 我推出來的（寫理由）。
> `[S數字]` 對到文末「來源清單」，每個來源都標了日期。IKEA 說明頁沒有日期，標「2026-11 讀取」，代表是現況。

## 一句話結論

Kreativ 的做法是：**伺服器先把房間照片算成「深度圖 + 牆和地板的平面 + 家具遮罩」，再讓手機或瀏覽器用 GPU 把 3D 商品即時疊上去**。這個分工我們可以直接抄。它 2019 年要多張照片才做得到的幾何，2026 年用一張照片加開源模型（MoGe）就能做到夠用。它**不支援吊燈，也沒有燈光控制**，這剛好是 Setdress 的機會。

## 背景

- **已證實** Geomagical Labs 2016 年成立，在 Mountain View。Ingka（經營最多 IKEA 門市的集團）2020-04 買下 100%，當獨立子公司經營。創辦人兼執行長是 Brian Totty，當時團隊有 6 位博士。[S1](https://www.ingka.com/newsroom/ingka-group-acquires-geomagical-labs/) [S2](https://techcrunch.com/2020/04/02/ikea-acquires-ai-imaging-startup-geomagical-labs-to-supercharge-room-visualisations)
- **已證實** Kreativ 2022-06-22 在美國上線，支援 iOS 和電腦網頁 [S3](https://www.ikea.com/us/en/newsroom/corporate-news/ikea-launches-new-ai-powered-digital-experience-empowering-customers-to-create-lifelike-room-designs-pub58c94890)。2023-02 上線英國、愛爾蘭 [S5](https://www.ikea.com/gb/en/newsroom/stories/ikea-kreativ-launches-making-home-design-even-easier-and-more-accessible-for-the-many-pub71d09380)。2024-12 已有 29 個市場（中國除外），每年 700 多萬活躍使用者 [S6](https://www.ingka.com/?p=161472)。
- **已證實** 2025 年的徵才寫著：Kreativ 由 Geomagical 開發和營運，有「數千萬人」使用 [S25](https://www.builtinboston.com/job/senior-web-engineering-tech-lead-ikea-kreativ/6884405)。

## 1. 拍攝：幾張照片？要什麼手機？只有 App 嗎？

- **已證實** 2022 上線時的「Scene Scanner」：站在房間後面，手機左右掃 5 個點，每點畫 8 字讓照片重疊。接著往旁邊走一步，再拍一次。掃描約 2 分鐘，處理和上傳再約 5 分鐘。不需要 LiDAR。[S4](https://techcrunch.com/?p=2340297)
- **已證實** 現在 App 會依手機自動選方法：「5 Point Panoramic」、「Ultrawide」或「1-Scan LiDAR」。沒有 LiDAR 的手機預設「廣角照片掃描」。有 LiDAR 的多一個「Full Room Scan」，做出空房間的數位分身。[S7](https://www.ikea.com/us/en/customer-service/knowledge/articles/e86d70g6-3673-4306-b373-20f7cg7fd5ed.html) [S8](https://www.ikea.com/ca/en/customer-service/knowledge/articles/g81237dc-557d-4d2e-b0fd-24c6d8e46705.html)
- **已證實** 網頁版**不能拍**，但可以**上傳一張照片**（JPEG、PNG、WebP、HEIC，最大 30 MB）。官方說照片「只有一個角度」。網頁也能手動輸入尺寸蓋房間（Room Builder）。[S9](https://www.ikea.com/ch/en/customer-service/knowledge/articles/1a780f75-e136-4945-9863-50687a959cd4.html)
- **已證實** 處理好會寄 email 通知。之後可以在手機或電腦網頁繼續設計。[S8](https://www.ikea.com/ca/en/customer-service/knowledge/articles/g81237dc-557d-4d2e-b0fd-24c6d8e46705.html)
- **已證實** IKEA App 需要 iOS 16 以上 [S14](https://apps.apple.com/us/app/ikea/id1452164827)。Android 要 9.0 以上，而且要是支援 ARCore 的手機（第三方整理 IKEA 說明頁）[S28](https://macmyths.com/ikea-place-review-what-ikea-kreativ-does-in-2026/)。
- **已證實** 官方拍攝建議：光線要足、橫拍、一定要拍到地板、背靠牆角站。[S12](https://www.ikea.com/pt/en/customer-service/knowledge/articles/e2187190-3508-4202-g02f-5b3566d4g084.html)
- **推測** 「上傳一張照片」是後來才加的。理由：2022–2023 的新聞稿都只講多張掃描。我找不到加入的日期。
- **推測** 拍攝時有用 ARKit / ARCore 拿相機位置、重力方向和真實尺度。理由：Android 版要求 ARCore，專利也寫了用 SLAM 位姿定尺度 [S15](https://patents.google.com/patent/EP3942468A1/en)，兩者對得上。
- **推測** LiDAR 的 Full Room Scan 可能用了 Apple RoomPlan。只是行為很像（空房間、要 LiDAR），沒有公開證據。

## 2. 幾何：相機、深度、牆地天花板、真實尺寸

主要證據是 Geomagical 2019 年申請的專利 [S15](https://patents.google.com/patent/EP3942468A1/en)、全景拼接專利 [S18](https://patents.google.com/patent/US11830163B2/en) 和論文。

- **已證實** 深度不是單一來源，而是**融合**多種：多視角立體（SfM + MVS / PatchMatch）、有 LiDAR 就用、再加單張深度神經網路（例子是 BTS）出粗略深度。[S15](https://patents.google.com/patent/EP3942468A1/en) 2022 新聞稿也說用「立體視覺」重建深度，用「神經網路」辨識室內物件和幾何。[S3](https://www.ikea.com/us/en/newsroom/corporate-news/ikea-launches-new-ai-powered-digital-experience-empowering-customers-to-create-lifelike-room-designs-pub58c94890)
- **已證實** 真實尺度有四個來源：SLAM 的公制位姿、已知尺寸的物件（例如一張紙）、深度感測器、**相機離地高度**（由地板平面和重力推出來）。[S15](https://patents.google.com/patent/EP3942468A1/en)
- **已證實** 地板：把分割成「地板」的點拿去做 RANSAC 平面擬合，並限制要跟重力垂直。牆：用垂直線、重力、法向量找牆。快要 90 度的兩面牆，直接修成 90 度。[S15](https://patents.google.com/patent/EP3942468A1/en)
- **已證實** 多張照片先拼成一張「能容忍視差」的廣角圖（用重力校正和網格變形），再在這張圖上算深度。[S18](https://patents.google.com/patent/US11830163B2/en)
- **已證實** 2022 年 ISMAR 論文：先分割出房間的平面，再用「相鄰關係 + 直角限制」最佳化，用真實住家照片測試。[S22](https://aunagar.github.io/publication/ismar20223dv)
- **已證實** IKEA 自己的說法：分析手機拍的全景照片，建出房間的 3D 模型，連現有家具也建模。[S34](https://www.ikea.com/fi/en/customer-service/knowledge/articles/ff043ec6-3527-4de3-96e2-9368671ec281.html)
- **推測** 網頁上傳單張照片時，沒有多視角，也沒有陀螺儀。只能靠單張深度網路、佈局網路和相機高度的假設，所以精度應該比 App 掃描差。官方特別說「照片只有一個角度」，可能是在降低期待。

## 3. 抹除家具：純 2D 補圖，還是有用 3D？

**答案：有用 3D（牆和地板的平面），不是單純 2D 補圖。**

- **已證實** Geomagical 論文〈Layout Aware Inpainting for Automated Furniture Removal〉（2022-10）[S19](https://arxiv.org/abs/2210.15796)：
  - 輸入一張廣角照片。用實例分割找出家具。房間佈局（每個平面的方程式和範圍）當作輸入。
  - 每面牆、地板先「拉正」成正對相機，補完再變形回去。這樣地磚、木紋的透視才會對。
  - 補圖網路是 **LaMa**，用約 100 萬張圖重新訓練，加上顏色分布的 loss 和特徵精修。不是平面的地方再補第二輪。
  - 沒處理影子。論文明說測試用的遮罩不會有影子。
- **已證實** 另一篇（CVPR 2022 workshop）讓 LaMa 在高解析度下也補得出一致的結構：推論時直接最佳化網路中間的特徵。[S20](https://arxiv.org/abs/2206.13644) 程式碼有開源，Apache-2.0。[S21](https://github.com/geomagical/lama-with-refiner)
- **已證實** 專利 US11727587 [S17](https://patents.google.com/patent/US11727587B2/en)：
  - 抹掉區域的**深度**，用後面那面牆或地板的平面內插。也可以設成無限遠，讓補過的地方永遠不會擋住新商品。
  - **顏色**可以用 inpainting、PatchMatch 或神經網路。在拉正的平面上合成紋理，再用 homography 貼回。
  - 殘留的**影子**先偵測，再模糊、淡化。訓練資料可以用光線追蹤算「同一個房間有家具 / 沒家具」。
- **已證實** 操作方式：網頁上點有黃色外框的物件，它就消失。「Hide All」一次全清。[S8](https://www.ikea.com/ca/en/customer-service/knowledge/articles/g81237dc-557d-4d2e-b0fd-24c6d8e46705.html)

## 4. 擺放和遮擋：商品怎麼躲到既有家具後面？

- **已證實** 每張照片都配一個「虛擬房間模型」：深度圖、牆地天花板的平面、既有家具的遮罩。[S16](https://patents.google.com/patent/US11367250B2/en)
- **已證實** 擺放規則：落地商品貼地板（法向量跟重力平行的平面）、壁掛的貼牆、小東西放櫃子上。不能把沙發放進現有的沙發裡（物理檢查）。拖曳時，商品會依所在的表面改變透視和光線。[S16](https://patents.google.com/patent/US11367250B2/en) 2024 年另外加了 AI 規則引擎「Smart Item Placement」建議擺法。[S6](https://www.ingka.com/?p=161472)
- **已證實** 遮擋的實作 [S17](https://patents.google.com/patent/US11727587B2/en)：
  - 做法一：用自訂 fragment shader 把深度圖寫進深度緩衝區。**地板、牆、天花板不寫深度**，所以它們永遠不會擋住商品，只有家具會擋。
  - 做法二：用深度圖取樣建一個「看不見、只寫深度」的網格，地板那部分的三角形剪掉。
  - 被擋住的虛擬像素丟掉，其他疊在照片上。
- **已證實** 物件邊緣的深度，會用顏色和法向量修過，遮擋的邊才乾淨。[S15](https://patents.google.com/patent/EP3942468A1/en)
- **已證實** 尺寸：房間模型是公制。使用者可以用滑桿或兩指縮放調整整體比例，也可以選一個物件、輸入實際尺寸來校正。[S16](https://patents.google.com/patent/US11367250B2/en)

## 5. 光線和影子

- **已證實** 估光（專利）[S15](https://patents.google.com/patent/EP3942468A1/en)：
  - 環境光：找天花板這類只被環境光照到的區域，取 HSV 亮度（V）的平均。
  - 主要光源：從分割出來的燈和窗戶找，再用顏色確認。輸出光源的位置、類型、強度、色溫。
- **已證實** 影子（專利）[S16](https://patents.google.com/patent/US11367250B2/en)：照「主要光線方向」產生，方向可以自動偵測，也可以讓使用者指定。先用每件物件一個影子（或不畫）快速顯示，之後再補多個影子。也會配合照片調色偏、曝光和雜訊。
- **已證實** 專利寫了可以算「不同時段、增減光源」，也能改燈的顏色和亮度。[S16](https://patents.google.com/patent/US11367250B2/en)
- **推測** 產品裡**沒有**讓使用者調燈光或白天晚上的功能。理由：IKEA 說明頁和所有評測都沒提到。專利寫「可以」，不代表有做。
- **已證實** 吊燈、吸頂燈、吊扇等天花板安裝的商品**不在** Kreativ 目錄裡，原因是「還沒有 3D 模型」。[S10](https://www.ikea.com/us/en/customer-service/knowledge/articles/8ff2279b-068c-46a2-8877-90cf7b33eed3.html)
- **推測** 所以 Kreativ 不需要處理「開燈照亮房間」，也不需要準確的天花板平面。這正是 Setdress 的空白。

## 6. 算圖：手機上即時，還是雲端？

- **已證實** 分工（專利）：伺服器算深度、平面、遮罩；**使用者裝置**做即時算圖（render）和互動。[S17](https://patents.google.com/patent/US11727587B2/en) 專利舉的圖形函式庫例子是 WebGL。也可以漸進式顯示：先給低品質，再換成雲端算好的高品質圖。[S16](https://patents.google.com/patent/US11367250B2/en)
- **已證實** 網頁版要用電腦的 GPU 算圖。GPU 不夠時會跳「資源不足」。[S11](https://www.ikea.com/gb/en/customer-service/knowledge/articles/b48246c3-9c4g-4b19-b7g2-785c08b9dddf.html)
- **已證實** 徵才線索：
  - 2022-03 在 three.js 官方論壇徵 Three.js 工程師。[S23](https://discourse.threejs.org/t/geomagical-labs-hiring-three-js-engineer-for-3d-mixed-reality-apps/36471)
  - 2023-08 徵「Cloud Graphics」工程師：用 Python 把高精度 3D 模型轉成照片級算圖和**即時用的 LOD**、批次產生展示間、合成 AI 訓練資料。[S24](https://blenderartists.org/t/3d-cloud-graphics-asset-pipeline-engineer-contract/1479701)
  - 2025 徵網頁技術主管：JavaScript / TypeScript / React，用「client + cloud 混合架構」串起 UI、3D 引擎、AI 管線和雲端微服務。[S25](https://www.builtinboston.com/job/senior-web-engineering-tech-lead-ikea-kreativ/6884405)
- **推測** 網頁端很可能是 Three.js / WebGL。理由：徵才、專利、「需要 GPU」三條線索一致。但官方沒有明說。

## 7. 商品 3D 模型

- **已證實** IKEA 2005 年型錄第一次用 CG 商品圖（一張椅子），2008 年做出第一個全 CG 房間（廚房）。工具是 3ds Max + V-Ray，從產品的 CAD 檔建模。[S29](https://blog.chaos.com/putting-the-cgi-in-ikea-how-v-ray-helps-visualize-perfect-homes)
- **已證實** 2014 年：約 75% 的**單品**圖是 CG。模型庫約 25,000 個，貼圖 4K×4K。[S30](https://petapixel.com/2014/08/28/flip-ikea-catalog-75-photography-see-cgi/)
- **已證實** 2016 年：模型來自 CAD、圖面和打樣品，有自己寫的工具加速。[S31](https://develop3dlive.com/?p=15568)
- **已證實** 2019 年 IKEA 是 Khronos「3D Commerce」的發起者之一（glTF 的電商標準）。[S32](https://www.khronos.org/news/press/khronos-establishes-exploratory-group-for-3d-commerce-standards-and-guidelines)
- **已證實** 2024 年 AWE 演講：數萬個商品模型和材質，有自己的算圖和發佈系統，材質有分類標註，正在做生成式 AI 的房間情境。[S33](https://awexr.com/blog/1015-awe-talks-mapping-ikea-s-3d-journey)
- **已證實** 2022 上線時有 12,000 多件商品可用 [S4](https://techcrunch.com/?p=2340297)。現在還缺：天花板安裝的、紡織品（窗簾、抱枕、被子）、真的植物 [S10](https://www.ikea.com/us/en/customer-service/knowledge/articles/8ff2279b-068c-46a2-8877-90cf7b33eed3.html)。
- **推測** Kreativ 用的即時模型，是從離線高精度模型**自動**減面、烘焙出來的。理由：2023 年徵才寫了「real-time LODs」[S24](https://blenderartists.org/t/3d-cloud-graphics-asset-pipeline-engineer-contract/1479701)。格式可能是 glTF（因為參與 Khronos），未證實。

## 8. 已知限制和使用者抱怨

| 問題 | 標記 | 來源 |
|---|---|---|
| 掃描很麻煩（8 字、走一步再拍）；Beta 版會閃退 | 已證實 | [S4](https://techcrunch.com/?p=2340297) 2022 |
| 只能在拍照的那個角度編輯，不能走動、換角度看 | 已證實 | [S26](https://mixed-news.com/en/ikea-app-now-deletes-your-furniture-and-replaces-it-with-your-own/) 2022 |
| 抹除有瑕疵：分不清地毯邊界、被擋住的地方補不完整、插入的家具有破綻（MIXED 轉述 The Verge 實測） | 已證實 | [S26](https://mixed-news.com/en/ikea-app-now-deletes-your-furniture-and-replaces-it-with-your-own/) 2022 |
| 目錄不完整：吊燈、吸頂燈、紡織品、廚房都不能放 | 已證實 | [S9](https://www.ikea.com/ch/en/customer-service/knowledge/articles/1a780f75-e136-4945-9863-50687a959cd4.html) 2026-11 讀取 |
| 網頁版很吃 GPU，會跳「資源不足」 | 已證實 | [S11](https://www.ikea.com/gb/en/customer-service/knowledge/articles/b48246c3-9c4g-4b19-b7g2-785c08b9dddf.html) 2026-11 讀取 |
| 「全部隱藏」之後不能復原；看不出哪些商品已經在購物車 | 已證實 | [S27](https://ixd.prattsi.org/2024/02/design-critique-ikea-kreativ-ios-app/) 2024 |
| 不是量測工具：看起來對，不代表真的放得下 | 已證實（第三方評論） | [S28](https://macmyths.com/ikea-place-review-what-ikea-kreativ-does-in-2026/) 2026 |
| 只有 IKEA 自己的商品 | 已證實 | [S28](https://macmyths.com/ikea-place-review-what-ikea-kreativ-does-in-2026/) 2026 |

沒找到大量的 Reddit 或 App Store 抱怨。IKEA App 評分 4.8（15.1 萬則），評論多在講配送和庫存，很少提到 Kreativ。[S14](https://apps.apple.com/us/app/ikea/id1452164827)

## 9. 現在可以用的模型和 API（2026-11-19 查）

授權都看過 GitHub 的 LICENSE 或 Hugging Face 的標示。**程式和權重的授權常常不一樣，要分開看。**

### 9-1 深度 + 相機（對應第 2 題）

| 候選 | 版本 / 日期 | 授權 | 可商用？ | 備註 |
|---|---|---|---|---|
| [MoGe-2](https://github.com/microsoft/MoGe)（Microsoft） | 2025-07 論文 | 程式 MIT；權重 MIT（[HF](https://huggingface.co/Ruicheng/moge-2-vitl-normal)） | 可以 | 一次給公制深度、相機視角、法向量。有 ONNX（S/B/L），小版可在瀏覽器跑 |
| [MoGe-3](https://github.com/microsoft/MoGe) | 2026-08-18 | 程式 MIT；權重 MIT | 可以 | 細節更好；要 Linux GPU，放伺服器 |
| [Depth Anything 3](https://github.com/ByteDance-Seed/Depth-Anything-3) | 2025-11-14（1.1 版 2025-12） | Small / Base / Metric-Large：Apache-2.0；Large / Giant / Nested：CC BY-NC | 部分可以 | 只能用 Apache 那幾個 |
| [Apple Depth Pro](https://github.com/apple/ml-depth-pro) | 2024-10 | GitHub 是 Apple 自訂授權；[HF](https://huggingface.co/apple/DepthPro) 標 `apple-amlr`（研究用） | 兩邊衝突 | 先不要用 |
| [UniDepth V2](https://github.com/lpiccinelli-eth/UniDepth) | 2025-02 | CC BY-NC 4.0 | 不行 | |
| [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2) | 2024-06 | Small：Apache-2.0；其他：CC BY-NC | 只有 Small | 已被 DA3 取代 |

### 9-2 房間佈局（對應第 2 題）

- 沒有一個「授權乾淨、又能從一張普通照片估出牆地天花板」的現成網路。[HorizonNet](https://github.com/sunset1995/HorizonNet) 這類只吃 360 度全景；[SpatialLM](https://github.com/manycore-research/SpatialLM) 吃點雲，權重 CC BY-NC；[SceneScript](https://github.com/facebookresearch/scenescript) 也是 CC BY-NC。
- **建議照 Kreativ 專利自己組**：MoGe 的點雲 + 法向量 → 語意分割標出地板、牆、天花板 → RANSAC 擬合平面 → 修成直角。
- 分割用 [OneFormer ADE20K](https://huggingface.co/shi-labs/oneformer_ade20k_swin_large)（MIT）或 [EoMT](https://github.com/tue-mps/eomt)（MIT）。**不要用 SegFormer**：[NVIDIA 授權](https://github.com/NVlabs/SegFormer)只能研究用，瀏覽器上常見的 SegFormer 也一樣。

### 9-3 抹除（對應第 3 題）

| 候選 | 日期 | 授權 | 可商用？ | 備註 |
|---|---|---|---|---|
| [LaMa / big-lama](https://github.com/advimman/lama) | 2021–2022 | Apache-2.0 | 可以 | 便宜、快；不會清影子 |
| [lama-with-refiner](https://github.com/geomagical/lama-with-refiner)（Geomagical） | 2022 | Apache-2.0 | 可以 | 高解析度精修；不會清影子 |
| [FLUX.2 [klein] 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) | 2026-01 | Apache-2.0 | 可以 | 用文字指令編輯；9B 版是非商用 |
| [Qwen-Image-Edit-2511](https://huggingface.co/Qwen/Qwen-Image-Edit-2511) | 2025-12 | Apache-2.0 | 可以 | 約 20B 參數，要大 GPU |
| [FLUX.1 Fill [dev]](https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev) | 2024-11 | 非商用（可另外付費買授權） | 有條件 | |
| [ObjectClear](https://github.com/zjx0101/ObjectClear) | 2025 | S-Lab（非商用） | 不行 | 會連影子一起清 |
| [Bria Eraser（fal.ai）](https://fal.ai/models/fal-ai/bria/eraser) | 2026 | 商用 API，約 US$0.04 / 張 | 可以（付費） | 同家 FIBO Edit 版標示會清影子和倒影 |

### 9-4 遮擋用的分割（對應第 4 題）

| 候選 | 日期 | 授權 | 可商用？ | 備註 |
|---|---|---|---|---|
| [SAM 2.1](https://github.com/facebookresearch/sam2) | 2024-09 | Apache-2.0 | 可以 | tiny 版可在瀏覽器跑，適合「點一下選物件」 |
| [SAM 3 / 3.1](https://github.com/facebookresearch/sam3) | 2025-11 / 2026-03 | SAM License：免費可商用，但禁止軍事等用途、轉發要同授權 | 有條件 | 可以用文字找「沙發」「椅子」；要伺服器 GPU |

### 9-5 光線（對應第 5 題）

| 候選 | 日期 | 授權 | 可商用？ | 備註 |
|---|---|---|---|---|
| [DiffusionLight](https://github.com/DiffusionLight/DiffusionLight) | CVPR 2024 | 程式 MIT；底層 SDXL 是 OpenRAIL++（可商用、有使用限制） | 有條件 | 一張約 30 分鐘 |
| [DiffusionLight-Turbo](https://arxiv.org/abs/2507.01305) | 2025-07 | 同上 | 有條件 | 約 30 秒，要伺服器 GPU |
| [LuxDiT](https://github.com/nv-tlabs/LuxDiT)（NVIDIA） | 2025 | NVIDIA 非商用 | 不行 | |
| [ARCore](https://developers.google.com/ar/develop/java/lighting-estimation) / ARKit 光線估計 | — | 平台內建 | — | 只在即時 AR 裡有，**不能用在上傳的照片** |

MVP 建議：先不用學習式的 HDR 光照。照 Kreativ 專利的簡單做法：從照片取平均亮度和色調，加上使用者選的窗戶方向，變成一盞環境光 + 一盞方向光。

### 9-6 算圖（對應第 6 題）

- [Three.js](https://github.com/mrdoob/three.js/releases) 最新是 r187（2026-10，npm 0.187.0）。接影子用 `ShadowMaterial` 鋪一片看不見的地板。
- `WebGPURenderer` 還在大改，會自動退回 WebGL2，所以**版本要鎖死**。r186 拿掉了 `PCFSoftShadowMap`，舊範例要注意。
- 遮擋照 Kreativ 的做法：把深度圖做成「只寫深度」的網格或 shader，地板不寫深度。
- 備案：Babylon.js 9（2026-03）。

## 10. 結論：我們抄什麼、跳過什麼

### 抄

1. **伺服器算一次，之後都在瀏覽器裡互動。** 上傳時在伺服器算好「場景包」：相機、深度圖、地板 / 牆 / 天花板平面、家具遮罩。之後拖、轉、調燈都用瀏覽器 GPU，不花錢。Kreativ 就是這樣分工。[S17](https://patents.google.com/patent/US11727587B2/en)
2. **遮擋的 shader 技巧。** 深度圖寫進深度緩衝區，但地板和牆不寫。商品不會被地板吃掉，只會被沙發擋住。這可以回答 spec「待你決定」第 6 題，而且成本很低。
3. **用平面，不用雜亂的點。** 地板、牆、天花板都擬合成平面，再修成直角。商品貼平面，不貼雜訊。
4. **尺度三重保險。** 模型給的公制深度 → 用相機離地高度檢查 → 讓使用者輸入一個已知尺寸（例如天花板高度）校正。
5. **擺放規則。** 地毯貼地、吊燈掛天花板、不能穿進既有家具。
6. **影子先快後精。** 一個主光方向、每件商品一個影子。之後有空再加。
7. **拍照提示。** 上傳前提醒：光線要足、橫拍、拍到地板、站在牆角。我們要放吊燈，所以還要**拍到天花板**，這點要比 IKEA 嚴格。
8. **抹除（第二版再做）。** 照 Geomagical：把牆和地板拉正再補。LaMa（Apache-2.0）可以自己架；想省事就用 Bria Eraser API。

### 跳過

1. **多張掃描、8 字掃描、全景拼接。** 最難做，也是使用者最嫌麻煩的地方。IKEA 自己的網頁版也已經開放單張上傳。
2. **LiDAR 全房分身。** spec 已經排除，維持。
3. **自己訓練模型。** 他們有 6 位博士、做了好幾年。我們用 MoGe-2 / 3（MIT）就好。
4. **學習式光照估計（HDR 環境圖）。** 太慢，授權也麻煩。先用簡單燈光。
5. **雲端照片級算圖、自動 LOD 管線。** 我們只有 20–50 件商品，手工做、手工檢查就夠。
6. **全自動抹除所有家具。** 第一版不做。要做也先做「點一下，抹掉一件」。

### 我們跟它不一樣的地方

- Kreativ 不能放吊燈、吸頂燈，也不能調燈光。Setdress 的「燈 + 開關燈、調色溫」剛好是它沒做的。
- 代價：我們要估**天花板**，它不用。spec 第 1 步的測試，建議加一項「天花板平面準不準」。
- Kreativ 只有 IKEA。我們跨品牌比價。

## 來源清單

日期是來源的發佈日期。IKEA 說明頁沒有日期，標「2026-11 讀取」。

**IKEA / Ingka 官方**
- S1 Ingka：收購 Geomagical Labs — 2020-04-02 — https://www.ingka.com/newsroom/ingka-group-acquires-geomagical-labs/
- S3 IKEA US 新聞稿：Kreativ 上線 — 2022-06-22 — https://www.ikea.com/us/en/newsroom/corporate-news/ikea-launches-new-ai-powered-digital-experience-empowering-customers-to-create-lifelike-room-designs-pub58c94890
- S5 IKEA UK 新聞稿：英國、愛爾蘭上線 — 2023-02-13 — https://www.ikea.com/gb/en/newsroom/stories/ikea-kreativ-launches-making-home-design-even-easier-and-more-accessible-for-the-many-pub71d09380
- S6 Ingka：臥室設計功能、29 個市場 — 2024-12-09 — https://www.ingka.com/?p=161472
- S7 IKEA US 說明頁：怎麼掃描 — 2026-11 讀取 — https://www.ikea.com/us/en/customer-service/knowledge/articles/e86d70g6-3673-4306-b373-20f7cg7fd5ed.html
- S8 IKEA CA 說明頁：掃描方式、網頁抹除 — 2026-11 讀取 — https://www.ikea.com/ca/en/customer-service/knowledge/articles/g81237dc-557d-4d2e-b0fd-24c6d8e46705.html
- S9 IKEA CH 說明頁：上傳照片、格式、限制 — 2026-11 讀取 — https://www.ikea.com/ch/en/customer-service/knowledge/articles/1a780f75-e136-4945-9863-50687a959cd4.html
- S10 IKEA US 說明頁：哪些商品沒有 — 2026-11 讀取 — https://www.ikea.com/us/en/customer-service/knowledge/articles/8ff2279b-068c-46a2-8877-90cf7b33eed3.html
- S11 IKEA GB 說明頁：資源不足（需要 GPU）— 2026-11 讀取 — https://www.ikea.com/gb/en/customer-service/knowledge/articles/b48246c3-9c4g-4b19-b7g2-785c08b9dddf.html
- S12 IKEA PT 說明頁：怎麼拍比較好 — 2026-11 讀取 — https://www.ikea.com/pt/en/customer-service/knowledge/articles/e2187190-3508-4202-g02f-5b3566d4g084.html
- S14 App Store：IKEA App（5.14.0，iOS 16+）— 2026-11 讀取 — https://apps.apple.com/us/app/ikea/id1452164827
- S34 IKEA FI 說明頁：技術怎麼運作 — 2026-11 讀取 — https://www.ikea.com/fi/en/customer-service/knowledge/articles/ff043ec6-3527-4de3-96e2-9368671ec281.html

**專利（Geomagical Labs，Google Patents）**
- S15 EP3942468A1 室內場景建模（優先權 2019-03-18，公開 2022-01-26）— https://patents.google.com/patent/EP3942468A1/en
- S16 US11367250B2 跟 3D 室內影像互動（優先權 2019-03-18，核准 2022-06-21）— https://patents.google.com/patent/US11367250B2/en
- S17 US11727587B2 場景影像修改（優先權 2019-11-12，核准 2023-08-15）— https://patents.google.com/patent/US11727587B2/en
- S18 US11830163B2 影像產生／全景拼接（優先權 2019-07-01，核准 2023-11-28）— https://patents.google.com/patent/US11830163B2/en

**論文和程式碼（Geomagical Labs）**
- S19 Layout Aware Inpainting for Automated Furniture Removal — arXiv 2022-10 — https://arxiv.org/abs/2210.15796
- S20 Feature Refinement to Improve High Resolution Image Inpainting — CVPR 2022 workshop — https://arxiv.org/abs/2206.13644
- S21 geomagical/lama-with-refiner（Apache-2.0）— 2022 — https://github.com/geomagical/lama-with-refiner
- S22 Robust Planar Optimization for General 3D Room Layout Estimation — ISMAR 2022 — https://aunagar.github.io/publication/ismar20223dv

**徵才**
- S23 three.js 論壇：Geomagical 徵 Three.js 工程師 — 2022-03-29 — https://discourse.threejs.org/t/geomagical-labs-hiring-three-js-engineer-for-3d-mixed-reality-apps/36471
- S24 Blender Artists：3D Cloud Graphics & Asset Pipeline Engineer — 2023-08-24 — https://blenderartists.org/t/3d-cloud-graphics-asset-pipeline-engineer-contract/1479701
- S25 Built In：Senior Web Engineering Tech Lead, IKEA Kreativ — 2025（2025-10-10 下架）— https://www.builtinboston.com/job/senior-web-engineering-tech-lead-ikea-kreativ/6884405

**新聞和評測**
- S2 TechCrunch：IKEA 收購 Geomagical — 2020-04-02 — https://techcrunch.com/2020/04/02/ikea-acquires-ai-imaging-startup-geomagical-labs-to-supercharge-room-visualisations
- S4 TechCrunch：Kreativ 上線實測 — 2022-06-22 — https://techcrunch.com/?p=2340297
- S26 MIXED：Kreativ 實測（轉述 The Verge）— 2022-06-23 — https://mixed-news.com/en/ikea-app-now-deletes-your-furniture-and-replaces-it-with-your-own/
- S27 Pratt：Kreativ iOS 設計評論 — 2024-02-07 — https://ixd.prattsi.org/2024/02/design-critique-ikea-kreativ-ios-app/
- S28 MacMyths：Kreativ 2026 現況整理（第三方）— 2026-09-28 — https://macmyths.com/ikea-place-review-what-ikea-kreativ-does-in-2026/

**IKEA 3D / CGI**
- S29 Chaos 部落格：IKEA 的 CGI 和 V-Ray — 日期不明（內容講到 2008 年前後）— https://blog.chaos.com/putting-the-cgi-in-ikea-how-v-ray-helps-visualize-perfect-homes
- S30 PetaPixel：IKEA 型錄 75% 是 CG — 2014-08-28 — https://petapixel.com/2014/08/28/flip-ikea-catalog-75-photography-see-cgi/
- S31 Develop3D Live：Martin Enthed 演講 — 2016 — https://develop3dlive.com/?p=15568
- S32 Khronos：成立 3D Commerce 小組 — 2019-04-24 — https://www.khronos.org/news/press/khronos-establishes-exploratory-group-for-3d-commerce-standards-and-guidelines
- S33 AWE：Mapping IKEA's 3D Journey — 2024-08-22 — https://awexr.com/blog/1015-awe-talks-mapping-ikea-s-3d-journey

**模型授權**：見第 9 節表格裡的連結，全部在 2026-11-19 查詢。
