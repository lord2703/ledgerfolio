/* Ledgerfolio 3D: the drifting particle backdrop, the hero "ledger core" and the
   per-system 3D previews. Colours are read from the page's CSS variables, so the
   scenes follow dark/light mode and every colour-vision mode automatically. */

import * as THREE from '../vendor/three/three.module.min.js';

const root = document.documentElement;
const TAU = Math.PI * 2;

const cssColor = (name) =>
  new THREE.Color(getComputedStyle(root).getPropertyValue(name).trim() || '#ffffff');

function readPalette() {
  return {
    accent: cssColor('--accent'),
    accent2: cssColor('--accent-2'),
    accent3: cssColor('--accent-3'),
    text: cssColor('--text'),
    surface: cssColor('--surface-solid'),
    light: root.dataset.theme === 'light',
  };
}

function motionReduced() {
  if (root.dataset.motion === 'reduce') return true;
  if (root.dataset.motion === 'full') return false;
  return matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/* Seeded random numbers: the backdrop looks the same on every page, which
   together with a clock-based phase makes it feel continuous across navigation. */
function seeded(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function dotTexture() {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, 'rgba(255,255,255,1)');
  gradient.addColorStop(0.35, 'rgba(255,255,255,0.55)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
}

/* ---------- Stage: one canvas, one renderer -------------------------------- */

const stages = [];

class Stage {
  constructor(canvas, { fov = 38, distance = 9 } = {}) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(fov, 1, 0.1, 100);
    this.camera.position.z = distance;
    this.visible = true;
    this.dirty = true;
    this.painters = [];   // (palette) => void, re-run when the appearance changes
    this.update = () => {};

    new ResizeObserver(() => this.resize()).observe(canvas);
    new IntersectionObserver(([entry]) => { this.visible = entry.isIntersecting; }).observe(canvas);
    this.resize();
    stages.push(this);
  }

  resize() {
    const { clientWidth: width, clientHeight: height } = this.canvas;
    if (!width || !height) return;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.dirty = true;
  }

  /* Register a material (or any object with .color) to be tinted by a palette role. */
  tint(target, role, key = 'color') {
    this.painters.push((palette) => target[key].copy(palette[role]));
    return target;
  }

  paint() {
    const palette = readPalette();
    this.painters.forEach((painter) => painter(palette));
    this.dirty = true;
  }

  frame(time, still) {
    if (!this.visible) return;
    if (still && !this.dirty) return;
    this.update(time, still);
    this.renderer.render(this.scene, this.camera);
    this.dirty = false;
    this.canvas.classList.add('is-ready');
  }
}

function loop() {
  const still = motionReduced();
  // Wall-clock time keeps animation phase continuous from one page to the next.
  const time = (Date.now() / 1000) % 100000;
  if (!document.hidden) stages.forEach((stage) => stage.frame(time, still));
  requestAnimationFrame(loop);
}

window.addEventListener('lf:appearance', () => stages.forEach((stage) => stage.paint()));

/* Smoothed pointer position in -1..1, shared by every scene. */
const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
window.addEventListener('pointermove', (event) => {
  pointer.tx = (event.clientX / window.innerWidth) * 2 - 1;
  pointer.ty = (event.clientY / window.innerHeight) * 2 - 1;
}, { passive: true });
function easePointer() {
  pointer.x += (pointer.tx - pointer.x) * 0.04;
  pointer.y += (pointer.ty - pointer.y) * 0.04;
}

/* ---------- Shared building blocks ----------------------------------------- */

function addLights(stage) {
  const ambient = new THREE.AmbientLight(0xffffff, 0.7);
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(4, 6, 8);
  const warm = new THREE.PointLight(0xffffff, 60, 30);
  warm.position.set(5, -3, 4);
  const cool = new THREE.PointLight(0xffffff, 70, 30);
  cool.position.set(-6, 3, 5);
  stage.tint(warm, 'accent');
  stage.tint(cool, 'accent2');
  stage.painters.push((palette) => { ambient.intensity = palette.light ? 1.5 : 0.7; });
  stage.scene.add(ambient, key, warm, cool);
}

function solid(stage, role, { glow = 0, ...options } = {}) {
  const material = new THREE.MeshStandardMaterial({
    metalness: 0.35, roughness: 0.32, flatShading: true, ...options,
  });
  stage.tint(material, role);
  if (glow) {
    material.emissiveIntensity = glow;
    stage.tint(material, role, 'emissive');
  }
  return material;
}

function wire(stage, geometry, role, opacity = 0.4) {
  const material = new THREE.LineBasicMaterial({ transparent: true, opacity });
  stage.tint(material, role);
  return new THREE.LineSegments(new THREE.EdgesGeometry(geometry), material);
}

function ring(stage, radius, role, opacity = 0.7, tube = 0.012) {
  const material = new THREE.MeshBasicMaterial({ transparent: true, opacity });
  stage.tint(material, role);
  return new THREE.Mesh(new THREE.TorusGeometry(radius, tube, 8, 200), material);
}

function dust(stage, count, spread, seed, size = 0.07) {
  const random = seeded(seed);
  const positions = new Float32Array(count * 3);
  const mix = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const [x, y, z] = spread(random);
    positions.set([x, y, z], i * 3);
    mix[i] = random();
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
  const material = new THREE.PointsMaterial({
    size, map: dotTexture(), vertexColors: true, transparent: true, depthWrite: false,
    sizeAttenuation: true,
  });
  stage.painters.push((palette) => {
    const colors = geometry.attributes.color;
    const color = new THREE.Color();
    for (let i = 0; i < count; i++) {
      const pick = mix[i];
      color.copy(pick < 0.45 ? palette.accent : pick < 0.8 ? palette.accent2 : palette.text);
      colors.setXYZ(i, color.r, color.g, color.b);
    }
    colors.needsUpdate = true;
    // Glowing dots on dark, ink dots on light.
    material.blending = palette.light ? THREE.NormalBlending : THREE.AdditiveBlending;
    material.opacity = palette.light ? 0.5 : 0.85;
    material.needsUpdate = true;
  });
  return new THREE.Points(geometry, material);
}

/* ---------- Backdrop: slow particle field behind every page ----------------- */

function buildBackdrop(canvas) {
  const stage = new Stage(canvas, { fov: 50, distance: 10 });
  const field = dust(stage, 900, (random) => [
    (random() - 0.5) * 34, (random() - 0.5) * 22, (random() - 0.5) * 18 - 4,
  ], 20260101, 0.09);
  stage.scene.add(field);

  stage.update = (time, still) => {
    if (still) return;
    easePointer();
    field.rotation.y = time * 0.012 + pointer.x * 0.05;
    field.rotation.x = Math.sin(time * 0.05) * 0.06 + pointer.y * 0.04;
    field.position.y = window.scrollY * 0.0016;
  };
  stage.paint();
}

/* ---------- Hero: the ledger core -------------------------------------------
   A faceted gold core inside a wire shell, circled by a ring of linked blocks:
   a small picture of a chain orbiting the thing it protects. */

function buildHero(canvas) {
  const stage = new Stage(canvas, { fov: 36, distance: 14 });
  addLights(stage);
  const world = new THREE.Group();
  stage.scene.add(world);

  const gem = new THREE.Mesh(
    new THREE.IcosahedronGeometry(1.35, 0), solid(stage, 'accent', { glow: 0.16 })
  );
  const shell = wire(stage, new THREE.IcosahedronGeometry(1.95, 1), 'accent2', 0.38);
  world.add(gem, shell);

  // Orbit of blocks, linked into a chain.
  const orbit = new THREE.Group();
  orbit.rotation.set(1.15, 0.2, 0.25);
  const radius = 3.0;
  const blockGeometry = new THREE.BoxGeometry(0.34, 0.34, 0.34);
  const blocks = [];
  const count = 14;
  for (let i = 0; i < count; i++) {
    const angle = (i / count) * TAU;
    const block = new THREE.Group();
    block.add(new THREE.Mesh(blockGeometry, solid(stage, 'surface', { metalness: 0.1, roughness: 0.5 })));
    block.add(wire(stage, blockGeometry, i % 3 === 0 ? 'accent' : 'accent2', 0.95));
    block.position.set(Math.cos(angle) * radius, Math.sin(angle) * radius, 0);
    blocks.push(block);
    orbit.add(block);
  }
  orbit.add(ring(stage, radius, 'accent', 0.55));
  world.add(orbit);

  const outer = new THREE.Group();
  outer.rotation.set(-0.5, 0.6, -0.3);
  outer.add(ring(stage, 3.75, 'accent3', 0.4, 0.008));
  const nodeGeometry = new THREE.SphereGeometry(0.09, 16, 16);
  for (let i = 0; i < 3; i++) {
    const node = new THREE.Mesh(nodeGeometry, stage.tint(new THREE.MeshBasicMaterial(), 'accent3'));
    const angle = (i / 3) * TAU;
    node.position.set(Math.cos(angle) * 3.75, Math.sin(angle) * 3.75, 0);
    outer.add(node);
  }
  world.add(outer);

  const halo = dust(stage, 260, (random) => {
    const r = 2.4 + random() * 2.6, theta = random() * TAU, phi = Math.acos(2 * random() - 1);
    return [r * Math.sin(phi) * Math.cos(theta), r * Math.sin(phi) * Math.sin(theta), r * Math.cos(phi)];
  }, 7, 0.06);
  world.add(halo);

  stage.update = (time, still) => {
    const t = still ? 12 : time;
    easePointer();
    gem.rotation.set(t * 0.21, t * 0.3, 0);
    shell.rotation.set(-t * 0.07, t * 0.1, t * 0.04);
    orbit.rotation.z = 0.25 + t * 0.12;
    outer.rotation.z = -0.3 - t * 0.07;
    halo.rotation.y = t * 0.03;
    blocks.forEach((block, i) => block.rotation.set(t * 0.6 + i, t * 0.4 + i * 0.5, 0));
    if (!still) {
      world.rotation.y += (pointer.x * 0.5 - world.rotation.y) * 0.05;
      world.rotation.x += (pointer.y * 0.3 - world.rotation.x) * 0.05;
      world.position.y = Math.sin(t * 0.7) * 0.12;
    }
  };
  stage.paint();
}

/* ---------- System previews -------------------------------------------------- */

const SHAPES = {
  crystal(stage, group) {
    const core = new THREE.Mesh(new THREE.OctahedronGeometry(1.6, 0), solid(stage, 'accent', { glow: 0.14 }));
    const cage = wire(stage, new THREE.OctahedronGeometry(2.35, 0), 'accent2', 0.6);
    const shards = [];
    for (let i = 0; i < 5; i++) {
      const shard = new THREE.Mesh(new THREE.OctahedronGeometry(0.22, 0), solid(stage, 'accent3'));
      shards.push(shard);
      group.add(shard);
    }
    group.add(core, cage);
    return (t) => {
      core.rotation.y = t * 0.4;
      cage.rotation.set(t * 0.15, -t * 0.22, 0);
      shards.forEach((shard, i) => {
        const angle = t * 0.5 + (i / shards.length) * TAU;
        shard.position.set(Math.cos(angle) * 2.9, Math.sin(angle * 1.3) * 1.2, Math.sin(angle) * 2.9);
        shard.rotation.set(t + i, t * 0.7, 0);
      });
    };
  },

  knot(stage, group) {
    const knot = new THREE.Mesh(
      new THREE.TorusKnotGeometry(1.35, 0.4, 220, 28),
      solid(stage, 'accent', { flatShading: false, metalness: 0.5, roughness: 0.22, glow: 0.1 })
    );
    const shell = wire(stage, new THREE.IcosahedronGeometry(2.75, 1), 'accent2', 0.28);
    group.add(knot, shell);
    return (t) => {
      knot.rotation.set(t * 0.25, t * 0.35, 0);
      shell.rotation.set(-t * 0.08, t * 0.05, 0);
    };
  },

  stack(stage, group) {
    const slabGeometry = new THREE.BoxGeometry(2.9, 0.3, 2.9);
    const roles = ['accent', 'accent2', 'accent3', 'accent2', 'accent'];
    const slabs = roles.map((role, i) => {
      const slab = new THREE.Group();
      slab.add(new THREE.Mesh(slabGeometry, solid(stage, role, { glow: 0.08 })));
      slab.add(wire(stage, slabGeometry, 'text', 0.35));
      slab.position.y = (i - 2) * 0.72;
      group.add(slab);
      return slab;
    });
    group.rotation.x = 0.45;
    return (t) => slabs.forEach((slab, i) => {
      slab.rotation.y = t * 0.3 + Math.sin(t * 0.6 + i * 0.8) * 0.35;
      slab.position.y = (i - 2) * 0.72 + Math.sin(t * 0.9 + i) * 0.06;
    });
  },

  orbit(stage, group) {
    const planet = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1.25, 2), solid(stage, 'accent', { glow: 0.14 })
    );
    const rings = [
      [2.1, 'accent2', [1.2, 0.1, 0]], [2.7, 'accent3', [0.5, 0.9, 0.3]], [3.3, 'accent', [-0.8, 0.4, 0.6]],
    ].map(([radius, role, tilt]) => {
      const holder = new THREE.Group();
      holder.rotation.set(...tilt);
      holder.add(ring(stage, radius, role, 0.6));
      const moon = new THREE.Mesh(new THREE.SphereGeometry(0.14, 20, 20), stage.tint(new THREE.MeshBasicMaterial(), role));
      moon.position.x = radius;
      holder.add(moon);
      group.add(holder);
      return holder;
    });
    group.add(planet);
    return (t) => {
      planet.rotation.y = t * 0.3;
      rings.forEach((holder, i) => { holder.rotation.z = t * (0.35 - i * 0.09) + i; });
    };
  },

  lattice(stage, group) {
    const sphere = new THREE.SphereGeometry(0.17, 18, 18);
    const points = [];
    for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (let z = -1; z <= 1; z++) {
      const position = new THREE.Vector3(x, y, z).multiplyScalar(1.35);
      const centre = x === 0 && y === 0 && z === 0;
      const node = new THREE.Mesh(sphere, solid(stage, centre ? 'accent' : (x + y + z) % 2 ? 'accent2' : 'accent3',
        { flatShading: false, glow: 0.3 }));
      node.position.copy(position);
      if (centre) node.scale.setScalar(2.2);
      points.push(position);
      group.add(node);
    }
    const segments = [];
    points.forEach((a, i) => points.slice(i + 1).forEach((b) => {
      if (Math.abs(a.distanceTo(b) - 1.35) < 0.01) segments.push(a.x, a.y, a.z, b.x, b.y, b.z);
    }));
    const lineGeometry = new THREE.BufferGeometry();
    lineGeometry.setAttribute('position', new THREE.Float32BufferAttribute(segments, 3));
    const lineMaterial = stage.tint(new THREE.LineBasicMaterial({ transparent: true, opacity: 0.4 }), 'text');
    group.add(new THREE.LineSegments(lineGeometry, lineMaterial));
    return (t) => { group.rotation.set(0.5 + Math.sin(t * 0.3) * 0.15, t * 0.25, 0); };
  },

  prism(stage, group) {
    const prism = new THREE.Mesh(new THREE.CylinderGeometry(1.5, 1.5, 2.5, 3), solid(stage, 'accent', { glow: 0.14 }));
    const cage = wire(stage, new THREE.CylinderGeometry(2.25, 2.25, 3.4, 6), 'accent2', 0.55);
    const halo = ring(stage, 3.0, 'accent3', 0.5);
    halo.rotation.x = Math.PI / 2;
    group.add(prism, cage, halo);
    group.rotation.x = 0.35;
    return (t) => {
      prism.rotation.y = t * 0.45;
      cage.rotation.y = -t * 0.2;
      halo.position.y = Math.sin(t * 0.8) * 1.1;
    };
  },
};

