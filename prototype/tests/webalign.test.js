// 網頁版 AI 對齊的計算（webalign.js）。驗收句子：docs/web-align.md
// 跟 Python 版（tools/autoalign）同一套假房間、同一套驗收句子；Python 的答案在 fixtures/python_parity.json
// （重新產生：tools/autoalign 底下 .venv/Scripts/python.exe make_web_fixtures.py）
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const room = require('./synthetic_room.js');
const {
  fitCamera, NoFloorError, upVector, tiltDeg, occluderDepthMm, recoverFocalShift, modelOutputToPoints,
  tokenGrid, modelInputSize, alignResult, _internal,
} = require('../webalign.js');

const PARITY = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'python_parity.json'), 'utf8'));
const BOXES = {
  SOFA: room.SOFA, SIDE_TABLE: room.SIDE_TABLE, LOW_PLATFORM: room.LOW_PLATFORM, BED: room.BED, FUTON: room.FUTON,
  SOFFIT: room.SOFFIT, UPPER_CABINET: room.UPPER_CABINET,
};
const shotFrom = (d) => room.shot({ ...d, boxes: d.boxes.map((b) => BOXES[b]) });

const near = (a, b, tol, what = '') => assert.ok(Math.abs(a - b) <= tol, `${what} ${a} 應該是 ${b}（誤差 ${tol} 內）`);
const rel = (a, b, r, what) => near(a, b, Math.abs(b) * r, what);
const fit = (map, fy) => fitCamera(map, fy, { seed: 0 });

function assertMatches(r, s, { cm = 1, deg = 0.5 } = {}) {
  near(r.heightM, s.height, cm / 100, '鏡頭離地');
  near(r.pitchDeg, s.pitch, deg, '往下看');
  near(r.rollDeg, s.roll, deg, '歪斜');
  near(r.vfovDeg, s.vfov, 0.5, '視角');
  near(r.ceilingM, s.ceiling, (2 * cm) / 100, '天花板');
}
const BEDROOM = room.shot({ height: 1.6, pitch: 20, vfov: 65, width: 120, rows: 160, boxes: [room.BED] });
const FLOOR_BED = room.shot({ height: 0.87, pitch: -5, vfov: 67, width: 120, rows: 160, boxes: [room.FUTON] });

// ---------- 找地板、天花板（跟 test_geometry.py 一樣） ----------
test('乾淨的房間', () => {
  const s = room.shot();
  const { map, fy } = room.render(s);
  assertMatches(fit(map, fy), s);
});

for (const roll of [-4, 5]) {
  test(`鏡頭往下 15°、歪 ${roll}°`, () => {
    const s = room.shot({ height: 1.6, pitch: 15, roll, vfov: 65, ceiling: 2.9 });
    const { map, fy } = room.render(s);
    assertMatches(fit(map, fy), s);
  });
}

test('深度有 2% 雜訊：鏡頭離地、天花板 5% 內，角度 2° 內', () => {
  const s = room.shot();
  const { map, fy } = room.render(s);
  const r = fit(room.withNoise(map, 0.02, 1), fy);
  rel(r.heightM, s.height, 0.05, '鏡頭離地');
  rel(r.ceilingM, s.ceiling, 0.05, '天花板');
  near(r.pitchDeg, s.pitch, 2, '往下看');
  near(r.rollDeg, s.roll, 2, '歪斜');
});

test('30% 的點是壞的', () => {
  const s = room.shot();
  const { map, fy } = room.render(s);
  assertMatches(fit(room.withHoles(map, 0.3, 2), fy), s);
});

test('地板上有沙發和桌子，不會把桌面當地板', () => {
  const s = room.shot({ boxes: [room.SOFA, room.SIDE_TABLE] });
  const { map, fy } = room.render(s);
  assertMatches(fit(map, fy), s);
});

test('很大很低的平台不是地板', () => {
  const s = room.shot({ boxes: [room.LOW_PLATFORM] });
  const { map, fy } = room.render(s);
  assertMatches(fit(map, fy), s);
});

for (const [name, s] of [['床', BEDROOM], ['地上的床墊', FLOOR_BED]]) {
  test(`${name}蓋住大半地板，還是找到真的地板`, () => {
    const { map, fy } = room.render(s);
    const r = fit(map, fy);
    near(r.heightM, s.height, 0.01, '鏡頭離地');
    near(r.pitchDeg, s.pitch, 0.5, '往下看');
    near(r.rollDeg, s.roll, 0.5, '歪斜');
  });
  for (const seed of [3, 4, 5]) {
    test(`${name}：深度一大片一大片偏 3%（種子 ${seed}），鏡頭離地 5% 內`, () => {
      const { map, fy } = room.render(s);
      rel(fit(room.withSmoothNoise(map, 0.03, seed), fy).heightM, s.height, 0.05, '鏡頭離地');
    });
  }
}

