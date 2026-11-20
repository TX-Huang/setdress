// 燈具目錄的純計算（不用 Three.js、不用瀏覽器）。執行：在 prototype/ 底下 `node --test`
// 驗收句子：docs/lamps.md
const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  LAMPS, CATEGORIES, MOUNTS, STOCK, partBounds, lampFit, fittedBounds,
  mountY, maxHang, clampHang, cordSpan, bestOffer, sizeLabel, dragPlane, withShape,
} = require('../lamps.js');

const near = (a, b, tol = 1e-6) => assert.ok(Math.abs(a - b) <= tol, `${a} 應該是 ${b}（誤差 ${tol} 內）`);
const nearAll = (got, want, tol = 1e-6) => want.forEach((w, i) => near(got[i], w, tol));
const byId = (id) => LAMPS.find((l) => l.id === id);
const MM = 0.001;

// ---------- 資料 ----------
test('14 盞，7 類每類剛好 2 盞，代號不重複', () => {
  assert.equal(LAMPS.length, 14);
  assert.equal(CATEGORIES.length, 7);
  for (const c of CATEGORIES) assert.equal(LAMPS.filter((l) => l.category === c).length, 2, c);
  assert.equal(new Set(LAMPS.map((l) => l.id)).size, 14);
});

test('每盞都有名稱、品牌、尺寸、lampclub 網址、放法和至少 1 家通路', () => {
  for (const l of LAMPS) {
    assert.ok(l.name && l.brand, l.id);
    assert.ok(CATEGORIES.includes(l.category), l.id);
    assert.ok(MOUNTS.includes(l.mount), l.id);
    assert.ok(l.size.w > 0 && (l.size.h === undefined || l.size.h > 0), l.id);
    assert.match(l.page, /^https:\/\/lampclub\.tw\/lamps\/[a-z0-9-]+\/$/, l.id);
    assert.ok(l.offers.length >= 1, l.id);
    for (const o of l.offers) {
      assert.ok(o.store, l.id);
      assert.ok(Number.isInteger(o.price) && o.price > 0, `${l.id} ${o.store}`);
      assert.ok(STOCK.includes(o.stock), `${l.id} ${o.store}`);
    }
  }
});

// ---------- 每種形狀的範圍（[minX, minY, minZ, maxX, maxY, maxZ]） ----------
test('旋轉體：繞著垂直軸轉，最寬的半徑決定左右和前後', () => {
  nearAll(partBounds({ k: 'lathe', pts: [[2, 0], [5, 4], [1, 6]], at: [1, 2, 3] }), [-4, 2, -2, 6, 8, 8]);
});

test('圓柱：直立的取上下兩個半徑裡大的；只有前半的從中心往前', () => {
  nearAll(partBounds({ k: 'cyl', r: 2, r2: 4, h: 6, at: [0, 10, 0] }), [-4, 7, -4, 4, 13, 4]);
  nearAll(partBounds({ k: 'cyl', r: 3, h: 2, half: true, at: [0, 0, 1] }), [-3, -1, 1, 3, 1, 4]);
});

test('圓柱：橫躺朝前（貼牆的圓盤）', () => {
  nearAll(partBounds({ k: 'cyl', r: 5, h: 2, axis: 'z', at: [0, 0, 1] }), [-5, -5, 0, 5, 5, 2]);
});

test('球：可以上下壓扁', () => {
  nearAll(partBounds({ k: 'sphere', r: 4, sy: 0.5, at: [1, 1, 1] }), [-3, -1, -3, 5, 3, 5]);
});

test('管子：兩端點加上管子粗細，斜的照角度算', () => {
  nearAll(partBounds({ k: 'tube', a: [0, 0, 0], b: [0, 10, 0], r: 1 }), [-1, 0, -1, 1, 10, 1]);
  nearAll(partBounds({ k: 'tube', a: [0, 0, 0], b: [10, 0, 0], r: 1 }), [0, -1, -1, 10, 1, 1]);
  const s = Math.SQRT1_2;
  nearAll(partBounds({ k: 'tube', a: [0, 0, 0], b: [10, 10, 0], r: 1 }), [-s, -s, -1, 10 + s, 10 + s, 1]);
});

test('提把（上半個圓環）：兩端平平地落在中心高度', () => {
  nearAll(partBounds({ k: 'arc', R: 6, r: 0.5, at: [0, 10, 0] }), [-6.5, 10, -0.5, 6.5, 16.5, 0.5]);
});

test('方塊', () => {
  nearAll(partBounds({ k: 'box', s: [2, 4, 6], at: [1, 1, 1] }), [0, -1, -2, 2, 3, 4]);
});

