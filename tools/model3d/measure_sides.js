// 量 3D 側面的條紋（docs/model3d.md 第 18 句）。在瀏覽器打開 prototype/index.html#debug，
// 把這整段貼到主控台跑（要 window.__setdress 的 modelMaterial、renderer、standeeOf）。
// 每件畫四個方向（正面、兩個側面、背面）三種材質：原本（只有照片）、現在（照片＋平滑顏色）、單色（扣掉形狀本身的明暗）。
// 每次畫之前都清畫面（這個網頁 renderer.autoClear 是 false）；只算模型蓋到的像素（背景不算）。
(async () => {
  const S = window.__setdress, T = S.THREE, R = S.renderer;
  const models = (await (await fetch('models3d/index.json')).json()).models;
  const items = [];
  for (const g of ['sofa', 'chair']) items.push(...(await S.goodsOfGroup(g)).filter((i) => models[i.id]).slice(0, g === 'sofa' ? 10 : 6));
  const SZ = 256, rt = new T.WebGLRenderTarget(SZ, SZ, { type: T.FloatType });
  const scene = new T.Scene();
  scene.add(new T.AmbientLight(0xffffff, 0.8));
  const sun = new T.DirectionalLight(0xffffff, 1.6);
  sun.position.set(1, 2, 3);
  scene.add(sun);
  const cam = new T.PerspectiveCamera(30, 1, 0.01, 1000);
  const toSrgb = (v) => 255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * Math.pow(v, 1 / 2.4) - 0.055);
  const oldColor = new T.Color(); R.getClearColor(oldColor); const oldAlpha = R.getClearAlpha();
  function shot(mesh, yaw) {
    mesh.rotation.y = yaw;
    R.setRenderTarget(rt); R.setClearColor(0x000000, 0); R.clear(); R.render(scene, cam);
    const buf = new Float32Array(SZ * SZ * 4);
    R.readRenderTargetPixels(rt, 0, 0, SZ, SZ, buf); R.setRenderTarget(null);
    const L = new Float32Array(SZ * SZ), rgb = new Float32Array(SZ * SZ * 3), mask = new Uint8Array(SZ * SZ);
    for (let i = 0; i < SZ * SZ; i++) {
      mask[i] = buf[4 * i + 3] > 0.5 ? 1 : 0;
      for (let c = 0; c < 3; c++) rgb[3 * i + c] = toSrgb(Math.max(0, buf[4 * i + c]));
      L[i] = 0.2126 * rgb[3 * i] + 0.7152 * rgb[3 * i + 1] + 0.0722 * rgb[3 * i + 2];
    }
    return { L, rgb, mask };
  }
  // 條紋：上下相鄰兩個像素（都在模型上）的亮度差平均
  function stripes(s) {
    let sum = 0, n = 0;
    for (let i = 0; i < SZ * (SZ - 1); i++) if (s.mask[i] && s.mask[i + SZ]) { sum += Math.abs(s.L[i + SZ] - s.L[i]); n++; }
    return sum / n;
  }
  // 兩張圖在模型上的平均顏色差（0–255）
  function change(a, b) {
    let sum = 0, n = 0;
    for (let i = 0; i < SZ * SZ; i++) if (a.mask[i] && b.mask[i]) { for (let c = 0; c < 3; c++) sum += Math.abs(a.rgb[3 * i + c] - b.rgb[3 * i + c]); n += 3; }
    return sum / n;
  }
  function meanColor(tex) {
    const img = tex.image, c = document.createElement('canvas');
    c.width = img.width; c.height = img.height;
    const ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, c.width, c.height).data, n = d.length / 4, s = [0, 0, 0];
    for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) s[k] += d[4 * i + k];
    return new T.Color(`rgb(${s.map((v) => Math.round(v / n)).join(',')})`);
  }
  const rows = [];
  for (const it of items) {
    const look = await S.standeeOf({ id: it.id, size: 0 });
    if (!look || look.kind !== '3d' || !look.tex) continue;
    const [, ey] = look.extent, big = Math.max(...look.extent), D = (1.3 * big) / Math.tan((15 * Math.PI) / 180);
    cam.position.set(0, ey / 2, D); cam.lookAt(0, ey / 2, 0); cam.near = D / 100; cam.far = D * 3; cam.updateProjectionMatrix();
    const views = (mat) => {
      const m = new T.Mesh(look.geometry, mat); scene.add(m);
      const r = { front: shot(m, 0), s1: shot(m, -Math.PI / 2), s2: shot(m, Math.PI / 2) };
      scene.remove(m); mat.dispose(); return r;
    };
    const side = (r) => (stripes(r.s1) + stripes(r.s2)) / 2;
    const before = views(new T.MeshStandardMaterial({ map: look.tex, roughness: 0.9, metalness: 0 }));
    const after = views(S.modelMaterial(look.tex, look.soft));
    const plain = views(new T.MeshStandardMaterial({ color: meanColor(look.soft), roughness: 0.9, metalness: 0 }));
    const cut = 1 - (side(after) - side(plain)) / (side(before) - side(plain));
    rows.push({ name: it.name, sideCut: Math.round(cut * 100) / 100, frontChange: Math.round(change(before.front, after.front) * 100) / 100 });
  }
  R.setClearColor(oldColor, oldAlpha); rt.dispose(); S.update();
  console.table(rows);
  return rows;
})();
