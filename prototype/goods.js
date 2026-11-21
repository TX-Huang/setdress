/* 全部商品放進模擬器（docs/goods.md）：照片網址、立牌大小、高度、總價這些純計算。
 * 商品資料在 goods/<種類>.json（tools/outline/goods.py 產生），用到才讀。
 *
 * 瀏覽器用 <script src="goods.js">（window.SetdressGoods），Node 測試用 require。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SetdressGoods = api;
})(typeof self !== 'undefined' ? self : this, () => {
  'use strict';

  const WIDTH = 800; // 照片讀 800 px 寬的就夠（手機比較快）
  const PROXY = 'https://wsrv.nl/?url='; // 免費的圖片轉送：加上「別的網站可以讀」的標頭、縮小
  const TABLE_Y = 0.75; // 一般桌面高度（公尺）
  const WALL_CENTER = 1.5; // 掛牆上的，中心離地
  const DROP = 0.5; // 吊燈、吸頂燈先吊在天花板下這麼多
  const LOWEST_HANG = 0.6;
  const TABLE_MAX = 1.2;
  const round3 = (v) => Math.round(v * 1000) / 1000;

  // 店家的照片網址 → 瀏覽器讀得到（可以拿來去背、貼在 3D 上）的網址
  function photoUrl(url) {
    const u = new URL(url);
    if (u.hostname === 'cdn.shopify.com') {
      u.searchParams.set('width', String(WIDTH));
      return u.toString();
    }
    if (u.hostname === 'img.shoplineapp.com') return url;
    return `${PROXY}${encodeURIComponent(url)}&w=${WIDTH}&we&output=webp`;
  }

  // 選單上的小圖：一律經過 wsrv.nl 縮小（手機不用讀原圖）
  const THUMB = 96;
  const thumbUrl = (url) => `${PROXY}${encodeURIComponent(url)}&w=${THUMB}&h=${THUMB}&fit=contain&bg=white&output=webp`;

  // 立牌的大小（公尺）：形狀照照片裡商品的比例，大小照店家標的寬、高。
  // 寬和高各算一次「照片上一個像素是幾公尺」，取大的：店家常把座高、燈罩高當高度、
  // 吊燈照片連電線一起，標的邊偏小比偏大常見。box：照片裡商品的範圍 [x0, y0, x1, y1]（px）
  function standeeSize(size, box) {
    const bw = box[2] - box[0], bh = box[3] - box[1];
    const byW = size.w ? size.w / 100 / bw : 0, byH = size.h ? size.h / 100 / bh : 0;
    const perPx = Math.max(byW, byH);
    return { w: round3(bw * perPx), h: round3(bh * perPx) };
  }

  function sizeLabel(s) {
    const text = `寬 ${s.w} × 深 ${s.d} × 高 ${s.h} cm`;
    return s.guess ? `${text}（沒標尺寸，用一般大小）` : text;
  }

  // 剛放進來時，底部離地多高（公尺）。h：商品高度、ceiling：天花板高度
  function startY(mount, h, ceiling) {
    if (mount === 'table') return TABLE_Y;
    if (mount === 'wall') return round3(WALL_CENTER - h / 2);
    if (mount === 'ceiling') return round3(Math.max(LOWEST_HANG, ceiling - DROP - h));
    return 0;
  }

  // 高度滑桿的範圍（底部離地）；地上的不能調（null）
  function heightRange(mount, h, ceiling) {
    if (mount === 'table') return [0, TABLE_MAX];
    if (mount === 'wall' || mount === 'ceiling') return [0, round3(Math.max(0, ceiling - h))]; // 比天花板高的：只能放 0
    return null;
  }

  // 換尺寸後的高度：放法變了（大鏡子改靠地上）就照新放法重新放；沒變就留在原處，但不超出新的範圍
  function heightAfterResize(y, oldMount, mount, h, ceiling) {
    if (mount !== oldMount) return startY(mount, h, ceiling);
    const range = heightRange(mount, h, ceiling);
    return range ? Math.min(Math.max(y, range[0]), range[1]) : 0;
  }

  // 放進來的每一件，照它選的尺寸、最便宜有現貨的價格加起來。itemOf(id) 還沒讀到的不算
  function total(placed, itemOf) {
    let sum = 0;
    for (const p of placed) {
      const item = itemOf(p.id);
      if (!item) continue;
      const offers = (item.sizes[p.size] || item.sizes[0]).offers;
      const inStock = offers.filter((o) => o.stock === 'in');
      sum += Math.min(...(inStock.length ? inStock : offers).map((o) => o.price));
    }
    return sum;
  }

  return { photoUrl, thumbUrl, standeeSize, sizeLabel, startY, heightRange, heightAfterResize, total, WIDTH };
});