// ---------- 尺寸 ----------
test('每盞的示意模型，寬和高等於網頁上寫的尺寸（誤差 1 mm 內）', () => {
  for (const l of LAMPS) {
    const b = fittedBounds(l);
    near(b[3] - b[0], l.size.w / 100, MM);
    if (l.size.h !== undefined) near(b[4] - b[1], l.size.h / 100, MM);
  }
});

test('只寫寬的燈，高照原本比例等比縮放', () => {
  const only = LAMPS.filter((l) => l.size.h === undefined);
  assert.ok(only.length >= 1);
  for (const l of only) {
    const { scale } = lampFit(l);
    near(scale[1], scale[0]);
  }
});

test('前後方向跟左右用同一個比例縮放，圓的燈不會被壓扁', () => {
  for (const l of LAMPS) {
    const { scale } = lampFit(l);
    near(scale[2], scale[0]);
  }
});

test('燈泡在模型範圍裡面', () => {
  for (const l of LAMPS) {
    const b = fittedBounds(l), p = lampFit(l).light;
    for (let i = 0; i < 3; i++) assert.ok(p[i] >= b[i] - 1e-9 && p[i] <= b[i + 3] + 1e-9, `${l.id} 軸 ${i}`);
  }
});

// ---------- 怎麼放 ----------
test('立燈、桌燈、吊燈：模型最低點就是放的那個點', () => {
  for (const l of LAMPS.filter((x) => ['floor', 'table', 'pendant'].includes(x.mount))) near(fittedBounds(l)[1], 0, 1e-9);
});

test('吸頂燈：模型最高點就是天花板', () => {
  for (const l of LAMPS.filter((x) => x.mount === 'ceiling')) near(fittedBounds(l)[4], 0, 1e-9);
});

test('壁燈：背面貼牆、上下以中心為準', () => {
  for (const l of LAMPS.filter((x) => x.mount === 'wall')) {
    const b = fittedBounds(l);
    near(b[2], 0, 1e-9);
    near((b[1] + b[4]) / 2, 0, 1e-9);
  }
});

test('不管形狀畫在哪裡，都會移到掛的那個點', () => {
  // 一個 20 × 10 × 4 cm 的方塊，故意畫在離原點很遠的地方
  const box = (mount) => ({ mount, size: { w: 20, h: 10 }, light: [0, 50, 10], parts: [{ k: 'box', s: [20, 10, 4], at: [0, 50, 10] }] });
  nearAll(fittedBounds(box('floor')), [-0.1, 0, 0.08, 0.1, 0.1, 0.12]);
  nearAll(fittedBounds(box('ceiling')), [-0.1, -0.1, 0.08, 0.1, 0, 0.12]);
  nearAll(fittedBounds(box('wall')), [-0.1, -0.05, 0, 0.1, 0.05, 0.04]);
  nearAll(lampFit(box('wall')).light, [0, 0, 0.02]);
});

test('每一類燈放在對的高度', () => {
  const place = { hang: 1.7, table: 0.75, wallY: 1.6 };
  const ceiling = 2.8;
  const want = { floor: 0, table: 0.75, pendant: 1.7, ceiling: 2.8, wall: 1.6 };
  for (const l of LAMPS) near(mountY(l, place, ceiling), want[l.mount]);
});

test('吊燈：電線從燈頂接到天花板，長度跟著變', () => {
  const ph5 = byId('louis-poulsen-ph-5');
  const h = ph5.size.h / 100;
  const c = cordSpan(ph5, 1.7, 2.8);
  near(c.from, 1.7 + h);
  near(c.to, 2.8);
  near(c.length, 2.8 - 1.7 - h);
});

test('吊燈：燈頂到天花板至少留 5 cm，太長會自動調低', () => {
  const milk = byId('kimu-paper-milk');
  const h = milk.size.h / 100;
  near(maxHang(milk, 2.5), 2.5 - h - 0.05);
  near(clampHang(milk, 2.4, 2.5), 2.5 - h - 0.05);
  near(clampHang(milk, 1.5, 2.5), 1.5);
});

// ---------- 拖曳 ----------
test('拖曳：點到的高度離鏡頭夠遠，沿著那個高度的水平面移動', () => {
  assert.deepEqual(dragPlane(0.8, 1.4), { kind: 'level', y: 0.8 });
  assert.deepEqual(dragPlane(1.6, 1.4), { kind: 'level', y: 1.6 });
});

