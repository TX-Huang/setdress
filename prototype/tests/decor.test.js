// 擺飾：花瓶、花器（decor.js）。驗收句子：docs/decor.md
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { LAMPS, STOCK, fittedBounds, catalogLamp, bestOffer, decorItem } = require('../lamps.js');
const DECOR = require('../decor.js');
const CATALOG = require('../catalog.js');

const near = (a, b, tol) => assert.ok(Math.abs(a - b) <= tol, `${a} 應該是 ${b}（誤差 ${tol} 內）`);
const MM = 0.001;

test('decor.js：有幾十件，id 是 d: 開頭、不重複、不跟燈撞', () => {
  assert.ok(DECOR.items.length >= 30, `只有 ${DECOR.items.length} 件`);
  const ids = DECOR.items.map((d) => d.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(ids.every((id) => id.startsWith('d:')));
  const lampIds = new Set([...LAMPS.map((l) => l.id), ...CATALOG.lamps.map((l) => l.id)]);
  assert.ok(!ids.some((id) => lampIds.has(id)));
});

test('decor.js：每件是花瓶或花器、放桌上或地上（60 cm 以上放地上）、不會亮、有價格（連到店家）', () => {
  for (const d of DECOR.items) {
    assert.ok(['花瓶', '花器'].includes(d.category), d.id);
    const h = d.size.h ?? d.size.hEst;
    assert.equal(d.mount, h >= 60 ? 'floor' : 'table', d.id);
    assert.ok(!('light' in d) && !('beam' in d), `${d.id} 擺飾沒有燈泡`);
    assert.ok(d.offers.length >= 1, d.id);
    for (const o of d.offers) {
      assert.ok(o.store && o.price > 0 && STOCK.includes(o.stock), d.id);
      assert.match(o.url, /^https?:\/\//, d.id);
    }
  }
});

test('decor.js：照片和照片連結不上網站', () => {
  const text = fs.readFileSync(path.join(__dirname, '..', 'decor.js'), 'utf8');
  assert.ok(!/\.(jpe?g|png|webp|gif)\b/i.test(text), '有照片連結');
  assert.ok(!/image|photo/i.test(text), '有照片欄位');
});

test('decorItem：全部是不透光的陶瓷質感、不會亮；寬、高等於資料的尺寸', () => {
  for (const entry of DECOR.items) {
    const item = decorItem(entry);
    assert.ok(item.parts.every((p) => p.k === 'lathe' && p.m === 'ceramic' && !p.inner), item.id);
    const b = fittedBounds(item);
    near(b[3] - b[0], item.size.w / 100, MM);
    const h = item.size.h ?? item.size.hEst;
    near(b[4] - b[1], h / 100, MM);
    assert.ok(bestOffer(item.offers).offer.price > 0);
  }
});

test('decorItem：顏色照每一段（跟燈一樣在換色的地方切開）；不改原本的資料', () => {
  const entry = {
    id: 'd:t', brand: 'T', name: 'Vase', variant: '', category: '花瓶', mount: 'table',
    size: { w: 20, h: 30 }, offers: [{ store: 'A', price: 900, stock: 'in', url: 'https://a.example.com/p' }],
    lathe: [[6, 0], [10, 12], [4, 27], [5, 30]],
    bands: [{ to: 10, m: 'metal', c: 0x222222 }, { to: 30, m: 'shade', c: 0xeeeeee }],
  };
  const before = JSON.stringify(entry);
  const item = decorItem(entry);
  assert.deepEqual(item.parts.map((p) => p.c), [0x222222, 0xeeeeee]);
  assert.equal(item.parts[0].pts.at(-1)[1], 10, '在高 10 切開');
  assert.equal(item.source, 'decor');
  assert.equal(JSON.stringify(entry), before);
  assert.ok(catalogLamp(entry).parts.some((p) => p.inner), '燈的版本燈罩會亮；擺飾的不會');
});