test('看不到天花板：回傳「不知道」', () => {
  const s = room.shot({ pitch: 35, vfov: 45 });
  const { map, fy } = room.render(s);
  const r = fit(map, fy);
  assert.equal(r.ceilingM, null);
  near(r.heightM, s.height, 0.01);
});

test('只看到比鏡頭高的牆，不會當成天花板', () => {
  for (const s of [room.shot({ pitch: 5, vfov: 26 }), room.shot({ pitch: 30, vfov: 75 })]) {
    const { map, fy } = room.render(s);
    const r = fit(map, fy);
    assert.equal(r.ceilingM, null);
    near(r.heightM, s.height, 0.01);
  }
});

for (const seed of [3, 4, 5]) {
  test(`天花板有拍到、深度一大片一大片偏 3%（種子 ${seed}）：還是找得到`, () => {
    const s = room.shot();
    const { map, fy } = room.render(s);
    const r = fit(room.withSmoothNoise(map, 0.03, seed), fy);
    rel(r.heightM, s.height, 0.05, '鏡頭離地');
    rel(r.ceilingM, s.ceiling, 0.05, '天花板');
  });
}

test('天花板降一階：回傳高的那段', () => {
  const s = room.shot({ pitch: -5, vfov: 65, ceiling: 3.0, boxes: [room.SOFFIT] });
  const { map, fy } = room.render(s);
  const r = fit(map, fy);
  near(r.ceilingM, 3.0, 0.02, '天花板');
  near(r.heightM, s.height, 0.01, '鏡頭離地');
});

test('吊櫃底面只比鏡頭高一點，不是天花板', () => {
  const { map, fy } = room.render(room.shot({ pitch: 5, vfov: 26, boxes: [room.UPPER_CABINET] }));
  assert.equal(fit(map, fy).ceilingM, null);
});

test('分層：相差不到 15 cm 的兩個高峰算同一層，留密的那個', () => {
  const values = [...Array(300).fill(1.0), ...Array(100).fill(1.1), ...Array(300).fill(1.6)];
  const got = _internal.layers(values);
  assert.equal(got.length, 2);
  near(got[0], 1.0, 0.02);
  near(got[1], 1.6, 0.02);
});

test('看不到地板：回報「看不到地板」', () => {
  const { map, fy } = room.render(room.shot({ pitch: -12, vfov: 30 }));
  assert.throws(() => fit(map, fy), (e) => e instanceof NoFloorError && /看不到地板/.test(e.message));
});

test('輸入形狀不對、焦距 ≤ 0：回報錯誤', () => {
  assert.throws(() => fitCamera({ rows: 10, cols: 10, data: new Float64Array(100) }, 100), /列, 欄, 3/);
  const { map } = room.render(room.shot());
  assert.throws(() => fitCamera(map, 0), /fy/);
});

test('同一份點，JS 跟 Python 的結果一樣（鏡頭離地 1 cm、角度 0.5°、天花板 2 cm）', () => {
  for (const [name, c] of Object.entries(PARITY.fit)) {
    const { map, fy } = room.render(shotFrom(c.shot));
    const r = fit(map, fy), e = c.expected;
    near(r.heightM, e.height_m, 0.01, `${name} 鏡頭離地`);
    near(r.pitchDeg, e.pitch_deg, 0.5, `${name} 往下看`);
    near(r.rollDeg, e.roll_deg, 0.5, `${name} 歪斜`);
    near(r.vfovDeg, e.vfov_deg, 1e-6, `${name} 視角`);
    if (e.ceiling_m === null) assert.equal(r.ceilingM, null, `${name} 天花板`);
    else near(r.ceilingM, e.ceiling_m, 0.02, `${name} 天花板`);
  }
});

test('往上的方向跟 pitch、roll 可以互換', () => {
  for (const [p, r] of [[0, 0], [12, 3], [-5, -4], [40, 8]]) {
    const t = tiltDeg(upVector(p, r));
    near(t.pitch, p, 1e-9);
    near(t.roll, r, 1e-9);
  }
});

