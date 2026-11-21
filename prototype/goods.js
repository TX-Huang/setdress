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
  // 店家沒標、照比例補的邊（est）不拿來算。都沒標（guess）：用一般大小裡最不會差的那一邊——
  // 家具照高度（單人、三人沙發都差不多 80 cm 高，寬差很多；LN1 單人被當成 2 公尺寬就是這樣），
  // 吊燈照寬度（燈罩差不多寬，照片又連著電線）
  function standeeSize(size, box) {
    const bw = box[2] - box[0], bh = box[3] - box[1];
    const use = usableSides(size);
    const byW = use.w ? size.w / 100 / bw : 0, byH = use.h ? size.h / 100 / bh : 0;
    const perPx = Math.max(byW, byH);
    return { w: round3(bw * perPx), h: round3(bh * perPx) };
  }
  function usableSides(size) {
    if (size.guess) return size.mount === 'ceiling' ? { w: true } : { h: true };
    const est = size.est || [];
    return { w: Boolean(size.w) && !est.includes('w'), h: Boolean(size.h) && !est.includes('h') };
  }

  // 卡片上的尺寸：只寫店家標的；沒標的寫「沒標尺寸」，有照片估的大小（dims，公尺）就一起寫
  function sizeLabel(s, dims) {
    if (s.guess) {
      return dims ? `沒標尺寸：照照片估約寬 ${Math.round(dims.w * 100)} × 高 ${Math.round(dims.h * 100)} cm` : '沒標尺寸';
    }
    const est = s.est || [];
    const names = { w: '寬', d: '深', h: '高' };
    const known = ['w', 'd', 'h'].filter((k) => !est.includes(k)).map((k) => `${names[k]} ${s[k]}`);
    const missing = est.map((k) => names[k]).join('、');
    return `${known.join(' × ')} cm${missing ? `（${missing}沒標）` : ''}`;
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

  // ---------- 3D 的方向（docs/model3d.md 第 11 到 15 句）：角度都是度，(-180, 180] ----------
  const angle = (a) => { const n = ((a % 360) + 360) % 360; return n > 180 ? n - 360 : n; };
  const gap = (a, b) => Math.abs(angle(a - b));
  // 牆的四個方向裡，離 deg 最近的那個；wallDeg 是 null（不知道牆在哪）回 null
  function nearestWall(deg, wallDeg) {
    if (wallDeg === null || wallDeg === undefined) return null;
    const ks = [-2, -1, 0, 1, 2].map((k) => angle(wallDeg + k * 90));
    return ks.reduce((best, w) => (gap(w, deg) < gap(best, deg) ? w : best));
  }
  // 放進來時：跟牆平行、正面朝鏡頭那一側（facingDeg：正面朝鏡頭的角度）
  function startYaw(facingDeg, wallDeg) {
    const w = nearestWall(facingDeg, wallDeg);
    return w === null ? angle(facingDeg) : w;
  }
  // 滑桿拉到牆的方向 tol 度以內就吸過去
  const SNAP_DEG = 5;
  function snapYaw(deg, wallDeg, tol = SNAP_DEG) {
    const w = nearestWall(deg, wallDeg);
    return w !== null && gap(w, deg) <= tol ? w : angle(deg);
  }
  const turn90 = (deg) => angle(deg + 90);

  // 3D 的一點用多少照片（docs/model3d.md 第 16 句）：nz 是面朝 +Z（照片那一面）的程度，
  // 0.6 以上完全用照片，0.25 以下（照片被拉長 4 倍以上）完全用平滑顏色，中間 smoothstep。
  // 試過 0.35/0.7、0.25/0.6、0.2/0.5：0.35/0.7 正面變太多（有的差到 3.3），0.2/0.5 側面條紋少得比較少，
  // 0.25/0.6 兩邊都好（docs/model3d.md 第 18 句）。
  // 網頁的 shader 用同一組數字（index.html 的 modelMaterial）
  const FRONT_LO = 0.25, FRONT_HI = 0.6;
  function frontWeight(nz) {
    const t = Math.min(1, Math.max(0, (nz - FRONT_LO) / (FRONT_HI - FRONT_LO)));
    return t * t * (3 - 2 * t);
  }

  // ---------- AI 生的 3D（docs/model3d.md）----------
  // 讀 tools/model3d/glb.py 存的 GLB：點、照片座標、面（只有一個網格，沒有圖片）
  const TYPES = { 5126: Float32Array, 5123: Uint16Array, 5125: Uint32Array };
  function parseGlb(buffer) {
    const view = new DataView(buffer);
    if (buffer.byteLength < 20 || view.getUint32(0, true) !== 0x46546c67) throw new Error('不是 GLB');
    const jsonLen = view.getUint32(12, true);
    const doc = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 20, jsonLen)));
    const binStart = 20 + jsonLen + 8;
    const read = (i) => {
      const a = doc.accessors[i], v = doc.bufferViews[a.bufferView], Type = TYPES[a.componentType];
      const width = { VEC3: 3, VEC2: 2, SCALAR: 1 }[a.type];
      return new Type(buffer.slice(binStart + (v.byteOffset || 0), binStart + (v.byteOffset || 0) + a.count * width * Type.BYTES_PER_ELEMENT));
    };
    const prim = doc.meshes[0].primitives[0];
    return { positions: read(prim.attributes.POSITION), uvs: read(prim.attributes.TEXCOORD_0), indices: read(prim.indices) };
  }

  // 3D 的一單位是幾公尺：跟立牌同一個規則（寬、高各算一次取大的）。extent：3D 的寬、高、深（模型單位）
  const modelScale = (size, extent) => standeeSize(size, [0, 0, extent[0], extent[1]]).w / extent[0];

  // 這個尺寸有沒有 3D：做 3D 用的那張照片在這個尺寸的同一個位置才算
  // （小的紅椅子、大的藍椅子；藍色款前面是自己的照片、後面才是紅色的大圖：Codex 審查）
  function modelFor(models, item, sizeIndex) {
    const m = models && models[item.id], s = item.sizes[sizeIndex] || item.sizes[0];
    return m && s.photos[m.photoIndex] === m.photo ? m : null;
  }

  // 現在讀到的照片跟做 3D 時是不是同一張（店家可能換了同一個網址的照片，Codex 審查）：
  // 照片比例差不到 2%，商品在照片裡的位置（換成 0 到 1）差不到 10%
  // （同一張照片縮放不同，去背邊緣會多留或少留一小塊，實測差到 8%）
  const ASPECT_TOL = 0.02, BOX_TOL = 0.1;
  function sameFraming(model, box, wh) {
    const [w0, h0] = model.wh, [w1, h1] = wh;
    if (Math.abs(w0 / h0 / (w1 / h1) - 1) > ASPECT_TOL) return false;
    const norm = (b, w, h) => [b[0] / w, b[1] / h, b[2] / w, b[3] / h];
    const a = norm(model.box, w0, h0), b = norm(box, w1, h1);
    return a.every((v, i) => Math.abs(v - b[i]) <= BOX_TOL);
  }

  return {
    photoUrl, thumbUrl, standeeSize, sizeLabel, startY, heightRange, heightAfterResize, total, WIDTH,
    parseGlb, modelScale, modelFor, sameFraming, startYaw, snapYaw, turn90, FRONT_LO, FRONT_HI, frontWeight,
  };
});
