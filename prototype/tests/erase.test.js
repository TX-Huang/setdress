// 擦掉照片裡的東西（erase.js）：不用模型就能測的計算。驗收句子：docs/erase.md
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const E = require('../erase.js');

// ---------- 圈物件（MobileSAM）的輸入 ----------
test('照片縮到最長邊 1024 給 MobileSAM', () => {
  assert.deepEqual(E.samSize(2048, 1536), { w: 1024, h: 768, scale: 0.5 });
  assert.deepEqual(E.samSize(300, 600), { w: 512, h: 1024, scale: 1024 / 600 });
});

test('點的位置換成 MobileSAM 的座標，最後補一個「沒有框」的空點', () => {
  const p = E.samPrompt([{ x: 100, y: 50 }, { x: 10, y: 20 }], 0.5);
  assert.deepEqual(Array.from(p.coords), [50, 25, 5, 10, 0, 0]);
  assert.deepEqual(Array.from(p.labels), [1, 1, -1]);
  assert.equal(p.count, 3);
});

test('拖一個框：框的兩個角（標 2、3）接在點後面，不加補位的點（大沙發一次圈起來）', () => {
  const p = E.samPrompt([{ x: 100, y: 50 }], 0.5, { x0: 10, y0: 20, x1: 300, y1: 200 });
  assert.deepEqual(Array.from(p.coords), [50, 25, 5, 10, 150, 100]);
  assert.deepEqual(Array.from(p.labels), [1, 2, 3]);
  assert.equal(p.count, 3);
});

test('只有框、沒有點也可以；框畫反了（由右下往左上拖）也對', () => {
  const p = E.samPrompt([], 1, { x0: 300, y0: 200, x1: 10, y1: 20 });
  assert.deepEqual(Array.from(p.coords), [10, 20, 300, 200]);
  assert.deepEqual(Array.from(p.labels), [2, 3]);
});

test('照片像素（RGBA）換成 MobileSAM 要的 [高, 寬, 3]（0 到 255，不用先正規化）', () => {
  const rgba = Uint8ClampedArray.from([10, 20, 30, 255, 40, 50, 60, 255]);
  assert.deepEqual(Array.from(E.toHWC(rgba)), [10, 20, 30, 40, 50, 60]);
});

test('模型輸出大於 0 的是物件', () => {
  assert.deepEqual(Array.from(E.maskFromLogits(Float32Array.from([-1, 0, 0.5, 3]))), [0, 0, 1, 1]);
});

// ---------- 往外多擴一點 ----------
test('範圍往外擴 r 個像素（上下左右斜角都擴），不會超出照片', () => {
  const w = 7, h = 7, m = new Uint8Array(w * h);
  m[3 * w + 3] = 1;
  const d = E.dilate(m, w, h, 2);
  const at = (x, y) => d[y * w + x];
  assert.equal(at(3, 3), 1);
  assert.equal(at(5, 3), 1, '右邊 2 格');
  assert.equal(at(1, 1), 1, '斜角 2 格');
  assert.equal(at(6, 3), 0, '3 格以外不算');
  assert.equal(d.reduce((a, b) => a + b, 0), 25);
  const edge = new Uint8Array(w * h);
  edge[0] = 1;
  assert.equal(E.dilate(edge, w, h, 1).reduce((a, b) => a + b, 0), 4, '角落不會跑到照片外面');
});

test('擴多少：照片長邊的 1%，至少 3 px', () => {
  assert.equal(E.growPixels(2000, 1500), 20);
  assert.equal(E.growPixels(200, 100), 3);
});

// ---------- 補圖（MI-GAN）----------
test('MI-GAN 的遮罩：0 是要補的、255 是保留的（實際跑模型試出來的）', () => {
  assert.deepEqual(Array.from(E.miganMask(Uint8Array.from([1, 0, 1]))), [0, 255, 0]);
});