// ---------- MoGe 的後處理 ----------
// 真實的點 = (模型輸出 + (0, 0, shift)) × scale
function fakeOutput(s, shift, scale) {
  const { map, fy } = room.render(s);
  const points = new Float32Array(map.data.length);
  for (let k = 0; k < map.data.length; k += 3) {
    points[k] = map.data[k] / scale;
    points[k + 1] = map.data[k + 1] / scale;
    points[k + 2] = map.data[k + 2] / scale - shift;
  }
  return { points, mask: new Float32Array(map.rows * map.cols).fill(0.9), metricScale: scale, rows: map.rows, cols: map.cols, fy };
}

test('從模型輸出算回焦距和深度位移，誤差 0.5% 內', () => {
  const s = room.shot({ width: 96, rows: 72 });
  const out = fakeOutput(s, 0.6, 1.7);
  const r = recoverFocalShift(out.points, out.mask.map((m) => m > 0.5), out.rows, out.cols);
  // focal 是相對於「半條對角線」的焦距
  const want = out.fy / (Math.hypot(out.rows, out.cols) / 2);
  rel(r.focal, want, 0.005, '焦距');
  rel(r.shift, 0.6, 0.005, '位移');
});

test('模型輸出變成真實的點：跟 Python（MoGe 原本的程式）一樣', () => {
  const c = PARITY.postprocess;
  const r = modelOutputToPoints({
    points: Float32Array.from(c.raw), mask: Float32Array.from(c.mask), metricScale: c.metric_scale, rows: c.rows, cols: c.cols,
  });
  rel(r.fy, c.expected.fy_px, 0.005, 'fy（像素）');
  for (const [i, xyz] of Object.entries(c.expected.samples)) {
    for (let a = 0; a < 3; a++) {
      const got = r.map.data[Number(i) * 3 + a];
      if (xyz[a] === null) assert.ok(Number.isNaN(got), `點 ${i} 應該沒有深度`);
      else near(got, xyz[a], 0.01 + 0.005 * Math.abs(xyz[a]), `點 ${i} 軸 ${a}`);
    }
  }
  const f = fit(r.map, r.fy), e = c.expected.fit;
  near(f.heightM, e.height_m, 0.01, '鏡頭離地');
  near(f.pitchDeg, e.pitch_deg, 0.5, '往下看');
  near(f.rollDeg, e.roll_deg, 0.5, '歪斜');
  near(f.ceilingM, e.ceiling_m, 0.02, '天花板');
});

test('模型說沒有深度、或深度 ≤ 0 的點，都當成沒有深度', () => {
  const s = room.shot({ width: 32, rows: 24 });
  const out = fakeOutput(s, 0.6, 1.7);
  out.mask[0] = 0.2;              // 模型說沒有深度
  out.points[5 * 3 + 2] = -50;    // 深度會變成負的
  const r = modelOutputToPoints(out);
  assert.ok(Number.isNaN(r.map.data[0]));
  assert.ok(Number.isNaN(r.map.data[5 * 3 + 2]));
  assert.ok(Number.isFinite(r.map.data[1 * 3 + 2]));
});

test('token 格子：照長寬比分，跟 MoGe 一樣四捨五入', () => {
  assert.deepEqual(tokenGrid(784, 588, 2400), { rows: 42, cols: 57 });
  assert.deepEqual(tokenGrid(588, 784, 2400), { rows: 57, cols: 42 });
  assert.deepEqual(tokenGrid(640, 480, 1200), { rows: 30, cols: 40 });
});

// ---------- 遮擋深度圖（跟 test_occlusion.py 一樣） ----------
const SCENE = (() => {
  const s = room.shot({ boxes: [room.SOFA] });
  const { map, fy } = room.render(s);
  const f = fit(map, fy);
  return { s, map, fy, f, world: room.toWorld(map, s), depth: occluderDepthMm(map, f) };
})();
const eachPixel = (pred) => {
  const out = [];
  for (let p = 0; p < SCENE.map.rows * SCENE.map.cols; p++) if (pred(SCENE.world[p * 3], SCENE.world[p * 3 + 1], SCENE.world[p * 3 + 2])) out.push(p);
  return out;
};

test('遮擋圖：小的時候跟點一樣大，是 0–65535 的整數', () => {
  assert.equal(SCENE.depth.width, SCENE.map.cols);
  assert.equal(SCENE.depth.height, SCENE.map.rows);
  assert.ok(SCENE.depth.mm instanceof Uint16Array);
});