test('拖曳：跟鏡頭差不多高（15 cm 內）時，水平面會穿過鏡頭，改成面對鏡頭左右移、離鏡頭的距離不變', () => {
  assert.deepEqual(dragPlane(1.38, 1.4), { kind: 'facing' });
  assert.deepEqual(dragPlane(1.52, 1.4), { kind: 'facing' });
  assert.deepEqual(dragPlane(1.4, 1.4), { kind: 'facing' });
});

// ---------- 價格 ----------
test('預設選「有現貨」裡最便宜的，沒標示的再便宜也不選', () => {
  const offers = [
    { store: 'A', price: 33800, stock: 'unknown' },
    { store: 'B', price: 39900, stock: 'in' },
    { store: 'C', price: 39900, stock: 'in' },
    { store: 'D', price: 30000, stock: 'out' },
  ];
  const r = bestOffer(offers);
  assert.equal(r.offer.store, 'B'); // 一樣便宜時選先列的
  assert.equal(r.noneInStock, false);
});

test('沒有一家標「有現貨」時，選最便宜的並標出來', () => {
  const r = bestOffer([
    { store: 'A', price: 6800, stock: 'unknown' },
    { store: 'B', price: 6300, stock: 'out' },
    { store: 'C', price: 6300, stock: 'unknown' },
  ]);
  assert.equal(r.offer.store, 'B');
  assert.equal(r.noneInStock, true);
});

test('尺寸文字', () => {
  assert.equal(sizeLabel(byId('louis-poulsen-ph-5')), '寬 50 × 高 26.7 cm');
  assert.equal(sizeLabel(LAMPS.find((l) => l.size.h === undefined)), '寬 35 cm');
});

// ---------- 形狀：手描 / 照片自動描（docs/outline.md） ----------
const TRACED = ['audo-copenhagen-jwda', 'flos-mini-glo-ball', 'foscarini-rituals', 'kimu-paper-milk',
  'louis-poulsen-panthella', 'louis-poulsen-ph-5', 'tom-dixon-bell'];

test('有照片自動描輪廓的，是那 7 盞「轉一圈」的燈', () => {
  assert.deepEqual(LAMPS.filter((l) => l.traced).map((l) => l.id).sort(), TRACED);
});

test('選「手描」就是原本的形狀', () => {
  for (const l of LAMPS) assert.equal(withShape(l, 'hand'), l);
});

test('沒有自動描的燈（壁燈、有提把的），選「自動描」也還是手描', () => {
  for (const l of LAMPS.filter((x) => !x.traced)) assert.equal(withShape(l, 'traced'), l);
});

test('自動描：旋轉體，上下封起來，接起來就是完整的輪廓', () => {
  for (const id of TRACED) {
    const l = byId(id), parts = withShape(l, 'traced').parts;
    assert.ok(parts.every((p) => p.k === 'lathe'), id);
    assert.equal(parts[0].pts[0][0], 0, `${id} 底部封起來`);
    assert.equal(parts.at(-1).pts.at(-1)[0], 0, `${id} 頂部封起來`);
    for (let i = 1; i < parts.length; i++) {
      assert.deepEqual(parts[i].pts[0], parts[i - 1].pts.at(-1), `${id} 第 ${i} 段接著上一段`);
    }
    const joined = parts.flatMap((p, i) => (i === 0 ? p.pts : p.pts.slice(1)));
    assert.deepEqual(withoutSplitPoints(joined, l.traced), closed(l.traced), `${id} 輪廓的點一個都沒少、沒有亂加`);
  }
});

