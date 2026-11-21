// AI 生的 3D 放進模擬器（goods.js 的 parseGlb、modelScale、modelFor；cutout.js 的 fillBackground）
// 驗收句子：docs/model3d.md 第 7 到 10 句
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const G = require('../goods.js');
const { fillBackground } = require('../cutout.js');

// 跟 tools/model3d/glb.py 一樣的格式：點、照片座標、面
function makeGlb(positions, uvs, indices) {
  const pos = Buffer.from(new Float32Array(positions).buffer);
  const tex = Buffer.from(new Float32Array(uvs).buffer);
  const small = positions.length / 3 < 65536;
  let idx = Buffer.from((small ? new Uint16Array(indices) : new Uint32Array(indices)).buffer);
  const idxLen = idx.length;
  if (idx.length % 4) idx = Buffer.concat([idx, Buffer.alloc(4 - (idx.length % 4))]);
  const bin = Buffer.concat([pos, tex, idx]);
  const doc = {
    asset: { version: '2.0' },
    meshes: [{ primitives: [{ attributes: { POSITION: 0, TEXCOORD_0: 1 }, indices: 2 }] }],
    accessors: [
      { bufferView: 0, componentType: 5126, count: positions.length / 3, type: 'VEC3' },
      { bufferView: 1, componentType: 5126, count: uvs.length / 2, type: 'VEC2' },
      { bufferView: 2, componentType: small ? 5123 : 5125, count: indices.length, type: 'SCALAR' },
    ],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: pos.length },
      { buffer: 0, byteOffset: pos.length, byteLength: tex.length },
      { buffer: 0, byteOffset: pos.length + tex.length, byteLength: idxLen },
    ],
    buffers: [{ byteLength: bin.length }],
  };
  let json = Buffer.from(JSON.stringify(doc));
  if (json.length % 4) json = Buffer.concat([json, Buffer.alloc(4 - (json.length % 4), 0x20)]);
  const head = Buffer.alloc(12), jh = Buffer.alloc(8), bh = Buffer.alloc(8);
  head.write('glTF', 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(12 + 8 + json.length + 8 + bin.length, 8);
  jh.writeUInt32LE(json.length, 0); jh.write('JSON', 4);
  bh.writeUInt32LE(bin.length, 0); bh.write('BIN\0', 4);
  const all = Buffer.concat([head, jh, json, bh, bin]);
  return all.buffer.slice(all.byteOffset, all.byteOffset + all.length);
}

test('parseGlb：讀出點、照片座標、面', () => {
  const g = G.parseGlb(makeGlb([0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 1, 1, 0, 0], [0, 1, 2]));
  assert.deepEqual([...g.positions], [0, 0, 0, 1, 0, 0, 0, 1, 0]);
  assert.deepEqual([...g.uvs], [0, 1, 1, 1, 0, 0]);
  assert.deepEqual([...g.indices], [0, 1, 2]);
  assert.ok(g.indices instanceof Uint16Array);
});

test('parseGlb：點很多時面是 32 位元', () => {
  const n = 70000, pos = new Array(n * 3).fill(0), uv = new Array(n * 2).fill(0);
  const g = G.parseGlb(makeGlb(pos, uv, [0, 1, n - 1]));
  assert.ok(g.indices instanceof Uint32Array);
  assert.deepEqual([...g.indices], [0, 1, n - 1]);
});

test('parseGlb：不是 GLB 就丟錯（退回立牌）', () => {
  const png = new Uint8Array(64);
  png.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  assert.throws(() => G.parseGlb(png.buffer), /不是 GLB/);
});

test('modelScale：一單位是幾公尺，照 goods.md 第 11 句（寬、高各算一次取大的）', () => {
  assert.equal(G.modelScale({ w: 200, d: 90, h: 80 }, [2, 0.8, 1]), 1);
  assert.equal(G.modelScale({ w: 207, d: 99, h: 40 }, [1.8, 0.6, 1]), 1.15, '高度只是座高：照寬度');
  assert.equal(G.modelScale({ w: null, d: null, h: 90 }, [1, 0.6, 1]), 1.5);
});

