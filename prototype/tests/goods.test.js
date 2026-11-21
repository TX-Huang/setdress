// 全部商品放進模擬器的計算（goods.js）。驗收句子：docs/goods.md
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const G = require('../goods.js');
const { STOCK } = require('../lamps.js');

test('photoUrl：Shopify 要 800 寬的；Shopline 直接讀；其他店（不讓別的網站讀）經過 wsrv.nl', () => {
  assert.equal(G.photoUrl('https://cdn.shopify.com/s/files/a.jpg?v=1'), 'https://cdn.shopify.com/s/files/a.jpg?v=1&width=800');
  assert.equal(G.photoUrl('https://cdn.shopify.com/s/files/a.jpg?width=2000&v=1'), 'https://cdn.shopify.com/s/files/a.jpg?width=800&v=1');
  assert.equal(G.photoUrl('https://img.shoplineapp.com/media/image_clips/x/original.jpg?1'), 'https://img.shoplineapp.com/media/image_clips/x/original.jpg?1');
  assert.equal(
    G.photoUrl('https://www.nordic.com.tw/uploads/a b.jpg'),
    'https://wsrv.nl/?url=https%3A%2F%2Fwww.nordic.com.tw%2Fuploads%2Fa%20b.jpg&w=800&we&output=webp',
  );
});

test('thumbUrl：選單上的小圖，一律經過 wsrv.nl 縮成 96 px（手機不用讀原圖）', () => {
  assert.equal(
    G.thumbUrl('https://img.shoplineapp.com/a.jpg?1'),
    'https://wsrv.nl/?url=https%3A%2F%2Fimg.shoplineapp.com%2Fa.jpg%3F1&w=96&h=96&fit=contain&bg=white&output=webp',
  );
});

test('standeeSize：照片裡商品的比例；大小照店家標的寬和高（公尺）', () => {
  assert.deepEqual(G.standeeSize({ w: 200, d: 90, h: 80 }, [100, 200, 600, 400]), { w: 2, h: 0.8 }, '寬高都對得上');
});

test('standeeSize：標的高度只是座高（比照片小很多）：照寬度，不會變成小沙發', () => {
  const s = G.standeeSize({ w: 207, d: 99, h: 40 }, [0, 0, 452, 200]);
  assert.equal(s.w, 2.07);
  assert.ok(s.h > 0.9 && s.h < 0.93, String(s.h));
});

test('standeeSize：吊燈照片連電線一起：照寬度（燈罩），電線照比例', () => {
  assert.deepEqual(G.standeeSize({ w: 40, d: 40, h: 40 }, [0, 0, 100, 400]), { w: 0.4, h: 1.6 });
});

test('standeeSize：只有寬或只有高，就照那一個', () => {
  assert.deepEqual(G.standeeSize({ w: 60, d: null, h: null }, [0, 0, 300, 600]), { w: 0.6, h: 1.2 });
  assert.deepEqual(G.standeeSize({ w: null, d: null, h: 90 }, [0, 0, 300, 600]), { w: 0.45, h: 0.9 });
});

test('sizeLabel：寫有的邊；猜的要說', () => {
  assert.equal(G.sizeLabel({ w: 200, d: 90, h: 80 }), '寬 200 × 深 90 × 高 80 cm');
  assert.equal(G.sizeLabel({ w: 55, d: 55, h: 80, guess: true }), '寬 55 × 深 55 × 高 80 cm（沒標尺寸，用一般大小）');
});

test('startY：剛放進來的高度（底部離地）', () => {
  assert.equal(G.startY('floor', 0.8, 2.6), 0);
  assert.equal(G.startY('table', 0.3, 2.6), 0.75, '一般桌面');
  assert.equal(G.startY('wall', 0.6, 2.6), 1.2, '中心在 1.5 m');
  assert.equal(G.startY('ceiling', 0.4, 2.6), 1.7, '吊在天花板下 50 cm');
  assert.equal(G.startY('ceiling', 1.8, 2.6), 0.6, '太長的：最低吊到離地 60 cm');
});

test('heightRange：比天花板還高的東西，範圍不會變成負的（Codex 審查）', () => {
  assert.deepEqual(G.heightRange('wall', 3.1, 2.6), [0, 0]);
});