test('RGBA 和 MI-GAN 的 [3, 高, 寬] 互換', () => {
  const rgba = Uint8ClampedArray.from([1, 2, 3, 255, 4, 5, 6, 255]); // 2 x 1
  const chw = E.toCHW(rgba, 2, 1);
  assert.deepEqual(Array.from(chw), [1, 4, 2, 5, 3, 6]);
});

test('補好的只用在範圍裡；範圍外的像素一個都不變', () => {
  const orig = Uint8ClampedArray.from([10, 10, 10, 255, 20, 20, 20, 255, 30, 30, 30, 255]); // 3 x 1
  const result = Uint8Array.from([99, 98, 97, 88, 87, 86, 77, 76, 75]); // CHW
  const mask = Uint8Array.from([0, 1, 0]);
  const out = E.composite(orig, result, mask, 3, 1);
  assert.deepEqual(Array.from(out), [10, 10, 10, 255, 98, 87, 76, 255, 30, 30, 30, 255]);
  assert.deepEqual(Array.from(orig), [10, 10, 10, 255, 20, 20, 20, 255, 30, 30, 30, 255], '原本的不改');
});

// ---------- 遮擋深度 ----------
test('擦掉的地方遮擋深度變成 0；深度圖解析度跟照片不一樣也對得上；原本的不改', () => {
  const depth = { width: 2, height: 2, mm: Uint16Array.from([1000, 2000, 3000, 4000]) };
  const mask = new Uint8Array(4 * 4); // 照片 4 x 4，右上角 2 x 2 擦掉
  for (const [x, y] of [[2, 0], [3, 0], [2, 1], [3, 1]]) mask[y * 4 + x] = 1;
  const out = E.eraseDepth(depth, mask, 4, 4);
  assert.deepEqual(Array.from(out.mm), [1000, 0, 3000, 4000]);
  assert.deepEqual(Array.from(depth.mm), [1000, 2000, 3000, 4000]);
  assert.equal(out.width, 2);
});

test('深度圖的一格只要碰到擦掉的範圍就變成 0（寧可不擋）', () => {
  const depth = { width: 1, height: 1, mm: Uint16Array.from([1500]) };
  const mask = new Uint8Array(16);
  mask[0] = 1; // 照片 4 x 4 只擦一個像素
  assert.deepEqual(Array.from(E.eraseDepth(depth, mask, 4, 4).mm), [0]);
});

test('沒有深度圖（示範房間、AI 沒跑）：還是沒有', () => {
  assert.equal(E.eraseDepth(null, new Uint8Array(4), 2, 2), null);
});

// ---------- 復原 ----------
test('復原一步一步回去；全部還原回到第一張；換照片清掉', () => {
  let h = E.history('原本');
  h = E.pushStep(h, '擦 1');
  h = E.pushStep(h, '擦 2');
  assert.equal(E.current(h), '擦 2');
  h = E.undoStep(h);
  assert.equal(E.current(h), '擦 1');
  h = E.undoStep(E.undoStep(h));
  assert.equal(E.current(h), '原本', '回到原本就停住');
  h = E.pushStep(E.pushStep(h, 'a'), 'b');
  assert.equal(E.current(E.resetSteps(h)), '原本');
  assert.equal(E.canUndo(E.history('新照片')), false);
});

test('最多記 MAX_STEPS 步（含原本）：太多時丟掉最舊的中間步，原本的一定留著（Codex 審查：記憶體）', () => {
  let h = E.history('原本');
  for (let i = 1; i <= 10; i++) h = E.pushStep(h, `擦 ${i}`, 4);
  assert.deepEqual(h.steps, ['原本', '擦 8', '擦 9', '擦 10']);
  assert.equal(E.current(h), '擦 10');
  h = E.undoStep(E.undoStep(E.undoStep(h)));
  assert.equal(E.current(h), '原本');
  assert.ok(E.MAX_STEPS >= 4 && E.MAX_STEPS <= 10, '照片 2048 px 一步約 20 MB，不能太多');
});
