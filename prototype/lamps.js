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
      traced: [[5.2, 0.0], [5.8, 2.4], [10.4, 2.5], [8.0, 7.2], [25.0, 8.3], [16.8, 12.5], [9.4, 14.3], [8.6, 17.3], [15.1, 19.4], [12.5, 20.3], [3.6, 21.0], [3.5, 25.9], [1.2, 26.7]], // 照片自動描的側面輪廓（tools/outline，2026-11-21）
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
      traced: [[1.1, 0.0], [8.2, 1.8], [13.1, 5.0], [24.4, 9.6], [26.8, 11.9], [27.5, 14.2], [25.0, 23.6], [23.4, 26.5], [21.4, 28.2], [15.0, 31.0], [12.0, 36.2], [9.5, 38.3], [6.1, 39.6], [5.7, 42.6], [3.8, 43.0]], // 照片自動描的側面輪廓（tools/outline，2026-11-21）
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
      traced: [[0.0, 0.0], [4.1, 0.2], [5.1, 1.0], [5.2, 1.9], [4.8, 2.3], [5.0, 2.6], [4.9, 10.3], [6.1, 11.1], [7.5, 13.0], [8.5, 16.1], [8.4, 21.8], [8.0, 23.4], [7.1, 25.3], [5.8, 27.0], [4.6, 27.9], [2.7, 28.7], [1.3, 29.0]], // 照片自動描的側面輪廓（tools/outline，2026-11-21）
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
      traced: [[0.8, 0.0], [2.9, 0.1], [4.4, 0.6], [3.7, 1.2], [3.5, 9.6], [2.6, 11.1], [0.6, 12.1], [0.6, 15.2], [9.4, 15.7], [9.5, 18.7], [8.8, 22.1], [6.9, 25.1], [5.0, 26.7], [3.7, 27.3], [0.8, 28.0]], // 照片自動描的側面輪廓（tools/outline，2026-11-21）
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
      traced: [[5.6, 0.0], [13.0, 1.2], [15.7, 2.4], [16.4, 5.2], [6.2, 10.1], [3.4, 14.0], [1.2, 21.3], [1.2, 97.9], [2.8, 103.1], [24.4, 103.4], [25.0, 104.6], [23.8, 108.2], [23.8, 111.9], [22.2, 113.1], [22.2, 115.3], [21.0, 115.6], [15.7, 122.0], [10.2, 123.5], [0.0, 123.8], [0.0, 128.4], [0.9, 128.7], [0.3, 130.5]], // 照片自動描的側面輪廓（tools/outline，2026-11-21）
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
      traced: [[1.0, 0.0], [8.0, 0.9], [12.2, 2.3], [15.3, 4.4], [17.0, 7.7], [16.4, 11.2], [13.6, 14.6], [9.1, 17.2], [2.1, 19.0]], // 照片角度偏（從下面拍），量出的高度差 23%，形狀要人看（tools/outline，2026-11-21）
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
      traced: [[1.0, 0.0], [2.8, 0.4], [3.7, 0.8], [4.5, 1.4], [5.4, 2.9], [5.6, 4.5], [5.0, 6.3], [3.9, 7.4], [2.4, 8.3], [0.3, 8.5]], // 照片自動描的側面輪廓（tools/outline，2026-11-21）
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

  // ---------- 形狀：手描 / 照片自動描 ----------
  // traced：tools/outline 從商品照片自動描的側面輪廓 [[半徑, 高], ...]（公分，真實大小），
  // 繞中心轉一圈就是 3D。沒有原廠 3D 模型時的替代（docs/outline.md）。只有「轉一圈」的燈有。
  function widestPart(parts) {
    let best = parts[0], width = -1;
    for (const p of parts) {
      const b = partBounds(p);
      if (b[3] - b[0] > width) { best = p; width = b[3] - b[0]; }
    }
    return best;
  }
  function closedOutline(pts) {
    const out = pts.map((q) => [...q]);
    if (out[0][0] !== 0) out.unshift([0, out[0][1]]);
    if (out[out.length - 1][0] !== 0) out.push([0, out[out.length - 1][1]]);
    return out;
  }
  // 燈泡放在自動描的形狀裡「相對同一個位置」（手描和自動描的座標不一樣）
  function mapPoint(v, from, to) {
    return v.map((x, i) => to[i] + (x - from[i]) / ((from[i + 3] - from[i]) || 1) * (to[i + 3] - to[i]));
  }
  // 手描在某個高度最寬的零件（拿它的材質、顏色）；那個高度沒有零件就回 null
  function partAt(parts, y) {
    let best = null, width = -1;
    for (const p of parts) {
      const b = partBounds(p);
      if (y >= b[1] && y <= b[4] && b[3] - b[0] > width) { best = p; width = b[3] - b[0]; }
    }
    return best;
  }
  // 輪廓上跨過 heights 裡某個高度的那一段，在那個高度切開（加一個在連線上的點，形狀不變）
  function splitAtHeights(pts, heights) {
    const out = [pts[0]];
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i], dir = Math.sign(b[1] - a[1]);
      const cross = heights.filter((y) => (y - a[1]) * (y - b[1]) < 0).sort((p, q) => (p - q) * dir);
      for (const y of cross) out.push([a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y]);
      out.push(b);
    }
    return out;
  }
  const lathePart = (pts, { m, c, inner }) => ({ k: 'lathe', pts, m, c, ...(inner ? { inner } : {}) });
  // 材質、顏色、要不要畫內面都一樣，就併成同一段（JWDA 的底座是兩個金屬圓柱，還是一段）
  const sameLook = (a, b) => a.m === b.m && a.c === b.c && Boolean(a.inner) === Boolean(b.inner);
  // 自動描的輪廓按高度分段：每一段的材質、顏色照手描在那個高度的零件（JWDA：上面玻璃球、下面深色金屬座）。
  // 先在手描零件的上下緣切開，換材質的地方才會剛好在交界（Codex 審查）。相鄰兩段共用接縫那一圈
  function tracedParts(lamp) {
    const outline = closedOutline(lamp.traced);
    const from = designBounds(lamp.parts), to = designBounds([{ k: 'lathe', pts: outline }]);
    const handY = (y) => mapPoint([0, y, 0], to, from)[1];
    const edges = lamp.parts.map(partBounds).flatMap((b) => [b[1], b[4]].map((y) => mapPoint([0, y, 0], from, to)[1]));
    const pts = splitAtHeights(outline, edges);
    const parts = [];
    let src = null;
    for (let i = 1; i < pts.length; i++) {
      const here = partAt(lamp.parts, handY((pts[i - 1][1] + pts[i][1]) / 2)) || src || widestPart(lamp.parts);
      if (src && sameLook(here, src)) parts[parts.length - 1].pts.push(pts[i]);
      else parts.push(lathePart([pts[i - 1], pts[i]], here));
      src = here;
    }
    return parts;
  }
  // shape：'hand' 手描（原本的零件）或 'traced' 照片自動描。沒有自動描的燈一律手描。不改原本的資料
  function withShape(lamp, shape) {
    if (shape !== 'traced' || !lamp.traced) return lamp;
    const parts = tracedParts(lamp);
    const light = mapPoint(lamp.light, designBounds(lamp.parts), designBounds(parts));
    return { ...lamp, parts, light };
  }

  // ---------- 爬到的燈（catalog.js；docs/catalog.md） ----------
  // entry.lathe：從商品照片自動描的輪廓（公分，真實大小）；entry.bands：照片量的顏色，一段一段由下往上
  // [{ to: 這段的頂, m: 'shade' 淺色燈罩 | 'metal' 深色, c: 顏色 }]。燈罩那幾段裡面也會亮
  const bandAt = (bands, y) => bands.find((b) => y <= b.to) || bands[bands.length - 1];
  function catalogLamp(entry) {
    const cuts = entry.bands.slice(0, -1).map((b) => b.to);
    const pts = splitAtHeights(closedOutline(entry.lathe), cuts);
    const parts = [];
    let src = null;
    for (let i = 1; i < pts.length; i++) {
      const band = bandAt(entry.bands, (pts[i - 1][1] + pts[i][1]) / 2);
      const look = { m: band.m, c: band.c, inner: band.m === 'shade' };
      if (src && sameLook(look, src)) parts[parts.length - 1].pts.push(pts[i]);
      else parts.push(lathePart([pts[i - 1], pts[i]], look));
      src = look;
    }
    // 連結：最便宜（有現貨優先）那家的商品頁
    return { ...entry, source: 'catalog', page: bestOffer(entry.offers).offer.url, parts };
  }
  // 搜尋：空白分開的每個字都要出現在品牌、型號、類別或款式裡（不分大小寫）
  function searchLamps(lamps, query) {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const text = (l) => `${l.brand} ${l.name} ${l.category} ${l.variant || ''}`.toLowerCase();
    return lamps.filter((l) => words.every((w) => text(l).includes(w)));
  }

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
  // hEst：爬到的燈店家沒標高度時，照片的比例估的高度（docs/catalog.md）
  const sizeLabel = (lamp) => {
    const { w, h, hEst } = lamp.size;
    if (h !== undefined) return `寬 ${w} × 高 ${h} cm`;
    return hEst === undefined ? `寬 ${w} cm` : `寬 ${w} cm · 高約 ${hEst} cm（照片估的）`;
  };

  return {
    LAMPS, CATEGORIES, MOUNTS, STOCK, UPDATED, MIN_CORD,
    partBounds, designBounds, lampFit, fittedBounds, lampHeight,
    mountY, maxHang, clampHang, cordSpan, bestOffer, sizeLabel, dragPlane, withShape,
    catalogLamp, searchLamps,
  };
});
