// 爬到的燈放進模擬器：catalog.js 的資料、lamps.js 的 catalogLamp。驗收句子：docs/catalog.md
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  LAMPS, CATEGORIES, MOUNTS, STOCK, fittedBounds, lampFit, catalogLamp, bestOffer, searchLamps,
} = require('../lamps.js');
const CATALOG = require('../catalog.js');

const near = (a, b, tol) => assert.ok(Math.abs(a - b) <= tol, `${a} 應該是 ${b}（誤差 ${tol} 內）`);
const MM = 0.001;

// ---------- 用自己寫的一筆資料測 catalogLamp ----------
const ENTRY = {
  id: 'c:test__lamp', brand: 'Test', name: 'Lamp', variant: '白', category: '桌燈', mount: 'table',
  size: { w: 30, h: 45 }, updated: '2026-11-21',
  offers: [{ store: 'A', price: 1000, stock: 'in', url: 'https://a.example.com/p' }],
  lathe: [[10, 0], [10, 2], [2, 3], [2, 30], [15, 32], [12, 45]],
  bands: [{ to: 30, m: 'metal', c: 0x333333 }, { to: 45, m: 'shade', c: 0xf0eadc }],
  light: [0, 32, 0], beam: 'all',
};

test('catalogLamp：全部是旋轉體，上下封起來，一段接一段', () => {
  const parts = catalogLamp(ENTRY).parts;
  assert.ok(parts.every((p) => p.k === 'lathe'));
  assert.equal(parts[0].pts[0][0], 0, '底部封起來');
  assert.equal(parts.at(-1).pts.at(-1)[0], 0, '頂部封起來');
  for (let i = 1; i < parts.length; i++) assert.deepEqual(parts[i].pts[0], parts[i - 1].pts.at(-1));
});

test('catalogLamp：每個高度的材質和顏色照那一段（換色的地方切開）', () => {
  const parts = catalogLamp(ENTRY).parts;
  assert.deepEqual(parts.map((p) => [p.m, p.c]), [['metal', 0x333333], ['shade', 0xf0eadc]]);
  assert.equal(parts[0].pts.at(-1)[1], 30, '金屬剛好到高 30');
  assert.ok(parts[1].inner, '燈罩裡面也會亮');
  assert.ok(!parts[0].inner);
});

test('catalogLamp：換色的高度在一條線段中間，就在那裡切開（不是整段用中點的顏色）', () => {
  const entry = { ...ENTRY, bands: [{ to: 20, m: 'metal', c: 0x333333 }, { to: 45, m: 'shade', c: 0xf0eadc }] };
  const parts = catalogLamp(entry).parts;
  assert.deepEqual(parts[0].pts.at(-1), [2, 20], '金屬切在高 20');
  assert.deepEqual(parts[1].pts[0], [2, 20], '燈罩從高 20 開始');
});

test('catalogLamp：寬、高等於資料的尺寸（誤差 1 mm 內），燈泡在模型裡', () => {
  const lamp = catalogLamp(ENTRY);
  const b = fittedBounds(lamp), { light } = lampFit(lamp);
  near(b[3] - b[0], 0.30, MM);
  near(b[4] - b[1], 0.45, MM);
  for (let i = 0; i < 3; i++) assert.ok(light[i] >= b[i] - MM && light[i] <= b[i + 3] + MM);
});

test('catalogLamp：連結是最便宜那家的商品頁；不改原本的資料', () => {
  const before = JSON.stringify(ENTRY);
  const lamp = catalogLamp({ ...ENTRY, offers: [...ENTRY.offers, { store: 'B', price: 900, stock: 'in', url: 'https://b.example.com/p' }] });
  assert.equal(lamp.page, 'https://b.example.com/p');
  assert.equal(lamp.source, 'catalog');
  assert.equal(JSON.stringify(ENTRY), before);
});

// ---------- 搜尋 ----------
test('搜尋：品牌或型號，不分大小寫，空白分開的每個字都要有', () => {
  const lamps = [
    { id: 'a', brand: 'Louis Poulsen', name: 'PH 5', category: '吊燈' },
    { id: 'b', brand: 'Louis Poulsen', name: 'Panthella', category: '立燈' },
    { id: 'c', brand: 'Flos', name: 'Bellhop', category: '桌燈' },
  ];
  assert.deepEqual(searchLamps(lamps, 'louis').map((l) => l.id), ['a', 'b']);
  assert.deepEqual(searchLamps(lamps, 'poulsen panth').map((l) => l.id), ['b']);
  assert.deepEqual(searchLamps(lamps, '  ').map((l) => l.id), ['a', 'b', 'c']);
  assert.deepEqual(searchLamps(lamps, '吊燈').map((l) => l.id), ['a'], '類別也搜得到');
});

