// Luciazero intro: every pixel is a pure function of time t.
//
// render.mjs calls window.__seek(t) once per frame and screenshots the page,
// so nothing here may read the wall clock or unseeded randomness. Three.js
// draws the world; GSAP owns the DOM typography on one paused timeline; both
// read their cue times from timeline.json, which music.py reads as well.

import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { loadLucia } from './lucia.js';

const TL = await (await fetch('timeline.json')).json();
const EV = TL.events;
const W = TL.width;
const H = TL.height;
const { gsap, SplitText } = window;
gsap.registerPlugin(SplitText);

// A cut (timeline.json › cuts, ?cut=name) plays shots in order: ranges of this
// timeline, whose times and cues are unchanged, and full-frame chapter cards. With
// no cut the one shot is the whole film.
const CUT_NAME = new URLSearchParams(location.search).get('cut');
const CUT = CUT_NAME ? TL.cuts?.[CUT_NAME] : null;
if (CUT_NAME && !CUT) throw new Error(`timeline.json: unknown cut ${CUT_NAME}`);
const SHOTS = [];
{
  let at = 0;
  for (const s of CUT?.shots ?? [{ src: [0, TL.duration] }]) {
    const dur = s.src ? s.src[1] - s.src[0] : s.dur;
    SHOTS.push({ ...s, at, end: at + dur });
    at += dur;
  }
  // under a card the film holds on the first frame of the next range; the card hides it
  SHOTS.forEach((s, i) => { if (s.card) s.hold = (SHOTS.slice(i + 1).find((n) => n.src) ?? SHOTS.slice(0, i).reverse().find((n) => n.src)).src[0]; });
}
const DURATION = SHOTS[SHOTS.length - 1].end;
const sceneKept = (name) => { const [a, b] = TL.scenes[name]; return SHOTS.some((s) => s.src && s.src[0] < b && s.src[1] > a); };
// The caught scenes open on the loop scene's last frame; a cut without the loop hides it.
const LOOP_ON = sceneKept('loop');

// ------------------------------------------------------------------ helpers

function mulberry32(seed) {
  let a = seed;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = mulberry32(41321);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, u) => a + (b - a) * u;
const easeCache = new Map();
const ease = (name) => {
  if (!easeCache.has(name)) easeCache.set(name, gsap.parseEase(name));
  return easeCache.get(name);
};
// Keyframes [[time, value, easeIntoThisKey], ...]; value may be a number or an array.
function k(t, keys) {
  if (t <= keys[0][0]) return keys[0][1];
  for (let i = 1; i < keys.length; i++) {
    const [t1, v1, e] = keys[i];
    if (t <= t1) {
      const [t0, v0] = keys[i - 1];
      const u = ease(e || 'sine.inOut')((t - t0) / (t1 - t0));
      return Array.isArray(v0) ? v0.map((a, j) => lerp(a, v1[j], u)) : lerp(v0, v1, u);
    }
  }
  return keys[keys.length - 1][1];
}
const pulse = (t, t0, decay) => (t < t0 ? 0 : Math.exp(-(t - t0) / decay));
const lin = (hex) => new THREE.Color(hex); // sRGB hex -> linear working color
// Lucia's palette: the silver-white of her hair and jacket, the cyan of her ear
// lights, her blue and amber eyes, her blush and the navy of her straps.
const C = {
  bg: lin('#e3f1fb'), bg2: lin('#fbfcff'), teal: lin('#3cc8ec'), halo: lin('#8fe6f8'), deep: lin('#1b8fc0'),
  amber: lin('#f2a93b'), red: lin('#f2577a'), green: lin('#2dbe8c'), paper: lin('#ffffff'), dim: lin('#c9d3df'),
  ink: lin('#1f2a44'), blue: lin('#2e8fe0'), pink: lin('#ff93ab'),
};
const arr = (c, s = 1) => [c.r * s, c.g * s, c.b * s];
// A cue is seconds, an event name, or an event name plus or minus seconds ("c1Red-0.25").
function cue(v) {
  if (typeof v === 'number') return v;
  const m = /^(\w+)([+-][\d.]+)?$/.exec(v);
  if (!m || !(m[1] in EV)) throw new Error(`timeline.json: unknown cue ${v}`);
  return EV[m[1]] + (m[2] ? Number(m[2]) : 0);
}
const VERT_UV = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

// The world is a corridor down -z. Each later scene has a stage the camera dives to
// and parks 12 units in front of, looking straight ahead.
const GATE_Z = -14; // the caught scenes
const BIS_Z = -32; // bisect
const RELAY_Z = -50;
const BUS_Z = -68;
const EVI_Z = -86; // evidence and safe to try
const STAGE5_Z = -104; // skills
const STAGE6_Z = -122; // call to action
const HALF_H = 12 * Math.tan(THREE.MathUtils.degToRad(16)); // half the view height at a parked stage (fov 32)
const HALF_W = (HALF_H * W) / H;
// The world point on a stage plane that a camera parked at height camY sees at screen
// pixel (x, y). placeCamera looks 12 ahead at a fifth of its height, a slight tilt.
function stagePoint(x, y, z, camY = 0.15) {
  const tilt = Math.atan((camY * 0.8) / 12);
  const v = Math.atan((1 - (y / H) * 2) * Math.tan(THREE.MathUtils.degToRad(16)));
  return new THREE.Vector3(((x / W) * 2 - 1) * HALF_W, camY + 12 * Math.tan(v - tilt), z);
}
const hash01 = (a, b) => { const s = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453; return s - Math.floor(s); };
// Sum of decaying pulses [[time, amplitude, decay], ...].
const pulses = (t, list) => list.reduce((sum, [at, amp, decay]) => sum + amp * pulse(t, at, decay), 0);
// A color that switches at each key's time, blending over `blend` seconds.
function stepColor(t, keys, out, blend = 0.2) {
  out.copy(keys[0][1]);
  for (let i = 1; i < keys.length && t >= keys[i][0]; i++) out.lerp(keys[i][1], clamp((t - keys[i][0]) / blend));
  return out;
}

async function loadImage(src) {
  const img = new Image();
  img.src = src;
  await img.decode();
  return img;
}

// ------------------------------------------------------------------ renderer

const canvas = document.getElementById('gl');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
renderer.toneMapping = THREE.NoToneMapping;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(32, W / H, 0.1, 400);