// 自動描的輪廓上下封起來（半徑 0），跟 lamps.js 的 closedOutline 分開寫
function closed(pts) {
  const out = pts[0][0] === 0 ? [...pts] : [[0, pts[0][1]], ...pts];
  return out.at(-1)[0] === 0 ? out : [...out, [0, out.at(-1)[1]]];
}
// 拿掉「為了換材質切開」加的點：不在原本的輪廓上、而且剛好在前後兩點的連線上（不改形狀）
function withoutSplitPoints(joined, traced) {
  const original = (p) => traced.some((q) => q[0] === p[0] && q[1] === p[1]);
  const onLine = (a, p, b) => Math.abs((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) < 1e-9;
  return joined.filter((p, i) => i === 0 || i === joined.length - 1 || original(p) || !onLine(joined[i - 1], p, joined[i + 1]));
}

// 手描在這個高度（手描的座標）最寬的零件；沒有就是 null
function handPartAt(parts, y) {
  const hits = parts.filter((p) => { const b = partBounds(p); return y >= b[1] && y <= b[4]; });
  const width = (p) => { const b = partBounds(p); return b[3] - b[0]; };
  return hits.reduce((best, p) => (best && width(best) >= width(p) ? best : p), null);
}

test('自動描：輪廓上每個高度的材質，都是手描在那個高度的零件（交界的那一段要切開）', () => {
  for (const id of TRACED) {
    const l = byId(id), parts = withShape(l, 'traced').parts;
    // 自動描的高（公分）→ 手描的座標：兩邊的最低點對最低點、最高點對最高點
    const hb = l.parts.map(partBounds).reduce((u, b) => [Math.min(u[0], b[1]), Math.max(u[1], b[4])], [Infinity, -Infinity]);
    const tb = parts.flatMap((p) => p.pts.map((q) => q[1])).reduce((u, y) => [Math.min(u[0], y), Math.max(u[1], y)], [Infinity, -Infinity]);
    const handY = (y) => hb[0] + (y - tb[0]) / (tb[1] - tb[0]) * (hb[1] - hb[0]);
    for (const p of parts) {
      for (let i = 1; i < p.pts.length; i++) {
        for (const t of [0.1, 0.5, 0.9]) {
          const y = p.pts[i - 1][1] + t * (p.pts[i][1] - p.pts[i - 1][1]);
          const hand = handPartAt(l.parts, handY(y));
          if (!hand) continue;
          assert.equal(`${p.m}/${p.c}`, `${hand.m}/${hand.c}`, `${id} 高 ${y.toFixed(2)} cm`);
        }
      }
    }
  }
});

test('自動描：每一段的材質，照手描在那個高度的零件（JWDA：玻璃球、深色金屬座）', () => {
  const l = byId('audo-copenhagen-jwda'), parts = withShape(l, 'traced').parts;
  const base = l.parts.find((p) => p.k === 'cyl' && p.at[1] < 5);
  const globe = l.parts.find((p) => p.k === 'sphere');
  assert.equal(parts[0].m, base.m);
  assert.equal(parts[0].c, base.c);
  assert.equal(parts.at(-1).m, globe.m);
  assert.equal(parts.at(-1).c, globe.c);
  assert.equal(parts.length, 2, '同一個零件的連續幾段併成一段：JWDA 只有座和球兩段');
});

test('自動描：手描零件之間有空隙的高度，接著用下面那個零件的材質（不是最寬的）', () => {
  const lamp = {
    id: 'gap', light: [0, 5, 0],
    parts: [
      { k: 'cyl', r: 2, h: 4, at: [0, 2, 0], m: 'metal', c: 1 }, // 高 0 到 4：細桿
      { k: 'cyl', r: 20, h: 2, at: [0, 9, 0], m: 'shade', c: 2 }, // 高 8 到 10：最寬的燈罩
    ],
    traced: [[2, 0], [2, 4], [2, 6], [20, 8], [20, 10]], // 高 4 到 8 沒有手描零件
  };
  const parts = withShape(lamp, 'traced').parts;
  assert.deepEqual(parts.map((p) => p.m), ['metal', 'shade']);
  assert.deepEqual(parts[0].pts.at(-1), [20, 8], '空隙那兩段（高 4 到 8）還是細桿的金屬');
});

test('自動描的形狀，寬和高也等於網頁上寫的尺寸（誤差 1 mm 內）', () => {
  for (const id of TRACED) {
    const l = byId(id), b = fittedBounds(withShape(l, 'traced'));
    near(b[3] - b[0], l.size.w / 100, MM);
    if (l.size.h !== undefined) near(b[4] - b[1], l.size.h / 100, MM);
  }
});

test('自動描的燈泡也在模型範圍裡面、放的位置跟手描一樣', () => {
  for (const id of TRACED) {
    const l = byId(id), t = withShape(l, 'traced');
    const b = fittedBounds(t), { light } = lampFit(t);
    for (let i = 0; i < 3; i++) assert.ok(light[i] >= b[i] - MM && light[i] <= b[i + 3] + MM, `${id} 第 ${i} 軸`);
    const hb = fittedBounds(l);
    near(b[1], hb[1], MM);
    near(b[4], hb[4], MM);
    // 照比例搬：燈泡在外框裡的相對位置（0 是最左／最低／最後面，1 是另一邊）跟手描一樣
    const hl = lampFit(l).light, rel = (v, bb, i) => (v - bb[i]) / (bb[i + 3] - bb[i]);
    for (let i = 0; i < 3; i++) near(rel(light[i], b, i), rel(hl[i], hb, i), 1e-9);
  }
});

test('換形狀不會改到原本的資料', () => {
  const l = byId('tom-dixon-bell'), before = JSON.stringify(l);
  withShape(l, 'traced');
  assert.equal(JSON.stringify(l), before);
});
