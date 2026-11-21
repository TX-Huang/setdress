// 房間的牆往哪個方向（webalign.js 的 wallAngle）、3D 放進來的方向、吸到牆（goods.js）
// 驗收句子：docs/model3d.md 第 11 到 15 句
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const W = require('../webalign.js');
const G = require('../goods.js');

const DEG = Math.PI / 180;
const CAM = { height: 1.4, pitch: 10, roll: 0, fov: 60, aspect: 4 / 3, ceiling: 2.7 };

// 假的深度圖：鏡頭站在一個 6 x 6 公尺的房間裡（中心在前方 2.5 公尺），房間轉了 turn 度。
// 跟遮擋圖一樣：地板、天花板是 0，只有牆有深度。
// noise：AI 深度的誤差是一大片一大片的（8 x 8 一塊偏一樣多，跟 webalign 其他測試一樣），不是每個像素亂跳
function roomDepth(turn, { width = 96, height = 72, noise = 0, table = false, slats = false, fineSlats = 0 } = {}) {
  const t = Math.tan((CAM.fov * DEG) / 2), a = -CAM.pitch * DEG;
  const R = [[1, 0, 0], [0, Math.cos(a), -Math.sin(a)], [0, Math.sin(a), Math.cos(a)]];
  const o = [0, CAM.height, 0], centre = [0, 0, -2.5], half = 3, r = turn * DEG;
  const normals = [0, 90, 180, 270].map((k) => [Math.sin(r + k * DEG), 0, Math.cos(r + k * DEG)]); // 朝房間裡面
  const meters = new Float32Array(width * height);
  let s = 5;
  const rand = () => ((s = (s * 16807) % 2147483647) / 2147483647 - 0.5) * 2;
  const blocks = Array.from({ length: Math.ceil(width / 8) * Math.ceil(height / 8) }, () => 1 + noise * rand());
  const blockAt = (row, col) => blocks[Math.floor(row / 8) * Math.ceil(width / 8) + Math.floor(col / 8)];
  for (let row = 0; row < height; row++) {
    for (let col = 0; col < width; col++) {
      const u = (col + 0.5) / width, v = (row + 0.5) / height;
      const c = [(2 * u - 1) * t * CAM.aspect, (1 - 2 * v) * t, -1];
      const dir = R.map((rr) => rr[0] * c[0] + rr[1] * c[1] + rr[2] * c[2]);
      let best = Infinity;
      for (const n of normals) {
        const wall = centre.map((x, i) => x - n[i] * half); // 牆上的一點（法線朝裡面）
        const nd = n[0] * dir[0] + n[2] * dir[2];
        if (nd >= 0) continue;
        const tt = (n[0] * (wall[0] - o[0]) + n[2] * (wall[2] - o[2])) / nd;
        if (tt > 0) best = Math.min(best, tt);
      }
      const y = o[1] + dir[1] * best;
      let d = y <= 0 || y >= CAM.ceiling ? 0 : best * blockAt(row, col);
      // 桌面：75 cm 高、平的一大塊（不是牆，不能算進去）
      const tTable = dir[1] < 0 ? (0.75 - o[1]) / dir[1] : Infinity;
      const hit = along(o, dir, tTable);
      if (table && tTable < best && Math.abs(hit[0]) < 1.2 && hit[2] < -1.5 && hit[2] > -3) d = tTable;
      // 格柵隔間：畫面左邊三分之一，每兩欄前後差 0.6 公尺（深度一直斷掉的地方不能算進去）
      if (slats && col < width / 3 && d > 0) d = Math.min(d, 2.2 + (Math.floor(col / 2) % 2) * 0.6);
      // 細格柵：左半邊，跟牆平行、在牆前面，每 fineSlats 欄一前一後差 0.3 公尺（差一成，深度斷掉但不明顯）
      if (fineSlats && col < width / 2 && d > 0 && Math.floor(col / fineSlats) % 2) d -= 0.3;
      meters[row * width + col] = d;
    }
  }
  return { meters, width, height };
}
const along = (o, dir, t) => o.map((x, i) => x + dir[i] * t);
const near = (got, want, tol, msg) => {
  assert.ok(Number.isFinite(got), `${msg}：沒算出來（${got}）`); // null 不能當 0 過關（Codex 審查）
  const d = Math.abs((((got - want) % 90) + 135) % 90 - 45);
  assert.ok(d <= tol, `${msg}：算出 ${got}，應該是 ${want}`);
};