const target = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, samples: 4 });
const composer = new EffectComposer(renderer, target);
composer.setPixelRatio(1);
composer.setSize(W, H);
composer.addPass(new RenderPass(scene, camera));
composer.addPass(new OutputPass());
const finish = new ShaderPass({
  uniforms: { tDiffuse: { value: null }, uTime: { value: 0 }, uAberr: { value: 0 }, uVignette: { value: 0.06 }, uGrain: { value: 0 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `
    uniform sampler2D tDiffuse; uniform float uTime, uAberr, uVignette, uGrain; varying vec2 vUv;
    float hash(vec2 p){ p = fract(p * vec2(443.897, 441.423)); p += dot(p, p.yx + 19.19); return fract((p.x + p.y) * p.x); }
    void main(){
      vec2 c = vUv - 0.5;
      float r2 = dot(c, c);
      vec2 off = c * uAberr * (0.5 + r2 * 2.0);
      vec3 col = vec3(texture2D(tDiffuse, vUv + off).r, texture2D(tDiffuse, vUv).g, texture2D(tDiffuse, vUv - off).b);
      col *= 1.0 - uVignette * smoothstep(0.08, 0.6, r2 * 1.35);
      col += (hash(vUv * vec2(1920.0, 1080.0) + fract(uTime * 7.31) * 97.0) - 0.5) * uGrain;
      gl_FragColor = vec4(col, 1.0);
    }`,
});
composer.addPass(finish);

const ambient = new THREE.AmbientLight(0xffffff, 0.5);
const key = new THREE.DirectionalLight(0xffffff, 2.6);
key.position.set(3, 4, 6);
const rim = new THREE.PointLight(C.halo, 30, 30);
rim.position.set(-4, 2, 3);
scene.add(ambient, key, rim);

// ------------------------------------------------------------------ backdrop

const backdrop = new THREE.Mesh(
  new THREE.PlaneGeometry(2, 2),
  new THREE.ShaderMaterial({
    depthTest: false, depthWrite: false,
    uniforms: { uTop: { value: C.bg2 }, uBottom: { value: C.bg }, uDot: { value: C.teal }, uGlowColor: { value: new THREE.Color() }, uGlowPos: { value: new THREE.Vector2(0.5, 0.5) }, uGlow: { value: 0 }, uTime: { value: 0 } },
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`,
    fragmentShader: `
      varying vec2 vUv; uniform vec3 uTop, uBottom, uDot, uGlowColor; uniform vec2 uGlowPos; uniform float uGlow, uTime;
      void main(){
        vec3 col = mix(uBottom, uTop, smoothstep(0.0, 1.0, vUv.y));
        vec2 d = (vUv - uGlowPos) * vec2(1.7778, 1.0);
        col = mix(col, uGlowColor, uGlow * 0.55 * exp(-dot(d, d) * 2.6));
        // faint polka dots, offset every other row, drifting on the diagonal
        vec2 cell = (vUv * vec2(1920.0, 1080.0) + vec2(uTime * 9.0, uTime * 6.0)) / 46.0;
        vec2 f = fract(cell + vec2(0.5 * mod(floor(cell.y), 2.0), 0.0)) - 0.5;
        col = mix(col, uDot, (1.0 - smoothstep(0.075, 0.1, length(f))) * 0.12);
        gl_FragColor = vec4(col, 1.0);
      }`,
  }),
);
backdrop.frustumCulled = false;
backdrop.renderOrder = -100;
scene.add(backdrop);

// ------------------------------------------------------------------ confetti (all scenes): a few pastel sparkles and dots

// The first field fills the corridor of the 60-second cut (z 10 to -70) from the
// shared stream, so everything drawn from it after the dust keeps its layout; the
// second field extends the corridor to the later stages on a stream of its own.
function dustField(count, zNear, depth, rnd01) {
  const pos = new Float32Array(count * 3);
  const rnd = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    pos[i * 3] = (rnd01() - 0.5) * 30;
    pos[i * 3 + 1] = (rnd01() - 0.5) * 18;
    pos[i * 3 + 2] = zNear - rnd01() * depth;
    rnd[i] = rnd01();
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('aRand', new THREE.BufferAttribute(rnd, 1));
  const m = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { uTime: { value: 0 }, uC0: { value: C.teal }, uC1: { value: C.pink }, uC2: { value: C.amber }, uC3: { value: C.blue }, uAmount: { value: 1 } },
    vertexShader: `
      attribute float aRand; uniform float uTime; varying float vA, vR;
      void main(){
        vec3 p = position + vec3(sin(uTime * 0.11 + aRand * 40.0) * 0.4, cos(uTime * 0.09 + aRand * 30.0) * 0.3, 0.0);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        float shown = step(aRand, 0.13); // one point in eight: minimal
        float star = step(0.5, fract(aRand * 91.0));
        gl_PointSize = shown * mix(9.0, 20.0, fract(aRand * 53.0)) * mix(0.8, 1.6, star) * (12.0 / max(-mv.z, 0.5));
        vA = shown * 0.6 * smoothstep(0.5, 3.0, -mv.z);
        vR = aRand;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform vec3 uC0, uC1, uC2, uC3; uniform float uAmount; varying float vA, vR;
      void main(){
        vec2 p = gl_PointCoord - 0.5;
        float k = fract(vR * 37.0);
        vec3 c = k < 0.4 ? uC0 : k < 0.65 ? uC1 : k < 0.85 ? uC2 : uC3;
        vec2 q = abs(p) * 2.0;
        float shape = fract(vR * 91.0) >= 0.5
          ? 1.0 - smoothstep(0.88, 1.0, sqrt(q.x) + sqrt(q.y)) // a four-point sparkle
          : 1.0 - smoothstep(0.17, 0.2, length(p)); // a dot
        float a = shape * vA * uAmount;
        if (a < 0.01) discard;
        gl_FragColor = vec4(c, a);
      }`,
  });
  const pts = new THREE.Points(g, m);
  pts.frustumCulled = false;
  scene.add(pts);
  return m;
}
const dust = [dustField(1800, 10, 80, rand), dustField(1900, -70, 84, mulberry32(1154))];

// ------------------------------------------------------------------ toon look

// Three flat bands of light, like cel shading, and a navy outline (her straps' color)
// drawn as the back faces of a slightly larger copy.
const toonRamp = (() => {
  const t = new THREE.DataTexture(new Uint8Array([110, 205, 255]), 3, 1, THREE.RedFormat);
  t.minFilter = t.magFilter = THREE.NearestFilter;
  t.needsUpdate = true;
  return t;
})();
const toon = (color, extra = {}) => new THREE.MeshToonMaterial({ color: color.clone(), gradientMap: toonRamp, transparent: true, ...extra });
function inkOutline(mesh, grow = 0.06) {
  const o = new THREE.Mesh(mesh.geometry, new THREE.MeshBasicMaterial({ color: C.ink, side: THREE.BackSide, transparent: true }));
  o.scale.setScalar(1 + grow);
  mesh.add(o);
  mesh.userData.outline = o.material;
  return o;
}

// ------------------------------------------------------------------ the green check (scene 1)

const CHECK_POLY = [[-1.25, 0.12], [-0.98, 0.39], [-0.42, -0.17], [1.02, 1.27], [1.29, 1.0], [-0.42, -0.71]];
const CHECK_SCALE = 1.25;
const CHECK_Y = -0.22;
const checkShape = new THREE.Shape(CHECK_POLY.map(([x, y]) => new THREE.Vector2(x, y)));
const checkGeo = new THREE.ExtrudeGeometry(checkShape, { depth: 0.34, bevelEnabled: true, bevelThickness: 0.07, bevelSize: 0.05, bevelSegments: 5 });
checkGeo.computeBoundingBox();
const checkCenter = checkGeo.boundingBox.getCenter(new THREE.Vector3());
checkGeo.translate(-checkCenter.x, -checkCenter.y, -checkCenter.z);
const checkMat = toon(C.green, { emissive: C.green.clone(), emissiveIntensity: 0.1, transparent: false });
const check = new THREE.Mesh(checkGeo, checkMat);
check.scale.setScalar(CHECK_SCALE);
inkOutline(check, 0.05);
scene.add(check);

function insidePoly(x, y, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

// ------------------------------------------------------------------ Lucia

const LUCIA_H = 5.2;
const LUCIA_W = LUCIA_H * 0.8;

// Lucia presents the caught scenes and "safe to try" from the right edge. Her lines
// (bubble, gesture, face) are in timeline.json, since the music pops each bubble.
const LINES = TL.lucia.lines.map((l) => ({ ...l, at: cue(l.at), end: cue(l.end) }));
// She is on screen from the dive into the caught scenes to the bisect, and for "safe to try".
const PRESENT = [[EV.caught1 + 0.5, EV.c5Out + 0.3], [EV.safe + 0.2, EV.sfOut + 0.2]];
// She glances at the panels (toward screen left) as their news arrives.
const GLANCES = [
  [EV.c1Term + 0.2, EV.c1Term + 0.9], [EV.c1Nudge - 0.1, EV.c1Nudge + 0.6], [EV.c1Run, EV.c1Red],
  [EV.c2Panel + 0.3, EV.c2Left + 0.1], [EV.c3Count, EV.c3H1], [EV.c4Run, EV.c4Status + 0.1],
  [EV.c4Hostile, EV.c4Hostile + 1.0], [EV.c5Term + 0.2, EV.c5Fail], [EV.c5Fail + 0.9, EV.c5Pass], [EV.sfItems - 0.4, EV.sfItems + 0.3],
];
// Keys that are 0 outside the given [start, end, value] spans, easing in and out of each.
const spans = (list, fi = 0.18, fo = 0.3) => [[0, 0], ...list.flatMap(([a, b, v]) => [[a - fi, 0], [a, v], [b, v], [b + fo, 0]])].sort((x, y) => x[0] - y[0]);
const faceSpans = (name) => LINES.filter((l) => l.face[name]).map((l) => [l.at, l.end, l.face[name]]);

// What Lucia does while she is on screen (scenes 3-4, the presented scenes and the
// call to action). Clip names are the ones render.mjs serves; times follow the story.
const blinkRand = mulberry32(2718);
const LUCIA_BLINKS = [];
for (const [from, to] of [[EV.reveal + 1.1, EV.c5Out + 0.5], [EV.safe, EV.sfOut + 0.5], [EV.cta + 1.2, TL.duration]]) {
  for (let b = from; b < to; b += 2.4 + blinkRand() * 1.9) LUCIA_BLINKS.push(b);
}
const LUCIA_SPEC = {
  base: 'idle',
  frame: { top: 0.62, bottom: 0.12 }, // headroom for the ?, ! and ♪ that pop above her head
  gestures: [
    { clip: 'head-tilt', start: EV.title + 0.3, end: EV.title + 4.6 },
    { clip: 'shake', start: EV.verifyRed + 0.1, end: EV.fix - 0.3, fade: 0.3 },
    { clip: 'think', start: EV.fix + 0.1, end: EV.verifyGreen - 0.4, fade: 0.3 },
    { clip: 'nod-yes', start: EV.verifyGreen + 0.05, end: EV.verifyGreen + 2.9, fade: 0.25 },
    ...LINES.map((l) => ({ clip: l.clip, start: l.at - 0.1, end: l.end, fade: 0.3 })),
    { clip: 'raise-hand', start: EV.cta + 0.5, end: TL.duration + 1 },
  ],
  face: {
    relaxed: [[0, 0.35], [EV.verifyRed - 0.1, 0.35], [EV.verifyRed + 0.1, 0], [EV.verifyGreen + 2.9, 0], [EV.verifyGreen + 3.3, 0.35]],
    happy: spans([[EV.verifyGreen + 0.25, EV.verifyGreen + 2.6, 0.9], ...faceSpans('happy'), [EV.final + 0.2, TL.duration + 1, 0.8]]),
    Surprised: spans([[EV.verifyRed + 0.12, EV.fix - 0.3, 0.85], ...faceSpans('Surprised')]),
    ear_alert: spans([[EV.verifyRed + 0.1, EV.fix, 1], ...faceSpans('ear_alert')]),
    serious: spans([[EV.fix + 0.3, EV.verifyGreen - 0.1, 0.55], ...faceSpans('serious')]),
    blush: spans(faceSpans('blush')),
    frag_exclamation: spans([[EV.verifyRed + 0.1, EV.fix, 1], ...faceSpans('frag_exclamation')], 0.15, 0.2),
    frag_question: spans([[EV.fix + 0.2, EV.verifyGreen - 0.1, 1], ...faceSpans('frag_question')], 0.15, 0.2),
    frag_happy: spans([[EV.verifyGreen + 0.2, EV.quote + 1.5, 1], ...faceSpans('frag_happy'), [EV.final + 0.2, TL.duration + 1, 1]], 0.15, 0.3),
  },
  // she stands left of the title in scene 3 and glances at it as it lands; later she
  // glances at the panels beside her
  look: {
    yaw: [[EV.title, 0], [EV.title + 0.4, -30], [EV.tagline + 1.5, -30], [EV.tagline + 2, 0], ...spans(GLANCES.map(([a, b]) => [a, b, 24]), 0.3, 0.35).slice(1)],
    pitch: [[0, 0]],
  },
  blinks: LUCIA_BLINKS,
};
const lucia = await loadLucia({ renderer, fps: TL.fps, size: [800, 1000], spec: LUCIA_SPEC });
// The shards assemble into her pose at this moment, so the dissolve lands on them.
const LUCIA_SHARD_T = EV.reveal + 0.9;
let luciaTex;
let luciaPx; // { width, height, data }: RGBA, top row first
if (lucia) {
  luciaTex = lucia.texture;
  luciaPx = lucia.pixels(LUCIA_SHARD_T);
} else {
  const img = await loadImage('../site/lucia-3d.png');
  luciaTex = new THREE.Texture(img);
  luciaTex.colorSpace = THREE.SRGBColorSpace;
  luciaTex.anisotropy = 8;
  luciaTex.needsUpdate = true;
  const c = document.createElement('canvas');
  c.width = img.width;
  c.height = img.height;
  const cx = c.getContext('2d', { willReadFrequently: true });
  cx.drawImage(img, 0, 0);
  luciaPx = { width: c.width, height: c.height, data: cx.getImageData(0, 0, c.width, c.height).data };
}

function luciaMaterial() {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: true,
    uniforms: { uMap: { value: luciaTex }, uPremul: { value: lucia ? 1 : 0 }, uReveal: { value: 0 }, uOpacity: { value: 1 }, uEdge: { value: C.teal }, uBright: { value: 1 } },
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `
      uniform sampler2D uMap; uniform float uPremul, uReveal, uOpacity, uBright; uniform vec3 uEdge; varying vec2 vUv;
      float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      float vnoise(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
        return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y); }
      void main(){
        vec4 tex = texture2D(uMap, vUv);
        if (uPremul > 0.5) tex.rgb /= max(tex.a, 0.004); // the live render is premultiplied
        float n = vnoise(vUv * vec2(9.0, 11.25)) * 0.45 + vnoise(vUv * vec2(40.0, 50.0)) * 0.2 + (1.0 - vUv.y) * 0.35;
        float d = uReveal * 1.25 - 0.12 - n;
        float vis = smoothstep(0.0, 0.015, d);
        float edge = smoothstep(-0.03, 0.0, d) * (1.0 - smoothstep(0.0, 0.03, d));
        vec3 col = mix(tex.rgb * uBright, uEdge, edge * (1.0 - vis));
        float a = tex.a * max(vis, edge) * uOpacity * smoothstep(0.0, 0.14, vUv.y);
        if (a < 0.02) discard;
        gl_FragColor = vec4(col, a);
      }`,
  });
}
const luciaA = new THREE.Mesh(new THREE.PlaneGeometry(LUCIA_W, LUCIA_H), luciaMaterial());
const luciaB = new THREE.Mesh(new THREE.PlaneGeometry(LUCIA_W, LUCIA_H), luciaMaterial());
// luciaP presents from the right edge; it is pinned to the screen like the relay card.
const luciaP = new THREE.Mesh(new THREE.PlaneGeometry(LUCIA_W, LUCIA_H), luciaMaterial());
luciaP.material.depthTest = false;
luciaA.renderOrder = 1;
luciaB.renderOrder = 1;
luciaP.renderOrder = 5;
scene.add(luciaA, luciaB, luciaP);
const PRES = { x: 1540, y: 590, px: 960, d: 10 }; // screen center, on-screen height, view depth
const LUCIA_S3 = new THREE.Vector3(-2.55, -0.08, 0);
const LUCIA_S4 = new THREE.Vector3(0, -0.35, -0.4);
const LUCIA_S6 = new THREE.Vector3(-3.35, -0.12, STAGE6_Z);

// ------------------------------------------------------------------ shards: check -> debris -> vortex -> Lucia

const SHARDS = 26000;
const shardMat = (() => {
  const { width: pw, height: ph, data: px } = luciaPx;
  const cells = [];
  for (let y = 0; y < ph; y += 2) {
    for (let x = 0; x < pw; x += 2) {
      if (px[(y * pw + x) * 4 + 3] > 200) cells.push([x, y]);
    }
  }
  for (let i = cells.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [cells[i], cells[j]] = [cells[j], cells[i]];
  }
  const aCheck = new Float32Array(SHARDS * 3);
  const aLucia = new Float32Array(SHARDS * 3);
  const aColor = new Float32Array(SHARDS * 3);
  const aRand = new Float32Array(SHARDS * 4);
  const col = new THREE.Color();
  const [minX, maxX, minY, maxY] = [-1.3, 1.3, -0.72, 1.28];
  for (let i = 0; i < SHARDS; i++) {
    let x, y;
    do { x = lerp(minX, maxX, rand()); y = lerp(minY, maxY, rand()); } while (!insidePoly(x, y, CHECK_POLY));
    const z = rand() * 0.48 - 0.07;
    aCheck[i * 3] = (x - checkCenter.x) * CHECK_SCALE;
    aCheck[i * 3 + 1] = (y - checkCenter.y) * CHECK_SCALE + CHECK_Y;
    aCheck[i * 3 + 2] = (z - checkCenter.z) * CHECK_SCALE;
    const [cxp, cyp] = cells[i % cells.length];
    const jx = (rand() - 0.5) * 2;
    const jy = (rand() - 0.5) * 2;
    aLucia[i * 3] = LUCIA_S3.x + ((cxp + jx) / pw - 0.5) * LUCIA_W;
    aLucia[i * 3 + 1] = LUCIA_S3.y + (0.5 - (cyp + jy) / ph) * LUCIA_H;
    aLucia[i * 3 + 2] = LUCIA_S3.z + (rand() - 0.5) * 0.08;
    const o = (cyp * pw + cxp) * 4;
    if (lucia) {
      const a = px[o + 3];
      col.setRGB(px[o] / a, px[o + 1] / a, px[o + 2] / a, THREE.LinearSRGBColorSpace);
    } else {
      col.setRGB(px[o] / 255, px[o + 1] / 255, px[o + 2] / 255, THREE.SRGBColorSpace);
    }
    aColor.set([col.r, col.g, col.b], i * 3);
    aRand.set([rand(), rand(), rand(), rand()], i * 4);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(aCheck.slice(), 3));
  g.setAttribute('aCheck', new THREE.BufferAttribute(aCheck, 3));
  g.setAttribute('aLucia', new THREE.BufferAttribute(aLucia, 3));
  g.setAttribute('aColor', new THREE.BufferAttribute(aColor, 3));
  g.setAttribute('aRand', new THREE.BufferAttribute(aRand, 4));
  const m = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: {
      uTime: { value: 0 }, uGreen: { value: C.green }, uRed: { value: C.red }, uPink: { value: C.pink }, uTeal: { value: C.teal }, uAmber: { value: C.amber }, uBlue: { value: C.blue },
      uCenter: { value: LUCIA_S3.clone() },
      uShatter: { value: EV.shatter }, uVortex: { value: EV.vortex }, uDrop: { value: EV.drop }, uReveal: { value: EV.reveal },
    },
    vertexShader: `
      attribute vec3 aCheck, aLucia, aColor; attribute vec4 aRand;
      uniform float uTime, uShatter, uVortex, uDrop, uReveal; uniform vec3 uGreen, uRed, uPink, uTeal, uAmber, uBlue, uCenter;
      varying vec3 vColor; varying float vAlpha;
      vec3 rotY(vec3 p, float a){ float c = cos(a), s = sin(a); return vec3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z); }
      vec3 rotZ(vec3 p, float a){ float c = cos(a), s = sin(a); return vec3(c * p.x - s * p.y, s * p.x + c * p.y, p.z); }
      void main(){
        float t = uTime;
        float dt = max(t - uShatter, 0.0);
        vec3 dir = normalize(aCheck - vec3(0.0, 0.25, 0.0) + (aRand.xyz - 0.5) * 1.7);
        float speed = mix(2.2, 11.5, aRand.w * aRand.w);
        vec3 p = aCheck + dir * speed * (1.0 - exp(-1.5 * dt)) / 1.5;
        p.z += (aRand.x - 0.35) * 2.4 * (1.0 - exp(-dt));
        p += 0.35 * sin(vec3(dt * 0.35 + aRand.x * 6.283, dt * 0.29 + aRand.y * 6.283, dt * 0.31 + aRand.z * 6.283)) * smoothstep(0.0, 3.0, dt);
        p = rotY(p, dt * 0.035);

        float v = smoothstep(uVortex, uDrop + 0.2, t);
        vec3 q = p - uCenter;
        q = rotZ(q, v * v * (2.4 + aRand.y * 2.8));
        q *= 1.0 - 0.5 * v * v;
        p = uCenter + q;

        float c = clamp((t - (uDrop - 0.15 + aRand.z * 0.4)) / 0.85, 0.0, 1.0);
        float ce = 1.0 - pow(1.0 - c, 4.0);
        p = mix(p, aLucia, ce);

        float off = smoothstep(uReveal, uReveal + 1.1, t);
        p += ((aRand.xyz - 0.5) * 0.7 + vec3(0.0, 0.35, 0.4) * aRand.w) * off;

        vec3 col = mix(uGreen, mix(uRed, uPink, aRand.x), smoothstep(uShatter + 0.12, uShatter + 0.9, t));
        vec3 confetti = aRand.y < 0.4 ? uTeal : aRand.y < 0.65 ? uPink : aRand.y < 0.85 ? uAmber : uBlue;
        col = mix(col, confetti, v);
        col = mix(col, aColor, ce);
        float glow = 0.95 + 0.35 * exp(-dt * 2.2);
        vColor = col * glow;
        vAlpha = step(uShatter, t) * mix(mix(0.9, 0.45, smoothstep(uShatter + 0.5, uShatter + 2.0, t)), 1.0, max(ce, v)) * (1.0 - off);

        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        float size = mix(mix(2.6, 7.5, aRand.w), 3.3, ce);
        gl_PointSize = vAlpha > 0.0 ? size * (12.0 / max(-mv.z, 0.5)) : 0.0;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      varying vec3 vColor; varying float vAlpha;
      void main(){ float d = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.12, d) * vAlpha; if (a < 0.01) discard; gl_FragColor = vec4(vColor, a); }`,
  });
  const pts = new THREE.Points(g, m);
  pts.frustumCulled = false;
  pts.renderOrder = 2;
  scene.add(pts);
  return m;
})();

// ------------------------------------------------------------------ sparkles (the mascot's four-point stars)

function starTexture() {
  const s = 128;
  const c = document.createElement('canvas');
  c.width = c.height = s;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  grad.addColorStop(0, 'rgba(255,255,255,0.35)');
  grad.addColorStop(0.3, 'rgba(255,255,255,0.05)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, s, s);
  g.fillStyle = '#fff';
  g.beginPath();
  const m = s / 2;
  const r = s * 0.46;
  const w = s * 0.07;
  g.moveTo(m, m - r);
  g.quadraticCurveTo(m + w, m - w, m + r, m);
  g.quadraticCurveTo(m + w, m + w, m, m + r);
  g.quadraticCurveTo(m - w, m + w, m - r, m);
  g.quadraticCurveTo(m - w, m - w, m, m - r);
  g.fill();
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}
const SPARKS = 44;
const sparkMat = (() => {
  const pos = new Float32Array(SPARKS * 3);
  const col = new Float32Array(SPARKS * 3);
  const rnd = new Float32Array(SPARKS * 2);
  const palette = [C.teal, C.amber, C.pink, C.blue];
  for (let i = 0; i < SPARKS; i++) {
    const group = i < SPARKS / 2 ? 0 : 1;
    const base = group === 0 ? LUCIA_S3 : LUCIA_S6;
    const a = Math.PI * (0.3 + rand() * 1.4);
    const rr = 1.9 + rand() * 1.9;
    pos.set([base.x + Math.cos(a) * rr * 0.9, base.y + 0.4 + Math.sin(a) * rr * 0.95, base.z + (rand() - 0.5) * 2.4], i * 3);
    const c = palette[i % palette.length];
    col.set([c.r, c.g, c.b], i * 3);
    rnd.set([rand(), group], i * 2);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('aColor', new THREE.BufferAttribute(col, 3));
  g.setAttribute('aRand', new THREE.BufferAttribute(rnd, 2));
  const m = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { uTime: { value: 0 }, uMap: { value: starTexture() }, uVis: { value: new THREE.Vector2() }, uBurst: { value: 0 } },
    vertexShader: `
      attribute vec3 aColor; attribute vec2 aRand; uniform float uTime, uBurst; uniform vec2 uVis; varying vec3 vColor; varying float vA;
      void main(){
        float vis = aRand.y < 0.5 ? uVis.x : uVis.y;
        float tw = 0.55 + 0.45 * sin(uTime * (1.6 + aRand.x * 2.2) + aRand.x * 40.0);
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = (26.0 + 46.0 * aRand.x) * (0.6 + 0.4 * tw) * (1.0 + uBurst) * vis * (12.0 / max(-mv.z, 0.5));
        vColor = aColor;
        vA = vis;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform sampler2D uMap; varying vec3 vColor; varying float vA;
      void main(){ vec4 s = texture2D(uMap, gl_PointCoord); gl_FragColor = vec4(vColor, s.a * vA); }`,
  });
  const pts = new THREE.Points(g, m);
  pts.frustumCulled = false;
  pts.renderOrder = 3;
  scene.add(pts);
  return m;
})();

// ------------------------------------------------------------------ the loop ring (scene 4)

const RING_R = 3.4;
const ring = new THREE.Group();
ring.position.set(0, -0.55, -0.4);
ring.rotation.x = -1.18;
scene.add(ring);
const ringMat = new THREE.ShaderMaterial({
  transparent: true, depthWrite: false,
  uniforms: { uHead: { value: 0 }, uBase: { value: C.teal.clone() }, uHeadColor: { value: C.halo.clone() }, uOpacity: { value: 0 }, uTail: { value: 2.2 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `
    uniform float uHead, uOpacity, uTail; uniform vec3 uBase, uHeadColor; varying vec2 vUv;
    void main(){
      float a = vUv.x * 6.2831853;
      float d = mod(a - uHead, 6.2831853);
      float tail = exp(-d * uTail);
      float head = exp(-d * 60.0) + exp(-(6.2831853 - d) * 60.0);
      vec3 col = mix(uBase, uHeadColor, clamp(tail * 1.3 + head, 0.0, 1.0));
      gl_FragColor = vec4(col, uOpacity);
    }`,
});
const loopTorus = new THREE.Mesh(new THREE.TorusGeometry(RING_R, 0.04, 12, 480), ringMat);
loopTorus.renderOrder = 2;
ring.add(loopTorus);
const NODE_ANG = { plan: Math.PI / 2, change: 0, verify: -Math.PI / 2, fix: Math.PI };
const nodes = {};
for (const [name, a] of Object.entries(NODE_ANG)) {
  const m = new THREE.Mesh(new THREE.OctahedronGeometry(0.2, 0), toon(C.teal, { opacity: 0 }));
  m.position.set(Math.cos(a) * RING_R, Math.sin(a) * RING_R, 0);
  m.renderOrder = 2;
  inkOutline(m, 0.12);
  ring.add(m);
  nodes[name] = m;
}

// ------------------------------------------------------------------ skill chips (scene 6)

function chipTexture(name, desc) {
  const c = document.createElement('canvas');
  c.width = 1024;
  c.height = 256;
  const g = c.getContext('2d');
  const r = 36;
  g.beginPath();
  g.roundRect(6, 6, 1012, 244, r);
  g.fillStyle = '#ffffff';
  g.fill();
  g.lineWidth = 7;
  g.strokeStyle = '#1f2a44';
  g.stroke();
  g.fillStyle = '#3cc8ec'; // a cyan tab, like her ear lights
  g.beginPath();
  g.roundRect(26, 60, 12, 136, 6);
  g.fill();
  g.fillStyle = '#1b8fc0';
  let size = 84; // long names and lines shrink to fit the chip
  do g.font = `600 ${size--}px "IBM Plex Mono"`; while (g.measureText(name).width > 920);
  g.textBaseline = 'alphabetic';
  g.fillText(name, 58, 118);
  g.fillStyle = '#44546c';
  size = 60;
  do g.font = `700 ${size--}px "M PLUS Rounded 1c"`; while (g.measureText(desc).width > 920);
  g.fillText(desc, 60, 204);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

// ------------------------------------------------------------------ relay card (scene 5)

// One LUCIA_RELAY.json card: drafted beside session A, filled row by row,
// sealed by finalize, flown to session B, dissolved when B consumes it. Its path
// is written in screen pixels and unprojected every frame, so it stays lined up
// with the DOM terminals whatever the camera does.
const RL = TL.relay;
const CARD_W = 3.3; // world width of the card body at scale 1
const CARD_D = 12; // view depth the card flies at
const CARD_PX = CARD_W * H / (2 * CARD_D * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))); // on-screen body width at scale 1
const CARD_HOME = [1400, 250];
const CARD_SLOT = [1680, 320, 0.42]; // above session B's window, clear of its title bar
const rowAt = (i) => EV.relayRows + i * EV.relayRowStep;
const relayRand = mulberry32(7); // own stream, so the chip wall keeps its layout

function relayCardTexture() {
  const c = document.createElement('canvas');
  c.width = 1024;
  c.height = 640;
  const g = c.getContext('2d');
  g.textBaseline = 'alphabetic';
  g.fillStyle = '#1b8fc0';
  g.font = '600 54px "IBM Plex Mono"';
  g.fillText('LUCIA_RELAY.json', 56, 96);
  g.fillStyle = '#d5dee8';
  g.fillRect(56, 128, 912, 3);
  const tone = { bad: '#e0456b', warn: '#d98a1c' };
  RL.rows.forEach(([key, value, t], i) => { // row i fills the band 150 + 80i .. 230 + 80i
    g.font = '500 40px "IBM Plex Mono"';
    g.fillStyle = '#1b8fc0';
    g.fillText(key, 56, 205 + i * 80);
    g.fillStyle = tone[t] ?? '#1f2a44';
    g.fillText(value, 400, 205 + i * 80);
  });
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

// The body is a rounded rectangle drawn by its distance field, inside a 60 px
// margin that carries a soft cyan halo. Output is premultiplied.
const cardMat = new THREE.ShaderMaterial({
  // forceSinglePass: a transparent DoubleSide material otherwise draws its back in a
  // separate pass with the winding flipped, where gl_FrontFacing reads true and the
  // mirrored text would show during the flight spin.
  transparent: true, depthTest: false, depthWrite: false, premultipliedAlpha: true, side: THREE.DoubleSide, forceSinglePass: true,
  uniforms: {
    uText: { value: null }, uRowVis: { value: RL.rows.map(() => 0) }, uOpacity: { value: 0 }, uEdge: { value: C.teal.clone() },
    uEdgeGain: { value: 1 }, uGlow: { value: 0 }, uFill: { value: C.paper.clone() }, uDissolve: { value: 0 },
  },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `
    uniform sampler2D uText; uniform float uRowVis[${RL.rows.length}]; uniform float uOpacity, uEdgeGain, uGlow, uDissolve; uniform vec3 uEdge, uFill; varying vec2 vUv;
    float sdRound(vec2 p, vec2 b, float r){ vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
    float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
    float vnoise(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
      return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y); }
    void main(){
      vec2 px = vUv * vec2(1144.0, 760.0) - 60.0; // card pixels, origin bottom left
      float d = sdRound(px - vec2(512.0, 320.0), vec2(509.0, 317.0), 34.0);
      float body = 1.0 - smoothstep(-1.0, 1.0, d);
      float edge = 1.0 - smoothstep(2.5, 4.5, abs(d + 4.0));
      float top = 640.0 - px.y; // canvas rows run top down
      float show = top < 150.0 ? 1.0 : 0.0;
      for (int i = 0; i < ${RL.rows.length}; i++) if (top >= 150.0 + 80.0 * float(i) && top < 230.0 + 80.0 * float(i)) show = uRowVis[i];
      vec4 tx = texture2D(uText, px / vec2(1024.0, 640.0));
      vec3 base = mix(uFill, tx.rgb, tx.a * show * (gl_FrontFacing ? 1.0 : 0.0));
      float n = vnoise(px / 70.0) * 0.65 + vnoise(px / 19.0) * 0.35;
      float th = uDissolve * 1.15;
      float keep = smoothstep(th - 0.03, th, n);
      float burn = (1.0 - keep) * smoothstep(th - 0.12, th - 0.03, n) * step(0.001, uDissolve);
      float ring = edge * keep;
      vec3 col = mix(base, uEdge, clamp(ring * min(uEdgeGain, 1.6) * 0.75 + burn * 2.0, 0.0, 1.0));
      float a = clamp(body * keep + ring + burn * body, 0.0, 1.0);
      float halo = uGlow * 0.35 * exp(-max(d, 0.0) / 24.0) * (1.0 - smoothstep(30.0, 58.0, d)) * (1.0 - body) * (1.0 - uDissolve);
      gl_FragColor = vec4((col * a + uEdge * halo) * uOpacity, (a + halo) * uOpacity);
    }`,
});
const card = new THREE.Mesh(new THREE.PlaneGeometry(CARD_W * 1144 / 1024, CARD_W * 760 / 1024), cardMat);
card.renderOrder = 5;
card.visible = false;
scene.add(card);

// Screen position (px), scale and spin of the card at time t.
function cardState(t) {
  const [x, y, s, spin] = k(t, [
    [EV.relayCard, [880, 413, 0.18, -0.9]],
    [EV.relayCard + 0.85, [...CARD_HOME, 1, 0], 'power3.out'],
    [EV.relayLaunch, [...CARD_HOME, 1, 0]],
    [EV.relayLand, [...CARD_SLOT, Math.PI * 2], 'power2.inOut'],
  ]);
  const fly = clamp((t - EV.relayLaunch) / (EV.relayLand - EV.relayLaunch));
  const hover = clamp((t - EV.relayCard - 0.85) / 0.4) * (1 - fly);
  return [x, y - 60 * Math.sin(Math.PI * fly) + 6 * Math.sin((t - EV.relayCard) * 2.6) * hover, s, spin];
}

const ray = new THREE.Vector3();
const fwd = new THREE.Vector3();
function screenToWorld(x, y, depth, out) {
  camera.getWorldDirection(fwd);
  ray.set((x / W) * 2 - 1, 1 - (y / H) * 2, 0.5).unproject(camera).sub(camera.position).normalize();
  return out.copy(camera.position).addScaledVector(ray, depth / ray.dot(fwd));
}

// Screen-facing points with per-point color, size and alpha.
function fxPointsMaterial() {
  return new THREE.ShaderMaterial({
    transparent: true, depthTest: false, depthWrite: false,
    vertexShader: `
      attribute vec3 aColor; attribute float aSize, aAlpha; varying vec3 vColor; varying float vA;
      void main(){
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = aAlpha > 0.0 ? aSize * (12.0 / max(-mv.z, 0.5)) : 0.0;
        vColor = aColor; vA = aAlpha;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      varying vec3 vColor; varying float vA;
      void main(){ float d = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.3, d) * vA; if (a < 0.004) discard; gl_FragColor = vec4(vColor, a); }`,
  });
}
function fxPoints(n, renderOrder) {
  const g = new THREE.BufferGeometry();
  const attr = (size) => new THREE.BufferAttribute(new Float32Array(n * size), size).setUsage(THREE.DynamicDrawUsage);
  g.setAttribute('position', attr(3));
  g.setAttribute('aColor', attr(3));
  g.setAttribute('aSize', attr(1));
  g.setAttribute('aAlpha', attr(1));
  const pts = new THREE.Points(g, fxPointsMaterial());
  pts.frustumCulled = false;
  pts.renderOrder = renderOrder;
  scene.add(pts);
  return g;
}

// Sparks: a trail behind the moving card, then the burst when it is consumed.
const TRAIL = 480;
const BURST = 900;
const relayFx = (() => {
  const n = TRAIL + BURST;
  const g = fxPoints(n, 4); // behind the card: the trail must not speckle its face
  const seeds = Array.from({ length: n }, () => [relayRand(), relayRand(), relayRand(), relayRand()]);
  const trailColors = [C.teal, C.blue, C.pink];
  const burstColors = [C.green, C.teal, C.pink];
  seeds.forEach((r, i) => {
    const c = (i < TRAIL ? trailColors : burstColors)[Math.floor(r[3] * 3)];
    g.attributes.aColor.array.set([c.r, c.g, c.b], i * 3);
  });
  return { g, seeds };
})();

function updateRelayFx(t) {
  const { g, seeds } = relayFx;
  const pos = g.attributes.position.array;
  const size = g.attributes.aSize.array;
  const alpha = g.attributes.aAlpha.array;
  const live = t > EV.relayCard && t < EV.relayConsumed + 2;
  for (let i = 0; i < TRAIL + BURST; i++) {
    alpha[i] = 0;
    if (!live) continue;
    const [r0, r1, r2, r3] = seeds[i];
    let x, y, depth;
    if (i < TRAIL) {
      const lag = r0 * 0.45;
      const tt = t - lag;
      const moving = (tt >= EV.relayCard && tt <= EV.relayCard + 0.85) || (tt >= EV.relayLaunch && tt <= EV.relayLand);
      if (!moving) continue;
      const [sx, sy, ss] = cardState(tt);
      x = sx + (r1 - 0.5) * CARD_PX * ss * 0.95;
      y = sy + (r2 - 0.5) * CARD_PX * ss * 0.6 + (r3 - 0.5) * 60 * lag;
      depth = CARD_D + (r3 - 0.5) * 0.8;
      alpha[i] = 0.85 * (1 - lag / 0.45) ** 1.5;
      size[i] = 1.5 + 4.5 * r3 * (1 - lag / 0.45);
    } else {
      // leave the card as the dissolve front reaches them, fly out, rise, fade
      const age = t - EV.relayConsumed - r3 * 0.6;
      if (age < 0 || age > 1.6) continue;
      const [ox, oy, os] = CARD_SLOT;
      const dx = (r0 - 0.5) * CARD_PX * os;
      const dy = (r1 - 0.5) * CARD_PX * os * 0.62;
      const len = Math.hypot(dx, dy) + 1e-3;
      const travel = ((80 + 420 * r2 * r2) * (1 - Math.exp(-3 * age))) / 3;
      x = ox + dx + (dx / len) * travel;
      y = oy + dy + (dy / len) * travel - 90 * age ** 1.3;
      depth = CARD_D - 2.5 * r2 * (1 - Math.exp(-2 * age));
      alpha[i] = Math.exp(-age * 2.4) * clamp(age / 0.05);
      size[i] = 2 + 4.5 * r1;
    }
    screenToWorld(x, y, depth, tmpFx);
    pos.set([tmpFx.x, tmpFx.y, tmpFx.z], i * 3);
  }
  g.attributes.position.needsUpdate = true;
  g.attributes.aSize.needsUpdate = true;
  g.attributes.aAlpha.needsUpdate = true;
}
const tmpFx = new THREE.Vector3();

// ------------------------------------------------------------------ rings (bisect, bus hub)

// A flat ring, cut into uSeg arcs that each fill uFill of their span and can be
// dashed; uRot turns the pattern, in turns. uGain above 1 thickens nothing, it only
// keeps the ring fully opaque; below 1 it fades it.
function ringMaterial() {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, side: THREE.DoubleSide,
    uniforms: { uColor: { value: C.teal.clone() }, uOpacity: { value: 0 }, uRot: { value: 0 }, uSeg: { value: 1 }, uFill: { value: 1 }, uDash: { value: 0 }, uGain: { value: 1 } },
    vertexShader: `varying vec2 vP; void main(){ vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `
      uniform vec3 uColor; uniform float uOpacity, uRot, uSeg, uFill, uDash, uGain; varying vec2 vP;
      void main(){
        float u = fract(atan(vP.y, vP.x) / 6.2831853 + uRot);
        float w = length(fwidth(vP)) / (6.2831853 * length(vP)); // one pixel, in turns
        float s = fract(u * uSeg);
        float arc = uFill >= 0.999 ? 1.0 : smoothstep(0.0, w * uSeg, s) * (1.0 - smoothstep(uFill - w * uSeg, uFill, s));
        float d = fract(u * uDash);
        float dash = uDash > 0.0 ? smoothstep(0.0, w * uDash, d) * (1.0 - smoothstep(0.55 - w * uDash, 0.55, d)) : 1.0;
        gl_FragColor = vec4(uColor, arc * dash * uOpacity * clamp(uGain, 0.0, 1.0));
      }`,
  });
}
function ringMesh(r, width, uniforms = {}) {
  const m = new THREE.Mesh(new THREE.RingGeometry(r - width / 2, r + width / 2, 256, 1), ringMaterial());
  for (const [name, v] of Object.entries(uniforms)) m.material.uniforms[name].value = v;
  m.renderOrder = 3;
  return m;
}

// ------------------------------------------------------------------ bisect: twelve commits in a row

const BIS = TL.bisect;
const BIS_N = BIS.commits.length;
const BIS_Y = stagePoint(0, 330, BIS_Z, 0.2).y;
const bisX = (i) => (i - (BIS_N - 1) / 2) * 0.95;
const bisGroup = new THREE.Group();
scene.add(bisGroup);
const bisNodes = BIS.commits.map((_, i) => {
  const m = new THREE.Mesh(new THREE.IcosahedronGeometry(0.2, 1), toon(C.paper, { emissive: C.paper.clone(), emissiveIntensity: 0 }));
  m.position.set(bisX(i), BIS_Y, BIS_Z);
  m.renderOrder = 2;
  inkOutline(m, 0.12);
  bisGroup.add(m);
  return m;
});
// What is known about each commit, and since when: both ends from the start, each
// tested commit at its step, and the commits its result implies a moment later.
const bisKnown = BIS.commits.map(() => ({ at: Infinity }));
bisKnown[0] = { at: EV.bisNodes, state: 'good' };
bisKnown[BIS_N - 1] = { at: EV.bisNodes, state: 'bad' };
// The range the first bad commit can still be in, narrowing after each step.
const BAND = [[EV.bisNodes, [1, BIS_N - 2]]];
{
  let [lo, hi] = [1, BIS_N - 2];
  for (const [idx, ev, state] of BIS.steps) {
    const at = EV[ev];
    bisKnown[idx] = { at, state };
    const [from, to] = state === 'bad' ? [idx + 1, BIS_N - 2] : [1, idx - 1];
    for (let j = from; j <= to; j++) if (bisKnown[j].at === Infinity) bisKnown[j] = { at: at + 0.2 + Math.abs(j - idx) * 0.06, state, implied: true };
    BAND.push([at + 0.1, [lo, hi]]);
    if (state === 'bad') hi = idx; else lo = idx + 1;
    BAND.push([at + 0.6, [lo, hi], 'power3.inOut']);
  }
}
const chain = new THREE.Mesh(new THREE.BoxGeometry(bisX(BIS_N - 1) - bisX(0), 0.03, 0.03), new THREE.MeshBasicMaterial({ color: C.ink.clone(), transparent: true, opacity: 0 }));
chain.position.set(0, BIS_Y, BIS_Z - 0.05);
const bandMat = new THREE.ShaderMaterial({
  transparent: true, depthWrite: false,
  uniforms: { uColor: { value: C.amber.clone() }, uOpacity: { value: 0 }, uSize: { value: new THREE.Vector2(1, 1) } },
  vertexShader: VERT_UV,
  fragmentShader: `
    uniform vec3 uColor; uniform float uOpacity; uniform vec2 uSize; varying vec2 vUv;
    void main(){
      vec2 p = vUv * uSize; vec2 q = min(p, uSize - p); // distance to the nearest edge, world units
      float edge = 1.0 - smoothstep(0.02, 0.035, min(q.x, q.y));
      gl_FragColor = vec4(uColor, (0.16 + edge * 0.84) * uOpacity);
    }`,
});
const band = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), bandMat);
band.position.set(0, BIS_Y, BIS_Z - 0.3);
const BEAM_H = 3.4;
const beamMat = new THREE.ShaderMaterial({
  transparent: true, depthWrite: false,
  uniforms: { uColor: { value: C.teal.clone() }, uOpacity: { value: 0 }, uReach: { value: 0 } },
  vertexShader: VERT_UV,
  fragmentShader: `
    uniform vec3 uColor; uniform float uOpacity, uReach; varying vec2 vUv;
    void main(){
      float on = 1.0 - smoothstep(uReach - 0.04, uReach, 1.0 - vUv.y); // grows down from the top
      float core = 1.0 - smoothstep(0.08, 0.12, abs(vUv.x - 0.5));
      gl_FragColor = vec4(uColor, core * on * (0.35 + 0.65 * (1.0 - vUv.y)) * uOpacity);
    }`,
});
const beam = new THREE.Mesh(new THREE.PlaneGeometry(0.34, BEAM_H), beamMat);
const shock = ringMesh(0.32, 0.035);
bisGroup.add(chain, band, beam, shock);

// ------------------------------------------------------------------ agent bus: the daemon between two sessions

const HUB = stagePoint(960, 360, BUS_Z);
const HUB_SHIELD = 0.8;
const PX_PER_UNIT = H / (2 * HALF_H); // at a parked stage
const SHIELD_PX = HUB_SHIELD * PX_PER_UNIT;
const hub = new THREE.Group();
hub.position.copy(HUB);
scene.add(hub);
const hubCore = new THREE.Mesh(new THREE.SphereGeometry(0.21, 32, 16), toon(C.teal));
inkOutline(hubCore, 0.1);
const hubOrbits = [
  [ringMesh(0.44, 0.03, { uSeg: 3, uFill: 0.7 }), [-1.2, 0, 0], 1.4, 0.25],
  [ringMesh(0.58, 0.016, { uDash: 40 }), [0, 0, 0], 0.9, -0.12],
  [ringMesh(0.5, 0.02, { uSeg: 2, uFill: 0.4 }), [-1.2, 0.9, 0], 1.2, 0.4],
].map(([m, rot, level, speed]) => { m.rotation.set(...rot); return { m, level, speed }; });
const shieldMat = new THREE.ShaderMaterial({
  transparent: true, depthWrite: false,
  uniforms: { uColor: { value: C.teal.clone() }, uOpacity: { value: 0 } },
  vertexShader: `varying vec3 vN; varying vec3 vV; void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.0); vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }`,
  fragmentShader: `
    uniform vec3 uColor; uniform float uOpacity; varying vec3 vN; varying vec3 vV;
    void main(){ float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 3.0); gl_FragColor = vec4(uColor, (0.1 + 0.9 * f) * uOpacity); }`,
});
const shield = new THREE.Mesh(new THREE.SphereGeometry(HUB_SHIELD, 48, 24), shieldMat);
hub.add(hubCore, shield, ...hubOrbits.map((o) => o.m));
// Packets are comets drawn in screen pixels, like the relay card's sparks.
const PKT_TRAIL = 44;
const PKT_MAX = 16;
const pktFx = fxPoints(PKT_MAX * PKT_TRAIL, 6);

// ------------------------------------------------------------------ evidence: two bars

const EV_BASE = stagePoint(0, 860, EVI_Z).y;
const EV_FULL = stagePoint(0, 300, EVI_Z).y - EV_BASE;
const barGeo = new THREE.BoxGeometry(0.9, 1, 0.5).translate(0, 0.5, 0);
function barMaterial(color) {
  return new THREE.ShaderMaterial({
    transparent: true,
    uniforms: { uColor: { value: color }, uOpacity: { value: 0 }, uH: { value: 1 }, uGain: { value: 1 } },
    vertexShader: `varying vec3 vN; varying vec3 vP; void main(){ vN = normal; vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `
      uniform vec3 uColor; uniform float uOpacity, uH, uGain; varying vec3 vN; varying vec3 vP;
      void main(){
        float shade = vN.y > 0.5 ? 1.0 : vN.x > 0.5 ? 0.72 : vN.x < -0.5 ? 0.82 : 0.9;
        vec3 col = mix(uColor * shade, vec3(1.0), clamp(uGain - 1.0, 0.0, 1.0) * 0.35);
        gl_FragColor = vec4(col, uOpacity);
      }`,
  });
}
const bars = [['bare', 1260, lin('#b4bfcd'), 'evBare', 'bare agent'], ['luciazero', 1580, C.teal, 'evLz', 'with Luciazero']].map(([key, sx, color, ev, label]) => {
  const [n, d] = TL.evidence[key];
  const x = stagePoint(sx, 540, EVI_Z).x;
  const mesh = new THREE.Mesh(barGeo, barMaterial(color));
  mesh.position.set(x, EV_BASE, EVI_Z);
  const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(0.9, EV_FULL, 0.5)), new THREE.LineBasicMaterial({ color: C.ink, transparent: true, opacity: 0 }));
  frame.position.set(x, EV_BASE + EV_FULL / 2, EVI_Z);
  scene.add(mesh, frame);
  return { key, x, mesh, frame, n, d, frac: n / d, at: EV[ev], label };
});
// +32pp: the bare bar's level carried across, and the gap above it lit on the Luciazero bar.
const EV_LEVEL = EV_BASE + bars[0].frac * EV_FULL;
const gapMat = new THREE.MeshBasicMaterial({ color: C.deep.clone(), transparent: true, opacity: 0, depthWrite: false });
const gap = new THREE.Mesh(new THREE.PlaneGeometry(0.07, 1).translate(0, 0.5, 0), gapMat);
gap.position.set(bars[1].x + 0.62, EV_LEVEL, EVI_Z + 0.25);
const levelMat = new THREE.ShaderMaterial({
  transparent: true, depthWrite: false,
  uniforms: { uColor: { value: C.amber.clone() }, uOpacity: { value: 0 } },
  vertexShader: VERT_UV,
  fragmentShader: `uniform vec3 uColor; uniform float uOpacity; varying vec2 vUv; void main(){ gl_FragColor = vec4(uColor, step(0.45, fract(vUv.x * 30.0)) * uOpacity); }`,
});
const level = new THREE.Mesh(new THREE.PlaneGeometry(1, 0.026), levelMat);
level.scale.x = bars[1].x + 0.62 - (bars[0].x - 0.45);
level.position.set((bars[0].x - 0.45 + bars[1].x + 0.62) / 2, EV_LEVEL, EVI_Z + 0.25);
scene.add(gap, level);

// ------------------------------------------------------------------ camera path

// Each later stage is watched from 12 units in front, looking straight down the corridor.
const DIVE_START = EV.caught1 + 0.2;
const DIVE_END = EV.cta;
const park = (z, back = 0, x = 0, y = 0.15) => [x, y, z + 12 - back];
const CAM_POS = [
  [0, [0, 0.35, 13.2]],
  [EV.shatter, [0, 0.1, 12], 'sine.inOut'],
  [EV.fail1, [0, 0, 12], 'sine.out'],
  [EV.vortex, [0.7, -0.25, 10.6], 'sine.inOut'],
  [EV.drop, [0, 0, 12.6], 'power2.in'],
  [EV.plan, [0.3, 0, 11.3], 'sine.out'],
  [EV.plan + 1.4, [0, 1.9, 11.4], 'power3.inOut'],
  [EV.quote, [0, 2.0, 11.0], 'sine.inOut'],
  [EV.quote + 1.2, [0, 2.9, 12.3], 'power2.inOut'],
  [DIVE_START, [0, 2.6, 12.0], 'sine.inOut'],
  [EV.caught1 + 1.4, park(GATE_Z), 'power3.inOut'],
  [EV.caught2, park(GATE_Z, 0.25, 0.1)],
  [EV.caught3, park(GATE_Z, 0.5, -0.1)],
  [EV.exact, park(GATE_Z, 0.2, 0.08)],
  [EV.probe, park(GATE_Z, 0.5, -0.08)],
  [EV.bisect + 0.2, park(GATE_Z, 0.7)],
  [EV.bisect + 1.6, park(BIS_Z, 0, 0, 0.2), 'power3.inOut'],
  [EV.bisOut, park(BIS_Z, 0.4, -0.15, 0.2)],
  [EV.relay + 1.4, park(RELAY_Z), 'power3.inOut'],
  [EV.relayOut, park(RELAY_Z, 0.3, 0.12, 0.1)],
  [EV.bus + 1.6, park(BUS_Z), 'power3.inOut'],
  [EV.busOut, park(BUS_Z, 0.2, 0.08)],
  [EV.bsOut, park(BUS_Z, 0.4, -0.08)],
  [EV.evidence + 1.6, park(EVI_Z), 'power3.inOut'],
  [EV.evOut, park(EVI_Z, 0.3, 0.1)],
  [EV.sfOut, park(EVI_Z, 0.5, -0.1)],
  [EV.chips + 0.3, [0, 0.35, STAGE5_Z + 10.5], 'power3.inOut'],
  [EV.dive, [0.15, 0.25, STAGE5_Z + 10.0], 'sine.inOut'],
  [DIVE_END, [0, 0, STAGE6_Z + 12.6], 'power3.inOut'],
  [TL.duration, [0.25, 0.05, STAGE6_Z + 11.4], 'sine.out'],
];
const CAM_TGT = [
  [0, [0, 0, 0]],
  [EV.plan, [0, 0, 0]],
  [EV.plan + 1.4, [0, -1.0, 0], 'power3.inOut'],
  [EV.quote, [0, -1.0, 0]],
  [EV.quote + 1.2, [0, 1.2, 0], 'power2.inOut'],
];
const SHAKE = [
  [EV.shatter, 0.13, 0.35], [EV.drop, 0.05, 0.3], [EV.verifyRed, 0.07, 0.35],
  [EV.fail1, 0.04, 0.2], [EV.fail2, 0.04, 0.2], [EV.fail3, 0.04, 0.2],
  [EV.c1Red, 0.05, 0.3], [EV.c1Gate, 0.08, 0.35], [EV.c5Fail, 0.03, 0.25],
  [EV.bis1, 0.03, 0.25], [EV.bisFound, 0.07, 0.35],
  [EV.bsDown, 0.04, 0.3], [EV.bsUp, 0.06, 0.35], [EV.bsRef1, 0.03, 0.2], [EV.bsRef2, 0.03, 0.2], [EV.bsRef3, 0.03, 0.2],
  [EV.evDiff, 0.03, 0.3], [EV.final, 0.05, 0.3],
];
function placeCamera(t) {
  const p = k(t, CAM_POS);
  const still = k(t, CAM_TGT);
  const ahead = [p[0] * 0.8, p[1] * 0.2, p[2] - 12];
  const w = k(t, [[DIVE_START, 0], [DIVE_START + 1.4, 1, 'sine.inOut']]);
  const tg = still.map((v, i) => lerp(v, ahead[i], w));
  const shake = pulses(t, SHAKE);
  const sx = Math.sin(t * 71.3) * 0.6 + Math.sin(t * 43.1) * 0.4;
  const sy = Math.sin(t * 63.7 + 1.3) * 0.6 + Math.sin(t * 37.9) * 0.4;
  camera.position.set(p[0] + sx * shake, p[1] + sy * shake, p[2]);
  camera.up.set(0, 1, 0);
  camera.lookAt(tg[0], tg[1], tg[2]);
  const roll = k(t, [[EV.fail1, 0], [EV.vortex, 0.025], [EV.drop, -0.06, 'power2.in'], [EV.drop + 1, 0, 'power2.out']]);
  camera.rotateZ(roll);
  camera.updateMatrixWorld();
}

// ------------------------------------------------------------------ DOM + GSAP

await Promise.all(['400 30px "IBM Plex Mono"', '500 30px "IBM Plex Mono"', '600 30px "IBM Plex Mono"', '500 30px "M PLUS Rounded 1c"', '700 30px "M PLUS Rounded 1c"', '800 30px "M PLUS Rounded 1c"'].map((f) => document.fonts.load(f)));
await document.fonts.ready;

// A wall of chips at STAGE5_Z, read row by row; the 13th sits bottom right, clear of the headline.
const chipSlots = [];
for (let r = 0; r < 4; r++) for (let c = 0; c < 3; c++) chipSlots.push([(c - 1) * 2.95, 1.62 - r * 0.76]);
chipSlots.push([2.95, -1.42]);
const chips = TL.skills.map(([name, desc], i) => {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 0.65), new THREE.MeshBasicMaterial({ map: chipTexture(name, desc), transparent: true, depthWrite: false, opacity: 0 }));
  const [x, y] = chipSlots[i];
  const home = new THREE.Vector3(x, y + 0.35, STAGE5_Z + (rand() - 0.5) * 0.6);
  const out = (x === 0 ? new THREE.Vector3(0, Math.sign(y + 0.05), 0) : new THREE.Vector3(Math.sign(x) * 1.6, y + 0.05, 0)).normalize();
  mesh.userData = { tick: EV.chips + i * EV.chipStep, home, out, spin: (rand() - 0.5) * 2 };
  scene.add(mesh);
  return mesh;
});

cardMat.uniforms.uText.value = relayCardTexture();

const $ = (s) => document.querySelector(s);
const make = (tag, className, text) => Object.assign(document.createElement(tag), { className, ...(text !== undefined && { textContent: text }) });

// Terminal panels, built from timeline.json so music.py can tick on the same keystrokes.
const termLines = [];
const termStatus = [];
const termItems = {};
for (const [id, spec] of Object.entries(TL.terms)) {
  if (id.startsWith('_')) continue;
  const panel = $(`#${id}`);
  const body = panel.querySelector('.body');
  termItems[id] = spec.lines.map((ln, i, lines) => {
    const kind = 'cmd' in ln ? 'cmd' : 'box' in ln ? 'box' : 'out';
    const el = make('div', `ln ${kind} ${ln.cls ?? ''}`);
    const item = { el, kind, at: cue(ln.at), next: i + 1 < lines.length ? cue(lines[i + 1].at) : Infinity, cps: spec.cps };
    if (kind === 'cmd') {
      item.chars = [...ln.cmd];
      item.tx = make('span', 'tx');
      item.caret = make('span', 'caret', '▌');
      el.append(make('span', 'ps', ln.ps ?? '$'), ' ', item.tx, item.caret);
    } else if (kind === 'box') {
      el.append(make('b', '', ln.title), ln.box);
    } else {
      el.textContent = ln.out;
    }
    if (ln.note) {
      item.pill = make('span', 'pill', ln.note);
      item.pillAt = item.at + (item.chars ? item.chars.length / spec.cps : 0) + 0.25;
      el.append(item.pill);
    }
    body.append(el);
    termLines.push(item);
    return item;
  });
  if (spec.status) {
    const s = { sl: make('div', 'sl'), st: make('span', 'st'), pill: make('span', 'pill') };
    s.sl.append(s.st, s.pill);
    panel.append(s.sl);
    s.keys = spec.status.map(([at, text, cls, note]) => ({ at: cue(at), text, cls, note }));
    termStatus.push(s);
  }
}
// Vertical center of a panel's line in stage pixels (the layout is fixed once the fonts load).
const lineY = (id, i) => { const el = termItems[id][i].el; return $(`#${id}`).offsetTop + el.offsetTop + el.offsetHeight / 2; };

// caught 03: the lessons ledger
const ledgerList = $('#ledger .list');
const ledgerItems = TL.lessons.titles.map((title, i) => {
  const el = make('div', 'item');
  el.append(make('i', '', '##'), make('span', 't', title));
  if (i === TL.lessons.hit) el.append(make('span', 'h1', 'H1'));
  ledgerList.append(el);
  return el;
});
const LEDGER_ROW = 44;
const LEDGER_VIEW = 388;

// bisect: a label under each commit, the two known ends marked above
const shaEls = BIS.commits.map((sha) => {
  const pos = make('div', 'sha-pos');
  const el = make('div', 'sha', sha);
  pos.append(el);
  $('#shas').append(pos);
  return { pos, el };
});
shaEls[0].pos.append(make('div', 'sha end', 'GOOD'));
shaEls[BIS_N - 1].pos.append(make('div', 'sha end', 'BAD · HEAD'));

// evidence: a count above each bar, its name below
const evLabels = bars.map((b) => {
  const top = make('div', 'evl-pos');
  const box = make('div', 'evl-top');
  const L = { top, p: make('div', 'p'), f: make('div', 'f'), bot: make('div', 'evl-pos') };
  box.append(L.p, L.f);
  top.append(box);
  L.bot.append(make('div', 'evl-bot', b.label));
  if (b.key === 'luciazero') { L.p.style.color = '#1b8fc0'; L.bot.firstChild.style.color = '#1b8fc0'; }
  $('#evl').append(top, L.bot);
  return L;
});

// bus packets: comets in screen pixels. An end is a point, 'hub' (the daemon, where
// the camera sees it this frame) or a function of the hub's position.
const WIN_A = [790, 340];
const WIN_B = [1130, 340];
const IMPL = [2000, 120]; // codex-implementer has no window here; its packets leave and return past the top right
const ORBIT_R = 150;
const orbitAt = (h, dt) => { const a = Math.PI + dt * 3.2; return [h[0] + Math.cos(a) * ORBIT_R, h[1] + Math.sin(a) * ORBIT_R * 0.42]; };
const watchDrop = (n) => (h) => [h[0], lineY('tWatch', n + 1)];
const hop = (at, from, to, color) => [
  { color, legs: [{ t0: at - 0.75, t1: at - 0.35, from, to: 'hub', bend: 50 }, { t0: at - 0.35, t1: at + 0.05, from: 'hub', to, bend: 50 }] },
  { color, legs: [{ t0: at - 0.35, t1: at, from: 'hub', to: null }] },
];
const PACKETS = [
  ...hop(EV.pkt1, WIN_A, WIN_B, C.blue),
  ...hop(EV.pkt2, WIN_B, WIN_A, C.red),
  ...hop(EV.pkt3, WIN_A, IMPL, C.amber),
  ...hop(EV.pkt4, IMPL, WIN_B, C.amber),
  ...hop(EV.pkt5, WIN_B, WIN_A, C.green),
  // busSafe: a delivery queued while the daemon is down, carried across the restart
  { color: C.amber, legs: [
    { t0: EV.bsDown - 0.6, t1: EV.bsDown, from: [-60, 300], to: (h) => orbitAt(h, 0), bend: 30 },
    { t0: EV.bsDown, t1: EV.bsUp, orbit: true },
    { t0: EV.bsUp, t1: EV.bsUp + 0.5, from: (h) => orbitAt(h, EV.bsUp - EV.bsDown), to: [1990, 330], ease: 'power2.in' },
  ] },
  // three refusals bounce off the shield
  ...[EV.bsRef1, EV.bsRef2, EV.bsRef3].map((at, i) => {
    const hit = (h) => [h[0] - SHIELD_PX * Math.cos((i - 1) * 0.35), h[1] + SHIELD_PX * Math.sin((i - 1) * 0.35)];
    return { color: C.red, legs: [
      { t0: at - 0.45, t1: at, from: [-60, 250 + i * 70], to: hit, ease: 'power1.in', bend: 20 },
      { t0: at, t1: at + 0.6, from: hit, to: [-80, 470 + i * 50], ease: 'power2.out', bend: -40 },
    ] };
  }),
];
PACKETS.forEach((p, n) => { if (p.legs[0].to === null) p.legs[0].to = watchDrop(Math.floor(n / 2) + 1); }); // hop k lands on watch line k
{
  const col = pktFx.attributes.aColor.array;
  PACKETS.forEach((p, pi) => { for (let j = 0; j < PKT_TRAIL; j++) col.set(arr(p.color), (pi * PKT_TRAIL + j) * 3); });
}
function packetAt(p, tt, h) {
  for (const leg of p.legs) {
    if (tt < leg.t0 || tt > leg.t1) continue;
    if (leg.orbit) return orbitAt(h, tt - leg.t0);
    const pt = (v) => (v === 'hub' ? h : typeof v === 'function' ? v(h) : v);
    const a = pt(leg.from);
    const b = pt(leg.to);
    const u = ease(leg.ease ?? 'power1.inOut')((tt - leg.t0) / (leg.t1 - leg.t0));
    const v = 1 - u;
    const mx = (a[0] + b[0]) / 2;
    const my = (a[1] + b[1]) / 2 - (leg.bend ?? 0);
    return [v * v * a[0] + 2 * v * u * mx + u * u * b[0], v * v * a[1] + 2 * v * u * my + u * u * b[1]];
  }
  return null;
}
function updatePackets(t, h) {
  const pos = pktFx.attributes.position.array;
  const size = pktFx.attributes.aSize.array;
  const alpha = pktFx.attributes.aAlpha.array;
  alpha.fill(0);
  PACKETS.forEach((p, pi) => {
    for (let j = 0; j < PKT_TRAIL; j++) {
      const xy = packetAt(p, t - j * 0.012, h);
      if (!xy) continue;
      const i = pi * PKT_TRAIL + j;
      screenToWorld(xy[0], xy[1], 12, tmpFx);
      pos.set([tmpFx.x, tmpFx.y, tmpFx.z], i * 3);
      const f = 1 - j / PKT_TRAIL;
      alpha[i] = f ** 1.4;
      size[i] = j === 0 ? 16 : 2 + 6 * f;
    }
  });
  pktFx.attributes.position.needsUpdate = true;
  pktFx.attributes.aSize.needsUpdate = true;
  pktFx.attributes.aAlpha.needsUpdate = true;
}

const tl = gsap.timeline({ paused: true, defaults: { immediateRender: false, ease: 'power3.out' } });
const IN = { autoAlpha: 1, x: 0, y: 0, scale: 1, filter: 'blur(0px)' };
function enter(el, at, from, dur = 0.6, extra = {}) {
  // A fromTo with immediateRender: false renders nothing before it starts, so a
  // child of a layer that appeared earlier would show at full opacity until then.
  tl.set(el, { autoAlpha: 0 }, 0);
  tl.fromTo(el, { autoAlpha: 0, x: 0, y: 0, scale: 1, filter: 'blur(0px)', ...from }, { ...IN, duration: dur, ...extra }, at);
}
function leave(el, at, to, dur = 0.35, fromState = {}) {
  tl.fromTo(el, { ...IN, ...fromState }, { autoAlpha: 0, duration: dur, ease: 'power2.in', ...to }, at);
}
const appear = (el, at) => tl.fromTo(el, { autoAlpha: 1 }, { autoAlpha: 1, duration: 0.01 }, at);
// Opacity only, for elements whose CSS transform centers them on a projected point.
function fadeIn(el, at, dur = 0.3) {
  tl.set(el, { autoAlpha: 0 }, 0);
  tl.fromTo(el, { autoAlpha: 0 }, { autoAlpha: 1, duration: dur, ease: 'power1.out' }, at);
}
const fadeOut = (el, at, dur = 0.3) => tl.fromTo(el, { autoAlpha: 1 }, { autoAlpha: 0, duration: dur, ease: 'power1.in' }, at);
const panelIn = (el, at, from = { y: 40 }) => enter(el, at, { ...from, filter: 'blur(8px)' }, 0.55);
const out = (els, at) => els.forEach((el, i) => leave(el, at + i * 0.04, { y: -40, filter: 'blur(12px)' }, 0.35));
function charsIn(sel, at) {
  appear(sel, at);
  new SplitText(sel, { type: 'chars' }).chars.forEach((ch, i) => enter(ch, at + i * 0.03, { y: 80, filter: 'blur(8px)' }, 0.55, { ease: 'power4.out' }));
}
function wordsIn(sel, at, step = 0.06) {
  new SplitText(sel, { type: 'words' }).words.forEach((w, i) => enter(w, at + i * step, { y: 40, filter: 'blur(12px)' }, 0.55));
}

// 1 · false green
enter('#term', EV.prompt, { y: 40, scale: 0.96 }, 0.7);
tl.fromTo('#term', { y: 0, scale: 1 }, { y: -292, scale: 0.8, duration: 0.85, ease: 'power3.inOut' }, EV.checkRise);
enter('#zero', EV.zeroRun, { x: -24 }, 0.3);
appear('#question', EV.question);
const qWords = new SplitText('#question', { type: 'words' }).words;
qWords.forEach((w, i) => enter(w, EV.question + i * EV.qStep, { y: 34, filter: 'blur(12px)' }, 0.45));
leave('#term', EV.shatter, { scale: 0.95, filter: 'blur(18px)' }, 0.3, { y: -292, scale: 0.8 });
leave('#question', EV.shatter, { scale: 1.12, filter: 'blur(20px)' }, 0.3);

// 2 · failures
['#fail1', '#fail2', '#fail3'].forEach((id, i) => {
  const at = EV[`fail${i + 1}`];
  appear(id, at);
  enter(`${id} .tag`, at, { x: -40 }, 0.4);
  enter(`${id} h2`, at, { scale: 1.22, filter: 'blur(16px)' }, 0.38, { ease: 'power4.out' });
  enter(`${id} p`, at + 0.45, { y: 22 }, 0.5);
  leave(id, at + 1.72, { y: -64, filter: 'blur(10px)' }, 0.25);
});

// 3 · Lucia
appear('#title', EV.title);
const titleChars = new SplitText('#title', { type: 'chars' }).chars;
titleChars.forEach((ch, i) => enter(ch, EV.title + i * 0.045, { y: 120, rotationX: -75, filter: 'blur(8px)' }, 0.75, { rotationX: 0, ease: 'power4.out' }));
appear('#tagline', EV.tagline);
const tagWords = new SplitText('#tagline', { type: 'words' }).words;
tagWords.forEach((w, i) => enter(w, EV.tagline + i * 0.07, { y: 28, filter: 'blur(10px)' }, 0.5));
tl.fromTo('#subline', { autoAlpha: 1, clipPath: 'inset(0 100% 0 0)' }, { autoAlpha: 1, clipPath: 'inset(0 0% 0 0)', duration: 0.9, ease: 'steps(28)' }, EV.subline);
['#title', '#tagline', '#subline'].forEach((id, i) => leave(id, EV.plan - 0.4 + i * 0.05, { x: 90, filter: 'blur(12px)' }, 0.35));

// 4 · loop
['plan', 'change', 'verify', 'fix'].forEach((n, i) => {
  tl.fromTo(`#nl-${n} .node-label`, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.5 }, EV.plan + 0.9 + i * 0.12);
  tl.fromTo(`#nl-${n} .node-label`, { autoAlpha: 1 }, { autoAlpha: 0, duration: 0.3 }, EV.quote - 0.35);
});
enter('#status', EV.change, { y: 40 }, 0.5);
leave('#status', EV.quote - 0.35, { y: 30 }, 0.3);
appear('#quote', EV.quote);
if (!LOOP_ON) $('#quote').style.display = 'none';
const quoteWords = new SplitText('#quote h2', { type: 'words' }).words;
quoteWords.forEach((w, i) => enter(w, EV.quote + i * 0.06, { y: 40, filter: 'blur(12px)' }, 0.55));
enter('#quote p', EV.quote + 0.8, { y: 16 }, 0.5);
leave('#quote', EV.caught1 + 0.1, { y: -50, filter: 'blur(14px)' }, 0.4);

// 5-9 · caught: each failure from scene 2 comes back, and this time it is caught
function caughtHead(id, at) {
  appear(id, at);
  enter(`${id} .tag`, at, { x: -40 }, 0.4);
  enter(`${id} h2`, at + 0.08, { x: -30, filter: 'blur(14px)' }, 0.45, { ease: 'power4.out' });
}
caughtHead('#c1h', EV.c1Head);
panelIn('#t1', EV.c1Term);
out(['#c1h', '#t1'], EV.c1Out);

caughtHead('#c2h', EV.c2Head);
panelIn('#t2', EV.c2Panel);
enter('#t2cap', EV.c2Panel + 0.6, { y: 12 }, 0.4);
enter('#rule9', EV.c2Rule, { y: 30, filter: 'blur(12px)' }, 0.55);
out(['#c2h', '#t2', '#t2cap', '#rule9'], EV.c2Out);

caughtHead('#c3h', EV.c3Head);
panelIn('#ledger', EV.c3List);
fadeIn('#count27 .in', EV.c3Count, 0.01);
enter('#count27 .num', EV.c3Count, { scale: 0.6, filter: 'blur(14px)' }, 0.5);
enter('#count27 .lbl', EV.c3Count + 0.3, { y: 12 }, 0.4);
enter('#c3cap1', EV.c3Count + 1.0, { y: 20, filter: 'blur(8px)' }, 0.5);
enter('#c3cap2', EV.c3H1 + 0.4, { y: 20, filter: 'blur(8px)' }, 0.5);
out(['#c3h', '#ledger', '#c3cap1', '#c3cap2'], EV.c3Out);
fadeOut('#count27 .in', EV.c3Out, 0.35);

caughtHead('#c4h', EV.c4Head);
panelIn('#t4a', EV.c4A, { x: -50 });
panelIn('#t4b', EV.c4B, { x: -50 });
panelIn('#t4c', EV.c4Hostile, { y: 30 });
out(['#c4h', '#t4a', '#t4b', '#t4c'], EV.c4Out);

caughtHead('#c5h', EV.c5Head);
panelIn('#t5', EV.c5Term);
out(['#c5h', '#t5'], EV.c5Out);

// 10 · bisect
charsIn('#bisHead .n', EV.bisHead);
appear('#bisHead', EV.bisHead);
enter('#bisHead .d', EV.bisHead + 0.4, { y: 22, filter: 'blur(8px)' }, 0.5);
panelIn('#tBis', EV.bisTerm);
shaEls.forEach(({ pos }, i) => { fadeIn(pos, EV.bisNodes + 0.15 + i * 0.06); fadeOut(pos, EV.bisOut); });
appear('#bisFoundBox', EV.bisFound + 0.25);
['.k', '.v', '.m'].forEach((c, i) => enter(`#bisFoundBox ${c}`, EV.bisFound + 0.25 + i * 0.12, { y: 30, filter: 'blur(10px)' }, 0.5));
out(['#bisHead', '#tBis', '#bisFoundBox'], EV.bisOut);

// 11 · relay
charsIn('#relayHead .n', EV.relayHead);
appear('#relayHead', EV.relayHead);
enter('#relayHead .d', EV.relayHead + 0.45, { y: 22, filter: 'blur(8px)' }, 0.5);
enter('#relayA', EV.relayA, { x: -60, filter: 'blur(8px)' }, 0.5);
enter('#relayB', EV.relayB, { x: 60, filter: 'blur(8px)' }, 0.5);
appear('#relayFoot', EV.relayFooter);
document.querySelectorAll('#relayFoot .x span').forEach((el, i) => { // new session, new agent, new machine
  enter(el, EV.relayFooter + 0.25 * i, { y: 18, scale: 0.92, filter: 'blur(6px)' }, 0.4, { ease: 'back.out(1.6)' });
});
enter('#relayFoot .d', EV.relayFooter + 0.9, { y: 16 }, 0.45);
out(['#relayHead', '#relayA', '#relayB', '#relayFoot'], EV.relayOut);

// 12-13 · agent bus
appear('#busHead', EV.busHead);
enter('#busHead .n', EV.busHead, { y: 60, filter: 'blur(10px)' }, 0.55, { ease: 'power4.out' });
enter('#busHead .d', EV.busHead + 0.4, { y: 22, filter: 'blur(8px)' }, 0.5);
panelIn('#tBusA', EV.busA, { x: -60 });
panelIn('#tBusB', EV.busB, { x: 60 });
panelIn('#tWatch', EV.busWatch);
// the story in four plain steps, each landing as its packet leaves; earlier steps
// stay on screen, dimmed, so the whole round trip can be read before the scene ends
const STEPS = [EV.pkt1, EV.pkt2, EV.pkt3, EV.pkt5];
document.querySelectorAll('#hubLabel .step').forEach((el, i) => {
  enter(el, STEPS[i] - 0.8, { y: 18, scale: 0.92, filter: 'blur(6px)' }, 0.4, { ease: 'back.out(1.6)' });
  if (STEPS[i + 1]) tl.fromTo(el, { opacity: 1 }, { opacity: 0.5, duration: 0.3, ease: 'power1.out' }, STEPS[i + 1] - 0.8);
});
fadeOut('#hubLabel .steps', EV.busOut, 0.35);
enter('#busFoot', EV.busFoot, { y: 20, filter: 'blur(8px)' }, 0.5);
out(['#busHead', '#tBusA', '#tBusB', '#tWatch', '#busFoot'], EV.busOut);
appear('#bsHead', EV.bsHead);
wordsIn('#bsHead h2', EV.bsHead, 0.05);
panelIn('#tLog', EV.bsHead + 0.35);
fadeIn('#hubLabel .in', EV.bsHead + 0.3, 0.4);
out(['#bsHead', '#tLog'], EV.bsOut);
fadeOut('#hubLabel .in', EV.bsOut, 0.35);

// 14 · evidence
appear('#evHead', EV.evHead);
wordsIn('#evHead h2', EV.evHead, 0.07);
enter('#evHead p', EV.evHead + 0.5, { y: 16 }, 0.5);
evLabels.forEach((L, i) => {
  fadeIn(L.top, bars[i].at, 0.25);
  fadeIn(L.bot, EV.evHead + 0.8 + i * 0.1, 0.4);
  fadeOut(L.top, EV.evOut);
  fadeOut(L.bot, EV.evOut);
});
appear('#evDiff', EV.evDiff);
enter('#evDiff .v', EV.evDiff, { scale: 0.7, filter: 'blur(16px)', transformOrigin: '0% 60%' }, 0.5, { ease: 'back.out(1.6)' });
enter('#evDiff .l', EV.evDiff + 0.3, { y: 16 }, 0.45);
enter('#evCaveat', EV.evCaveat, { y: 16 }, 0.5);
out(['#evHead', '#evDiff', '#evCaveat'], EV.evOut);

// 15 · safe to try
appear('#sfHead', EV.sfHead);
enter('#sfHead h2', EV.sfHead, { x: -60, filter: 'blur(12px)' }, 0.55);
appear('#sfList', EV.sfItems);
if (CUT?.safeItems) document.querySelectorAll('#sfList .sf').forEach((el, i) => { if (i >= CUT.safeItems) el.remove(); });
document.querySelectorAll('#sfList .sf').forEach((el, i) => enter(el, EV.sfItems + i * EV.sfStep, { x: -40, filter: 'blur(8px)' }, 0.45));
out(['#sfHead', '#sfList'], EV.sfOut);

// 16 · skills
appear('#skillsHead', EV.skills + 0.3);
enter('#skillsHead .n', EV.skills + 0.3, { x: -60, filter: 'blur(12px)' }, 0.55);
enter('#skillsHead .d', EV.skills + 0.75, { x: -40, filter: 'blur(10px)' }, 0.55);
enter('#agents', EV.agents, { y: 24 }, 0.5);
leave('#skillsHead', EV.dive + 0.25, { x: -60, filter: 'blur(12px)' }, 0.35);
leave('#agents', EV.dive + 0.25, { x: -60, filter: 'blur(12px)' }, 0.35);

// 17 · call to action
appear('#cta', EV.cta + 0.3);
const ctaWord = new SplitText('#cta .word', { type: 'chars' }).chars;
appear('#cta .word', EV.cta + 0.3);
ctaWord.forEach((ch, i) => enter(ch, EV.cta + 0.3 + i * 0.04, { y: 90, filter: 'blur(8px)' }, 0.6, { ease: 'power4.out' }));
enter('#cta .tag', EV.cta + 0.95, { y: 24, filter: 'blur(8px)' }, 0.5);
enter('#cta .install', EV.cta + 1.35, { y: 30 }, 0.55);
enter('#cta .first', EV.cta + 2.2, { y: 20, filter: 'blur(8px)' }, 0.5);
enter('#cta .more', EV.cta + 2.9, { y: 16 }, 0.45);
enter('#cta .url', EV.cta + 3.3, { y: 20 }, 0.5);
enter('#cta .try', EV.final + 1.0, { scale: 0.6, filter: 'blur(8px)' }, 0.5, { ease: 'back.out(2)' });
tl.fromTo('#cta .word', { textShadow: '0 6px 0 rgba(60,200,236,0.35)' }, { textShadow: '0 14px 0 rgba(60,200,236,0.7)', y: -8, duration: 0.2, ease: 'power2.out' }, EV.final);
tl.fromTo('#cta .word', { textShadow: '0 14px 0 rgba(60,200,236,0.7)', y: -8 }, { textShadow: '0 6px 0 rgba(60,200,236,0.35)', y: 0, duration: 0.9, ease: 'bounce.out' }, EV.final + 0.2);
tl.set({}, {}, TL.duration);

// ------------------------------------------------------------------ per-frame state

const typedEl = $('#typed');
const caretEl = $('#caret');
const zeroEl = $('#zero');
const exitEl = $('#exit');
const slEl = $('#sl');
const flashEl = $('#flash');
const fadeEl = $('#fade');
const bubbleEl = $('#bubble');
const bubbleText = $('#bubble .t');
const stampEl = $('#stamp');
const labelPos = Object.fromEntries(Object.keys(NODE_ANG).map((n) => [n, $(`#nl-${n}`)]));
const labelName = Object.fromEntries(Object.keys(NODE_ANG).map((n) => [n, $(`#nl-${n} b`)]));
const tmp = new THREE.Vector3();
const pinV = new THREE.Vector3();
// Place a zero-size DOM anchor on the screen point of a world position.
function pin(el, v) {
  pinV.copy(v).project(camera);
  el.style.transform = `translate(${(((pinV.x + 1) / 2) * W).toFixed(1)}px, ${(((1 - pinV.y) / 2) * H).toFixed(1)}px)`;
}
const TONE = { ok: '31,168,118', warn: '242,169,59', bad: '224,69,107' };

// Comet angle on the ring: dwell on a node, travel on the bar's last beats.
const HEAD = [
  [EV.plan, NODE_ANG.plan],
  [EV.change - 0.8, NODE_ANG.plan], [EV.change, NODE_ANG.change, 'power2.inOut'],
  [EV.verifyRed - 0.8, NODE_ANG.change], [EV.verifyRed, NODE_ANG.verify, 'power2.inOut'],
  [EV.fix - 0.8, NODE_ANG.verify], [EV.fix, -Math.PI, 'power2.inOut'],
  [EV.verifyGreen - 1.1, -Math.PI], [EV.verifyGreen, NODE_ANG.verify - 2 * Math.PI, 'power3.inOut'],
  [EV.caught1 + 1, NODE_ANG.verify - 2 * Math.PI - 2.4, 'none'],
];

function statusAt(t) {
  if (t < EV.verifyRed) return ['', '✎ unverified', '#d98a1c'];
  if (t < EV.fix) return ['exit 1', '❌ verify RED', '#e0456b'];
  if (t < EV.verifyGreen) return ['', '✎ unverified', '#d98a1c'];
  return ['exit 0', '✅ verify 0s', '#1fa876'];
}

// Backdrop glow: [time, [r, g, b, x, y, amount]]; x and y are in screen uv.
const gk = (t, c, x, y, a, e) => [t, [...arr(c), x, y, a], e];
// hold `from` until t, then swing to `to` at its peak
const gflash = (t, from, to, x, y, base, peak) => [gk(t - 0.05, from, x, y, base), gk(t + 0.15, to, x, y, peak, 'power2.out')];
const bisU = (i) => 0.5 + (bisX(i) * PX_PER_UNIT) / W;
const GA = [0.74, 0.5]; // gate A
const HB = [0.5, 0.67]; // the bus hub
const GLOW = [
  gk(0, C.green, 0.5, 0.5, 0.0),
  gk(EV.checkRise, C.green, 0.5, 0.5, 0.05),
  gk(EV.checkRise + 0.8, C.green, 0.5, 0.5, 0.22, 'power2.out'),
  gk(EV.shatter - 0.04, C.green, 0.5, 0.5, 0.3, 'power2.in'),
  gk(EV.shatter + 0.12, C.red, 0.5, 0.5, 0.3, 'power2.out'),
  gk(EV.fail1, C.red, 0.5, 0.5, 0.12),
  gk(EV.vortex, C.red, 0.35, 0.5, 0.1),
  gk(EV.drop, C.teal, 0.3, 0.52, 0.3, 'power2.in'),
  gk(EV.plan, C.teal, 0.3, 0.52, 0.24),
  gk(EV.plan + 1.4, C.teal, 0.5, 0.48, 0.2),
  gk(EV.verifyRed - 0.1, C.teal, 0.5, 0.48, 0.18),
  gk(EV.verifyRed + 0.15, C.red, 0.5, 0.45, 0.32, 'power2.out'),
  gk(EV.fix, C.teal, 0.5, 0.48, 0.18),
  gk(EV.verifyGreen - 0.1, C.teal, 0.5, 0.48, 0.18),
  gk(EV.verifyGreen + 0.2, C.green, 0.5, 0.45, 0.4, 'power2.out'),
  gk(EV.caught1, C.green, 0.5, 0.45, 0.18),
  gk(EV.caught1 + 1.5, C.teal, ...GA, 0.14),
  ...gflash(EV.c1Nudge, C.teal, C.amber, ...GA, 0.14, 0.28),
  ...gflash(EV.c1Red, C.amber, C.red, ...GA, 0.18, 0.28),
  ...gflash(EV.c1Gate, C.red, C.red, ...GA, 0.2, 0.34),
  gk(EV.caught2, C.red, ...GA, 0.14),
  gk(EV.caught2 + 0.8, C.teal, ...GA, 0.13),
  ...gflash(EV.c2Left, C.teal, C.amber, ...GA, 0.13, 0.24),
  gk(EV.caught3, C.teal, ...GA, 0.12),
  ...gflash(EV.c3H1, C.teal, C.amber, ...GA, 0.12, 0.26),
  gk(EV.exact, C.teal, ...GA, 0.12),
  ...gflash(EV.c4Status, C.teal, C.amber, ...GA, 0.12, 0.24),
  ...gflash(EV.c4Hostile + 1.0, C.amber, C.red, ...GA, 0.16, 0.26),
  gk(EV.probe, C.teal, ...GA, 0.12),
  ...gflash(EV.c5Fail, C.teal, C.red, ...GA, 0.12, 0.3),
  ...gflash(EV.c5Pass, C.red, C.green, ...GA, 0.16, 0.4),
  gk(EV.bisect, C.green, ...GA, 0.16),
  gk(EV.bisect + 1.5, C.teal, 0.5, 0.69, 0.1),
  ...gflash(EV.bis1, C.teal, C.red, bisU(5), 0.69, 0.12, 0.3),
  ...gflash(EV.bis2, C.teal, C.green, bisU(2), 0.69, 0.12, 0.26),
  ...gflash(EV.bis3, C.teal, C.green, bisU(4), 0.69, 0.12, 0.26),
  ...gflash(EV.bisFound, C.teal, C.red, bisU(5), 0.69, 0.14, 0.32),
  gk(EV.bisOut, C.red, bisU(5), 0.69, 0.16),
  gk(EV.relay + 1.5, C.teal, 0.72, 0.74, 0.14),
  gk(EV.relaySeal - 0.05, C.teal, 0.72, 0.74, 0.16),
  gk(EV.relaySeal + 0.12, C.teal, 0.72, 0.74, 0.3, 'power2.out'),
  gk(EV.relayLand, C.teal, 0.86, 0.66, 0.16),
  gk(EV.relayValid - 0.05, C.teal, 0.86, 0.66, 0.16),
  gk(EV.relayValid + 0.15, C.green, 0.86, 0.66, 0.24, 'power2.out'),
  gk(EV.relayConsumed, C.green, 0.86, 0.66, 0.16),
  gk(EV.relayConsumed + 0.15, C.green, 0.86, 0.66, 0.3, 'power2.out'),
  gk(EV.relayOut, C.teal, 0.5, 0.5, 0.12),
  gk(EV.bus + 1.6, C.teal, ...HB, 0.14),
  ...gflash(EV.pkt1 - 0.35, C.teal, C.teal, ...HB, 0.14, 0.3),
  gk(EV.pkt1 + 0.5, C.teal, ...HB, 0.14),
  ...gflash(EV.pkt2 - 0.35, C.teal, C.red, ...HB, 0.14, 0.3),
  gk(EV.pkt2 + 0.5, C.teal, ...HB, 0.14),
  ...gflash(EV.pkt3 - 0.35, C.teal, C.amber, ...HB, 0.14, 0.3),
  gk(EV.pkt3 + 0.5, C.teal, ...HB, 0.14),
  ...gflash(EV.pkt4 - 0.35, C.teal, C.amber, ...HB, 0.14, 0.3),
  gk(EV.pkt4 + 0.5, C.teal, ...HB, 0.14),
  ...gflash(EV.pkt5 - 0.35, C.teal, C.green, ...HB, 0.14, 0.32),
  gk(EV.pkt5 + 0.6, C.teal, ...HB, 0.14),
  gk(EV.bsDown - 0.05, C.teal, ...HB, 0.14),
  gk(EV.bsDown + 0.2, C.amber, ...HB, 0.04, 'power2.out'),
  gk(EV.bsUp - 0.05, C.amber, ...HB, 0.05),
  gk(EV.bsUp + 0.15, C.teal, ...HB, 0.38, 'power2.out'),
  ...gflash(EV.bsRef1, C.teal, C.red, ...HB, 0.14, 0.3),
  ...gflash(EV.bsRef2, C.teal, C.red, ...HB, 0.14, 0.3),
  ...gflash(EV.bsRef3, C.teal, C.red, ...HB, 0.14, 0.3),
  ...gflash(EV.bsPass, C.teal, C.green, ...HB, 0.14, 0.32),
  gk(EV.bsOut, C.green, ...HB, 0.14),
  gk(EV.evidence + 1.5, C.teal, 0.76, 0.42, 0.1),
  gk(EV.evLz + 0.8, C.green, 0.76, 0.42, 0.2),
  ...gflash(EV.evDiff, C.green, C.green, 0.76, 0.42, 0.2, 0.34),
  gk(EV.evOut, C.green, 0.76, 0.45, 0.14),
  gk(EV.safe + 1.0, C.green, 0.77, 0.5, 0.18),
  gk(EV.sfOut, C.green, 0.77, 0.5, 0.14),
  gk(EV.skills + 1.5, C.teal, 0.5, 0.5, 0.1),
  gk(EV.cta, C.teal, 0.3, 0.5, 0.26),
];

// caught tags: FAILURE 0n is struck through, then CAUGHT 0n pops in its place
const CAUGHT = TL.lucia.caught.map((at, i) => {
  const el = $(`#c${i + 1}h .tag`);
  const from = el.textContent;
  const tx = make('span', 'tx');
  const word = make('span', '', from);
  const strike = make('span', 'strike');
  tx.append(word, strike);
  el.replaceChildren(tx);
  return { el, tx, word, strike, from, to: from.replace('FAILURE', 'CAUGHT'), at: cue(at) };
});

const HUB_COLORS = [
  [0, C.teal], [EV.pkt2 - 0.35, C.red], [EV.pkt2 + 0.6, C.teal], [EV.pkt3 - 0.35, C.amber], [EV.pkt3 + 0.6, C.teal],
  [EV.pkt4 - 0.35, C.amber], [EV.pkt4 + 0.6, C.teal], [EV.pkt5 - 0.35, C.green], [EV.pkt5 + 0.8, C.teal],
  [EV.bsDown, C.amber], [EV.bsUp, C.teal], [EV.bsPass, C.green],
];
const HUB_PULSES = [[EV.busHub + 0.5, 1.2, 0.5], [EV.pkt1 - 0.35, 1, 0.3], [EV.pkt2 - 0.35, 1, 0.3], [EV.pkt3 - 0.35, 1, 0.3], [EV.pkt4 - 0.35, 1, 0.3], [EV.pkt5 - 0.35, 1, 0.3], [EV.bsUp, 2, 0.5], [EV.bsPass, 1.2, 0.5]];
const REFUSALS = [[EV.bsRef1, 1.6, 0.35], [EV.bsRef2, 1.6, 0.35], [EV.bsRef3, 1.6, 0.35]];
const FLASH = [
  [EV.shatter, 0.55, 0.12], [EV.drop, 0.3, 0.15], [EV.verifyGreen, 0.18, 0.2], [EV.c1Gate, 0.15, 0.15], [EV.c5Pass, 0.16, 0.2],
  [EV.bisFound, 0.2, 0.15], [EV.bsUp, 0.18, 0.15], [EV.final, 0.2, 0.2],
];
const hubCol = new THREE.Color();

function update(t) {
  // typing
  const ty = TL.typing;
  const n = clamp(Math.floor((t - ty.start) * ty.cps) + 1, 0, ty.text.length);
  typedEl.textContent = t < ty.start ? '' : [...ty.text].slice(0, n).join('');
  caretEl.style.opacity = (t * 2) % 1 < 0.55 ? 1 : 0;
  zeroEl.style.color = t > EV.zeroRun && t < EV.zeroRun + 0.4 && Math.floor(t * 30) % 3 === 0 ? '#d98a1c' : '#e0456b';

  // status strip
  const [code, sl, color] = statusAt(t);
  exitEl.textContent = code;
  exitEl.style.color = color;
  slEl.textContent = sl;
  slEl.style.color = color;

  // backdrop glow follows the story's color
  const glow = k(t, GLOW);
  const bu = backdrop.material.uniforms;
  bu.uGlowColor.value.setRGB(glow[0], glow[1], glow[2]);
  bu.uGlowPos.value.set(glow[3], glow[4]);
  bu.uGlow.value = glow[5] * (1 + 0.8 * pulse(t, EV.final, 0.6));

  for (const d of dust) d.uniforms.uTime.value = t;
  bu.uTime.value = t;

  // check
  const rise = k(t, [[EV.checkRise, -5.0], [EV.checkRise + 0.75, CHECK_Y, 'back.out(1.4)']]);
  check.visible = t >= EV.checkRise && t < EV.shatter;
  check.position.set(0, rise, 0);
  check.rotation.set(k(t, [[EV.checkRise, 0.5], [EV.checkRise + 0.9, 0.08, 'power3.out'], [EV.shatter, 0]]), k(t, [[EV.checkRise, -1.4], [EV.checkRise + 1.0, -0.35, 'power3.out'], [EV.shatter, 0]]), 0);
  const glitch = t > EV.zeroRun && t < EV.shatter ? (Math.sin(Math.floor(t * 30) * 12.9898) * 43758.5453) % 1 : 0;
  const bad = t > EV.zeroRun && Math.abs(glitch) > 0.55;
  checkMat.color.copy(bad ? C.red : C.green);
  checkMat.emissive.copy(C.paper);
  checkMat.emissiveIntensity = 0.5 * pulse(t, EV.checkRise + 0.7, 0.5) + 0.5 * clamp((t - EV.zeroRun) / (EV.shatter - EV.zeroRun)) ** 3;
  if (t > EV.zeroRun && t < EV.shatter) check.position.x += (bad ? glitch * 0.12 : 0);

  // shards
  shardMat.uniforms.uTime.value = t;

  // Lucia A: assembles in scene 3, stands in the ring in scene 4, dissolves as the camera dives
  const la = luciaA.material.uniforms;
  const toCenter = k(t, [[EV.plan - 0.3, 0], [EV.plan + 1.3, 1, 'power3.inOut']]);
  luciaA.position.lerpVectors(LUCIA_S3, LUCIA_S4, toCenter);
  luciaA.scale.setScalar(lerp(1, 0.7, toCenter));
  la.uReveal.value = k(t, [[EV.reveal - 0.05, 0], [EV.reveal + 0.9, 1, 'power1.inOut'], [EV.caught1, 1], [EV.caught1 + 0.7, 0, 'power1.in']]);
  la.uBright.value = 1;
  la.uOpacity.value = k(t, [[EV.quote, 1], [EV.quote + 0.6, 0.45]]);
  luciaA.visible = t > EV.reveal - 0.1 && t < (LOOP_ON ? EV.caught1 + 0.8 : EV.plan);

  // Lucia B: waits at the end of the dive
  const lb = luciaB.material.uniforms;
  luciaB.position.copy(LUCIA_S6);
  lb.uReveal.value = k(t, [[EV.cta - 0.1, 0], [EV.cta + 0.9, 1, 'power1.inOut']]);
  luciaB.visible = t > EV.cta - 0.2;
  luciaB.scale.setScalar(1 + 0.03 * pulse(t, EV.final, 0.5));

  // sparkles
  sparkMat.uniforms.uTime.value = t;
  sparkMat.uniforms.uVis.value.set(
    k(t, [[EV.reveal + 0.3, 0], [EV.reveal + 1.2, 1], [EV.plan - 0.4, 1], [EV.plan + 0.3, 0]]),
    k(t, [[EV.cta + 0.4, 0], [EV.cta + 1.4, 1]]),
  );
  sparkMat.uniforms.uBurst.value = 1.2 * pulse(t, EV.final, 0.45);

  // ring
  const ringOn = k(t, [[EV.plan + 0.4, 0], [EV.plan + 1.4, 1], [EV.caught1, 1], [EV.caught1 + 1.0, 0, 'power2.in']]);
  const ru = ringMat.uniforms;
  ru.uOpacity.value = ringOn;
  ru.uHead.value = k(t, HEAD);
  ring.visible = ringOn > 0.001 && LOOP_ON;
  ring.scale.setScalar(k(t, [[EV.plan + 0.4, 0.6], [EV.plan + 1.6, 1, 'power3.out'], [EV.caught1, 1], [EV.caught1 + 1.0, 3.2, 'power2.in']]));
  const red = pulse(t, EV.verifyRed, 1.2) * (t < EV.fix ? 1 : 0);
  const green = t >= EV.verifyGreen ? 1 : 0;
  ru.uBase.value.copy(C.teal).lerp(C.red, red).lerp(C.green, green * 0.85);
  ru.uHeadColor.value.copy(C.blue).lerp(C.red, t >= EV.verifyRed && t < EV.fix ? 1 : 0).lerp(C.green, green);
  const hit = { plan: EV.plan + 1.2, change: EV.change, verify: t >= EV.verifyGreen ? EV.verifyGreen : EV.verifyRed, fix: EV.fix };
  for (const [name, mesh] of Object.entries(nodes)) {
    const p = pulse(t, hit[name], 0.45) * (t >= hit[name] ? 1 : 0);
    let c = name === 'change' ? C.amber : C.teal;
    if (name === 'verify') c = t >= EV.verifyGreen ? C.green : t >= EV.verifyRed ? C.red : C.teal;
    mesh.material.color.copy(c);
    mesh.material.emissive.copy(C.paper);
    mesh.material.emissiveIntensity = 0.6 * p;
    mesh.material.opacity = ringOn;
    mesh.userData.outline.opacity = ringOn;
    mesh.scale.setScalar(1 + 0.6 * p);
    mesh.rotation.set(t * 0.8, t * 1.1, 0);
  }
  ring.rotation.z = k(t, [[EV.quote, 0], [EV.caught1 + 1, 0.35, 'sine.in']]);

  // chips
  for (const chip of chips) {
    const { tick, home, out: dir, spin } = chip.userData;
    const u = clamp((t - tick) / 0.4);
    const burst = ease('power2.in')(clamp((t - EV.dive - 0.15) / 0.9));
    chip.visible = t >= tick && t < EV.cta + 0.3;
    chip.position.copy(home).addScaledVector(dir, burst * 9);
    chip.position.z += burst * 3;
    chip.rotation.set((1 - ease('back.out(1.6)')(u)) * -1.5, -0.1 + spin * burst, spin * burst * 0.6);
    chip.material.opacity = ease('power2.out')(u);
  }

  placeCamera(t);

  // Lucia presents: she dissolves in at the right edge, reacts, and slides out
  const span = PRESENT.find(([a, b]) => t > a - 0.1 && t < b + 0.7);
  luciaP.visible = !!span;
  if (span) {
    const [a, b] = span;
    const pu = luciaP.material.uniforms;
    pu.uReveal.value = k(t, [[a, 0], [a + 0.8, 1, 'power1.inOut']]);
    pu.uOpacity.value = 1 - clamp((t - b) / 0.5);
    const slide = 260 * ease('power2.in')(clamp((t - b) / 0.6));
    const hop = LINES.reduce((sum, l) => sum + 14 * Math.sin(Math.PI * clamp((t - l.at) / 0.28)), 0); // a little hop on each line
    screenToWorld(PRES.x + slide, PRES.y - hop, PRES.d, luciaP.position);
    luciaP.quaternion.copy(camera.quaternion);
    luciaP.scale.setScalar(PRES.px / (LUCIA_H * H / (2 * PRES.d * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)))));
  }
  if (lucia && (luciaA.visible || luciaB.visible || luciaP.visible)) lucia.update(t);

  // her speech bubble: pops in on each line, shrinks away at its end
  const line = LINES.find((l) => t > l.at - 0.05 && t < l.end + 0.25);
  if (line) {
    if (bubbleText.textContent !== line.text) bubbleText.textContent = line.text;
    const pop = ease('back.out(2.2)')(clamp((t - line.at) / 0.3));
    const gone = ease('power2.in')(clamp((t - line.end) / 0.22));
    bubbleEl.style.opacity = (clamp((t - line.at) / 0.1) * (1 - gone)).toFixed(3);
    bubbleEl.style.transform = `translate(-100%, -50%) scale(${(0.4 + 0.6 * pop - 0.3 * gone).toFixed(3)}) rotate(${(-3 * (1 - pop)).toFixed(2)}deg)`;
  }
  bubbleEl.style.visibility = line ? 'visible' : 'hidden';

  // a CAUGHT stamp pops beside her each time a failure is caught
  const stamp = CAUGHT.find((c) => t > c.at && t < c.at + 1.9);
  if (stamp) {
    const u = (t - stamp.at);
    stampEl.firstChild.textContent = stamp.to.trim() + ' ✓';
    stampEl.style.opacity = (clamp(u / 0.08) * (1 - clamp((u - 1.6) / 0.3))).toFixed(3);
    stampEl.style.transform = `translate(-50%, -50%) rotate(-10deg) scale(${(1 + 0.9 * (1 - ease('back.out(2.5)')(clamp(u / 0.3)))).toFixed(3)})`;
  }
  stampEl.style.visibility = stamp ? 'visible' : 'hidden';

  // terminals: commands type, output lines appear, hook boxes wipe in
  for (const ln of termLines) {
    ln.el.style.opacity = clamp((t - ln.at) / 0.08).toFixed(3);
    if (ln.kind === 'cmd') {
      const typed = clamp(Math.floor((t - ln.at) * ln.cps) + 1, 0, ln.chars.length);
      ln.tx.textContent = t < ln.at ? '' : ln.chars.slice(0, typed).join('');
      ln.caret.style.visibility = t >= ln.at && t < ln.next && (typed < ln.chars.length || (t * 2) % 1 < 0.55) ? 'visible' : 'hidden';
    } else if (ln.kind === 'box') {
      ln.el.style.clipPath = `inset(0 ${(100 - 100 * ease('power2.out')(clamp((t - ln.at) / 0.45))).toFixed(2)}% 0 0)`;
    }
    if (ln.pill) ln.pill.style.opacity = clamp((t - ln.pillAt) / 0.15).toFixed(3);
  }
  for (const s of termStatus) {
    let cur = s.keys[0];
    for (const key of s.keys) if (t >= key.at) cur = key;
    s.st.textContent = cur.text;
    s.st.className = `st ${cur.cls}`;
    s.pill.textContent = cur.note ?? '';
    s.pill.className = `pill ${cur.cls}`;
    s.pill.style.display = cur.note ? '' : 'none';
    s.pill.style.opacity = clamp((t - cur.at - 0.3) / 0.2).toFixed(3);
    const flash = cur === s.keys[0] ? 0 : pulse(t, cur.at, 0.4);
    s.sl.style.background = `rgba(${TONE[cur.cls]}, ${(0.22 * flash).toFixed(3)})`;
  }

  // caught tags
  for (const c of CAUGHT) {
    const u = t - c.at;
    const swapped = u >= 0.3;
    c.word.textContent = swapped ? c.to : c.from;
    c.strike.style.transform = `scaleX(${(u >= 0 && !swapped ? ease('power2.out')(clamp(u / 0.22)) : 0).toFixed(3)})`;
    c.tx.style.transform = `scale(${(swapped ? 1 + 0.35 * (1 - ease('back.out(3)')(clamp((u - 0.3) / 0.35))) : 1).toFixed(3)})`;
    c.el.style.color = u < 0 ? '#e0456b' : !swapped ? '#d98a1c' : '#1fa876';
  }

  // caught 03: the ledger scrolls through all 27, then /debug lands on H1
  const hitTop = (TL.lessons.hit - 2) * LEDGER_ROW;
  const maxScroll = (ledgerItems.length + 1) * LEDGER_ROW - LEDGER_VIEW;
  const scroll = k(t, [[EV.c3Count, -LEDGER_ROW], [EV.c3Count + 2.0, maxScroll, 'power1.inOut'], [EV.c3H1 - 0.45, maxScroll], [EV.c3H1, hitTop, 'power3.inOut']]);
  ledgerList.style.transform = `translateY(${(-scroll).toFixed(1)}px)`;
  $('#count27 .num').textContent = String(Math.round(ledgerItems.length * ease('power1.inOut')(clamp((t - EV.c3Count) / 2.0))));
  const h1On = clamp((t - EV.c3H1) / 0.15);
  const hiEl = $('#ledgerHi');
  hiEl.style.top = `${TL.lessons.hit * LEDGER_ROW - hitTop}px`;
  hiEl.style.opacity = (h1On * (1 + 0.5 * pulse(t, EV.c3H1, 0.3))).toFixed(3);
  ledgerItems[TL.lessons.hit].classList.toggle('hit', t >= EV.c3H1);
  ledgerItems[TL.lessons.hit].querySelector('.h1').style.opacity = clamp((t - EV.c3H1 - 0.1) / 0.2).toFixed(3);

  // bisect
  const bOn = k(t, [[EV.bisect + 0.8, 0], [EV.bisect + 1.6, 1], [EV.bisOut, 1], [EV.bisOut + 0.5, 0]]);
  bisGroup.visible = bOn > 0.001;
  bisNodes.forEach((m, i) => {
    const s = ease('back.out(2)')(clamp((t - EV.bisNodes - i * 0.06) / 0.35));
    const kn = bisKnown[i];
    const known = t >= kn.at;
    const hitP = known ? pulse(t, kn.at, 0.35) : 0;
    const found = i === BIS.firstBad && t >= EV.bisFound;
    const col = !known ? C.paper : kn.state === 'good' ? C.green : C.red;
    m.material.color.copy(col);
    if (known && kn.implied) m.material.color.lerp(C.paper, 0.6);
    m.material.emissive.copy(C.paper);
    m.material.emissiveIntensity = 0.7 * hitP + (found ? 0.5 * pulse(t, EV.bisFound, 0.5) : 0);
    m.material.opacity = bOn;
    m.userData.outline.opacity = bOn;
    m.scale.setScalar(Math.max(1e-3, s * (1 + 0.4 * hitP + (found ? 0.35 + 0.4 * pulse(t, EV.bisFound, 0.4) : 0))));
    m.rotation.set(t * 0.6 + i, t * 0.9 + i * 0.5, 0);
    const lab = shaEls[i];
    lab.el.style.color = found ? '#1f2a44' : !known ? '#8a99ad' : kn.state === 'good' ? '#1fa876' : '#e0456b';
    lab.el.style.fontWeight = found ? '600' : '500';
    lab.el.style.opacity = known && kn.implied ? '0.6' : '1';
    pin(lab.pos, m.position);
  });
  chain.material.opacity = 0.8 * bOn * clamp((t - EV.bisNodes) / 0.6);
  const [lo, hi] = k(t, BAND);
  const bw = bisX(hi) - bisX(lo) + 0.84;
  band.scale.set(bw, 0.78, 1);
  band.position.x = (bisX(lo) + bisX(hi)) / 2;
  bandMat.uniforms.uSize.value.set(bw, 0.78);
  bandMat.uniforms.uOpacity.value = bOn * k(t, [[EV.bisTerm + 0.3, 0], [EV.bisTerm + 0.8, 1], [EV.bisFound, 1], [EV.bisFound + 0.6, 0.35]]);
  bandMat.uniforms.uColor.value.copy(C.amber).lerp(C.red, clamp((t - EV.bisFound) / 0.2));
  let beamO = 0;
  for (const [idx, ev] of BIS.steps) {
    const at = EV[ev];
    if (t >= at - 0.5 && t < at + 0.35) {
      beam.position.set(bisX(idx), BIS_Y + 0.2 + BEAM_H / 2, BIS_Z);
      beamMat.uniforms.uReach.value = ease('power2.in')(clamp((t - at + 0.5) / 0.35));
      beamO = t < at ? 0.8 : 1 - (t - at) / 0.35;
    }
  }
  beamMat.uniforms.uOpacity.value = beamO * bOn;
  beam.visible = beamO > 0;
  const sh = clamp((t - EV.bisFound) / 0.9);
  shock.visible = t >= EV.bisFound && sh < 1;
  shock.position.set(bisX(BIS.firstBad), BIS_Y, BIS_Z + 0.05);
  shock.scale.setScalar(1 + 3.2 * ease('power2.out')(sh));
  const su = shock.material.uniforms;
  su.uColor.value.copy(C.red);
  su.uOpacity.value = (1 - sh) ** 1.5;
  su.uGain.value = 1;

  // relay card (placed after the camera, since its path is in screen space)
  const [cx, cy, cs, spin] = cardState(t);
  card.visible = t >= EV.relayCard && t < EV.relayConsumed + 0.8;
  screenToWorld(cx, cy, CARD_D, card.position);
  card.quaternion.copy(camera.quaternion);
  card.rotateY(spin + 0.12 * Math.sin(t * 0.9));
  card.rotateX(0.07 * Math.sin(t * 1.3));
  card.scale.setScalar(cs);
  const cu = cardMat.uniforms;
  cu.uOpacity.value = clamp((t - EV.relayCard) / 0.15);
  RL.rows.forEach((_, i) => { cu.uRowVis.value[i] = clamp((t - rowAt(i)) / 0.1); });
  const rowFlash = RL.rows.reduce((sum, _, i) => sum + pulse(t, rowAt(i), 0.15), 0);
  cu.uEdgeGain.value = 1.1 + 0.6 * rowFlash + 1.5 * pulse(t, EV.relayCard, 0.25) + 2.6 * pulse(t, EV.relaySeal, 0.35) +
    1.4 * pulse(t, EV.relayLand, 0.3) + 1.8 * pulse(t, EV.relayValid, 0.4);
  cu.uGlow.value = 0.5 + 1.2 * pulse(t, EV.relaySeal, 0.5) + 0.8 * pulse(t, EV.relayValid, 0.5);
  cu.uEdge.value.copy(C.teal).lerp(C.green, clamp((t - EV.relayValid) / 0.2));
  cu.uDissolve.value = k(t, [[EV.relayConsumed, 0], [EV.relayConsumed + 0.7, 1, 'power1.in']]);
  updateRelayFx(t);

  // agent bus: the daemon, its packets, a restart and three refusals
  const hubOn = k(t, [[EV.busHub, 0], [EV.busHub + 0.7, 1, 'power2.out'], [EV.bsOut, 1], [EV.bsOut + 0.5, 0, 'power2.in']]);
  hub.visible = hubOn > 0.001;
  const down = t >= EV.bsDown && t < EV.bsUp;
  const flick = down ? 0.12 + 0.25 * (hash01(Math.floor(t * 14), 7) > 0.8 ? 1 : 0) : 1;
  stepColor(t, HUB_COLORS, hubCol);
  const hp = pulses(t, HUB_PULSES);
  hubCore.material.color.copy(hubCol).lerp(C.paper, down ? 0.7 * (1 - flick) + 0.3 : 0);
  hubCore.material.emissive.copy(C.paper);
  hubCore.material.emissiveIntensity = 0.5 * clamp(hp);
  hubCore.material.opacity = hubOn;
  hubCore.userData.outline.opacity = hubOn;
  const hubTime = t - clamp(t - EV.bsDown, 0, EV.bsUp - EV.bsDown); // the orbits stop while the daemon is down
  for (const { m, level: lv, speed } of hubOrbits) {
    const u = m.material.uniforms;
    u.uColor.value.copy(hubCol);
    u.uOpacity.value = hubOn;
    u.uGain.value = Math.min(1, lv * 1.4) * (down ? 0.35 + 0.65 * flick : 1);
    u.uRot.value = hubTime * speed;
  }
  const refused = pulses(t, REFUSALS);
  shieldMat.uniforms.uColor.value.copy(C.teal).lerp(C.red, clamp(refused));
  shieldMat.uniforms.uOpacity.value = hubOn * Math.min(1, 0.35 + refused) * (down ? 0.3 : 1);
  hub.scale.setScalar(Math.max(1e-3, ease('back.out(1.6)')(clamp((t - EV.busHub) / 0.7))) * (1 + 0.08 * hp));
  hub.position.copy(HUB);
  pinV.copy(HUB).project(camera);
  updatePackets(t, [((pinV.x + 1) / 2) * W, ((1 - pinV.y) / 2) * H]);
  pin($('#hubLabel'), HUB);

  // evidence
  const frameOn = k(t, [[EV.evHead + 0.2, 0], [EV.evHead + 1.0, 1], [EV.evOut, 1], [EV.safe + 0.3, 0]]);
  bars.forEach((b, i) => {
    const grow = ease('power3.out')(clamp((t - b.at) / 1.1));
    const sink = ease('power2.in')(clamp((t - EV.safe) / 0.6));
    const h = Math.max(1e-3, b.frac * grow * (1 - sink) * EV_FULL);
    b.mesh.visible = t >= b.at && sink < 1;
    b.mesh.scale.y = h;
    const mu = b.mesh.material.uniforms;
    mu.uH.value = h;
    mu.uOpacity.value = 0.95;
    mu.uGain.value = 1 + 0.9 * pulse(t, b.at + 1.0, 0.4) + (i === 1 ? 0.8 * pulse(t, EV.evDiff, 0.5) : 0);
    b.frame.material.opacity = 0.45 * frameOn;
    b.frame.visible = frameOn > 0.001;
    const L = evLabels[i];
    L.p.textContent = `${Math.round(100 * b.frac * grow)}%`;
    L.f.textContent = `${Math.round(b.n * grow)} / ${b.d} runs`;
    pin(L.top, tmp.set(b.x, EV_BASE + h, EVI_Z + 0.25));
    pin(L.bot, tmp.set(b.x, EV_BASE, EVI_Z + 0.25));
  });
  const gapOff = 1 - clamp((t - EV.safe) / 0.4);
  gap.visible = t >= EV.evDiff && gapOff > 0;
  gap.scale.y = Math.max(1e-3, ease('power3.out')(clamp((t - EV.evDiff) / 0.5)) * (bars[1].frac - bars[0].frac) * EV_FULL);
  gapMat.opacity = gapOff;
  level.visible = t >= EV.evDiff - 0.35 && gapOff > 0;
  levelMat.uniforms.uOpacity.value = clamp((t - EV.evDiff + 0.35) / 0.3) * gapOff;

  // node labels follow their nodes on screen
  for (const [name, mesh] of Object.entries(nodes)) {
    mesh.getWorldPosition(tmp).project(camera);
    labelPos[name].style.transform = `translate(${((tmp.x + 1) / 2) * W}px, ${((1 - tmp.y) / 2) * H}px)`;
    const active = pulse(t, hit[name], 1.4) * (t >= hit[name] ? 1 : 0);
    let col = '#1f2a44';
    if (name === 'verify' && t >= EV.verifyRed && t < EV.fix) col = '#e0456b';
    if (name === 'verify' && t >= EV.verifyGreen) col = '#1fa876';
    if (name === 'change' && t >= EV.change && t < EV.verifyRed) col = '#d98a1c';
    labelName[name].style.color = col;
    labelName[name].style.opacity = 0.45 + 0.55 * Math.max(active, name === 'verify' && t >= EV.verifyGreen ? 1 : 0);
  }

  // post
  finish.uniforms.uTime.value = t;
  flashEl.style.opacity = (0.6 * pulses(t, FLASH)).toFixed(3);
  fadeEl.style.opacity = Math.max(k(t, [[0, 1], [0.35, 0, 'power1.out']]), k(t, [[EV.fadeOut, 0], [TL.duration, 1, 'power1.in']])).toFixed(3);
}

