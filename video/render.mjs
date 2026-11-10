// Frame-by-frame renderer: seek the page to t = frame / fps, screenshot it,
// pipe the PNG into ffmpeg, then mux the synthesized score.
//
//   node render.mjs                     full video -> out/luciazero-intro.mp4
//   node render.mjs --cut launch        a cut from timeline.json › cuts -> its file (music from its music)
//   node render.mjs --stills 3,6.2,16   single frames -> out/stills/t-<sec>.png (<cut>-t-<sec>.png with --cut)
//   node render.mjs --from 24 --to 36   a time range only (no audio)
//   node render.mjs --fps 10            draft at a lower frame rate
//   node render.mjs --grain 0           no film grain (for GIF and poster encodes)
//   node render.mjs --cover             cover.html -> out/cover.png (the README cover)
//   node render.mjs --serve             serve for live preview in a browser

import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { parseArgs } from 'node:util';

const HERE = import.meta.dirname;
const ROOT = path.resolve(HERE, '..'); // repo root, so the page can load ../site/lucia-3d.png
const OUT = path.join(HERE, 'out');
const TL = JSON.parse(fs.readFileSync(path.join(HERE, 'timeline.json'), 'utf8'));

const { values: args } = parseArgs({
  options: {
    stills: { type: 'string' },
    from: { type: 'string' },
    to: { type: 'string' },
    fps: { type: 'string' },
    out: { type: 'string' },
    grain: { type: 'string' },
    serve: { type: 'boolean' },
    cover: { type: 'boolean' },
    cut: { type: 'string' },
  },
});

const CUT = args.cut ? TL.cuts?.[args.cut] : null;
if (args.cut && !CUT) throw new Error(`timeline.json has no cut named ${args.cut}`);
if (CUT && !(CUT.file && CUT.music)) throw new Error(`timeline.json › cuts › ${args.cut} needs a 'file' and a 'music' name, or it would overwrite the full render`);

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.png': 'image/png', '.woff2': 'font/woff2', '.wav': 'audio/wav', '.css': 'text/css', '.svg': 'image/svg+xml' };

// Lucia's VRM and motions stay outside this repository, because the model's licence
// forbids redistribution. They are read from a checkout of Lucia-AI-Waifu-Project
// (LUCIA_VRM_DIR, its vrm_model folder) and served by name under /lucia/. Without
// them the page falls back to site/lucia-3d.png.
const LUCIA_DIR = path.resolve(process.env.LUCIA_VRM_DIR ?? path.join(ROOT, '..', '..', 'Lucia-AI-Waifu-Project', 'vrm_model'));
const LUCIA_FILES = {
  vrm: 'exports/Lucia.vrm',
  idle: 'vrm_motion/hanami_overte/idle.vrma',
  'head-tilt': 'vrm_motion/hanami_overte/neutral.vrma',
  shake: 'vrm_motion/hanami_overte/shake.vrma',
  think: 'vrm_motion/hanami_overte/think.vrma',
  'nod-yes': 'vrm_motion/hanami_overte/nod-3.vrma',
  'raise-hand': 'vrm_motion/hanami_overte/raise-hand.vrma',
  talk: 'vrm_motion/hanami_overte/idle-talking.vrma',
  happy: 'vrm_motion/hanami_overte/happy.vrma',
  nod: 'vrm_motion/hanami_overte/nod.vrma',
};
const luciaFound = Object.values(LUCIA_FILES).every((f) => fs.existsSync(path.join(LUCIA_DIR, f)));
console.log(luciaFound ? `Lucia: VRM from ${LUCIA_DIR}` : `Lucia: no VRM at ${LUCIA_DIR} (set LUCIA_VRM_DIR); using site/lucia-3d.png`);

function serveLucia(name, res) {
  if (name === 'manifest.json') {
    res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ found: luciaFound }));
    return;
  }
  if (!luciaFound || !Object.hasOwn(LUCIA_FILES, name)) {
    res.writeHead(404).end();
    return;
  }
  fs.readFile(path.join(LUCIA_DIR, LUCIA_FILES[name]), (err, data) => {
    if (err) res.writeHead(404).end();
    else res.writeHead(200, { 'content-type': 'application/octet-stream' }).end(data);
  });
}

