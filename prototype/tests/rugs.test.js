// 地毯（rugs.js、lamps.js 的 rugShape）。驗收句子：docs/rugs.md
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { STOCK, rugShape, bestOffer, fetchPhoto, rugStartSize, rugNote, photoCache } = require('../lamps.js');
const RUGS = require('../rugs.js');

const near = (a, b, tol = 1e-9) => assert.ok(Math.abs(a - b) <= tol, `${a} 應該是 ${b}`);
const SQUARE = [[0, 0], [1, 0], [1, 1], [0, 1]];
const item = (photo, sizes = [{ shape: 'rect', w: 240, d: 170, offers: [], photoFits: Boolean(photo) }]) => ({ id: 'r:t', sizes, photo, colour: 0x999999 });

test('rugShape：照片橫的，地毯的長邊左右（x），外形照描的點、換成公尺、中心在原點', () => {
  const s = rugShape(item({ url: 'u', crop: [0.1, 0.2, 0.9, 0.8], outline: SQUARE, wide: true }), 0);
  assert.deepEqual([s.w, s.d], [2.4, 1.7]);
  near(s.points[0][0], -1.2); near(s.points[0][1], -0.85);
  near(s.points[2][0], 1.2); near(s.points[2][1], 0.85);
});

test('rugShape：照片直的，長邊前後（z）', () => {
  const s = rugShape(item({ url: 'u', crop: [0, 0, 1, 1], outline: SQUARE, wide: false }), 0);
  assert.deepEqual([s.w, s.d], [1.7, 2.4]);
});

test('rugShape：每個點的照片座標落在外框裡（照片上下顛倒：v = 1 是照片最上面）', () => {
  const s = rugShape(item({ url: 'u', crop: [0.1, 0.2, 0.9, 0.8], outline: SQUARE, wide: true }), 0);
  assert.deepEqual(s.uvs.map((p) => p.map((v) => +v.toFixed(6))), [[0.1, 0.8], [0.9, 0.8], [0.9, 0.2], [0.1, 0.2]]);
});

test('rugShape：toUV 對地上任何一點都算得出照片上的位置（跟外形的點一致）', () => {
  const s = rugShape(item({ url: 'u', crop: [0.1, 0.2, 0.9, 0.8], outline: SQUARE, wide: true }), 0);
  assert.deepEqual(s.toUV(0, 0).map((v) => +v.toFixed(6)), [0.5, 0.5], '中心對到外框的中心');
  s.points.forEach(([x, z], i) => s.toUV(x, z).forEach((v, k) => near(v, s.uvs[i][k], 1e-12)));
});

test('rugShape：沒有照片：方的是長方形、圓的是圓形，沒有照片座標', () => {
  const rect = rugShape(item(null), 0);
  assert.equal(rect.points.length, 4);
  assert.equal(rect.uvs, null);
  const round = rugShape(item(null, [{ shape: 'round', w: 200, d: 200, offers: [] }]), 0);
  assert.ok(round.points.length >= 24);
  for (const [x, z] of round.points) near(Math.hypot(x, z), 1.0, 1e-9);
});

test('rugShape：選不同尺寸，大小跟著變', () => {
  const sizes = [{ shape: 'rect', w: 240, d: 170, offers: [] }, { shape: 'rect', w: 300, d: 200, offers: [] }];
  assert.deepEqual([rugShape(item(null, sizes), 1).w, rugShape(item(null, sizes), 1).d], [3, 2]);
  assert.deepEqual([rugShape(item(null, sizes), 9).w], [2.4], '沒有這個尺寸就用第一個');
});

test('rugShape：照片不能用在這個尺寸（長寬比、圓方不一樣），就算這件有照片也不貼、照尺寸的形狀', () => {
  const photo = { url: 'u', crop: [0, 0, 1, 1], outline: [[0.5, 0], [1, 0.5], [0.5, 1], [0, 0.5]], wide: false };
  const sizes = [
    { shape: 'rect', w: 240, d: 170, offers: [], photoFits: true },
    { shape: 'rect', w: 250, d: 250, offers: [], photoFits: false },
    { shape: 'round', w: 200, d: 200, offers: [], photoFits: false },
  ];
  assert.ok(rugShape(item(photo, sizes), 0).uvs, '能用的尺寸有貼照片');
  const square = rugShape(item(photo, sizes), 1);
  assert.equal(square.uvs, null);
  assert.deepEqual(square.points.map((p) => p.map((v) => +v.toFixed(6))), [[-1.25, -1.25], [1.25, -1.25], [1.25, 1.25], [-1.25, 1.25]], '方的、不是照片的菱形');
  const round = rugShape(item(photo, sizes), 2);
  assert.equal(round.uvs, null);
  assert.ok(round.points.length >= 24);
});

