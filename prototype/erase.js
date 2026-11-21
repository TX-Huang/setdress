/* 擦掉照片裡的東西：不用模型的計算（docs/erase.md）
 *
 * 圈物件用 MobileSAM（瀏覽器裡跑，onnxruntime-web）：
 *   照片縮到最長邊 1024，[高, 寬, 3] 的 0–255（模型自己正規化、補邊；實際跑過兩種輸入，原始的才對）
 *   點的座標也乘同一個比例；最後補一個 (0, 0)、標籤 -1 的點，代表「沒有框」（SAM ONNX 的規定）
 *   輸出的 masks 已經是原照片大小，大於 0 的是物件
 * 補圖用 MI-GAN（pipeline v2）：輸入 [1, 3, 高, 寬] uint8 照片和 [1, 1, 高, 寬] 遮罩，
 *   遮罩 0 是要補的、255 是保留的（實際跑過：反過來的話什麼都不會補）
 *
 * 瀏覽器用 <script src="erase.js">（window.SetdressErase），Node 測試用 require。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SetdressErase = api;
})(typeof self !== 'undefined' ? self : this, () => {
  'use strict';

  const SAM_SIDE = 1024;

  // ---------- 圈物件 ----------
  function samSize(w, h) {
    const scale = SAM_SIDE / Math.max(w, h);
    return { w: Math.round(w * scale), h: Math.round(h * scale), scale };
  }
  // points：照片上的位置 [{x, y}]（像素）；box：拖出來的框 {x0, y0, x1, y1}（像素，可以沒有）。
  // 有框：框的左上、右下兩個角接在點後面（標 2、3）；沒框：最後補一個 (0, 0)、標 -1（SAM 的規定）
  function samPrompt(points, scale, box) {
    const all = points.map((p) => [p.x, p.y, 1]);
    if (box) {
      all.push([Math.min(box.x0, box.x1), Math.min(box.y0, box.y1), 2]);
      all.push([Math.max(box.x0, box.x1), Math.max(box.y0, box.y1), 3]);
    }
    const coords = new Float32Array((all.length + (box ? 0 : 1)) * 2);
    const labels = new Float32Array(all.length + (box ? 0 : 1));
    all.forEach(([x, y, label], i) => {
      coords[2 * i] = x * scale;
      coords[2 * i + 1] = y * scale;
      labels[i] = label;
    });
    if (!box) labels[all.length] = -1;
    return { coords, labels, count: labels.length };
  }
  // RGBA（canvas 的 ImageData）→ [高, 寬, 3] float
  function toHWC(rgba) {
    const n = rgba.length / 4, out = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      out[3 * i] = rgba[4 * i];
      out[3 * i + 1] = rgba[4 * i + 1];
      out[3 * i + 2] = rgba[4 * i + 2];
    }
    return out;
  }
  const maskFromLogits = (logits) => Uint8Array.from(logits, (v) => (v > 0 ? 1 : 0));

  // ---------- 往外多擴一點：邊緣和緊貼的影子一起補 ----------
  const growPixels = (w, h) => Math.max(3, Math.round(0.01 * Math.max(w, h)));
  // 一個方向的「r 格內有沒有 1」：跑一次，記住最近的 1 在哪
  function spread(src, w, h, r, horizontal) {
    const out = new Uint8Array(src.length);
    const [lines, len] = horizontal ? [h, w] : [w, h];
    const at = horizontal ? (line, k) => line * w + k : (line, k) => k * w + line;
    for (let line = 0; line < lines; line++) {
      let last = -Infinity;
      for (let k = 0; k < len; k++) { // 往前看
        if (src[at(line, k)]) last = k;
        if (k - last <= r) out[at(line, k)] = 1;
      }
      last = Infinity;
      for (let k = len - 1; k >= 0; k--) { // 往後看
        if (src[at(line, k)]) last = k;
        if (last - k <= r) out[at(line, k)] = 1;
      }
    }
    return out;
  }
  // 方形擴張（上下左右斜角都 r 格）：先橫的再直的
  const dilate = (mask, w, h, r) => spread(spread(mask, w, h, r, true), w, h, r, false);

  // ---------- 補圖 ----------
  const miganMask = (mask) => Uint8Array.from(mask, (v) => (v ? 0 : 255));
  function toCHW(rgba, w, h) {
    const n = w * h, out = new Uint8Array(3 * n);
    for (let i = 0; i < n; i++) {
      out[i] = rgba[4 * i];
      out[n + i] = rgba[4 * i + 1];
      out[2 * n + i] = rgba[4 * i + 2];
    }
    return out;
  }
  // 範圍裡用補好的，範圍外完全照原本（模型多少會動到別的像素，不讓它動）
  function composite(orig, chw, mask, w, h) {
    const out = Uint8ClampedArray.from(orig), n = w * h;
    for (let i = 0; i < n; i++) {
      if (!mask[i]) continue;
      out[4 * i] = chw[i];
      out[4 * i + 1] = chw[n + i];
      out[4 * i + 2] = chw[2 * n + i];
    }
    return out;
  }

  // ---------- 遮擋深度：擦掉的地方變成 0（不擋新商品） ----------
  // depth：{ width, height, mm }；深度圖的一格只要碰到擦掉的範圍就是 0（寧可不擋）
  function eraseDepth(depth, mask, w, h) {
    if (!depth) return null;
    const mm = Uint16Array.from(depth.mm), dw = depth.width, dh = depth.height;
    for (let y = 0; y < h; y++) {
      const row = Math.min(dh - 1, Math.floor((y * dh) / h)) * dw;
      for (let x = 0; x < w; x++) {
        if (mask[y * w + x]) mm[row + Math.min(dw - 1, Math.floor((x * dw) / w))] = 0;
      }
    }
    return { ...depth, mm };
  }

  // ---------- 復原 ----------
  // 每一步存一份（照片、擦掉的範圍）；復原就往回一步，最多回到原本。
  // 最多記 MAX_STEPS 步（含原本）：2048 px 的照片一步約 20 MB，太多手機會當掉（Codex 審查）。
  // 超過就丟掉最舊的中間步，原本的一定留著（「全部還原」要用）
  const MAX_STEPS = 8;
  const history = (first) => ({ steps: [first], i: 0 });
  const current = (h) => h.steps[h.i];
  function pushStep(h, s, max = MAX_STEPS) {
    let steps = [...h.steps.slice(0, h.i + 1), s];
    if (steps.length > max) steps = [steps[0], ...steps.slice(steps.length - (max - 1))];
    return { steps, i: steps.length - 1 };
  }
  const undoStep = (h) => ({ ...h, i: Math.max(0, h.i - 1) });
  const resetSteps = (h) => history(h.steps[0]);
  const canUndo = (h) => h.i > 0;

  return {
    SAM_SIDE, samSize, samPrompt, toHWC, maskFromLogits, growPixels, dilate,
    miganMask, toCHW, composite, eraseDepth,
    MAX_STEPS, history, current, pushStep, undoStep, resetSteps, canUndo,
  };
});
