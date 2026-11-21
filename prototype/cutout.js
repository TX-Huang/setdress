/* 商品照去背（docs/goods.md 6–8）：在瀏覽器裡做，照片不用先下載處理。
 *
 * 跟描燈的輪廓（tools/outline/outline.py）同一個方法：
 *   1. 背景色：照片邊框上常見的顏色（佔邊框兩成以上的都算；都不夠多就用中位數）
 *   2. 背景：跟背景色像的、從邊框往裡長得到的（白燈罩拍在白底上，有一圈淡灰邊就不會被吃掉）
 *   3. 留下最大的一塊，跟它差不多大的（一組兩件）也留；小灰塵丟掉
 *   4. 攝影棚地上的淡灰影子拿掉（模擬器自己畫影子）：每一行從最下面往上，一路變暗的灰色拿掉，
 *      往上變亮（白色商品）、變深或有顏色（商品本身）就停；只看商品範圍最下面三成
 *   5. 邊緣往內縮一個像素，免得留白邊
 * 只有「單色背景的商品照」才用：邊框大部分是背景、背景佔整張三成以上、商品沒碰到左右下三邊
 * （吊燈可以碰到上面，電線從上面下來）。
 *
 * cutout({ data: RGBA, width, height }, { allowTop }) →
 *   { ok: true, box: [x0, y0, x1, y1], alpha: Uint8Array(寬 x 高，0 或 255) }
 *   { ok: false, reason: 'scene' 不是單色背景 | 'cut' 切到商品 | 'empty' 找不到商品 }
 *
 * 瀏覽器用 <script src="cutout.js">（window.SetdressCutout），Node 測試用 require。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SetdressCutout = api;
})(typeof self !== 'undefined' ? self : this, () => {
  'use strict';

  const BG_TOL = 16; // 跟背景色差多少以內算背景（RGB 距離；網路上的照片有壓縮雜訊，比描燈的 12 寬一點）
  const BORDER_SHARE = 0.2; // 邊框上佔這麼多以上的顏色，都算背景色（一成的話，碰到邊的商品自己的顏色也會被算進去）
  const BORDER_BG = 0.9; // 邊框至少這麼多是背景，才算單色背景
  const MOSTLY = 0.5; // 邊框連一半都不是背景：一定是房間裡拍的（不用再看有沒有切到）
  const MIN_BG = 0.3; // 背景至少佔整張這麼多
  const KEEP_SHARE = 0.15; // 跟最大那塊比，大過這麼多的也留（一組兩件）
  const SHADOW_SHARE = 0.3; // 影子只在商品範圍最下面這三成找
  const SHADOW_DARK = 70; // 比背景暗不超過這麼多的灰色，才可能是影子
  const NEUTRAL = 14; // RGB 最大最小差不超過這麼多，算灰色
  const LIGHTER = 18; // 往上變亮超過這麼多：碰到（白色的）商品了

  // 邊框上的像素位置
  function borderIndexes(w, h) {
    const out = [];
    for (let x = 0; x < w; x++) out.push(x, (h - 1) * w + x);
    for (let y = 1; y < h - 1; y++) out.push(y * w, y * w + w - 1);
    return out;
  }

  // 邊框常見的顏色（每 16 一格分組，佔一成以上的取平均）；都不夠多就用中位數
  function borderColours(data, edge) {
    const bins = new Map();
    for (const i of edge) {
      const k = ((data[i * 4] >> 4) << 8 | (data[i * 4 + 1] >> 4) << 4 | (data[i * 4 + 2] >> 4));
      const b = bins.get(k) || { n: 0, r: 0, g: 0, b: 0 };
      b.n++; b.r += data[i * 4]; b.g += data[i * 4 + 1]; b.b += data[i * 4 + 2];
      bins.set(k, b);
    }
    const common = [...bins.values()].filter((b) => b.n >= BORDER_SHARE * edge.length);
    if (common.length) return common.map((b) => [b.r / b.n, b.g / b.n, b.b / b.n]);
    const median = (c) => edge.map((i) => data[i * 4 + c]).sort((a, b) => a - b)[edge.length >> 1];
    return [[median(0), median(1), median(2)]];
  }

  // 每個像素像不像背景（透明的一定是）
  function similarMap(data, n, colours) {
    const out = new Uint8Array(n), tol2 = BG_TOL * BG_TOL;
    for (let i = 0; i < n; i++) {
      if (data[i * 4 + 3] < 128) { out[i] = 1; continue; }
      const r = data[i * 4], g = data[i * 4 + 1], b = data[i * 4 + 2];
      for (const c of colours) {
        const dr = r - c[0], dg = g - c[1], db = b - c[2];
        if (dr * dr + dg * dg + db * db <= tol2) { out[i] = 1; break; }
      }
    }
    return out;
  }

  // 上下左右的鄰居
  function eachNeighbour(i, w, n, visit) {
    const x = i % w;
    if (x > 0) visit(i - 1);
    if (x < w - 1) visit(i + 1);
    if (i >= w) visit(i - w);
    if (i < n - w) visit(i + w);
  }

  // 從 seeds 往上下左右長，只長在 allowed 是 1 的地方；回 Uint8Array（1 = 長到了）
  function grow(seeds, allowed, w, h) {
    const n = w * h, got = new Uint8Array(n), queue = new Int32Array(n);
    let head = 0, tail = 0;
    const push = (i) => { if (allowed[i] && !got[i]) { got[i] = 1; queue[tail++] = i; } };
    for (const i of seeds) push(i);
    while (head < tail) eachNeighbour(queue[head++], w, n, push);
    return got;
  }

  // 不是背景的、連在一起的幾塊（每塊是像素位置的陣列），由大到小。每個像素只看一次
  function pieces(bg, w, h) {
    const n = w * h, seen = new Uint8Array(n), queue = new Int32Array(n), out = [];
    let head = 0, tail = 0;
    const push = (i) => { if (!bg[i] && !seen[i]) { seen[i] = 1; queue[tail++] = i; } };
    for (let s = 0; s < n; s++) {
      if (bg[s] || seen[s]) continue;
      const start = tail;
      push(s);
      head = start;
      while (head < tail) eachNeighbour(queue[head++], w, n, push);
      out.push(queue.slice(start, tail));
    }
    return out.sort((a, b) => b.length - a.length);
  }

  function boxOf(pixels, w) {
    let x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1;
    for (const i of pixels) {
      const x = i % w, y = (i - x) / w;
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
    return [x0, y0, x1 + 1, y1 + 1];
  }

  const lumAt = (d, i) => (d[i * 4] + d[i * 4 + 1] + d[i * 4 + 2]) / 3;
  const greyAt = (d, i) => Math.max(d[i * 4], d[i * 4 + 1], d[i * 4 + 2]) - Math.min(d[i * 4], d[i * 4 + 1], d[i * 4 + 2]) <= NEUTRAL;

  // 影子比背景暗、但暗不超過 SHADOW_DARK（黑底、透明底的照片，商品比背景亮，不會被當成影子）
  const shadowLum = (lum, bgLum) => lum <= bgLum && lum >= bgLum - SHADOW_DARK;

  // 一行（x）從最下面的商品像素往上：淡灰、一路變暗的是影子，拿掉；回拿掉幾個
  function dropShadowRun(data, keep, w, x, [y1, top], bgLum) {
    let y = y1 - 1, darkest = Infinity, dropped = 0;
    while (y >= top && !keep[y * w + x]) y--; // 底下本來就是背景的跳過
    for (; y >= top; y--) {
      const i = y * w + x, lum = lumAt(data, i);
      if (!keep[i] || !greyAt(data, i) || !shadowLum(lum, bgLum) || lum > darkest + LIGHTER) break;
      darkest = Math.min(darkest, lum);
      keep[i] = 0;
      dropped++;
    }
    return dropped;
  }
  function dropStudioShadow(data, keep, w, box, bgLum) {
    const [x0, y0, x1, y1] = box, top = y1 - Math.ceil((y1 - y0) * SHADOW_SHARE);
    let dropped = 0;
    for (let x = x0; x < x1; x++) dropped += dropShadowRun(data, keep, w, x, [y1, top], bgLum);
    return dropped;
  }
  function maskBox(keep, w, h) {
    const on = [];
    for (let i = 0; i < w * h; i++) if (keep[i]) on.push(i);
    return on.length ? boxOf(on, w) : null;
  }

  // 留下的範圍往內縮一個像素：上下左右有一個不是商品，就拿掉
  function shrink(keep, w, h) {
    const n = w * h, out = new Uint8Array(n);
    for (let i = 0; i < n; i++) {
      if (!keep[i]) continue;
      const x = i % w;
      const inside = x > 0 && x < w - 1 && i >= w && i < n - w
        && keep[i - 1] && keep[i + 1] && keep[i - w] && keep[i + w];
      out[i] = inside ? 255 : 0;
    }
    return out;
  }

  function touches([x0, y0, x1, y1], w, h, allowTop) {
    return x0 === 0 || x1 === w || y1 === h || (!allowTop && y0 === 0);
  }

  function cutout(img, { allowTop = false } = {}) {
    const { data, width: w, height: h } = img, n = w * h;
    const edge = borderIndexes(w, h);
    // 背景色只看不透明的邊框：透明背景的 PNG，透明像素讀出來常是黑的，不能拿來比（黑色商品會被吃掉）
    const opaque = edge.filter((i) => data[i * 4 + 3] >= 128);
    const colours = opaque.length >= edge.length / 2 ? borderColours(data, opaque) : [];
    const bg = grow(edge, similarMap(data, n, colours), w, h);
    let bgCount = 0;
    for (let i = 0; i < n; i++) bgCount += bg[i];
    const edgeBg = edge.reduce((s, i) => s + bg[i], 0) / edge.length;
    if (bgCount === n) return { ok: false, reason: 'empty' };
    if (edgeBg < MOSTLY) return { ok: false, reason: 'scene' };
    const all = pieces(bg, w, h);
    const kept = all.filter((p) => p.length >= KEEP_SHARE * all[0].length);
    const keep = new Uint8Array(n);
    for (const p of kept) for (const i of p) keep[i] = 1;
    const first = kept.map((p) => boxOf(p, w)).reduce((a, b) => [
      Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])]);
    // 先看有沒有切到商品，再拿掉影子（不然碰到下面的淺灰商品，底部被當影子拿掉就變成「沒碰到」）
    if (touches(first, w, h, allowTop)) return { ok: false, reason: 'cut' };
    const bgLum = Math.max(...colours.map((c) => (c[0] + c[1] + c[2]) / 3));
    const box = dropStudioShadow(data, keep, w, first, bgLum) ? maskBox(keep, w, h) : first;
    if (!box) return { ok: false, reason: 'empty' };
    if (edgeBg < BORDER_BG || bgCount < MIN_BG * n) return { ok: false, reason: 'scene' };
    return { ok: true, box, alpha: shrink(keep, w, h) };
  }

  // 去背以外的地方用最近的商品顏色補（AI 生的 3D 從正面投影照片：側面會碰到照片的背景，
  // 不補會出現白邊；docs/model3d.md 第 9 句）。data：RGBA（直接改），alpha：0 或 255
  function fillBackground(data, alpha, w, h) {
    const n = w * h, from = new Int32Array(n).fill(-1), queue = new Int32Array(n);
    let head = 0, tail = 0;
    for (let i = 0; i < n; i++) if (alpha[i] >= 128) { from[i] = i; queue[tail++] = i; }
    // 一層一層往外長（每個像素只看一次；不為每個像素做新的函式，手機比較快：Codex 審查）
    let src = -1;
    const visit = (j) => { if (from[j] < 0) { from[j] = src; queue[tail++] = j; } };
    while (head < tail) {
      const i = queue[head++];
      src = from[i];
      eachNeighbour(i, w, n, visit);
    }
    for (let i = 0; i < n; i++) {
      if (from[i] < 0 || from[i] === i) continue;
      const s = from[i] * 4;
      data[i * 4] = data[s]; data[i * 4 + 1] = data[s + 1]; data[i * 4 + 2] = data[s + 2]; data[i * 4 + 3] = 255;
    }
  }

  // 照片的平滑顏色（docs/model3d.md 第 17 句）：縮成長邊 cells 格，每格是那一格的平均。
  // 3D 照片沒拍到的側面、背面用它（放大時格子之間平滑過渡），沒有拉長的條紋。照片比格子小就照原本
  function softColors(data, w, h, cells) {
    const scale = Math.min(1, cells / Math.max(w, h));
    const cw = Math.max(1, Math.round(w * scale)), ch = Math.max(1, Math.round(h * scale));
    const out = new Uint8ClampedArray(cw * ch * 4);
    for (let gy = 0; gy < ch; gy++) {
      const y0 = Math.floor((gy * h) / ch), y1 = Math.floor(((gy + 1) * h) / ch);
      for (let gx = 0; gx < cw; gx++) {
        const x0 = Math.floor((gx * w) / cw), x1 = Math.floor(((gx + 1) * w) / cw);
        const sum = [0, 0, 0];
        for (let y = y0; y < y1; y++) {
          for (let x = x0; x < x1; x++) for (let c = 0; c < 3; c++) sum[c] += data[(y * w + x) * 4 + c];
        }
        const n = (x1 - x0) * (y1 - y0), o = (gy * cw + gx) * 4;
        out.set([sum[0] / n, sum[1] / n, sum[2] / n, 255], o); // Uint8ClampedArray 會四捨五入
      }
    }
    return { data: out, w: cw, h: ch };
  }

  return { cutout, fillBackground, softColors, BG_TOL };
});