// ---------- 真的 catalog.js ----------
const EXPANDED = CATALOG.lamps.map(catalogLamp);

test('catalog.js：有幾百盞，id 不重複、不跟原本 14 盞撞', () => {
  assert.ok(CATALOG.lamps.length >= 100, `只有 ${CATALOG.lamps.length} 盞`);
  const ids = CATALOG.lamps.map((l) => l.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(ids.every((id) => id.startsWith('c:')));
  assert.ok(!ids.some((id) => LAMPS.some((l) => l.id === id)));
  assert.match(CATALOG.updated, /^\d{4}-\d{2}-\d{2}$/);
});

test('catalog.js：每盞都有品牌、型號、類別、放法、尺寸、至少一家價格（連到店家）', () => {
  for (const l of CATALOG.lamps) {
    assert.ok(l.brand && l.name, l.id);
    assert.ok(['吊燈', '桌燈', '立燈', '吸頂燈'].includes(l.category) && CATEGORIES.includes(l.category), l.id);
    assert.ok(MOUNTS.includes(l.mount), l.id);
    assert.ok(l.size.w > 0 && (l.size.h === undefined || l.size.h > 0), l.id);
    assert.ok(l.offers.length >= 1, l.id);
    for (const o of l.offers) {
      assert.ok(o.store && o.price > 0 && STOCK.includes(o.stock), l.id);
      assert.match(o.url, /^https?:\/\//, l.id);
    }
    assert.ok(l.lathe.length >= 3 && l.bands.length >= 1 && l.bands.length <= 4, l.id);
  }
});

test('catalog.js：照片和照片連結不上網站', () => {
  const text = fs.readFileSync(path.join(__dirname, '..', 'catalog.js'), 'utf8');
  assert.ok(!/\.(jpe?g|png|webp|gif)\b/i.test(text), '有照片連結');
  assert.ok(!/image|photo/i.test(text), '有照片欄位');
});

test('catalog.js：每盞的模型寬、高等於資料的尺寸，燈泡在模型裡，價格挑得出最便宜的', () => {
  for (const lamp of EXPANDED) {
    const b = fittedBounds(lamp), { light } = lampFit(lamp);
    near(b[3] - b[0], lamp.size.w / 100, MM);
    if (lamp.size.h !== undefined) near(b[4] - b[1], lamp.size.h / 100, MM);
    for (let i = 0; i < 3; i++) assert.ok(light[i] >= b[i] - MM && light[i] <= b[i + 3] + MM, `${lamp.id} 第 ${i} 軸`);
    assert.ok(bestOffer(lamp.offers).offer.price > 0);
  }
});

test('沒標高度的：卡片寫「高約 X cm（照片估的）」，模型的高度就是那個估計（Codex 審查）', () => {
  const { sizeLabel } = require('../lamps.js');
  assert.equal(sizeLabel({ size: { w: 40, hEst: 52.3 } }), '寬 40 cm · 高約 52.3 cm（照片估的）');
  assert.equal(sizeLabel({ size: { w: 40, h: 50 } }), '寬 40 × 高 50 cm');
  const est = EXPANDED.filter((l) => l.size.h === undefined);
  assert.ok(est.length > 0 && est.every((l) => l.size.hEst > 0), '每盞沒標高度的都有估計');
  for (const lamp of est) {
    const b = fittedBounds(lamp);
    near(b[4] - b[1], lamp.size.hEst / 100, MM);
  }
});

test('catalog.js：名字寫壁燈（沒寫吸頂）的不在裡面（Codex 審查：Clessidra Wall Lamp 被分到吸頂燈）', () => {
  const wall = CATALOG.lamps.filter((l) => /wall|壁燈|壁掛|壁式/i.test(l.name) && !/ceiling|吸頂/i.test(l.name));
  assert.deepEqual(wall.map((l) => l.name), []);
});