test('wallAngle：房間轉了 30°，從深度算出牆的方向是 30°（四個方向一組，0 到 90）', () => {
  near(W.wallAngle(CAM, roomDepth(30)), 30, 2, '30°');
});

test('wallAngle：轉 75°、深度一大片一大片偏 3% 也找得到', () => {
  near(W.wallAngle(CAM, roomDepth(75, { noise: 0.03 })), 75, 3, '75°');
});

test('wallAngle：前面有一大張桌子（平的面不算牆）', () => {
  near(W.wallAngle(CAM, roomDepth(30, { table: true })), 30, 2, '有桌子');
});

test('wallAngle：有一排格柵隔間（深度一直斷掉的地方不算）', () => {
  near(W.wallAngle(CAM, roomDepth(30, { slats: true })), 30, 3, '有格柵');
});

test('uprightFacing：三個相鄰的點：牆回它朝哪；平的（桌面、地板）、跨過深度斷掉的地方不算', () => {
  const F = W._internal.uprightFacing;
  // 牆：x = 0 的面（朝 +x 或 -x），點在 3 公尺外
  near(F([0, 1, -3], [0, 1, -3.03], [0, 0.97, -3]), 90, 1, '朝 x 的牆');
  assert.equal(F([0, 0.75, -3], [0.03, 0.75, -3], [0, 0.75, -3.03]), null, '平的桌面');
  assert.equal(F([0, 1, -3], [0, 1, -3.8], [0, 0.97, -3]), null, '右邊那點在後面 0.8 公尺：深度斷掉');
  assert.equal(F(null, [0, 1, -3], [0, 0.97, -3]), null, '沒有深度');
});

test('wallAngle：照片解析度高、格柵很細（每 7 個像素一前一後）：抽樣不會把格柵看成斜的牆（Codex 審查）', () => {
  near(W.wallAngle(CAM, roomDepth(30, { width: 448, height: 336, fineSlats: 7 })), 30, 3, '細格柵');
});

test('wallAngle：深度有無限大、不是數字的點：跳過，不會算出 NaN（Codex 審查）', () => {
  const d = roomDepth(30);
  for (let i = 0; i < d.meters.length; i += 7) d.meters[i] = i % 2 ? Infinity : NaN;
  near(W.wallAngle(CAM, d), 30, 3, '有壞點');
  const bad = { meters: new Float32Array(96 * 72).fill(Infinity), width: 96, height: 72 };
  assert.equal(W.wallAngle(CAM, bad), null);
});

test('peakDeg：每個方向的票都差不多（亂的房間、沒有明顯的牆）回 null，不亂猜（Codex 審查）', () => {
  assert.equal(W._internal.peakDeg(new Float32Array(90).fill(10)), null);
});

test('peakDeg：牆的方向剛好在兩格中間，票分成兩半，還是比旁邊集中在一格的多', () => {
  const votes = new Float32Array(90);
  votes[30] = 40; votes[31] = 40; votes[60] = 60;
  near(W._internal.peakDeg(votes), 31, 1, '兩格中間');
});

test('wallAngle：牆跟畫面平行是 0', () => {
  near(W.wallAngle(CAM, roomDepth(0)), 0, 2, '0°');
});

test('wallAngle：沒有深度（示範房間、還沒對齊）回 null', () => {
  assert.equal(W.wallAngle(CAM, null), null);
  assert.equal(W.wallAngle(CAM, { meters: new Float32Array(96 * 72), width: 96, height: 72 }), null);
});

test('startYaw：放進來時轉成跟牆平行、正面朝鏡頭那一側', () => {
  assert.equal(G.startYaw(10, 30), 30, '鏡頭在 10° 方向：30° 那面最近');
  assert.equal(G.startYaw(-50, 30), -60, '30 - 90 = -60 最近');
  assert.equal(G.startYaw(170, 0), 180);
  assert.equal(G.startYaw(25, null), 25, '不知道牆在哪：照原本面對鏡頭');
});

test('snapYaw：拉到牆的方向 5° 以內就吸過去', () => {
  assert.equal(G.snapYaw(33, 30), 30);
  assert.equal(G.snapYaw(-57, 30), -60);
  assert.equal(G.snapYaw(40, 30), 40, '差 10° 不吸');
  assert.equal(G.snapYaw(178, 0), 180);
  assert.equal(G.snapYaw(12, null), 12);
});

test('turn90：轉 90° 換到旁邊那面牆，超過 180 繞回來', () => {
  assert.equal(G.turn90(30), 120);
  assert.equal(G.turn90(150), -120);
});