function serve() {
  const server = http.createServer((req, res) => {
    const pathname = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    if (pathname.startsWith('/lucia/')) {
      serveLucia(pathname.slice('/lucia/'.length), res);
      return;
    }
    const file = path.join(ROOT, pathname);
    if (file !== ROOT && !file.startsWith(ROOT + path.sep)) {
      res.writeHead(403).end();
      return;
    }
    fs.readFile(file, (err, data) => {
      if (err) {
        res.writeHead(404).end();
        return;
      }
      res.writeHead(200, { 'content-type': TYPES[path.extname(file)] ?? 'application/octet-stream' }).end(data);
    });
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

const server = await serve();
const base = `http://127.0.0.1:${server.address().port}/video/index.html`;

if (args.serve) {
  console.log(`preview: ${base}   (click to play with sound; ?t=12.5 shows one frame)`);
  await new Promise(() => {});
}

const browser = await chromium.launch({
  args: ['--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist', '--hide-scrollbars', '--force-color-profile=srgb', '--font-render-hinting=none'],
});
const page = await browser.newPage({ viewport: { width: TL.width, height: TL.height }, deviceScaleFactor: 1 });
const problems = [];
page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') problems.push(`console.${m.type()}: ${m.text()}`); });
page.on('requestfailed', (r) => problems.push(`requestfailed: ${r.url()}`));
page.on('response', (r) => { if (r.status() >= 400) problems.push(`http ${r.status()}: ${r.url()}`); });

if (args.cover) {
  await page.goto(base.replace('index.html', 'cover.html'));
  await page.evaluate(() => document.fonts.ready);
  fs.mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, 'cover.png') });
  console.log(path.join(OUT, 'cover.png'));
  await finish();
}

await page.goto(`${base}?render${args.grain === undefined ? '' : `&grain=${encodeURIComponent(args.grain)}`}${args.cut ? `&cut=${encodeURIComponent(args.cut)}` : ''}`);
try {
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 60000 });
} catch (e) {
  console.error(problems.join('\n'));
  throw e;
}
console.log(`webgl: ${await page.evaluate(() => window.__glInfo)}`);

async function frameAt(t, type = 'png') {
  await page.evaluate((tt) => window.__seek(tt), t);
  return page.screenshot({ type, animations: 'allow', caret: 'initial' });
}

function finish(code = 0) {
  if (problems.length) console.error(`page reported ${problems.length} problem(s):\n${problems.join('\n')}`);
  return browser.close().then(() => { server.close(); process.exit(problems.length ? 1 : code); });
}

if (args.stills) {
  const dir = path.join(OUT, 'stills');
  fs.mkdirSync(dir, { recursive: true });
  for (const s of args.stills.split(',').map(Number)) {
    const file = path.join(dir, `${args.cut ? `${args.cut}-` : ''}t-${s.toFixed(2).padStart(5, '0')}.png`);
    fs.writeFileSync(file, await frameAt(s));
    console.log(file);
  }
  await finish();
}

const duration = await page.evaluate(() => window.__duration); // the cut's length, or the timeline's
const fps = Number(args.fps ?? TL.fps);
const from = Number(args.from ?? 0);
const to = Number(args.to ?? duration);
const full = from === 0 && to === duration;
const first = Math.round(from * fps);
const last = Math.round(to * fps); // exclusive
const outFile = args.out ?? path.join(OUT, full && fps === TL.fps ? (CUT?.file ?? 'luciazero-intro.mp4') : `draft-${args.cut ? `${args.cut}-` : ''}${from}-${to}-${fps}fps.mp4`);
const music = path.join(OUT, CUT?.music ?? 'music.wav');
if (full && !fs.existsSync(music)) throw new Error(`${path.relative(HERE, music)} is missing; run music.py${args.cut ? ` --cut ${args.cut}` : ''} first`);

fs.mkdirSync(OUT, { recursive: true });
const ff = spawn('ffmpeg', [
  '-y', '-loglevel', 'error',
  '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'png', '-i', '-',
  ...(full ? ['-i', music, '-map', '0:v', '-map', '1:a', '-c:a', 'aac', '-b:a', '256k'] : []),
  '-vf', 'scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv420p',
  '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-g', String(fps * 2),
  '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
  '-movflags', '+faststart',
  outFile,
], { stdio: ['pipe', 'inherit', 'inherit'] });

const started = Date.now();
for (let f = first; f < last; f++) {
  const png = await frameAt(f / fps);
  if (!ff.stdin.write(png)) await once(ff.stdin, 'drain');
  if ((f - first) % (fps * 2) === 0) {
    const done = f - first + 1;
    const rate = done / ((Date.now() - started) / 1000);
    process.stdout.write(`\rframe ${f}/${last}  ${rate.toFixed(1)} fps  eta ${((last - f) / rate).toFixed(0)}s   `);
  }
}
ff.stdin.end();
const [code] = await once(ff, 'close');
console.log(`\n${outFile}: ${last - first} frames in ${((Date.now() - started) / 1000).toFixed(0)}s, ffmpeg exit ${code}`);
await finish(code);
