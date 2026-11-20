/* Setdress 燈具目錄（示意）＋擺放和價格的純計算。驗收句子：docs/lamps.md
 *
 * 資料：2026-11-20 用瀏覽器看 lampclub.tw 14 盞燈的頁面，人工抄下來（lampclub 條款不准用程式大量抓）。
 * 每盞只取一個尺寸，只列有賣這個尺寸的通路。價格、庫存以通路頁面為準。
 * stock：'in' = lampclub 在那家通路旁邊標「有現貨」（整個系列的標示）；'out' = 這個尺寸標預購；'unknown' = 沒標示。
 *
 * 形狀：看商品照片簡化的示意，不是原廠 3D。用公分畫，lampFit 再縮放成網頁上寫的尺寸。
 *   lathe  旋轉體：pts = [[半徑, 高], ...]，繞著通過 at 的垂直軸轉
 *   cyl    圓柱：r 上半徑、r2 下半徑（預設同 r）、h 長；axis 'y' 直立（預設）、'z' 朝前；
 *          half 只有前半（貼牆）；open 上下不封（燈罩）
 *   sphere 球：r 半徑，sy 上下壓扁的比例
 *   tube   管子：從 a 到 b，半徑 r
 *   arc    上半個圓環（提把）：R 大半徑、r 管子半徑，兩端落在 at 的高度
 *   box    方塊：s = [寬, 高, 深]
 * m：材質（metal 金屬、shade 透光燈罩、glass 乳白玻璃、wood 木頭）；c：顏色；inner：燈罩裡面會發亮
 * light：燈泡位置（公分，跟形狀同一套座標）；beam：'down' 往下照、'all' 往四周照
 *
 * 瀏覽器用 <script src="lamps.js">（window.SetdressLamps），Node 測試用 require。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SetdressLamps = api;
})(typeof self !== 'undefined' ? self : this, () => {
  'use strict';

  const CATEGORIES = ['吊燈', '桌燈', '無線桌燈', '立燈', '壁燈', '吸頂燈', '戶外燈'];
  const MOUNTS = ['floor', 'table', 'pendant', 'ceiling', 'wall'];
  const STOCK = ['in', 'out', 'unknown'];
  const UPDATED = '2026-11-20';
  const MIN_CORD = 0.05; // 吊燈燈頂到天花板至少留 5 cm
  const DRAG_GAP = 0.15; // 點到的高度跟鏡頭差這麼多以內，就不用水平面拖

  const WHITE = 0xf2f0eb, OPAL = 0xf4f2ec, BLACK = 0x2a2a29;
  const LP = (slug) => `https://lampclub.tw/lamps/${slug}/`;
  const shop = (store, price, stock) => ({ store, price, stock });

  const LAMPS = [
    {
      id: 'louis-poulsen-ph-5', category: '吊燈', mount: 'pendant',
      brand: 'Louis Poulsen', name: 'PH 5', variant: 'Ø50 cm', designer: 'Poul Henningsen',
      size: { w: 50, h: 26.7 }, page: LP('louis-poulsen-ph-5'),
      offers: [shop('北歐先生', 33800, 'unknown'), shop('居雅堂', 39900, 'unknown'), shop('Design Butik', 39900, 'in'),
        shop('Motive', 39900, 'in'), shop('散步舖', 39900, 'in')],
      beam: 'down', light: [0, 9, 0],
      parts: [
        { k: 'lathe', pts: [[4, 26.7], [8, 25.5], [12, 22.5], [15, 18.5], [16, 17]], m: 'shade', c: WHITE, inner: true },
        { k: 'lathe', pts: [[12.5, 19], [17, 16.5], [21, 13], [24, 10], [25, 8.6]], m: 'shade', c: WHITE, inner: true },
        { k: 'lathe', pts: [[9, 11], [12, 8], [14.5, 5], [16, 3.4]], m: 'shade', c: WHITE, inner: true },
        { k: 'lathe', pts: [[0.5, 0], [4, 0.6], [6.5, 1.8], [7.5, 2.6]], m: 'shade', c: WHITE },
        { k: 'cyl', r: 2, h: 6, at: [0, 15, 0], m: 'metal', c: 0x9a9a98 },
        { k: 'cyl', r: 0.8, h: 12, at: [0, 20.7, 0], m: 'metal', c: 0x9a9a98 }, // 中心桿：電線接到這裡
      ],
    },
    {
      id: 'kimu-paper-milk', category: '吊燈', mount: 'pendant',
      brand: '柒木 KIMU DESIGN', name: '紙牛奶燈', variant: 'Ø55 cm', designer: '',
      size: { w: 55, h: 43 }, page: LP('kimu-design-cd183a'),
      offers: [shop('瑪黑', 7280, 'unknown'), shop('Design Butik', 7280, 'in'), shop('散步舖', 7280, 'in'), shop('柒木', 7280, 'in')],
      beam: 'all', light: [0, 20, 0],
      parts: [
        { k: 'lathe', pts: [[17, 0], [22, 2], [26.5, 7], [27.5, 12], [26, 17], [23.5, 20], [22.5, 23], [21.5, 27], [18, 32], [13, 36], [8, 39], [4, 40.5]], m: 'shade', c: 0xf1ebdf },
        { k: 'cyl', r: 3.5, h: 3, at: [0, 41.5, 0], m: 'wood', c: 0x8a5a3c },
      ],
    },
    {
      id: 'audo-copenhagen-jwda', category: '桌燈', mount: 'table',
      brand: 'Audo Copenhagen', name: 'JWDA', variant: '金屬底座', designer: 'Jonas Wagell',
      size: { w: 17, h: 29 }, page: LP('audo-copenhagen-jwda'),
      offers: [shop('Design Butik', 8197, 'in'), shop('散步舖', 9990, 'unknown'), shop('瑪黑', 10170, 'unknown'),
        shop('Loft29', 10170, 'in'), shop('WOW', 10670, 'in')],
      beam: 'all', light: [0, 19.6, 0],
      parts: [
        { k: 'cyl', r: 5.5, h: 9, at: [0, 4.5, 0], m: 'metal', c: 0x6b5a45 },
        { k: 'cyl', r: 2.2, h: 1.6, at: [0, 9.8, 0], m: 'metal', c: 0x6b5a45 },
        { k: 'sphere', r: 8.5, sy: 1.1, at: [0, 19.65, 0], m: 'glass', c: OPAL },
      ],
    },
    {
      id: 'marset-ginger', category: '桌燈', mount: 'table',
      brand: 'Marset', name: 'Ginger', variant: 'S（Ø32）', designer: 'Joan Gaspar',
      size: { w: 32, h: 46.5 }, page: LP('marset-ginger'),
      offers: [shop('Loft29', 34500, 'unknown'), shop('Motive', 34500, 'unknown'), shop('散步舖', 34500, 'in')],
      beam: 'down', light: [0, 38.5, 0],
      parts: [
        { k: 'cyl', r: 9, h: 2, at: [0, 1, 0], m: 'metal', c: 0xe8e5de },
        { k: 'tube', a: [0, 2, 0], b: [0, 40, 0], r: 0.6, m: 'metal', c: 0xe8e5de },
        { k: 'lathe', pts: [[16, 36], [15.2, 39], [12.5, 42.5], [8, 45], [3, 46.3], [0.5, 46.5]], m: 'wood', c: 0xc49a6c, inner: true },
      ],
    },
    {
      id: 'audo-copenhagen-carrie', category: '無線桌燈', mount: 'table',
      brand: 'Audo Copenhagen', name: 'Carrie', variant: '黑色', designer: 'Norm Architects',
      size: { w: 13.5, h: 24.5 }, page: LP('audo-copenhagen-carrie'),
      offers: [shop('Loft29', 7570, 'in'), shop('WOW', 7570, 'unknown'), shop('NOSA', 7570, 'unknown'), shop('北歐先生', 8800, 'unknown'),
        shop('Design Butik', 9800, 'in'), shop('散步舖', 10070, 'unknown')],
      beam: 'all', light: [0, 8.6, 0],
      parts: [
        { k: 'cyl', r: 6.75, h: 3.5, at: [0, 1.75, 0], m: 'metal', c: BLACK },
        { k: 'sphere', r: 5.4, at: [0, 8.6, 0], m: 'glass', c: OPAL },
        { k: 'tube', a: [-6, 3.5, 0], b: [-6, 18.1, 0], r: 0.4, m: 'metal', c: BLACK },
        { k: 'tube', a: [6, 3.5, 0], b: [6, 18.1, 0], r: 0.4, m: 'metal', c: BLACK },
        { k: 'arc', R: 6, r: 0.4, at: [0, 18.1, 0], m: 'metal', c: BLACK },
      ],
    },
    {
      id: 'tom-dixon-bell', category: '無線桌燈', mount: 'table',
      brand: 'Tom Dixon', name: 'Bell', variant: '可攜式', designer: 'Tom Dixon',
      size: { w: 19, h: 28 }, page: LP('tom-dixon-bell'),
      offers: [shop('潤舍', 10600, 'unknown'), shop('Loft29', 10600, 'in'), shop('北歐先生', 12100, 'unknown'), shop('北歐櫥窗', 12500, 'unknown')],
      beam: 'down', light: [0, 15, 0],
      parts: [
        { k: 'cyl', r: 6, r2: 7, h: 2, at: [0, 1, 0], m: 'metal', c: 0xb87333 },
        { k: 'cyl', r: 1.2, h: 12, at: [0, 8, 0], m: 'metal', c: 0xb87333 },
        { k: 'lathe', pts: [[9.5, 13.5], [9.2, 15], [8, 17.5], [6.5, 20.5], [5.5, 23.5], [4.5, 26], [2.5, 27.5], [0.5, 28]], m: 'metal', c: 0xb87333, inner: true },
      ],
    },
    {
      id: 'louis-poulsen-panthella', category: '立燈', mount: 'floor',
      brand: 'Louis Poulsen', name: 'Panthella', variant: 'Floor', designer: 'Verner Panton',
      size: { w: 50, h: 130.5 }, page: LP('louis-poulsen-panthella'),
      offers: [shop('居雅堂', 42500, 'unknown'), shop('Design Butik', 42500, 'out'), shop('Motive', 42500, 'in'), shop('散步舖', 42500, 'in')],
      beam: 'down', light: [0, 109, 0],
      parts: [
        { k: 'lathe', pts: [[18.5, 0], [18.2, 1.2], [12, 4], [7, 10], [4.2, 25], [3.2, 50], [2.6, 85], [2.4, 106]], m: 'metal', c: 0xf4f4f1 },
        { k: 'lathe', pts: [[25, 105], [24.6, 107.5], [22.5, 113], [17.5, 119.5], [10.5, 125.5], [4.5, 129], [0.5, 130.5]], m: 'shade', c: 0xf7f6f2, inner: true },
      ],
    },
    {
      id: 'kimu-one-lamp-floor', category: '立燈', mount: 'floor',
      brand: '柒木 KIMU DESIGN', name: '一盞東西', variant: '小', designer: '',
      size: { w: 36, h: 153 }, page: LP('kimu-design-0cf1bd'),
      offers: [shop('Design Butik', 24800, 'in'), shop('散步舖', 24800, 'unknown'), shop('柒木', 24800, 'in')],
      beam: 'down', light: [18, 124, 0],
      parts: [
        { k: 'cyl', r: 9, h: 2.4, at: [0, 1.2, 0], m: 'metal', c: 0x232323 },
        { k: 'tube', a: [0, 2.4, 0], b: [0, 140, 0], r: 0.8, m: 'metal', c: 0x232323 },
        { k: 'tube', a: [0, 140, 0], b: [8, 150, 0], r: 0.8, m: 'metal', c: 0x232323 },
        { k: 'tube', a: [8, 150, 0], b: [18, 147.5, 0], r: 0.8, m: 'metal', c: 0x232323 },
        { k: 'tube', a: [18, 147.5, 0], b: [18, 134, 0], r: 0.3, m: 'metal', c: 0x111111 },
        { k: 'lathe', pts: [[8.5, 125], [8.1, 127.5], [6.8, 130.5], [4.4, 132.8], [1.5, 134]], at: [18, 0, 0], m: 'metal', c: 0x3f5b47, inner: true },
        { k: 'sphere', r: 8.2, sy: 0.85, at: [18, 125, 0], m: 'glass', c: OPAL },
      ],
    },
    {
      id: 'marset-mercer', category: '壁燈', mount: 'wall',
      brand: 'Marset', name: 'Mercer', variant: 'A', designer: 'Joan Gaspar',
      size: { w: 24.3, h: 15.4 }, page: LP('marset-mercer'),
      offers: [shop('Loft29', 25300, 'unknown'), shop('Motive', 25300, 'unknown'), shop('散步舖', 25300, 'in'), shop('viithe', 25300, 'unknown')],
      beam: 'all', light: [0, 0, 6],
      parts: [
        { k: 'box', s: [6, 10, 1], at: [0, 0, 0.5], m: 'metal', c: 0xd8d4cc },
        { k: 'cyl', r: 12.15, h: 15.4, half: true, at: [0, 0, 1.2], m: 'wood', c: 0xb98a5c, inner: true },
      ],
    },
    {
      id: 'audo-copenhagen-cast', category: '壁燈', mount: 'wall',
      brand: 'Audo Copenhagen', name: 'Cast Sconce', variant: '標準款', designer: 'Thomas Chung & Jordan Murphy',
      size: { w: 12, h: 19 }, page: LP('audo-copenhagen-cast'),
      offers: [shop('NOSA', 8000, 'unknown'), shop('Design Butik', 8560, 'in'), shop('WOW', 9500, 'unknown'), shop('北歐先生', 9800, 'unknown'),
        shop('Loft29', 10600, 'in'), shop('散步舖', 10600, 'unknown')],
      beam: 'down', light: [0, -5, 7],
      parts: [
        { k: 'box', s: [7, 7, 1], at: [0, 3, 0.5], m: 'metal', c: 0x3a3936 },
        { k: 'tube', a: [0, 3, 1], b: [0, 3, 6.5], r: 0.8, m: 'metal', c: 0x3a3936 },
        { k: 'lathe', pts: [[6, -9.5], [5.4, -6.5], [4.2, -2], [3.2, 3], [2.4, 7.5], [2, 9.5]], at: [0, 0, 7], m: 'metal', c: 0x3a3936, inner: true },
      ],
    },
    {
      id: 'foscarini-rituals', category: '吸頂燈', mount: 'ceiling',
      brand: 'Foscarini', name: 'Rituals 2', variant: 'Ø34', designer: 'Ludovica + Roberto Palomba',
      size: { w: 34, h: 19 }, page: LP('foscarini-rituals'),
      offers: [shop('北歐先生', 20200, 'unknown'), shop('Loft29', 25800, 'in')],
      beam: 'down', light: [0, -9, 0],
      parts: [
        { k: 'cyl', r: 6, h: 1.2, at: [0, -0.6, 0], m: 'metal', c: 0xeeeeea },
        { k: 'lathe', pts: [[6, -1.2], [11, -2.5], [15, -5.5], [17, -9.5], [16.5, -13], [13.5, -16.5], [8, -18.6], [0.5, -19]], m: 'glass', c: 0xf6f3ec },
      ],
    },
    {
      id: 'flos-mini-glo-ball', category: '吸頂燈', mount: 'ceiling',
      brand: 'Flos', name: 'Mini Glo-Ball C/W', variant: '可吸頂或壁掛', designer: 'Jasper Morrison',
      size: { w: 11.2, h: 8.5 }, page: LP('flos-mini-glo-ball'),
      offers: [shop('潤舍', 6300, 'unknown'), shop('散步舖', 6300, 'unknown'), shop('北歐先生', 6800, 'unknown')],
      beam: 'down', light: [0, -5, 0],
      parts: [
        { k: 'cyl', r: 4, h: 1.5, at: [0, -0.75, 0], m: 'metal', c: 0xefefec },
        { k: 'sphere', r: 5.6, sy: 0.625, at: [0, -5, 0], m: 'glass', c: OPAL },
      ],
    },
    {
      id: 'marset-cala', category: '戶外燈', mount: 'floor',
      brand: 'Marset', name: 'Cala', variant: 'IP65 戶外款', designer: 'Joan Gaspar',
      size: { w: 53, h: 140 }, page: LP('marset-cala'),
      offers: [shop('散步舖', 73000, 'unknown')],
      beam: 'all', light: [0, 122, 0],
      parts: [
        { k: 'cyl', r: 26.5, h: 30, open: true, at: [0, 125, 0], m: 'shade', c: 0xece6d8 },
        { k: 'tube', a: [0, 0, 20], b: [0, 112, -11], r: 0.9, m: 'metal', c: BLACK },
        { k: 'tube', a: [-17.32, 0, -10], b: [9.53, 112, 5.5], r: 0.9, m: 'metal', c: BLACK },
        { k: 'tube', a: [17.32, 0, -10], b: [-9.53, 112, 5.5], r: 0.9, m: 'metal', c: BLACK },
      ],
    },
    {
      id: 'louis-poulsen-aj-eklipta', category: '戶外燈', mount: 'wall',
      brand: 'Louis Poulsen', name: 'AJ Eklipta', variant: '戶外款 Ø35', designer: 'Arne Jacobsen',
      size: { w: 35 }, page: LP('louis-poulsen-aj-eklipta'),
      offers: [shop('居雅堂', 22100, 'unknown'), shop('散步舖', 22100, 'in')],
      beam: 'all', light: [0, 0, 4],
      parts: [
        { k: 'cyl', r: 17.5, h: 5, axis: 'z', at: [0, 0, 2.5], m: 'metal', c: 0xdcdcd8 },
        { k: 'cyl', r: 16, h: 1, axis: 'z', at: [0, 0, 5.5], m: 'glass', c: OPAL },
      ],
    },
  ];

  // ---------- 形狀的範圍：[minX, minY, minZ, maxX, maxY, maxZ]（公分） ----------
  function tubeBounds(a, b, r) {
    const d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const len = Math.hypot(d[0], d[1], d[2]);
    const lo = [], hi = [];
    for (let i = 0; i < 3; i++) {
      const e = r * Math.sqrt(Math.max(0, 1 - (d[i] / len) ** 2)); // 管口圓圈在這個軸上伸出去多少
      lo.push(Math.min(a[i], b[i]) - e);
      hi.push(Math.max(a[i], b[i]) + e);
    }
    return [...lo, ...hi];
  }
  function cylBounds(p, x, y, z) {
    const R = Math.max(p.r, p.r2 ?? p.r), H = p.h / 2;
    if (p.axis === 'z') return [x - R, y - R, z - H, x + R, y + R, z + H];
    return [x - R, y - H, p.half ? z : z - R, x + R, y + H, z + R];
  }
  const BOUNDS = {
    lathe(p, x, y, z) {
      const R = Math.max(...p.pts.map((q) => q[0]));
      const ys = p.pts.map((q) => q[1]);
      return [x - R, y + Math.min(...ys), z - R, x + R, y + Math.max(...ys), z + R];
    },
    cyl: cylBounds,
    sphere(p, x, y, z) {
      const ry = p.r * (p.sy ?? 1);
      return [x - p.r, y - ry, z - p.r, x + p.r, y + ry, z + p.r];
    },
    tube: (p) => tubeBounds(p.a, p.b, p.r),
    arc: (p, x, y, z) => [x - p.R - p.r, y, z - p.r, x + p.R + p.r, y + p.R + p.r, z + p.r],
    box: (p, x, y, z) => [x - p.s[0] / 2, y - p.s[1] / 2, z - p.s[2] / 2, x + p.s[0] / 2, y + p.s[1] / 2, z + p.s[2] / 2],
  };
  function partBounds(p) {
    const f = BOUNDS[p.k];
    if (!f) throw new Error('不認得的形狀：' + p.k);
    const [x, y, z] = p.at || [0, 0, 0];
    return f(p, x, y, z);
  }
  function designBounds(parts) {
    return parts.map(partBounds).reduce((u, b) => [
      Math.min(u[0], b[0]), Math.min(u[1], b[1]), Math.min(u[2], b[2]),
      Math.max(u[3], b[3]), Math.max(u[4], b[4]), Math.max(u[5], b[5]),
    ]);
  }

  // ---------- 縮放成真實尺寸，原點放在「掛的那個點」 ----------
  // 立燈、桌燈、吊燈：最低點；吸頂燈：最高點；壁燈：背面、上下中心
  const ANCHOR = {
    floor: (b, sy) => [0, -b[1] * sy, 0],
    table: (b, sy) => [0, -b[1] * sy, 0],
    pendant: (b, sy) => [0, -b[1] * sy, 0],
    ceiling: (b, sy) => [0, -b[4] * sy, 0],
    wall: (b, sy, sx) => [0, -(b[1] + b[4]) / 2 * sy, -b[2] * sx],
  };
  // 回傳 scale、offset（公尺）：真實位置 = 公分座標 × scale + offset。light 是燈泡的真實位置
  function lampFit(lamp) {
    const b = designBounds(lamp.parts);
    const sx = lamp.size.w / 100 / (b[3] - b[0]);
    const sy = lamp.size.h === undefined ? sx : lamp.size.h / 100 / (b[4] - b[1]);
    const offset = ANCHOR[lamp.mount](b, sy, sx);
    const scale = [sx, sy, sx];
    const light = lamp.light.map((v, i) => v * scale[i] + offset[i]);
    return { scale, offset, light, bounds: b };
  }
  function fittedBounds(lamp) {
    const { scale, offset, bounds } = lampFit(lamp);
    return bounds.map((v, i) => v * scale[i % 3] + offset[i % 3]);
  }
  const lampHeight = (lamp) => { const b = fittedBounds(lamp); return b[4] - b[1]; };

  // ---------- 放在哪個高度 ----------
  // place：{ hang 吊燈最低點離地, table 桌面高度, wallY 壁燈中心離地 }（公尺）
  function mountY(lamp, place, ceiling) {
    return { floor: 0, table: place.table, pendant: place.hang, ceiling, wall: place.wallY }[lamp.mount];
  }
  const maxHang = (lamp, ceiling) => ceiling - lampHeight(lamp) - MIN_CORD;
  const clampHang = (lamp, hang, ceiling) => Math.min(hang, maxHang(lamp, ceiling));
  function cordSpan(lamp, hang, ceiling) {
    const from = hang + lampHeight(lamp);
    return { from, to: ceiling, length: Math.max(0, ceiling - from) };
  }

  // ---------- 拖曳 ----------
  // 拖曳時燈沿著點到的那個高度的水平面移動（游標下的點一直在游標下）。
  // 點到的高度跟鏡頭差不多時，水平面會穿過鏡頭，滑鼠動一點燈就飛很遠，
  // 所以改用「面對鏡頭的直立平面」：只能左右移，離鏡頭的距離不變
  function dragPlane(hitY, camY) {
    return Math.abs(hitY - camY) >= DRAG_GAP ? { kind: 'level', y: hitY } : { kind: 'facing' };
  }

  // ---------- 價格 ----------
  // 「有現貨」裡最便宜（一樣便宜選先列的）；沒有一家標有現貨就選最便宜的，noneInStock = true
  function bestOffer(offers) {
    const cheapest = (list) => list.reduce((best, o) => (o.price < best.price ? o : best));
    const inStock = offers.filter((o) => o.stock === 'in');
    return inStock.length
      ? { offer: cheapest(inStock), noneInStock: false }
      : { offer: cheapest(offers), noneInStock: true };
  }
  const sizeLabel = (lamp) => (lamp.size.h === undefined
    ? `寬 ${lamp.size.w} cm`
    : `寬 ${lamp.size.w} × 高 ${lamp.size.h} cm`);

  return {
    LAMPS, CATEGORIES, MOUNTS, STOCK, UPDATED, MIN_CORD,
    partBounds, designBounds, lampFit, fittedBounds, lampHeight,
    mountY, maxHang, clampHang, cordSpan, bestOffer, sizeLabel, dragPlane,
  };
});