test('rugStartSize：選一件地毯時，先選照片能用的第一個尺寸；都不能用就第一個', () => {
  const sizes = (...fits) => fits.map((f) => ({ shape: 'rect', w: 200, d: 100, offers: [], photoFits: f }));
  assert.equal(rugStartSize(item({}, sizes(false, true, true))), 1);
  assert.equal(rugStartSize(item({}, sizes(true, false))), 0);
  assert.equal(rugStartSize(item(null, sizes(false, false))), 0);
});

test('rugNote：花紋從哪裡來、為什麼沒有花紋；款式名稱另外寫「照片是哪款」', () => {
  const sizes = [
    { shape: 'rect', w: 300, d: 200, offers: [], photoFits: true },
    { shape: 'rect', w: 270, d: 270, offers: [], photoFits: false },
    { shape: 'rect', w: 240, d: 160, offers: [], photoFits: true },
  ];
  const rug = { ...item({ url: 'u' }, sizes), variant: '200x300 cm / Marble Grey' };
  assert.match(rugNote(rug, 0), /^花紋是店家的商品照/);
  assert.match(rugNote(rug, 0), /照片是「200x300 cm \/ Marble Grey」這款/);
  assert.match(rugNote(rug, 0), /價格是這個尺寸各款裡最便宜的/, '價格不一定是照片那一款（Codex 審查）');
  const off = rugNote(rug, 1);
  assert.match(off, /這個尺寸.*跟照片不一樣/);
  assert.match(off, /300 × 200 cm、240 × 160 cm 有花紋/, '說哪幾個尺寸有花紋');
  assert.match(rugNote({ ...item(null), variant: '' }, 0), /^這張的照片不能當花紋/);
  assert.doesNotMatch(rugNote({ ...item(null), variant: '' }, 0), /照片是「/, '沒有款式名稱就不寫');
});

// ---------- fetchPhoto：從店家讀照片 ----------
const fakeFetch = (answers) => {
  const calls = [];
  const fn = async (url, opts) => {
    calls.push(opts);
    const a = answers[calls.length - 1];
    if (a instanceof Error) throw a;
    return { ok: a === 'ok', status: a === 'ok' ? 200 : 404, blob: async () => `blob:${url}` };
  };
  return { fn, calls };
};

test('fetchPhoto：第一次就拿到，只問一次（跨網站讀）', async () => {
  const f = fakeFetch(['ok']);
  assert.equal(await fetchPhoto('u', f.fn), 'blob:u');
  assert.deepEqual(f.calls, [{ mode: 'cors' }]);
});

test('fetchPhoto：第一次被擋（瀏覽器存了不准別的網站讀的舊檔），不用舊檔、重新跟店家要一次', async () => {
  const f = fakeFetch([new TypeError('Failed to fetch'), 'ok']);
  assert.equal(await fetchPhoto('u', f.fn), 'blob:u');
  assert.deepEqual(f.calls, [{ mode: 'cors' }, { mode: 'cors', cache: 'reload' }]);
});

test('fetchPhoto：第一次回錯誤碼，也重新要一次', async () => {
  const f = fakeFetch(['404', 'ok']);
  assert.equal(await fetchPhoto('u', f.fn), 'blob:u');
  assert.equal(f.calls.length, 2);
});

test('fetchPhoto：兩次都不行就放棄（回 null，地毯用顏色）', async () => {
  assert.equal(await fetchPhoto('u', fakeFetch([new TypeError('x'), new TypeError('x')]).fn), null);
  assert.equal(await fetchPhoto('u', fakeFetch(['404', '404']).fn), null);
});