test('modelFor：這個尺寸的照片裡有做 3D 用的那張，才用 3D', () => {
  const models = { 'g:a': { file: 'x.glb', photo: 'https://p/red.jpg', photoIndex: 0 } };
  const item = { id: 'g:a', sizes: [{ photos: ['https://p/red.jpg'] }, { photos: ['https://p/blue.jpg'] }] };
  assert.equal(G.modelFor(models, item, 0).file, 'x.glb');
  assert.equal(G.modelFor(models, item, 1), null, '藍色的那個尺寸照片不一樣：用立牌');
  assert.equal(G.modelFor(models, { ...item, id: 'g:b' }, 0), null);
  assert.equal(G.modelFor(null, item, 0), null, '沒有 index 也不會壞');
});

test('modelFor：做 3D 的照片在這個尺寸的同一個位置才算（藍色款前面是自己的照片、後面才是紅色的大圖）', () => {
  const models = { 'g:a': { file: 'x.glb', photo: 'https://p/red.jpg', photoIndex: 0 } };
  const item = { id: 'g:a', sizes: [{ photos: ['https://p/red.jpg'] }, { photos: ['https://p/blue.jpg', 'https://p/red.jpg'] }] };
  assert.equal(G.modelFor(models, item, 0).file, 'x.glb');
  assert.equal(G.modelFor(models, item, 1), null);
});

test('sameFraming：店家換了同一個網址的照片（商品的位置、照片比例變了）就不用 3D', () => {
  const model = { box: [100, 50, 700, 450], wh: [800, 600] };
  assert.equal(G.sameFraming(model, [50, 25, 350, 225], [400, 300]), true, '一樣的照片縮小一半');
  assert.equal(G.sameFraming(model, [52, 26, 351, 226], [400, 300]), true, '差一兩個像素沒關係');
  assert.equal(G.sameFraming(model, [50, 25, 320, 225], [400, 300]), true, '去背邊緣差一點（同一張照片縮放不同，多留或少留一小塊）沒關係');
  assert.equal(G.sameFraming(model, [100, 50, 300, 250], [400, 300]), false, '商品位置不一樣');
  assert.equal(G.sameFraming(model, [100, 67, 700, 600], [800, 800]), false, '照片比例不一樣（商品位置換成 0 到 1 一樣）');
});

test('fillBackground：去背以外的地方用最近的商品顏色補（側面不會出現白邊）', () => {
  // 3 x 1：左邊紅色是商品，中間、右邊是白底
  const data = new Uint8ClampedArray([200, 10, 10, 255, 255, 255, 255, 255, 250, 250, 250, 255]);
  fillBackground(data, new Uint8Array([255, 0, 0]), 3, 1);
  assert.deepEqual([...data], [200, 10, 10, 255, 200, 10, 10, 255, 200, 10, 10, 255]);
});

test('fillBackground：照片裡沒有商品（全透明）就不動', () => {
  const data = new Uint8ClampedArray([1, 2, 3, 0, 4, 5, 6, 0]);
  fillBackground(data, new Uint8Array([0, 0]), 2, 1);
  assert.deepEqual([...data], [1, 2, 3, 0, 4, 5, 6, 0]);
});

test('fillBackground：補的是最近的那個（兩邊不同色）', () => {
  const data = new Uint8ClampedArray(5 * 4).fill(255);
  data.set([10, 20, 30, 255], 0);
  data.set([90, 80, 70, 255], 16);
  fillBackground(data, new Uint8Array([255, 0, 0, 0, 255]), 5, 1);
  assert.deepEqual([...data.slice(4, 8)], [10, 20, 30, 255]);
  assert.deepEqual([...data.slice(12, 16)], [90, 80, 70, 255]);
});

// ---------- 真的資料 ----------
test('models3d/index.json：每一筆的 GLB 在、讀得出來、照片座標在 0 到 1、不超過 400 KB', () => {
  const dir = path.join(__dirname, '..', 'models3d');
  const index = JSON.parse(fs.readFileSync(path.join(dir, 'index.json'), 'utf8'));
  assert.ok(Object.keys(index.models).length >= 5, '至少有幾件 3D（空的就沒測到東西）');
  for (const [id, m] of Object.entries(index.models)) {
    assert.ok(Number.isInteger(m.photoIndex) && m.photoIndex >= 0, id);
    const file = path.join(dir, m.file);
    assert.ok(fs.statSync(file).size <= 400 * 1024, id);
    const buf = fs.readFileSync(file);
    const g = G.parseGlb(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length));
    assert.ok(g.positions.length > 0 && g.indices.length > 0, id);
    assert.ok(g.uvs.every((v) => v >= -1e-4 && v <= 1 + 1e-4), id);
    assert.match(m.photo, /^https:\/\//, id);
    assert.equal(m.extent.length, 3, id);
    assert.ok(m.score >= 0.6, id);
  }
});