// Chapter cards: the page pushes in slowly, a star and the word land, then the line.
const CARDS = Object.fromEntries([...document.querySelectorAll('.card')].map((el) => [el.id.replace('card-', ''), { el, parts: [...el.children] }]));
const CARD_EXIT = 0.5; // a card pushes through and fades over the first half second of the next shot

function updateCard(shot, t) {
  // After a card, it stays over the start of the next shot while it leaves, so the
  // cut lands on a moving card instead of on the empty page before the scene's title.
  const prev = SHOTS[SHOTS.indexOf(shot) - 1];
  const leaving = !shot.card && prev?.card && t - shot.at < CARD_EXIT;
  const card = shot.card ? shot : leaving ? prev : null;
  for (const [id, c] of Object.entries(CARDS)) c.el.style.visibility = card?.card === id ? 'visible' : 'hidden';
  if (!card) return;
  const { el, parts: [star, word, line] } = CARDS[card.card];
  const x = leaving ? ease('power2.in')(clamp((t - shot.at) / CARD_EXIT)) : 0;
  el.style.opacity = (1 - x).toFixed(3);
  el.style.filter = x ? `blur(${(10 * x).toFixed(2)}px)` : '';
  const u = Math.min(t - card.at, card.dur);
  el.style.backgroundPosition = `${(t * 9).toFixed(1)}px ${(t * 6).toFixed(1)}px, 0 0`;
  const push = (1 + 0.04 * ease('sine.inOut')(clamp(u / card.dur))) * (1 + 0.35 * x);
  const s = ease('back.out(2.5)')(clamp(u / 0.45));
  star.style.opacity = clamp(u / 0.12).toFixed(3);
  star.style.transform = `scale(${(s * push).toFixed(3)}) rotate(${(-90 * (1 - s)).toFixed(1)}deg)`;
  const w = ease('power4.out')(clamp((u - 0.05) / 0.55));
  word.style.opacity = clamp((u - 0.05) / 0.12).toFixed(3);
  word.style.transform = `scale(${((1.16 - 0.16 * w) * push).toFixed(4)})`;
  word.style.filter = `blur(${(16 * (1 - w)).toFixed(2)}px)`;
  const l = ease('power3.out')(clamp((u - 0.5) / 0.5));
  line.style.opacity = l.toFixed(3);
  line.style.transform = `translateY(${(26 * (1 - l)).toFixed(1)}px) scale(${push.toFixed(4)})`;
  line.style.filter = `blur(${(8 * (1 - l)).toFixed(2)}px)`;
}