test('遮擋圖：地板、天花板不擋東西', () => {
  const floor = eachPixel((x, y) => y < 0.01), ceiling = eachPixel((x, y) => y > SCENE.s.ceiling - 0.01);
  assert.ok(floor.length > 1000 && ceiling.length > 500);
  for (const p of [...floor, ...ceiling]) assert.equal(SCENE.depth.mm[p], 0);
});

test('遮擋圖：家具在它的距離擋東西，牆也擋', () => {
  const sofa = eachPixel((x, y, z) => y > 0.1 && y < room.SOFA.hi[1] + 0.001 && z > room.SOFA.lo[2] - 0.001 && Math.abs(x) < 1.2);
  assert.ok(sofa.length > 100);
  for (const p of sofa) near(SCENE.depth.mm[p] / 1000, SCENE.map.data[p * 3 + 2], 0.001);
  const wall = eachPixel((x, y, z) => z < -5.99 && y > 1 && y < 2);
  assert.ok(wall.length > 100);
  for (const p of wall) assert.ok(SCENE.depth.mm[p] > 0);
});

test('遮擋圖：沒有深度的點不擋東西', () => {
  const holes = room.withHoles(SCENE.map, 0.3, 2);
  const d = occluderDepthMm(holes, SCENE.f);
  for (let p = 0; p < holes.rows * holes.cols; p++) if (Number.isNaN(holes.data[p * 3])) assert.equal(d.mm[p], 0);
});

test('遮擋圖：大的縮到最長邊 512', () => {
  const s0 = room.shot({ width: 1600, rows: 1200, boxes: [room.SOFA] });
  const r0 = room.render(s0), f0 = fit(r0.map, r0.fy);
  const full = occluderDepthMm(r0.map, f0, 4096), small = occluderDepthMm(r0.map, f0, 512);
  // 取每格中心最近的點：縮小後 (r, c) 是原圖 (floor((r + 0.5) / 0.32), floor((c + 0.5) / 0.32))
  for (const [r, c] of [[0, 0], [100, 200], [383, 511], [250, 37]]) {
    const sr = Math.floor((r + 0.5) / 0.32), sc = Math.floor((c + 0.5) / 0.32);
    assert.equal(small.mm[r * 512 + c], full.mm[sr * 1600 + sc], `(${r}, ${c})`);
  }
  const s = room.shot({ width: 1600, rows: 1200, boxes: [room.SOFA] });
  const { map, fy } = room.render(s);
  const d = occluderDepthMm(map, fit(map, fy), 512);
  assert.deepEqual([d.height, d.width], [384, 512]);
});

test('結果跟本機服務回傳的一樣（5 個滑桿＋遮擋圖）', () => {
  const r = alignResult(SCENE.map, SCENE.fy, { seed: 0 });
  near(r.height_m, SCENE.s.height, 0.01);
  near(r.ceiling_m, SCENE.s.ceiling, 0.02);
  assert.deepEqual(Object.keys(r).sort(), ['ceiling_m', 'depth', 'height_m', 'pitch_deg', 'roll_deg', 'vfov_deg']);
  assert.ok(r.depth.mm instanceof Uint16Array && r.depth.width === SCENE.map.cols);
});

// ---------- Codex 審查找到的（2026-11-20） ----------
// 暴力搜尋：在 [lo, hi] 裡細細地掃，找最小平方誤差的位移（拿來對 LM 的答案）
function bruteShift(points, mask, rows, cols, lo, hi) {
  const { _internal: I } = require('../webalign.js');
  const s = I.focalShiftSamples(points, mask, rows, cols);
  let best = lo, bestCost = Infinity;
  for (let k = 0; k <= 4000; k++) {
    const x = lo + ((hi - lo) * k) / 4000, c = I.focalShiftCost(s.uv, s.xyz, x);
    if (c < bestCost) { bestCost = c; best = x; }
  }
  return best;
}

for (const [shift, scale] of [[0, 1], [0.6, 1.7], [2.0, 0.8], [-0.3, 1.2]]) {
  test(`算回位移和焦距：位移 ${shift}、尺寸倍數 ${scale}`, () => {
    const s = room.shot({ width: 96, rows: 72, boxes: [room.SOFA] });
    const out = fakeOutput(s, shift, scale);
    const r = recoverFocalShift(out.points, out.mask.map((m) => m > 0.5), out.rows, out.cols);
    rel(r.focal, out.fy / (Math.hypot(out.rows, out.cols) / 2), 0.005, '焦距');
    near(r.shift, shift, 0.005 * Math.max(1, Math.abs(shift)), '位移');
  });
}

