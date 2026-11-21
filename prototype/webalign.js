/* 網頁版 AI 對齊的計算：模型輸出 → 真實的點 → 鏡頭離地、角度、視角、天花板 → 遮擋深度圖。
 * 驗收句子：docs/web-align.md。Python 原版：tools/autoalign/geometry.py、occlusion.py，
 * 和 MoGe 的 infer 後處理（moge/model/v2.py、utils/geometry_numpy.py）。
 *
 * 點陣列：{ rows, cols, data }，data 是 rows × cols × 3 的 OpenCV 鏡頭座標（x 右、y 下、z 前，公尺），
 * 沒有深度是 NaN。輸出的角度用原型（Three.js）的慣例：往下看是正的 pitch。
 *
 * 瀏覽器用 <script src="webalign.js">（window.SetdressAlign），Node 測試用 require。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SetdressAlign = api;
})(typeof self !== 'undefined' ? self : this, () => {
  'use strict';

  // ---------- 跟 geometry.py 一樣的常數 ----------
  const UP_CV = [0, -1, 0];
  const MAX_TILT_DEG = 50;
  const FLOOR_REGION = 0.4, CEILING_REGION = 0.4;
  const RANSAC_ITERS = 300, MAX_SAMPLES = 20000, MIN_POINTS = 200;
  const MIN_PLANE_SHARE = 0.1, FLOOR_MIN_SHARE = 0.03;
  const MIN_CAMERA_HEIGHT_M = 0.3;
  const BIN_M = 0.02, LAYER_KERNEL = [1, 2, 3, 4, 3, 2, 1];
  const LAYER_MIN_SUPPORT = 0.25, LAYER_MIN_GAP_M = 0.15, LAYER_HALF_WIDTH_M = 0.08;
  const REFINE_ITERS = 3, MIN_REFINE_TOL_M = 0.01;
  const CEILING_MIN_ABOVE_CAMERA_M = 0.3, CEILING_MIN_SHARE = 0.03;
  const FLAT_MAX_TILT_DEG = 25, NORMAL_STEP_PX = 2;
  // 跟 occlusion.py 一樣
  const SURFACE_BAND_M = 0.03, SURFACE_BAND_REL = 0.01, MAX_MM = 65535;

  const DEG = Math.PI / 180;
  const COS_MAX_TILT = Math.cos(MAX_TILT_DEG * DEG), COS_FLAT = Math.cos(FLAT_MAX_TILT_DEG * DEG);

  class NoFloorError extends Error {
    constructor(message) {
      super(message);
      this.name = 'NoFloorError';
    }
  }

  // ---------- 小工具 ----------
  const dot = (a, i, n) => a[i] * n[0] + a[i + 1] * n[1] + a[i + 2] * n[2];
  const cross = (u, v) => [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const norm = (v) => Math.hypot(v[0], v[1], v[2]);
  const tolerance = (z) => 0.02 + 0.01 * z; // 離鏡頭越遠，深度越不準，容許的誤差也放寬
  function median(values) {
    const s = Float64Array.from(values).sort();
    const m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }
  // Python 的 round：剛好 .5 時取偶數（四捨六入五成雙）
  function roundHalfEven(x) {
    const f = Math.floor(x), d = x - f;
    if (d !== 0.5) return d < 0.5 ? f : f + 1;
    return f % 2 === 0 ? f : f + 1;
  }
  // 陣列很大時 Math.max(...a) 會超過參數上限
  function maxOf(a) {
    let m = -Infinity;
    for (const v of a) if (v > m) m = v;
    return m;
  }
  // 可以重現的亂數（mulberry32）
  function makeRng(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  // 不重複地抽 k 個索引（只洗前 k 個）
  function pick(n, k, rand) {
    const idx = Uint32Array.from({ length: n }, (_, i) => i);
    for (let i = 0; i < k; i++) {
      const j = i + Math.floor(rand() * (n - i));
      const t = idx[i]; idx[i] = idx[j]; idx[j] = t;
    }
    return idx.subarray(0, k);
  }

  // 一群點：xyz 是 n × 3
  const take = (list, keep) => {
    const out = [];
    for (let i = 0; i < list.n; i++) if (keep(i)) out.push(list.xyz[i * 3], list.xyz[i * 3 + 1], list.xyz[i * 3 + 2]);
    return { xyz: Float64Array.from(out), n: out.length / 3 };
  };

  // ---------- 檢查輸入 ----------
  function checkInput(map, fy) {
    if (!map || !map.data || map.data.length !== map.rows * map.cols * 3) throw new Error('points 要是 (列, 欄, 3) 的陣列');
    if (!(fy > 0)) throw new Error('fy 要大於 0');
  }
  function validMask(map) {
    const n = map.rows * map.cols, d = map.data, ok = new Uint8Array(n);
    for (let p = 0; p < n; p++) {
      const x = d[p * 3], y = d[p * 3 + 1], z = d[p * 3 + 2];
      ok[p] = Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z) && z > 0 ? 1 : 0;
    }
    return ok;
  }
  // 從第 start 到 stop（比例）的列，留下有效的點；同時拿對應的表面朝向
  function rowsOf(map, normals, valid, start, stop) {
    const lo = roundHalfEven(map.rows * start), hi = roundHalfEven(map.rows * stop);
    const pts = [], nrm = [];
    for (let p = lo * map.cols; p < hi * map.cols; p++) {
      if (!valid[p]) continue;
      pts.push(map.data[p * 3], map.data[p * 3 + 1], map.data[p * 3 + 2]);
      nrm.push(normals[p * 3], normals[p * 3 + 1], normals[p * 3 + 2]);
    }
    return { pts: { xyz: Float64Array.from(pts), n: pts.length / 3 }, normals: Float64Array.from(nrm) };
  }

  // 每個像素的表面朝向（單位向量），用左右、上下相隔 2 個像素的點算；算不出來是 NaN
  function gridNormals(map) {
    const { rows, cols, data } = map, s = NORMAL_STEP_PX;
    const out = new Float64Array(rows * cols * 3).fill(NaN);
    if (Math.min(rows, cols) <= 2 * s) return out;
    const at = (r, c, i) => data[(r * cols + c) * 3 + i];
    for (let r = s; r < rows - s; r++) {
      for (let c = s; c < cols - s; c++) {
        const dx = [0, 1, 2].map((i) => at(r, c + s, i) - at(r, c - s, i));
        const dy = [0, 1, 2].map((i) => at(r + s, c, i) - at(r - s, c, i));
        const n = cross(dx, dy), len = norm(n), k = (r * cols + c) * 3;
        out[k] = n[0] / len; out[k + 1] = n[1] / len; out[k + 2] = n[2] / len;
      }
    }
    return out;
  }
  // 表面是不是平躺的（朝上或朝下）
  const isFlat = (normals, i, up) => Math.abs(dot(normals, i * 3, up)) > COS_FLAT;

  // ---------- 最大的水平面（RANSAC） ----------
  function upwardNormal(xyz, ia, ib, ic) {
    const a = [xyz[ia], xyz[ia + 1], xyz[ia + 2]];
    const u = [xyz[ib] - a[0], xyz[ib + 1] - a[1], xyz[ib + 2] - a[2]];
    const v = [xyz[ic] - a[0], xyz[ic + 1] - a[1], xyz[ic + 2] - a[2]];
    let n = cross(u, v);
    const len = norm(n);
    if (len < 1e-9) return null;
    n = n.map((x) => x / len);
    if (n[1] * UP_CV[1] < 0) n = n.map((x) => -x);
    return n[1] * UP_CV[1] >= COS_MAX_TILT ? n : null;
  }
  // MSAC 評分：點越貼近平面分數越高，超過容許誤差就是 0
  function score(xyz, n, tol, a) {
    let s = 0;
    for (let i = 0; i < tol.length; i++) {
      const r = Math.abs(dot(xyz, i * 3, n) - a) / tol[i];
      if (r < 1) s += 1 - r * r;
    }
    return s;
  }
  function dominantPlane(pts, rand) {
    if (pts.n < MIN_POINTS) throw new NoFloorError('看不到地板：照片下半部的點太少');
    const chosen = pick(pts.n, Math.min(pts.n, MAX_SAMPLES), rand);
    const sample = { xyz: new Float64Array(chosen.length * 3), n: chosen.length };
    for (let i = 0; i < chosen.length; i++) for (let k = 0; k < 3; k++) sample.xyz[i * 3 + k] = pts.xyz[chosen[i] * 3 + k];
    const tol = Float64Array.from({ length: sample.n }, (_, i) => tolerance(sample.xyz[i * 3 + 2]));
    let bestScore = 0, best = null;
    for (let it = 0; it < RANSAC_ITERS; it++) {
      const [a, b, c] = pick(sample.n, 3, rand);
      const n = upwardNormal(sample.xyz, a * 3, b * 3, c * 3);
      const s = n ? score(sample.xyz, n, tol, dot(sample.xyz, a * 3, n)) : 0;
      if (s > bestScore) { bestScore = s; best = { n, d: dot(sample.xyz, a * 3, n) }; }
    }
    if (!best) throw new NoFloorError('看不到地板：找不到夠大的水平面');
    const inliers = take(sample, (i) => Math.abs(dot(sample.xyz, i * 3, best.n) - best.d) < tol[i]);
    if (inliers.n < MIN_PLANE_SHARE * sample.n) throw new NoFloorError('看不到地板：找不到夠大的水平面');
    return { up: best.n, level: median(Float64Array.from({ length: inliers.n }, (_, i) => -dot(inliers.xyz, i * 3, best.n))) };
  }

  // ---------- 分層 ----------
  // 把高度分層，回傳每層的中心（由小到大）；一層的密度至少要有最密那層的 minSupport 倍
  function layers(values, minSupport = LAYER_MIN_SUPPORT) {
    let lo = Infinity, hi = -Infinity;
    for (const v of values) { if (v < lo) lo = v; if (v > hi) hi = v; }
    const start = lo - 4 * BIN_M, step = start + BIN_M - start; // 跟 np.arange 一樣的步長
    const nEdges = Math.ceil((hi + 5 * BIN_M - start) / BIN_M);
    const edge = (i) => start + i * step, nBins = nEdges - 1;
    const counts = new Float64Array(nBins);
    for (const v of values) {
      let b = Math.floor((v - start) / step);
      if (b >= nBins) b = nBins - 1;
      if (v < edge(b)) b -= 1; // 浮點誤差：照 np.histogram 的邊界
      else if (b + 1 < nBins && v >= edge(b + 1)) b += 1;
      if (b >= 0 && b < nBins) counts[b] += 1;
    }
    const density = new Float64Array(nBins);
    for (let i = 0; i < nBins; i++) {
      for (let k = -3; k <= 3; k++) if (i + k >= 0 && i + k < nBins) density[i] += counts[i + k] * LAYER_KERNEL[k + 3];
    }
    const top = maxOf(density), peaks = [];
    for (let i = 0; i < nBins; i++) {
      const prev = density[(i - 1 + nBins) % nBins], next = density[(i + 1) % nBins];
      if (density[i] >= prev && density[i] > next && density[i] >= minSupport * top) peaks.push([(edge(i) + edge(i + 1)) / 2, density[i]]);
    }
    return mergeClose(peaks);
  }
  function mergeClose(peaks) {
    const kept = [];
    for (const [c, w] of peaks) {
      const last = kept[kept.length - 1];
      if (last && c - last[0] < LAYER_MIN_GAP_M) {
        if (w > last[1]) kept[kept.length - 1] = [c, w];
        continue;
      }
      kept.push([c, w]);
    }
    return kept.map((k) => k[0]);
  }

  // ---------- 平行平面的最小平方法 ----------
  // 3 × 3 對稱矩陣最小特徵值的特徵向量（Jacobi 轉軸）
  function smallestEigenvector(m) {
    const a = m.map((r) => r.slice()), v = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
    for (let sweep = 0; sweep < 50; sweep++) {
      const off = Math.abs(a[0][1]) + Math.abs(a[0][2]) + Math.abs(a[1][2]);
      if (off < 1e-15) break;
      for (const [p, q] of [[0, 1], [0, 2], [1, 2]]) jacobiRotate(a, v, p, q);
    }
    let k = 0;
    for (let i = 1; i < 3; i++) if (a[i][i] < a[k][k]) k = i;
    return [v[0][k], v[1][k], v[2][k]];
  }
  function jacobiRotate(a, v, p, q) {
    if (Math.abs(a[p][q]) < 1e-300) return;
    const theta = (a[q][q] - a[p][p]) / (2 * a[p][q]);
    const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
    const c = 1 / Math.sqrt(t * t + 1), s = t * c;
    for (let k = 0; k < 3; k++) {
      const akp = a[k][p], akq = a[k][q];
      a[k][p] = c * akp - s * akq; a[k][q] = s * akp + c * akq;
    }
    for (let k = 0; k < 3; k++) {
      const apk = a[p][k], aqk = a[q][k];
      a[p][k] = c * apk - s * aqk; a[q][k] = s * apk + c * aqk;
    }
    for (let k = 0; k < 3; k++) {
      const vkp = v[k][p], vkq = v[k][q];
      v[k][p] = c * vkp - s * vkq; v[k][q] = s * vkp + c * vkq;
    }
  }
  const centroid = (g) => [0, 1, 2].map((i) => { let s = 0; for (let k = 0; k < g.n; k++) s += g.xyz[k * 3 + i]; return s / g.n; });
  // 幾個互相平行的平面 n·p + d = 0（例如地板和床面）共用朝上的 n；第一群是地板
  function parallelPlanes(groups) {
    if (groups[0].n < MIN_POINTS) throw new NoFloorError('看不到地板：地板的點太少');
    const kept = [groups[0], ...groups.slice(1).filter((g) => g.n >= MIN_POINTS)];
    const cents = kept.map(centroid), cov = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
    kept.forEach((g, gi) => {
      for (let k = 0; k < g.n; k++) {
        const d = [0, 1, 2].map((i) => g.xyz[k * 3 + i] - cents[gi][i]);
        for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) cov[i][j] += d[i] * d[j];
      }
    });
    let n = smallestEigenvector(cov);
    if (n[1] * UP_CV[1] < 0) n = n.map((x) => -x);
    return { up: n, offsets: cents.map((c) => -(c[0] * n[0] + c[1] * n[1] + c[2] * n[2])) };
  }

  // ---------- 地板 ----------
  // 平躺的點裡，最低、點又夠多（至少佔下半部 3%）的那層（鏡頭下方多深）
  function floorLevel(below, flat) {
    const lying = below.filter((b, i) => flat[i] && b > 0);
    if (lying.length < MIN_POINTS) throw new NoFloorError('看不到地板：照片下半部沒有平躺的表面');
    const need = FLOOR_MIN_SHARE * below.length;
    const levels = layers(lying, 0).filter((c) => lying.reduce((k, v) => k + (Math.abs(v - c) < LAYER_HALF_WIDTH_M ? 1 : 0), 0) >= need);
    if (!levels.length) throw new NoFloorError('看不到地板：平躺的表面太少');
    return Math.max(...levels);
  }
  function fitFloor(bottom, flat, rough) {
    const below = Float64Array.from({ length: bottom.n }, (_, i) => -dot(bottom.xyz, i * 3, rough.up));
    const floor = floorLevel(below, flat);
    // 最大的水平面不是地板（例如床面）時，床面跟地板平行，一起算方向，高度還是只看地板
    const levels = floor - rough.level >= LAYER_MIN_GAP_M ? [floor, rough.level] : [floor];
    let groups = levels.map((lvl) => take(bottom, (i) => flat[i] && Math.abs(below[i] - lvl) < LAYER_HALF_WIDTH_M));
    const tol = Float64Array.from({ length: bottom.n }, (_, i) => tolerance(bottom.xyz[i * 3 + 2]));
    for (let step = 0; step < REFINE_ITERS; step++) {
      const { up, offsets } = parallelPlanes(groups);
      // 容許誤差一輪比一輪緊，把牆腳那一小條點慢慢擠出去
      const scale = 0.5 ** step;
      const tighter = offsets.map((d) => take(bottom, (i) => Math.abs(dot(bottom.xyz, i * 3, up) + d) < Math.max(tol[i] * scale, MIN_REFINE_TOL_M)));
      if (tighter[0].n < MIN_POINTS) break; // 再擠就沒點了：用上一輪的
      groups = tighter;
    }
    const { up, offsets } = parallelPlanes(groups);
    const height = offsets[0];
    let count = 0;
    for (let i = 0; i < bottom.n; i++) if (Math.abs(dot(bottom.xyz, i * 3, up) + height) < tol[i]) count++;
    checkFloor(up, height, count, bottom.n);
    return { up, height, count };
  }
  function checkFloor(up, height, count, total) {
    if (up[1] * UP_CV[1] < COS_MAX_TILT) throw new NoFloorError('看不到地板：找到的平面不是水平的');
    if (height < MIN_CAMERA_HEIGHT_M) throw new NoFloorError('看不到地板：找到的平面離鏡頭太近');
    if (count < FLOOR_MIN_SHARE * total) throw new NoFloorError('看不到地板：地板的點太少');
  }

  // ---------- 角度 ----------
  // OpenCV 座標的「往上」→ Three.js 的 pitch（往下看為正）和 roll
  function tiltDeg(up) {
    const ux = up[0], uy = -up[1], uz = -up[2];
    return { pitch: Math.asin(Math.max(-1, Math.min(1, uz))) / DEG, roll: Math.atan2(ux, uy) / DEG };
  }
  function upVector(pitchDeg, rollDeg) {
    const p = pitchDeg * DEG, r = rollDeg * DEG;
    return [Math.cos(p) * Math.sin(r), -Math.cos(p) * Math.cos(r), -Math.sin(p)];
  }

  // ---------- 天花板 ----------
  // 比鏡頭高、表面朝下（跟地板平行）的點裡，最高、點又夠多的那層；找不到是 null
  function ceilingHeight(top, normals, up, cameraHeight) {
    if (top.n === 0) return null;
    const above = [];
    for (let i = 0; i < top.n; i++) {
      const h = dot(top.xyz, i * 3, up) + cameraHeight;
      if (isFlat(normals, i, up) && h > cameraHeight + CEILING_MIN_ABOVE_CAMERA_M) above.push(h);
    }
    const need = CEILING_MIN_SHARE * top.n;
    if (above.length < need) return null;
    const level = layers(above).pop();
    if (level === undefined) return null;
    const support = above.filter((h) => Math.abs(h - level) < LAYER_HALF_WIDTH_M);
    return support.length < need ? null : median(support);
  }

  // ---------- 主程式 ----------
  // 回傳 { heightM, pitchDeg, rollDeg, vfovDeg, ceilingM（null = 不知道）, floorInlierRatio }
  function fitCamera(map, fy, { seed = 0 } = {}) {
    checkInput(map, fy);
    const rand = makeRng(seed), valid = validMask(map), normals = gridNormals(map);
    const bottom = rowsOf(map, normals, valid, 1 - FLOOR_REGION, 1);
    const rough = dominantPlane(bottom.pts, rand);
    const flat = Uint8Array.from({ length: bottom.pts.n }, (_, i) => (isFlat(bottom.normals, i, rough.up) ? 1 : 0));
    const floor = fitFloor(bottom.pts, flat, rough);
    const { pitch, roll } = tiltDeg(floor.up);
    const top = rowsOf(map, normals, valid, 0, CEILING_REGION);
    return {
      heightM: floor.height,
      pitchDeg: pitch,
      rollDeg: roll,
      vfovDeg: (2 * Math.atan(map.rows / 2 / fy)) / DEG,
      ceilingM: ceilingHeight(top.pts, top.normals, floor.up, floor.height),
      floorInlierRatio: floor.count / bottom.pts.n,
    };
  }

  // ---------- 遮擋深度圖（occlusion.py） ----------
  // 取最近的點縮小（不平均）：平均會把前面的椅子和後面的牆混成一個不存在的深度
  function shrink(map, maxEdge) {
    const scale = maxEdge / Math.max(map.rows, map.cols);
    if (scale >= 1) return map;
    const rows = roundHalfEven(map.rows * scale), cols = roundHalfEven(map.cols * scale);
    const data = new Float64Array(rows * cols * 3);
    for (let r = 0; r < rows; r++) {
      // 剛好 .5 往上進時，最後一格的來源會超出照片，要夾住
      const sr = Math.min(map.rows - 1, Math.floor((r + 0.5) / scale));
      for (let c = 0; c < cols; c++) {
        const sc = Math.min(map.cols - 1, Math.floor((c + 0.5) / scale));
        const src = (sr * map.cols + sc) * 3, dst = (r * cols + c) * 3;
        data[dst] = map.data[src]; data[dst + 1] = map.data[src + 1]; data[dst + 2] = map.data[src + 2];
      }
    }
    return { rows, cols, data };
  }
  // 地板、天花板、沒有深度的點是 0（不擋）；其他是往正前方的距離（mm）
  function occluderDepthMm(map, fit, maxEdge = 512) {
    const m = shrink(map, maxEdge), up = upVector(fit.pitchDeg, fit.rollDeg);
    const mm = new Uint16Array(m.rows * m.cols);
    for (let p = 0; p < mm.length; p++) {
      const z = m.data[p * 3 + 2], h = dot(m.data, p * 3, up) + fit.heightM, band = SURFACE_BAND_M + SURFACE_BAND_REL * z;
      const open = !Number.isFinite(h) || !(z > 0) || h < band || (fit.ceilingM !== null && h > fit.ceilingM - band);
      mm[p] = open ? 0 : Math.min(MAX_MM, Math.max(1, roundHalfEven(z * 1000)));
    }
    return { width: m.cols, height: m.rows, mm };
  }

  // ---------- MoGe 的後處理（infer） ----------
  // 每邊取 size 個點（最近的，跟 PyTorch 的 nearest 一樣）
  const nearest = (n, size) => Uint32Array.from({ length: size }, (_, i) => Math.floor((i * n) / size));
  // 每邊取 size 個點（模型說有深度、xyz 都是正常數字的），配上它們在畫面上的 uv
  function focalShiftSamples(points, mask, rows, cols, size = 64) {
    const aspect = cols / rows, diag = Math.sqrt(1 + aspect * aspect);
    const spanX = aspect / diag, spanY = 1 / diag;
    const uv = [], xyz = [];
    for (const r of nearest(rows, size)) {
      for (const c of nearest(cols, size)) {
        const p = r * cols + c, x = points[p * 3], y = points[p * 3 + 1], z = points[p * 3 + 2];
        if (!mask[p] || !Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;
        uv.push((spanX * (2 * c + 1 - cols)) / cols, (spanY * (2 * r + 1 - rows)) / rows);
        xyz.push(x, y, z);
      }
    }
    return { uv, xyz };
  }
  function bestFocal(uv, xyz, shift) {
    let num = 0, den = 0;
    for (let k = 0; k < uv.length / 2; k++) {
      const w = xyz[k * 3 + 2] + shift, px = xyz[k * 3] / w, py = xyz[k * 3 + 1] / w;
      num += px * uv[2 * k] + py * uv[2 * k + 1];
      den += px * px + py * py;
    }
    return num / den;
  }
  // 殘差：f × xy / (z + shift) − uv（f 用這個 shift 下最好的焦距）
  function residuals(uv, xyz, shift, out) {
    const f = bestFocal(uv, xyz, shift);
    for (let k = 0; k < uv.length / 2; k++) {
      const w = xyz[k * 3 + 2] + shift;
      out[2 * k] = (f * xyz[k * 3]) / w - uv[2 * k];
      out[2 * k + 1] = (f * xyz[k * 3 + 1]) / w - uv[2 * k + 1];
    }
    return out;
  }
  function focalShiftCost(uv, xyz, shift) {
    let c = 0;
    for (const r of residuals(uv, xyz, shift, new Float64Array(uv.length))) c += r * r;
    return Number.isFinite(c) ? c : Infinity;
  }
  // Levenberg–Marquardt（跟 scipy 的 least_squares(method='lm') 一樣用殘差，從 0 開始），
  // 一個變數，Jacobian 用中央差分。回傳 { shift, ok }
  function solveShift(uv, xyz) {
    const r = new Float64Array(uv.length), rp = new Float64Array(uv.length), rm = new Float64Array(uv.length);
    let s = 0, c = focalShiftCost(uv, xyz, s), lambda = 1e-3;
    if (!Number.isFinite(c)) return { shift: s, ok: false };
    for (let it = 0; it < 100; it++) {
      residuals(uv, xyz, s, r);
      const h = 1e-7 * (1 + Math.abs(s));
      residuals(uv, xyz, s + h, rp);
      residuals(uv, xyz, s - h, rm);
      let g = 0, jj = 0;
      for (let k = 0; k < r.length; k++) {
        const j = (rp[k] - rm[k]) / (2 * h);
        g += j * r[k];
        jj += j * j;
      }
      if (!(jj > 0) || !Number.isFinite(g)) break;
      const step = -g / (jj * (1 + lambda)), cn = focalShiftCost(uv, xyz, s + step);
      if (cn < c) {
        const done = c - cn <= 1e-14 * c || Math.abs(step) <= 1e-12 * (1 + Math.abs(s));
        s += step; c = cn; lambda = Math.max(lambda / 10, 1e-15);
        if (done) break;
      } else if ((lambda *= 10) > 1e15) {
        break;
      }
    }
    return { shift: s, ok: Number.isFinite(s) && Number.isFinite(c) };
  }
  // 解 min |focal × xy / (z + shift) − uv|：focal 是相對於半條對角線的焦距
  function recoverFocalShift(points, mask, rows, cols, size = 64) {
    const { uv, xyz } = focalShiftSamples(points, mask, rows, cols, size);
    if (uv.length < 4) return { focal: 1, shift: 0 }; // 跟 MoGe 一樣：點太少就不算
    const { shift, ok } = solveShift(uv, xyz);
    const focal = bestFocal(uv, xyz, shift);
    if (!ok || !(focal > 0) || !Number.isFinite(focal)) throw new Error('AI 算不出焦距和深度');
    return { focal, shift };
  }
  // 模型輸出（相對的點、有沒有深度的機率、真實尺寸的倍數）→ 真實的點和 fy（像素）
  function modelOutputToPoints({ points, mask, metricScale, rows, cols }) {
    if (!(metricScale > 0) || !Number.isFinite(metricScale)) throw new Error('模型給的真實尺寸倍數不對');
    const ok = Uint8Array.from(mask, (m) => (m > 0.5 ? 1 : 0));
    const { focal, shift } = recoverFocalShift(points, ok, rows, cols);
    const aspect = cols / rows, diag = Math.sqrt(1 + aspect * aspect);
    const fx = (focal / 2) * diag / aspect, fy = (focal / 2) * diag;
    const data = new Float64Array(rows * cols * 3);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const p = r * cols + c, depth = points[p * 3 + 2] + shift;
        if (!ok[p] || !(depth > 0)) { data[p * 3] = data[p * 3 + 1] = data[p * 3 + 2] = NaN; continue; }
        const z = depth * metricScale;
        data[p * 3] = (((c + 0.5) / cols - 0.5) / fx) * z;
        data[p * 3 + 1] = (((r + 0.5) / rows - 0.5) / fy) * z;
        data[p * 3 + 2] = z;
      }
    }
    return { map: { rows, cols, data }, fy: fy * rows };
  }

  // 照長寬比分 token（跟 MoGe 的 forward 一樣，Python 的 round）
  function tokenGrid(width, height, tokens) {
    const aspect = width / height;
    return { rows: roundHalfEven(Math.sqrt(tokens / aspect)), cols: roundHalfEven(Math.sqrt(tokens * aspect)) };
  }
  // 餵給模型的照片大小：寬是 token 格子 × 14，高照照片的長寬比（不能拉長：拉長了焦距就不對）
  function modelInputSize(width, height, tokens) {
    const w = tokenGrid(width, height, tokens).cols * 14;
    return { width: w, height: roundHalfEven((w * height) / width) };
  }

  // ---------- 量尺（docs/ruler.md） ----------
  // 原型的鏡頭（Three.js：往 -z 看、y 往上，旋轉順序 YXZ、y 轉 0）：房間座標 = Rx(-pitch) · Rz(roll) · 鏡頭座標
  // cam：{ height, pitch, roll, fov（垂直視角，度）, aspect（寬 / 高）, ceiling（公尺或 null） }
  function camRotation(cam) {
    const a = -cam.pitch * DEG, b = cam.roll * DEG;
    const ca = Math.cos(a), sa = Math.sin(a), cb = Math.cos(b), sb = Math.sin(b);
    return [
      [cb, -sb, 0],
      [ca * sb, ca * cb, -sa],
      [sa * sb, sa * cb, ca],
    ];
  }
  // 照片上的位置（u 往右、v 往下，0–1）在深度圖裡的距離（往正前方，公尺）；沒有是 0
  function depthAt(depth, u, v) {
    if (!depth || !depth.meters) return 0;
    const col = Math.min(depth.width - 1, Math.max(0, Math.floor(u * depth.width)));
    const row = Math.min(depth.height - 1, Math.max(0, Math.floor(v * depth.height)));
    return depth.meters[row * depth.width + col] || 0;
  }
  const along = (o, dir, t) => o.map((x, i) => x + dir[i] * t);
  // 打到地板（往下看）或天花板（往上看、知道天花板多高）；線幾乎水平就量不到
  function planePoint(o, dir, cam) {
    const EPS = 1e-6;
    if (dir[1] < -EPS) return { point: along(o, dir, -o[1] / dir[1]), from: 'floor' };
    if (dir[1] > EPS && cam.ceiling != null) return { point: along(o, dir, (cam.ceiling - o[1]) / dir[1]), from: 'ceiling' };
    return null;
  }
  // 照片上的一點 → 房間裡的點：有深度用深度，沒有就打到地板或天花板。回傳 { point, from } 或 null（量不到）
  function rulerPoint(cam, u, v, depth) {
    const t = Math.tan((cam.fov * DEG) / 2), c = [(2 * u - 1) * t * cam.aspect, (1 - 2 * v) * t, -1];
    const R = camRotation(cam), dir = R.map((r) => r[0] * c[0] + r[1] * c[1] + r[2] * c[2]);
    const o = [0, cam.height, 0], d = depthAt(depth, u, v);
    // 鏡頭座標的 z 是 -1，乘上 d 剛好往正前方 d 公尺
    return d > 0 ? { point: along(o, dir, d), from: 'depth' } : planePoint(o, dir, cam);
  }
  // ---------- 牆往哪個方向（docs/model3d.md 第 12 句）----------
  // 照片上撒格子點、用深度換成房間裡的點（跟量尺同一套），相鄰三點算面的方向；
  // 直立的面（牆、櫃子、沙發側面）的方向對 90° 取餘數投票（房間的牆通常互相垂直），最多的就是牆。
  // 回 0 到 90 度（0 是牆跟畫面平行）；直立的面太少（沒有深度）回 null
  const WALL_GRID = 64, WALL_MIN_VOTES = 60, WALL_MAX_UP = 0.25, WALL_JUMP = 0.15, WALL_SMOOTH = 3;
  const WALL_MIN_SHARE = 0.2; // 最多的那個方向（左右 3°）至少要有這麼多的票，不然是亂的房間、不猜（Codex 審查）
  // 格子點落在深度圖的像素中心（不然相鄰兩點會讀到同一個像素，面看起來一階一階、方向偏向正對鏡頭）
  function wallGrid(cam, depth) {
    const t = Math.tan((cam.fov * DEG) / 2), R = camRotation(cam), o = [0, cam.height, 0];
    const step = Math.max(1, Math.floor(Math.max(depth.width, depth.height) / WALL_GRID));
    const cols = Math.floor(depth.width / step), rows = Math.floor(depth.height / step), pts = [];
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const px = col * step, py = row * step, raw = depth.meters[py * depth.width + px];
        const d = Number.isFinite(raw) ? raw : 0; // 無限大、不是數字的點跳過（Codex 審查）
        const u = (px + 0.5) / depth.width, v = (py + 0.5) / depth.height;
        const c = [(2 * u - 1) * t * cam.aspect, (1 - 2 * v) * t, -1];
        pts.push(d > 0 ? along(o, R.map((r) => r[0] * c[0] + r[1] * c[1] + r[2] * c[2]), d) : null);
      }
    }
    return { pts, cols, rows };
  }
  const sub3 = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const len3 = (a) => Math.hypot(a[0], a[1], a[2]);
  // 三個相鄰的點圍成的面，是直立的話回它朝哪（度，水平方向）；不是、或跨過深度斷掉的地方回 null
  function uprightFacing(a, b, c) {
    if (!a || !b || !c) return null;
    const ab = sub3(b, a), ac = sub3(c, a), far = WALL_JUMP * len3(a);
    if (len3(ab) > far || len3(ac) > far) return null;
    const n = [ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0]];
    const size = len3(n);
    if (!size || Math.abs(n[1] / size) > WALL_MAX_UP) return null;
    return Math.atan2(n[0], n[2]) / DEG;
  }
  // 1° 一格的票，左右抹平後最高的那格，再用附近的票算小數；最高的那組票太少（沒有明顯的方向）回 null
  function peakDeg(votes) {
    const at = (i) => votes[((i % 90) + 90) % 90];
    let best = 0, bestScore = -1;
    for (let i = 0; i < 90; i++) {
      let score = 0;
      for (let k = -WALL_SMOOTH; k <= WALL_SMOOTH; k++) score += at(i + k);
      if (score > bestScore) { best = i; bestScore = score; }
    }
    const total = votes.reduce((a, b) => a + b, 0);
    if (!total || bestScore < WALL_MIN_SHARE * total) return null;
    let sum = 0, weight = 0;
    for (let k = -WALL_SMOOTH; k <= WALL_SMOOTH; k++) { sum += (best + k + 0.5) * at(best + k); weight += at(best + k); }
    return (((sum / weight) % 90) + 90) % 90;
  }
  function wallAngle(cam, depth) {
    if (!depth || !depth.meters) return null;
    const { pts, cols, rows } = wallGrid(cam, depth), votes = new Float32Array(90);
    let count = 0;
    for (let row = 0; row < rows - 1; row++) {
      for (let col = 0; col < cols - 1; col++) {
        const i = row * cols + col, deg = uprightFacing(pts[i], pts[i + 1], pts[i + cols]);
        if (deg === null) continue;
        votes[Math.floor((((deg % 90) + 90) % 90)) % 90] += 1;
        count++;
      }
    }
    return count < WALL_MIN_VOTES ? null : peakDeg(votes);
  }

  // 房間裡的一點 → 照片上的位置 { u, v }
  function projectToPhoto(cam, p) {
    const R = camRotation(cam), w = [p[0], p[1] - cam.height, p[2]];
    const c = [0, 1, 2].map((j) => R[0][j] * w[0] + R[1][j] * w[1] + R[2][j] * w[2]); // R 的轉置
    const t = Math.tan((cam.fov * DEG) / 2);
    return { u: (c[0] / -c[2] / (t * cam.aspect) + 1) / 2, v: (1 - c[1] / -c[2] / t) / 2 };
  }

  // 跟本機服務（server.py）回傳的一樣：5 個滑桿的值＋遮擋深度圖（mm 是 Uint16Array）
  function alignResult(map, fy, opts) {
    const fit = fitCamera(map, fy, opts);
    return {
      height_m: fit.heightM,
      pitch_deg: fit.pitchDeg,
      roll_deg: fit.rollDeg,
      vfov_deg: fit.vfovDeg,
      ceiling_m: fit.ceilingM,
      depth: occluderDepthMm(map, fit),
    };
  }

  return {
    NoFloorError, fitCamera, upVector, tiltDeg, occluderDepthMm, recoverFocalShift, modelOutputToPoints,
    tokenGrid, modelInputSize, alignResult, rulerPoint, projectToPhoto, wallAngle,
    _internal: { layers, focalShiftSamples, focalShiftCost, peakDeg, uprightFacing }, // 只給測試用
  };
});