function seek(t) {
  const shot = SHOTS.find((s) => t < s.end) ?? SHOTS[SHOTS.length - 1];
  const src = shot.src ? shot.src[0] + (t - shot.at) : shot.hold;
  tl.seek(src, false);
  update(src);
  updateCard(shot, t);
  composer.render();
}

window.__seek = seek;
window.__duration = DURATION;
window.__fps = TL.fps;
window.__glInfo = (() => {
  const gl = renderer.getContext();
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
})();

// ------------------------------------------------------------------ browser preview (not used by render.mjs)

const params = new URLSearchParams(location.search);
if (!params.has('render')) {
  const stage = document.getElementById('stage');
  const fit = () => { const s = Math.min(innerWidth / W, innerHeight / H); stage.style.transform = `scale(${s})`; };
  addEventListener('resize', fit);
  fit();
  if (params.has('t')) {
    seek(Number(params.get('t')));
  } else {
    const audio = new Audio(`out/${CUT?.music ?? 'music.wav'}`);
    seek(0);
    const loop = () => { seek(audio.currentTime); if (!audio.paused) requestAnimationFrame(loop); };
    addEventListener('click', () => { if (audio.paused) { audio.play(); requestAnimationFrame(loop); } else audio.pause(); });
  }
}
window.__ready = true;
