// 電腦做出來的假房間（tools/autoalign/tests/synthetic_room.py 的 JS 版）：答案已知，讓測試量得出誤差。
// 假房間：地板 y = 0、天花板 y = 天花板高度、左右牆 x = ±2.5、後牆 z = -6、鏡頭後面的牆 z = 1。
// 鏡頭在 (0, 鏡頭離地, 0)，用 Three.js 的慣例擺：往 -z 看、往下看是正的 pitch、繞前方軸轉是 roll。
// 點陣列：{ rows, cols, data }，data 是 rows × cols × 3 的 OpenCV 鏡頭座標（x 右、y 下、z 前），沒有深度是 NaN。
'use strict';

const ROOM_X = 2.5, ROOM_Z_BACK = -6.0, ROOM_Z_FRONT = 1.0;
const box = (lo, hi) => ({ lo, hi });

const SOFA = box([-1.2, 0.0, -5.9], [1.2, 0.45, -5.0]);
const SIDE_TABLE = box([-1.0, 0.72, -2.6], [1.0, 0.75, -1.6]);
const LOW_PLATFORM = box([-2.0, 0.42, -3.2], [2.0, 0.45, -1.5]);
const BED = box([-2.5, 0.0, -3.5], [0.7, 0.5, -0.2]);
const FUTON = box([-2.5, 0.0, -4.0], [1.5, 0.22, -0.2]);
// 天花板降一階（常見的格局）：後段從 3.0 m 降到 2.5 m
const SOFFIT = box([-2.5, 2.5, -6.0], [2.5, 3.0, -3.0]);
// 廚房吊櫃：底面朝下、只比鏡頭高 15 cm，不是天花板
const UPPER_CABINET = box([-2.5, 1.5, -6.0], [2.5, 2.3, -3.5]);

const DEFAULT_SHOT = { height: 1.35, pitch: 10, roll: 0, vfov: 55, ceiling: 2.7, width: 160, rows: 120, boxes: [] };
const shot = (o = {}) => ({ ...DEFAULT_SHOT, ...o });

const rad = (d) => (d * Math.PI) / 180;
// world_from_cam = Rx(-pitch) · Rz(roll)
function worldFromCam(s) {
  const a = rad(-s.pitch), b = rad(s.roll);
  const ca = Math.cos(a), sa = Math.sin(a), cb = Math.cos(b), sb = Math.sin(b);
  const rx = [[1, 0, 0], [0, ca, -sa], [0, sa, ca]];
  const rz = [[cb, -sb, 0], [sb, cb, 0], [0, 0, 1]];
  return rx.map((r) => [0, 1, 2].map((j) => r[0] * rz[0][j] + r[1] * rz[1][j] + r[2] * rz[2][j]));
}

function hitRoom(o, d, ceiling) {
  let t = Infinity;
  for (const [axis, value] of [[1, 0], [1, ceiling], [0, -ROOM_X], [0, ROOM_X], [2, ROOM_Z_BACK], [2, ROOM_Z_FRONT]]) {
    const tt = (value - o[axis]) / d[axis];
    if (tt > 1e-6 && tt < t) t = tt;
  }
  return t;
}
function hitBox(o, d, b) {
  let near = -Infinity, far = Infinity;
  for (let i = 0; i < 3; i++) {
    const t1 = (b.lo[i] - o[i]) / d[i], t2 = (b.hi[i] - o[i]) / d[i];
    near = Math.max(near, Math.min(t1, t2));
    far = Math.min(far, Math.max(t1, t2));
  }
  return far >= near && near > 1e-6 ? near : Infinity;
}

// 回傳 { map, fy }
function render(s) {
  const fy = s.rows / 2 / Math.tan(rad(s.vfov) / 2);
  const R = worldFromCam(s), o = [0, s.height, 0];
  const data = new Float64Array(s.rows * s.width * 3);
  for (let j = 0; j < s.rows; j++) {
    for (let i = 0; i < s.width; i++) {
      const c = [(i + 0.5 - s.width / 2) / fy, -(j + 0.5 - s.rows / 2) / fy, -1];
      const d = R.map((r) => r[0] * c[0] + r[1] * c[1] + r[2] * c[2]);
      let t = hitRoom(o, d, s.ceiling);
      for (const b of s.boxes) t = Math.min(t, hitBox(o, d, b));
      // 鏡頭座標 = dirs_cam × t；OpenCV 是 (x, -y, -z)
      const k = (j * s.width + i) * 3;
      data[k] = c[0] * t;
      data[k + 1] = -c[1] * t;
      data[k + 2] = -c[2] * t;
    }
  }
  return { map: { rows: s.rows, cols: s.width, data }, fy };
}

// 鏡頭座標 → 房間座標
function toWorld(map, s) {
  const R = worldFromCam(s), out = new Float64Array(map.data.length);
  for (let k = 0; k < map.data.length; k += 3) {
    const c = [map.data[k], -map.data[k + 1], -map.data[k + 2]];
    for (let i = 0; i < 3; i++) out[k + i] = (i === 1 ? s.height : 0) + R[i][0] * c[0] + R[i][1] * c[1] + R[i][2] * c[2];
  }
  return out;
}

// 可以重現的亂數（mulberry32）和常態分布（Box-Muller）
function rng(seed) {
  let a = seed >>> 0;
  const uniform = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const normal = () => Math.sqrt(-2 * Math.log(1 - uniform())) * Math.cos(2 * Math.PI * uniform());
  return { uniform, normal };
}
// 每個點的 x、y、z 乘上同一個倍數（沿著視線方向伸縮），f(p) 每個點只叫一次
const scaled = (map, f) => {
  const data = new Float64Array(map.data);
  for (let p = 0; p < map.rows * map.cols; p++) {
    const k = f(p);
    for (let i = 0; i < 3; i++) data[p * 3 + i] *= k;
  }
  return { ...map, data };
};
// 沿著視線方向加雜訊：每個點的距離乘上 (1 + rel × 常態分布)
function withNoise(map, rel, seed) {
  const r = rng(seed);
  return scaled(map, () => 1 + rel * r.normal());
}
// 像真的深度模型那樣錯：一大片一大片、慢慢變化（粗格子上抽亂數，再平滑放大）
function withSmoothNoise(map, rel, seed, cells = 6) {
  const r = rng(seed), coarse = Array.from({ length: cells * cells }, () => r.normal());
  const at = (y, x) => coarse[y * cells + x];
  return scaled(map, (p) => {
    const row = Math.floor(p / map.cols), col = p % map.cols;
    const ys = (row * (cells - 1)) / (map.rows - 1), xs = (col * (cells - 1)) / (map.cols - 1);
    const y0 = Math.min(Math.floor(ys), cells - 2), x0 = Math.min(Math.floor(xs), cells - 2);
    const wy = ys - y0, wx = xs - x0;
    const field = at(y0, x0) * (1 - wy) * (1 - wx) + at(y0 + 1, x0) * wy * (1 - wx)
      + at(y0, x0 + 1) * (1 - wy) * wx + at(y0 + 1, x0 + 1) * wy * wx;
    return 1 + rel * field;
  });
}
function withHoles(map, share, seed) {
  const r = rng(seed), data = new Float64Array(map.data);
  for (let p = 0; p < map.rows * map.cols; p++) if (r.uniform() < share) data[p * 3] = data[p * 3 + 1] = data[p * 3 + 2] = NaN;
  return { ...map, data };
}

module.exports = {
  SOFA, SIDE_TABLE, LOW_PLATFORM, BED, FUTON, SOFFIT, UPPER_CABINET, shot, render, toWorld, withNoise, withSmoothNoise, withHoles,
};