// ---------- photoCache：讀過的花紋留幾張，太多就丟掉最久沒用的 ----------
const fakeTex = (url) => ({ url, disposed: false, dispose() { this.disposed = true; } });
const tick = () => new Promise((r) => setImmediate(r));

test('photoCache：同一張只讀一次', async () => {
  const loads = [];
  const get = photoCache(async (u) => { loads.push(u); return fakeTex(u); }, 3);
  const a = await get('a'), b = await get('a');
  assert.equal(a, b);
  assert.deepEqual(loads, ['a']);
});

test('photoCache：讀不到的不留著，下次再試（網路斷了一下）', async () => {
  let ok = false;
  const get = photoCache(async (u) => (ok ? fakeTex(u) : null), 3);
  assert.equal(await get('a'), null);
  await tick();
  ok = true;
  assert.equal((await get('a')).url, 'a');
});

test('photoCache：超過張數，丟掉最久沒用的那張、放掉顯示卡記憶體', async () => {
  const loads = [];
  const get = photoCache(async (u) => { loads.push(u); return fakeTex(u); }, 2);
  const a = await get('a');
  const b = await get('b');
  await get('a'); // a 剛用過，最久沒用的變成 b
  assert.deepEqual(loads, ['a', 'b'], 'a、b 都還在');
  await get('c'); // 丟掉最久沒用的 b（不是最早讀的 a）
  await tick();
  assert.equal(b.disposed, true);
  assert.equal(a.disposed, false);
  await get('a');
  assert.deepEqual(loads, ['a', 'b', 'c'], 'a 還在，不用重讀');
  await get('b');
  assert.deepEqual(loads, ['a', 'b', 'c', 'b'], '丟掉的要重新讀');
});

// ---------- 真的 rugs.js ----------
test('rugs.js：每件有尺寸、每個尺寸至少一家價格（連到店家）', () => {
  assert.ok(RUGS.items.length >= 50, `只有 ${RUGS.items.length} 件`);
  const ids = RUGS.items.map((r) => r.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const r of RUGS.items) {
    assert.ok(r.id.startsWith('r:') && r.brand && r.name && r.category === '地毯', r.id);
    assert.ok(r.sizes.length >= 1, r.id);
    for (const s of r.sizes) {
      assert.ok(['rect', 'round'].includes(s.shape) && s.w > 0 && s.d > 0 && s.w >= s.d, r.id);
      assert.ok(s.offers.length >= 1, r.id);
      for (const o of s.offers) {
        assert.ok(o.store && o.price > 0 && STOCK.includes(o.stock), r.id);
        assert.match(o.url, /^https?:\/\//, r.id);
      }
      assert.ok(bestOffer(s.offers).offer.price > 0);
    }
  }
});

test('rugs.js：照片只有連結、只用允許別的網站讀的伺服器；外框、外形在 0 到 1', () => {
  for (const r of RUGS.items.filter((x) => x.photo)) {
    assert.match(r.photo.url, /^https:\/\/(cdn\.shopify\.com|img\.shoplineapp\.com)\//, r.id);
    assert.ok(r.photo.crop.every((v) => v >= 0 && v <= 1), r.id);
    assert.ok(r.photo.outline.length >= 3, r.id);
    assert.ok(r.photo.outline.flat().every((v) => v >= -1e-6 && v <= 1 + 1e-6), r.id);
    assert.equal(typeof r.photo.wide, 'boolean', r.id);
    assert.ok(r.sizes.some((s) => s.photoFits), `${r.id} 有照片但沒有尺寸能用`);
  }
  for (const r of RUGS.items) {
    assert.ok(r.sizes.every((s) => typeof s.photoFits === 'boolean'), r.id);
    if (!r.photo) assert.ok(r.sizes.every((s) => !s.photoFits), r.id);
  }
  assert.ok(RUGS.items.some((r) => r.photo), '至少有幾件用照片當花紋');
});

test('rugs.js：沒有本機的照片路徑（照片本身不在網站上）', () => {
  const text = fs.readFileSync(path.join(__dirname, '..', 'rugs.js'), 'utf8');
  assert.ok(!/out[\\/]photos|\.img\b|[A-Z]:\\\\/.test(text));
});