test('深度有雜訊時，LM 找到的位移跟暴力搜尋的最佳值一樣', () => {
  const s = room.shot({ width: 96, rows: 72, boxes: [room.SOFA, room.SIDE_TABLE] });
  const { map } = room.render(s);
  const noisy = room.withSmoothNoise(map, 0.05, 11);
  const out = fakeOutput(s, 0.6, 1.7);
  for (let k = 0; k < out.points.length; k += 3) {
    out.points[k] = noisy.data[k] / 1.7;
    out.points[k + 1] = noisy.data[k + 1] / 1.7;
    out.points[k + 2] = noisy.data[k + 2] / 1.7 - 0.6;
  }
  const ok = out.mask.map((m) => m > 0.5);
  const r = recoverFocalShift(out.points, ok, out.rows, out.cols);
  near(r.shift, bruteShift(out.points, ok, out.rows, out.cols, -1, 3), 0.002, '位移');
});

test('一個沒被遮掉的 NaN 點，不會讓整張照片算不出來', () => {
  const s = room.shot({ width: 96, rows: 72 });
  const out = fakeOutput(s, 0.6, 1.7);
  out.points[2] = NaN; // 左上角的深度：會被抽到（每邊取最近的點，第一個就是它）
  const r = modelOutputToPoints(out);
  assert.ok(Number.isFinite(r.fy) && r.fy > 0);
  rel(r.fy, out.fy, 0.005, 'fy');
  assert.ok(Number.isNaN(r.map.data[0]), '那個點自己沒有深度');
});

test('真實尺寸倍數不是正數：回報錯誤，不亂算', () => {
  const out = fakeOutput(room.shot({ width: 32, rows: 24 }), 0.6, 1.7);
  for (const bad of [NaN, 0, -1, Infinity]) assert.throws(() => modelOutputToPoints({ ...out, metricScale: bad }), /真實尺寸/);
});

test('模型輸入大小：照片長寬比不變（不拉長），大約是 token 格子 × 14', () => {
  for (const [w, h] of [[4032, 3024], [3024, 4032], [1920, 1080], [1108, 1477]]) {
    const size = modelInputSize(w, h, 2400), grid = tokenGrid(w, h, 2400);
    near(size.width / size.height, w / h, 0.01 * (w / h), `${w}x${h} 長寬比`);
    assert.equal(size.width, grid.cols * 14);
  }
});

test('遮擋圖縮小：長寬照 Python 的四捨六入五成雙，不會讀到照片外面', () => {
  // 1024 寬縮到 512：比例 0.5。769 × 0.5 = 384.5 → 384；771 × 0.5 = 385.5 → 386（取偶數）
  for (const [rows, want] of [[769, 384], [771, 386]]) {
    const s = room.shot({ width: 1024, rows, boxes: [room.SOFA] });
    const { map, fy } = room.render(s);
    const f = fit(map, fy), d = occluderDepthMm(map, f, 512), full = occluderDepthMm(map, f, 4096);
    assert.deepEqual([d.height, d.width], [want, 512]);
    // 最下面一列取原圖最下面那列（最多到最後一列，不能讀到外面）
    const src = Math.min(rows - 1, Math.floor((want - 0.5) / 0.5));
    for (const c of [0, 100, 511]) assert.equal(d.mm[(want - 1) * 512 + c], full.mm[src * 1024 + Math.floor((c + 0.5) / 0.5)], `第 ${c} 欄`);
  }
});

test('遮擋 mm 剛好 .5 時跟 Python 一樣取偶數', () => {
  const map = { rows: 1, cols: 1, data: Float64Array.from([0, 0, 1.0625]) };
  const d = occluderDepthMm(map, { heightM: 1.35, pitchDeg: 0, rollDeg: 0, ceilingM: null });
  assert.equal(d.mm[0], 1062);
});

test('分層：有一點極端的錯誤深度也不會當掉，結果不變', () => {
  const values = [...Array(500).fill(1.35), ...Array(200).fill(2.7), 9000, -8000];
  const got = _internal.layers(values);
  assert.equal(got.length, 2);
  near(got[0], 1.35, 0.02);
  near(got[1], 2.7, 0.02);
});

