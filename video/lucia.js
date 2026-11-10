// Lucia as a live VRM, rendered into a texture that main.js puts on her plane.
//
// The model and its motions stay outside this repository: the model's licence
// forbids redistribution. render.mjs serves them from a local checkout of
// Lucia-AI-Waifu-Project under /lucia/<name>, and /lucia/manifest.json says
// whether they were found. Without them main.js falls back to site/lucia-3d.png.
//
// Pose, face and gaze are pure functions of t: clips are sampled at t, never
// stepped. Only the hair and ear springs have memory. They step once per frame
// when frames arrive in order, and settle over the second leading up to t after a
// jump, so a full render is deterministic and a still is close to it.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { VRMAnimationLoaderPlugin, VRMLookAtQuaternionProxy, createVRMAnimationClip } from '@pixiv/three-vrm-animation';

const loadGltf = (url, plugin) => {
  const loader = new GLTFLoader();
  loader.register(plugin);
  return loader.loadAsync(url);
};
const smooth = (x) => x * x * (3 - 2 * x);

// Keys [[t, v], ...]: hold a value, then blend to the next one with a smoothstep.
function sample(keys, t) {
  if (t <= keys[0][0]) return keys[0][1];
  for (let i = 1; i < keys.length; i++) {
    const [t1, v1] = keys[i];
    if (t <= t1) {
      const [t0, v0] = keys[i - 1];
      return v0 + (v1 - v0) * smooth((t - t0) / Math.max(t1 - t0, 1e-6));
    }
  }
  return keys[keys.length - 1][1];
}

/**
 * spec.base      clip name that loops under everything
 * spec.gestures  [{ clip, start, end, fade, offset }]: a gesture replaces the base while it plays
 * spec.face      { expressionName: keys }
 * spec.look      { yaw: keys, pitch: keys } in degrees
 * spec.blinks    blink start times; a blink is skipped while an eye-shaping face is on
 * spec.frame     { top, bottom } in meters above the head bone and below the hips bone
 */
