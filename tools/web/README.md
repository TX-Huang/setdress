# Setdress 網頁版（原型）

把燈和地毯放進你家照片，邊看邊算總價。

**打開：** https://tx-huang.github.io/setdress/

## 怎麼用

1. 按「上傳你家照片」。要拍到地板，最好也拍到天花板
2. AI 自動對齊：算出鏡頭多高、往哪看、天花板多高。第一次會問要不要下載 AI 模型（71 MB，之後存在你的裝置上）
3. 「擺放」分頁換燈、拖曳；「燈光」分頁開燈、調色溫、白天晚上
4. 照片右上角的「量尺」：在照片上點兩下，量兩點的距離（可以拿捲尺對照，看比例準不準）

## 照片不會上傳

AI 在你的瀏覽器裡跑（[onnxruntime-web](https://onnxruntime.ai/)）。照片不會送到任何伺服器。

有支援 WebGPU 的電腦大約 1 秒；只能用 CPU 的裝置（多半是手機）大約 10–30 秒，而且比較不準。

## 這是原型

- 燈是 [lampclub.tw](https://lampclub.tw/) 上 14 盞真的燈（2026-11-20 抄的尺寸和價格，以通路頁面為準，每盞都有連回 lampclub 的連結）
- 3D 是照尺寸做的示意形狀，不是原廠模型
- 地毯是假的
- 光打在照片裡的牆上的樣子是估的

## 用到的東西

| | 授權 |
|---|---|
| [MoGe-2](https://github.com/microsoft/MoGe) 小版（`models/moge-2-s-fp16.onnx`，轉成 ONNX 半精度） | MIT（含 DINOv2 的部分是 Apache 2.0），見 `models/LICENSE-MoGe.txt` |
| [Three.js](https://threejs.org/) 0.170.0（從 jsDelivr 載入） | MIT |
| [onnxruntime-web](https://onnxruntime.ai/) 1.22.0（從 jsDelivr 載入） | MIT |