test('heightAfterResize：換尺寸後放法變了就重新放；沒變就留在原處但不超出範圍', () => {
  assert.equal(G.heightAfterResize(1.1, 'wall', 'floor', 1.6, 2.6), 0, '大鏡子改靠在地上');
  assert.equal(G.heightAfterResize(1.1, 'wall', 'wall', 0.8, 2.6), 1.1, '一樣掛牆：留在原處');
  assert.equal(G.heightAfterResize(2.0, 'wall', 'wall', 1.2, 2.6), 1.4, '變高了：往下移到碰得到天花板為止');
  assert.equal(G.heightAfterResize(0.75, 'table', 'floor', 0.9, 2.6), 0, '高的花瓶改放地上');
  assert.equal(G.heightAfterResize(0, 'floor', 'wall', 0.8, 2.6), 1.1, '改掛牆：照掛牆的高度重新放');
});

test('heightRange：桌上 0–1.2 m；牆上、天花板：0 到 天花板減掉本身高度', () => {
  assert.deepEqual(G.heightRange('table', 0.3, 2.6), [0, 1.2]);
  assert.deepEqual(G.heightRange('wall', 0.6, 2.6), [0, 2]);
  assert.deepEqual(G.heightRange('ceiling', 0.4, 2.6), [0, 2.2]);
  assert.equal(G.heightRange('floor', 0.8, 2.6), null, '地上的不能調');
});

test('total：每一件、照它選的尺寸、最便宜有現貨的價格加起來；拿掉的不算', () => {
  const items = new Map([
    ['g:a', { sizes: [{ offers: [{ price: 100, stock: 'in' }] }, { offers: [{ price: 300, stock: 'in' }] }] }],
    ['g:b', { sizes: [{ offers: [{ price: 50, stock: 'out' }, { price: 70, stock: 'in' }] }] }],
  ]);
  const placed = [{ id: 'g:a', size: 1 }, { id: 'g:b', size: 0 }, { id: 'g:a', size: 0 }, { id: 'g:x', size: 0 }];
  assert.equal(G.total(placed, (id) => items.get(id)), 300 + 70 + 100, '不在資料裡的（還沒讀到）不算');
});

// ---------- 真的資料 ----------
const DIR = path.join(__dirname, '..', 'goods');
const index = JSON.parse(fs.readFileSync(path.join(DIR, 'index.json'), 'utf8'));

test('goods/index.json：每一類有名稱、件數，檔案在', () => {
  assert.ok(index.groups.length >= 20);
  const total = index.groups.reduce((s, g) => s + g.count, 0);
  assert.ok(total >= 20000, `只有 ${total} 件`);
  for (const g of index.groups) {
    assert.ok(g.key && g.label && g.count > 0, g.key);
    assert.ok(fs.existsSync(path.join(DIR, `${g.key}.json`)), g.key);
  }
});

test('goods/*.json：每件有尺寸、價格連到店家、照片只有網址、放法對', () => {
  for (const g of index.groups) {
    const { items } = JSON.parse(fs.readFileSync(path.join(DIR, `${g.key}.json`), 'utf8'));
    assert.equal(items.length, g.count, g.key);
    for (const it of items) {
      assert.ok(it.id.startsWith('g:') && it.brand !== undefined && it.name, it.id);
      assert.ok(['floor', 'table', 'wall', 'ceiling'].includes(it.mount), it.id);
      assert.ok(it.sizes.length >= 1, it.id);
      assert.equal(it.mount, it.sizes[0].mount, it.id);
      for (const s of it.sizes) {
        assert.ok(s.w > 0 && s.d > 0 && s.h > 0, `${it.id} ${JSON.stringify(s)}`);
        assert.ok(['floor', 'table', 'wall', 'ceiling'].includes(s.mount), it.id);
        assert.ok(s.offers.length >= 1, it.id);
        assert.ok(s.photos.length <= 4 && s.photos.every((u) => /^https:\/\//.test(u)), it.id);
        for (const o of s.offers) {
          assert.ok(o.store && o.price > 0 && STOCK.includes(o.stock), it.id);
          assert.match(o.url, /^https?:\/\//, it.id);
        }
      }
    }
  }
});