// ---------- 量尺（docs/ruler.md） ----------
const { rulerPoint, projectToPhoto } = require('../webalign.js');
// 假房間的正確鏡頭，跟原型的 state.cam 同一個樣子
const camOf = (s) => ({ height: s.height, pitch: s.pitch, roll: s.roll, fov: s.vfov, aspect: s.width / s.rows, ceiling: s.ceiling });
// 用正確的答案做深度圖（地板、天花板是 0），跟原型拿到的一樣：公尺、第 0 列是照片最上面
function depthOf(s) {
  const { map } = room.render(s);
  const d = occluderDepthMm(map, { heightM: s.height, pitchDeg: s.pitch, rollDeg: s.roll, ceilingM: s.ceiling }, 4096);
  return { width: d.width, height: d.height, meters: Float32Array.from(d.mm, (v) => v / 1000) };
}
// 房間裡的一點 → 照片上的位置 → 量尺量到的點
function measure(s, depth, world) {
  const cam = camOf(s), uv = projectToPhoto(cam, world);
  return rulerPoint(cam, uv.u, uv.v, depth);
}
const dist = (a, b) => Math.hypot(a.point[0] - b.point[0], a.point[1] - b.point[1], a.point[2] - b.point[2]);

test('量尺：地板上相距 2 m 的兩點量出 2 m（有深度圖、沒有深度圖都一樣）', () => {
  const s = room.shot({ width: 320, rows: 240 });
  for (const depth of [depthOf(s), null]) {
    const a = measure(s, depth, [-1, 0, -3]), b = measure(s, depth, [1, 0, -3]);
    assert.equal(a.from, 'floor');
    near(dist(a, b), 2, 0.02, '地板');
  }
});

test('量尺：後牆上相距 4 m 的兩點量出 4 m，用的是深度圖', () => {
  const s = room.shot({ width: 320, rows: 240 }), depth = depthOf(s);
  const a = measure(s, depth, [-2, 1.5, -6]), b = measure(s, depth, [2, 1.5, -6]);
  assert.equal(a.from, 'depth');
  rel(dist(a, b), 4, 0.03, '後牆');
});

test('量尺：沙發正面相距 2.2 m 的兩點量出 2.2 m', () => {
  const s = room.shot({ width: 320, rows: 240, boxes: [room.SOFA] }), depth = depthOf(s);
  const a = measure(s, depth, [-1.1, 0.3, -5]), b = measure(s, depth, [1.1, 0.3, -5]);
  assert.equal(a.from, 'depth');
  rel(dist(a, b), 2.2, 0.03, '沙發');
});

test('量尺：地板到正上方的天花板，量出天花板高度', () => {
  const s = room.shot({ width: 320, rows: 240 }), depth = depthOf(s);
  const a = measure(s, depth, [0.5, 0, -5.5]), b = measure(s, depth, [0.5, s.ceiling, -5.5]);
  assert.deepEqual([a.from, b.from], ['floor', 'ceiling']);
  near(dist(a, b), s.ceiling, 0.02, '天花板高度');
});

test('量尺：往上看又不知道天花板多高，量不到（不亂給數字）', () => {
  const s = room.shot({ width: 320, rows: 240 });
  const cam = { ...camOf(s), ceiling: null };
  assert.equal(rulerPoint(cam, 0.5, 0.05, null), null);
});

test('量尺：照片上的位置換成房間裡的點，再換回來，一樣', () => {
  const s = room.shot({ width: 320, rows: 240, roll: 3, pitch: 14 }), cam = camOf(s);
  for (const [u, v] of [[0.2, 0.9], [0.7, 0.75], [0.5, 0.6]]) {
    const p = rulerPoint(cam, u, v, null), back = projectToPhoto(cam, p.point);
    near(back.u, u, 1e-6, 'u');
    near(back.v, v, 1e-6, 'v');
  }
});

test('量尺：鏡頭歪斜、往下看時，量到的點跟假房間畫出來的點一樣（不同的程式算的）', () => {
  const s = room.shot({ width: 320, rows: 240, roll: 6, pitch: 14, boxes: [room.SOFA] });
  const { map } = room.render(s), world = room.toWorld(map, s), depth = depthOf(s), cam = camOf(s);
  for (const [i, j] of [[40, 220], [280, 200], [160, 120], [60, 60], [250, 90]]) {
    const p = rulerPoint(cam, (i + 0.5) / s.width, (j + 0.5) / s.rows, depth), k = (j * s.width + i) * 3;
    for (let a = 0; a < 3; a++) near(p.point[a], world[k + a], 0.02, `像素 (${i}, ${j}) 軸 ${a}（${p.from}）`);
  }
});