export async function loadLucia({ renderer, fps, size: [w, h], spec }) {
  const manifest = await (await fetch('/lucia/manifest.json')).json();
  if (!manifest.found) return null;

  const gltf = await loadGltf('/lucia/vrm', (p) => new VRMLoaderPlugin(p));
  const vrm = gltf.userData.vrm;
  VRMUtils.removeUnnecessaryVertices(gltf.scene);
  VRMUtils.combineSkeletons(gltf.scene);
  VRMUtils.rotateVRM0(vrm);
  vrm.lookAt.autoUpdate = false;
  // createVRMAnimationClip wants this proxy; making it here keeps the console quiet.
  const lookAtProxy = new VRMLookAtQuaternionProxy(vrm.lookAt);
  lookAtProxy.name = 'lookAtQuaternionProxy';
  vrm.scene.add(lookAtProxy);

  // Lighting from the waifu project's preview page, so she looks as she does there.
  const scene = new THREE.Scene();
  scene.add(vrm.scene, new THREE.AmbientLight(0xffffff, 0.9));
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(0.5, 1.5, 2);
  scene.add(key);

  // Frame from above the ears to the upper thigh, like site/lucia-3d.png.
  vrm.scene.updateMatrixWorld(true);
  const bone = (name) => vrm.humanoid.getNormalizedBoneNode(name);
  const headY = bone('head').getWorldPosition(new THREE.Vector3()).y;
  const hipsY = bone('hips').getWorldPosition(new THREE.Vector3()).y;
  const top = headY + spec.frame.top;
  const bottom = hipsY - spec.frame.bottom;
  const camera = new THREE.PerspectiveCamera(20, w / h, 0.05, 50);
  camera.position.set(0, (top + bottom) / 2, (top - bottom) / 2 / Math.tan(THREE.MathUtils.degToRad(10)));
  camera.lookAt(0, (top + bottom) / 2, 0);

  const mixer = new THREE.AnimationMixer(vrm.scene);
  const clips = new Map();
  const clipFor = async (name) => {
    if (!clips.has(name)) {
      const motion = await loadGltf(`/lucia/${name}`, (p) => new VRMAnimationLoaderPlugin(p));
      const clip = createVRMAnimationClip(motion.userData.vrmAnimations[0], vrm);
      // Motions drive the body only; the face and gaze come from the spec.
      clip.tracks = clip.tracks.filter((tr) => !/expression|lookAt/i.test(tr.name) || /^Normalized_/.test(tr.name));
      clips.set(name, clip);
    }
    return clips.get(name);
  };
  const makeAction = (clip, id) => {
    const c = clip.clone();
    c.name = id;
    const action = mixer.clipAction(c);
    action.play();
    action.setEffectiveWeight(0);
    return action;
  };
  const base = makeAction(await clipFor(spec.base), 'base');
  const baseLen = clips.get(spec.base).duration;
  const gestures = [];
  for (const [i, g] of spec.gestures.entries()) {
    const clip = await clipFor(g.clip);
    gestures.push({ ...g, fade: g.fade ?? 0.4, offset: g.offset ?? 0, duration: clip.duration, action: makeAction(clip, `g${i}`) });
  }

  const em = vrm.expressionManager;
  const eyeFaces = ['happy', 'blush', 'sleepy', 'grin', 'error'].filter((n) => em.getExpression(n));
  function pose(t) {
    let sum = 0;
    const env = gestures.map((g) => {
      const e = smooth(Math.min(1, Math.max(0, Math.min((t - g.start + g.fade) / g.fade, (g.end + g.fade - t) / g.fade))));
      sum += e;
      return e;
    });
    gestures.forEach((g, i) => {
      g.action.time = Math.min(Math.max(0, t - g.start + g.offset), g.duration - 1e-3);
      g.action.setEffectiveWeight(env[i] / Math.max(1, sum));
    });
    base.time = ((t % baseLen) + baseLen) % baseLen;
    base.setEffectiveWeight(Math.max(0, 1 - sum));
    mixer.update(0);

    for (const e of em.expressions) em.setValue(e.expressionName, 0);
    const face = {};
    for (const [name, keys] of Object.entries(spec.face)) if (em.getExpression(name)) face[name] = sample(keys, t);
    if (!eyeFaces.some((n) => (face[n] ?? 0) > 0.15)) {
      for (const b of spec.blinks) {
        const u = (t - b) / 0.16;
        if (u >= 0 && u <= 1) face.blink = Math.max(face.blink ?? 0, Math.sin(Math.PI * u));
      }
    }
    for (const [name, v] of Object.entries(face)) em.setValue(name, Math.min(1, Math.max(0, v)));
    vrm.lookAt.yaw = sample(spec.look.yaw, t);
    vrm.lookAt.pitch = sample(spec.look.pitch, t);
  }

  let last = -Infinity;
  function step(t) {
    const delta = t - last;
    if (delta > 1e-6 && delta <= 0.25) {
      const n = Math.ceil(delta * 60 - 1e-6);
      for (let i = 1; i <= n; i++) {
        pose(last + (delta * i) / n);
        vrm.update(delta / n);
      }
    } else if (Math.abs(delta) > 1e-6) {
      // a jump: start the springs from rest and let them settle over the second before t
      pose(t - 1);
      vrm.springBoneManager?.reset();
      for (let i = 59; i >= 0; i--) {
        pose(t - i / 60);
        vrm.update(1 / 60);
      }
    }
    last = t;
  }

  const target = new THREE.WebGLRenderTarget(w, h, { type: THREE.HalfFloatType, samples: 4 });
  const clearColor = new THREE.Color();
  function render(rt) {
    renderer.getClearColor(clearColor);
    const alpha = renderer.getClearAlpha();
    renderer.setRenderTarget(rt);
    renderer.setClearColor(0x000000, 0);
    renderer.clear();
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    renderer.setClearColor(clearColor, alpha);
  }

  return {
    texture: target.texture, // linear, premultiplied by alpha
    update(t) {
      step(t);
      render(target);
    },
    // Linear, premultiplied RGBA of the pose at t, top row first (for the shards).
    pixels(t) {
      step(t);
      const rt = new THREE.WebGLRenderTarget(w, h, { type: THREE.UnsignedByteType });
      render(rt);
      const buf = new Uint8Array(w * h * 4);
      renderer.readRenderTargetPixels(rt, 0, 0, w, h, buf);
      rt.dispose();
      const data = new Uint8Array(w * h * 4);
      for (let y = 0; y < h; y++) data.set(buf.subarray((h - 1 - y) * w * 4, (h - y) * w * 4), y * w * 4);
      return { width: w, height: h, data };
    },
  };
}
