// 去背（cutout.js）。驗收句子：docs/goods.md 6–8
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { cutout } = require('../cutout.js');

// 做一張 RGBA 照片：背景色 bg，再畫幾個方塊 [x0, y0, x1, y1, [r, g, b]]
function photo(w, h, bg, boxes = [], { noise = 0, alpha = 255, seed = 1 } = {}) {
  const data = new Uint8ClampedArray(w * h * 4);
  let s = seed;
  const rand = () => ((s = (s * 16807) % 2147483647) / 2147483647 - 0.5) * 2 * noise;
  for (let i = 0; i < w * h; i++) {
    const c = typeof bg === 'function' ? bg(i % w, Math.floor(i / w)) : bg;
    data.set([c[0] + rand(), c[1] + rand(), c[2] + rand(), alpha], i * 4);
  }
  for (const [x0, y0, x1, y1, c] of boxes) {
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) data.set([...c, 255], (y * w + x) * 4);
  }
  return { data, width: w, height: h };
}
const WHITE = [255, 255, 255], DARK = [60, 40, 30];
const at = (r, x, y) => r.alpha[y * 100 + x];

test('白底、中間一件：找到它的範圍，裡面不透明、外面透明', () => {
  const r = cutout(photo(100, 100, WHITE, [[20, 30, 70, 80, DARK]]));
  assert.equal(r.ok, true);
  assert.deepEqual(r.box, [20, 30, 70, 80]);
  assert.equal(at(r, 45, 55), 255);
  assert.equal(at(r, 5, 5), 0);
});

test('邊緣往內縮一個像素（不留白邊）', () => {
  const r = cutout(photo(100, 100, WHITE, [[20, 30, 70, 80, DARK]]));
  assert.equal(at(r, 20, 50), 0, '最外面一圈拿掉');
  assert.equal(at(r, 21, 50), 255);
});

test('灰底有雜訊、上下有漸層，也算單色背景', () => {
  const grad = (x, y) => { const v = 228 + Math.round((y / 99) * 22); return [v, v, v]; };
  const r = cutout(photo(100, 100, grad, [[30, 30, 60, 70, DARK]], { noise: 4 }));
  assert.equal(r.ok, true);
  assert.deepEqual(r.box, [30, 30, 60, 70]);
});

test('商品碰到左、右或下面：照片切到商品，不用', () => {
  for (const box of [[0, 30, 50, 70], [50, 30, 100, 70], [30, 40, 60, 100]]) {
    const r = cutout(photo(100, 100, WHITE, [[...box, DARK]]));
    assert.equal(r.ok, false, String(box));
    assert.equal(r.reason, 'cut');
  }
});

test('碰到上面：一般不用；吊燈可以（電線從上面下來）', () => {
  const img = photo(100, 100, WHITE, [[48, 0, 52, 40, DARK], [30, 40, 70, 60, DARK]]);
  assert.equal(cutout(img).ok, false);
  assert.equal(cutout(img, { allowTop: true }).ok, true);
});

test('放在房間裡拍的（邊框不是同一個顏色）：不用', () => {
  let s = 7;
  const rand = () => (s = (s * 16807) % 2147483647) % 256;
  const r = cutout(photo(100, 100, () => [rand(), rand(), rand()], [[30, 30, 60, 60, DARK]]));
  assert.equal(r.ok, false);
  assert.equal(r.reason, 'scene');
});

test('背景有很多分開的小點（水泥牆、紙紋）：邊框只有七成是背景，不算單色背景', () => {
  const speck = (x, y) => ((x + y) % 7 === 0 ? [90, 90, 90] : WHITE); // 斜著排、上下左右不相連；佔邊框一成多
  const r = cutout(photo(100, 100, speck, [[30, 20, 70, 60, DARK]]));
  assert.equal(r.ok, false);
  assert.equal(r.reason, 'scene');
});

test('商品幾乎塞滿整張（背景不到三成）：不用', () => {
  const r = cutout(photo(100, 100, WHITE, [[3, 3, 97, 97, DARK]]));
  assert.equal(r.ok, false);
  assert.equal(r.reason, 'scene');
});

test('第二件小一點（最大那件的四成）也留：一組的椅子和腳凳', () => {
  const r = cutout(photo(100, 100, WHITE, [[10, 20, 50, 70, DARK], [60, 50, 80, 70, DARK]]));
  assert.equal(r.ok, true);
  assert.deepEqual(r.box, [10, 20, 80, 70]);
});

test('一組兩件都留；小灰塵丟掉', () => {
  const r = cutout(photo(100, 100, WHITE, [[10, 30, 40, 70, DARK], [60, 30, 90, 70, DARK], [50, 90, 52, 92, DARK]]));
  assert.equal(r.ok, true);
  assert.deepEqual(r.box, [10, 30, 90, 70], '灰塵不算進範圍');
  assert.equal(at(r, 51, 91), 0);
});

