// 給 Python 用的去背：跟網頁同一份 prototype/cutout.js（docs/model3d.md 第 1 句）
// node cutout_cli.js <rgba 檔> <寬> <高> <吊燈 1/0>
// 印出 { ok, reason, box }；成功的話把透明度（寬 x 高，0 或 255）寫到 <rgba 檔>.alpha
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { cutout } = require(path.join(__dirname, '..', '..', 'prototype', 'cutout.js'));

const [file, w, h, top] = process.argv.slice(2);
const data = new Uint8ClampedArray(fs.readFileSync(file));
const r = cutout({ data, width: Number(w), height: Number(h) }, { allowTop: top === '1' });
if (r.ok) fs.writeFileSync(`${file}.alpha`, Buffer.from(r.alpha));
process.stdout.write(JSON.stringify({ ok: r.ok, reason: r.reason || null, box: r.box || null }));