// ---------- 側面、背面不要條紋（docs/model3d.md 第 16、17 句） ----------
const { softColors } = require('../cutout.js');

test('frontWeight：正對照片（nz 0.6 以上）完全用照片，0.25 以下完全用平滑顏色', () => {
  assert.equal(G.frontWeight(1), 1);
  assert.equal(G.frontWeight(0.6), 1);
  assert.equal(G.frontWeight(0.25), 0);
  assert.equal(G.frontWeight(0), 0); // 側面
  assert.equal(G.frontWeight(-1), 0); // 背面
});

test('frontWeight：中間慢慢換（正中間一半、越正越多）', () => {
  assert.ok(Math.abs(G.frontWeight((G.FRONT_LO + G.FRONT_HI) / 2) - 0.5) < 1e-9);
  let last = -1;
  for (let nz = 0.3; nz <= 0.75; nz += 0.01) {
    const w = G.frontWeight(nz);
    assert.ok(w >= last, `nz ${nz.toFixed(2)} 應該不比前面少`);
    last = w;
  }
});

const rgba = (w, h, at) => {
  const d = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) d.set([...at(x, y), 255], (y * w + x) * 4);
  return d;
};

test('softColors：長邊縮成 16 格，短邊照比例', () => {
  const out = softColors(rgba(100, 50, () => [10, 20, 30]), 100, 50, 16);
  assert.equal(out.w, 16);
  assert.equal(out.h, 8);
  assert.equal(out.data.length, 16 * 8 * 4);
});

test('softColors：一樣顏色的照片，每格都是那個顏色', () => {
  const out = softColors(rgba(40, 30, () => [10, 20, 30]), 40, 30, 16);
  for (let i = 0; i < out.w * out.h; i++) assert.deepEqual([...out.data.slice(i * 4, i * 4 + 4)], [10, 20, 30, 255]);
});

test('softColors：每格是那一格的平均（左紅右藍、黑白相間）', () => {
  const halves = softColors(rgba(4, 2, (x) => (x < 2 ? [200, 0, 0] : [0, 0, 200])), 4, 2, 2);
  assert.deepEqual([...halves.data], [200, 0, 0, 255, 0, 0, 200, 255]);
  const checker = softColors(rgba(2, 2, (x, y) => ((x + y) % 2 ? [255, 255, 255] : [0, 0, 0])), 2, 2, 1);
  assert.deepEqual([...checker.data], [128, 128, 128, 255]);
});

test('softColors：照片比格子小就照原本（不放大）', () => {
  const src = rgba(3, 1, (x) => [x * 10, 0, 0]);
  const out = softColors(src, 3, 1, 16);
  assert.equal(out.w, 3);
  assert.equal(out.h, 1);
  assert.deepEqual([...out.data], [...src]);
});

test('frontWeight：兩頭是平的（smoothstep，跟 shader 一樣；換的地方看不出接縫）', () => {
  const at = (t) => G.frontWeight(G.FRONT_LO + t * (G.FRONT_HI - G.FRONT_LO));
  assert.ok(at(0.05) < 0.01, '剛開始換的地方幾乎還是平滑顏色');
  assert.ok(at(0.95) > 0.99, '快換完的地方幾乎已經是照片');
  assert.ok(Math.abs(at(0.25) - 0.15625) < 1e-9);
});

test('frontWeight：nz 剛超過 0.25 就開始用一點照片', () => {
  assert.ok(G.frontWeight(0.27) > 0);
  assert.ok(G.frontWeight(0.58) < 1);
});

test('softColors：每格用到那一格的每個像素（不多也不少）', () => {
  const row = softColors(rgba(4, 1, (x) => [[0, 100, 200, 60][x], 0, 0]), 4, 1, 2);
  assert.deepEqual([row.data[0], row.data[4]], [50, 130]);
  const col = softColors(rgba(2, 4, (x, y) => (y < 2 ? [200, 0, 0] : [0, 0, 200])), 2, 4, 2);
  assert.equal(col.w, 1);
  assert.deepEqual([...col.data], [200, 0, 0, 255, 0, 0, 200, 255]);
});