function buildPreview(canvas) {
  const stage = new Stage(canvas, { fov: 36, distance: 10 });
  addLights(stage);
  const world = new THREE.Group();
  const model = new THREE.Group();
  world.add(model);
  stage.scene.add(world);
  const animate = (SHAPES[canvas.dataset.shape] || SHAPES.crystal)(stage, model);
  world.add(dust(stage, 140, (random) => {
    const r = 3 + random() * 2, theta = random() * TAU, phi = Math.acos(2 * random() - 1);
    return [r * Math.sin(phi) * Math.cos(theta), r * Math.sin(phi) * Math.sin(theta), r * Math.cos(phi)];
  }, 11, 0.06));

  // Drag to rotate, with a little inertia.
  const spin = { x: 0, y: 0, vx: 0, vy: 0, dragging: false, lastX: 0, lastY: 0 };
  const surface = canvas.parentElement;
  surface.addEventListener('pointerdown', (event) => {
    spin.dragging = true; spin.lastX = event.clientX; spin.lastY = event.clientY;
    surface.setPointerCapture(event.pointerId);
  });
  surface.addEventListener('pointermove', (event) => {
    if (!spin.dragging) return;
    spin.vy = (event.clientX - spin.lastX) * 0.008;
    spin.vx = (event.clientY - spin.lastY) * 0.008;
    spin.lastX = event.clientX; spin.lastY = event.clientY;
    spin.y += spin.vy; spin.x += spin.vx;
    stage.dirty = true;
  });
  const release = () => { spin.dragging = false; };
  surface.addEventListener('pointerup', release);
  surface.addEventListener('pointercancel', release);

  stage.update = (time, still) => {
    animate(still ? 8 : time);
    if (!spin.dragging && !still) {
      spin.y += spin.vy; spin.x += spin.vx;
      spin.vy *= 0.94; spin.vx *= 0.94;
    }
    spin.x = Math.max(-1.2, Math.min(1.2, spin.x));
    world.rotation.set(spin.x, spin.y, 0);
  };
  stage.paint();
}

/* ---------- Boot ------------------------------------------------------------- */

const builders = { backdrop: buildBackdrop, hero: buildHero, preview: buildPreview };

export function init() {
  document.querySelectorAll('canvas[data-scene]').forEach((canvas) => {
    try {
      builders[canvas.dataset.scene]?.(canvas);
    } catch (error) {
      // No WebGL: the CSS aurora and SVG fallbacks carry the design on their own.
      console.warn('3D scene unavailable:', error);
    }
  });
  if (stages.length) requestAnimationFrame(loop);
}