test('桌腳中間看得到背景：那裡要透明（從下面連到邊框）', () => {
  const r = cutout(photo(100, 100, WHITE, [[20, 30, 80, 40, DARK], [20, 40, 26, 80, DARK], [74, 40, 80, 80, DARK]]));
  assert.equal(r.ok, true);
  assert.equal(at(r, 50, 60), 0, '兩支腳中間');
  assert.equal(at(r, 50, 35), 255, '桌面');
});

test('透明背景的 PNG：透明的地方是背景（不管透明像素藏著什麼顏色）', () => {
  let s = 3;
  const rand = () => (s = (s * 16807) % 2147483647) % 256;
  const img = photo(100, 100, () => [rand(), rand(), rand()], [], { alpha: 0 });
  for (let y = 30; y < 70; y++) for (let x = 30; x < 70; x++) img.data.set([200, 200, 200, 255], (y * 100 + x) * 4);
  const r = cutout(img);
  assert.equal(r.ok, true);
  assert.deepEqual(r.box, [30, 30, 70, 70]);
});

test('整張都是背景：找不到商品', () => {
  const r = cutout(photo(100, 100, WHITE));
  assert.equal(r.ok, false);
  assert.equal(r.reason, 'empty');
});

// 攝影棚地上的淡灰影子：從底部往上，一直變暗的灰色拿掉（模擬器自己畫影子）
const grey = (v) => [v, v, v];
function withShadow(body) {
  // 商品 30..70 x 30..70；影子在底下 70..80，左右也多出 10 px，越靠近商品越暗
  const img = photo(100, 100, WHITE, [[30, 30, 70, 70, body]]);
  for (let y = 70; y < 80; y++) {
    for (let x = 20; x < 80; x++) {
      const end = x >= 30 && x < 70 ? 80 : 76; // 兩邊的影子比較短：最下面幾列是背景
      if (y < end) img.data.set([...grey(200 + (y - 70) * 4), 255], (y * 100 + x) * 4);
    }
  }
  return img;
}

test('攝影棚的淡灰影子拿掉：範圍不算它、那裡透明', () => {
  const r = cutout(withShadow(DARK));
  assert.equal(r.ok, true);
  assert.deepEqual(r.box, [30, 30, 70, 70]);
  assert.equal(at(r, 50, 75), 0);
  assert.equal(at(r, 50, 68), 255);
});

test('白色的商品不會被當成影子吃掉（往上變亮就停）', () => {
  const r = cutout(withShadow(grey(232)));
  assert.equal(r.ok, true);
  assert.deepEqual(r.box, [30, 30, 70, 70]);
  assert.equal(at(r, 50, 68), 255, '白色商品的底部還在');
});

test('商品本身是淺灰、而且越往下越暗：只在最下面三成找影子，上面七成不動', () => {
  const img = photo(100, 100, WHITE);
  for (let y = 20; y < 80; y++) {
    for (let x = 30; x < 70; x++) img.data.set([...grey(Math.round(225 - (y - 20) * 0.5)), 255], (y * 100 + x) * 4);
  }
  const r = cutout(img);
  assert.equal(r.ok, true);
  assert.deepEqual([r.box[1], r.box[3]], [20, 62], '拿掉最下面三成（18 列）');
  assert.equal(at(r, 50, 50), 255);
});

test('有顏色的淺色底部（米色、木頭）不是影子', () => {
  const r = cutout(withShadow([235, 205, 170]));
  assert.equal(r.ok, true);
  assert.equal(r.box[3], 70);
  assert.equal(at(r, 50, 68), 255);
});

test('淺灰的商品碰到照片下面：照片切到商品，不能先當影子拿掉再說沒碰到（Codex 審查）', () => {
  const img = photo(100, 100, WHITE);
  for (let y = 40; y < 100; y++) {
    for (let x = 40; x < 60; x++) img.data.set([...grey(Math.round(230 - (y - 40) * 0.5)), 255], (y * 100 + x) * 4);
  }
  const r = cutout(img);
  assert.equal(r.ok, false);
  assert.equal(r.reason, 'cut');
});

test('透明背景、黑色的商品：透明像素讀出來是黑的，商品不能被當成背景（Codex 審查）', () => {
  const img = photo(100, 100, [0, 0, 0], [], { alpha: 0 });
  for (let y = 30; y < 70; y++) for (let x = 30; x < 70; x++) img.data.set([0, 0, 0, 255], (y * 100 + x) * 4);
  const r = cutout(img);
  assert.equal(r.ok, true);
  assert.deepEqual(r.box, [30, 30, 70, 70]);
});
