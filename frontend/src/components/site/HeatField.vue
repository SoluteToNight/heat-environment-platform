<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';

// 等温线背景：干净底面上一组缓慢漂移、随呼吸变形的等温线细线。
// - 光标是一次「指尖热岛」：局部场温隆起，等温线弯出暖色热穹并带一层淡辉光；
// - 点击荡开一圈等温线波纹。
// 刻意不做色斑填充与任何数值读数：背景只是氛围，真实数据属于卡片。
const canvasRef = ref<HTMLCanvasElement | null>(null);
const wrapRef = ref<HTMLDivElement | null>(null);

const CELL = 20;              // 等温线采样间距 px
const FRAME_MS = 33;          // ~30fps
const ISLANDS = [
  { x: 0.32, y: 0.46, sigma: 230, amp: 0.28, phase: 0 },
  { x: 0.72, y: 0.30, sigma: 260, amp: 0.24, phase: 2.1 },
  { x: 0.58, y: 0.78, sigma: 280, amp: 0.26, phase: 4.2 },
];
const CONTOURS = [
  { v: 0.30, color: 'rgba(85, 168, 220, 0.30)' },
  { v: 0.44, color: 'rgba(109, 163, 139, 0.32)' },
  { v: 0.58, color: 'rgba(229, 141, 60, 0.32)' },
  { v: 0.72, color: 'rgba(214, 120, 46, 0.36)' },
  { v: 0.86, color: 'rgba(214, 71, 50, 0.40)' },
];
const POINTER_SIGMA = 170;
const POINTER_AMP = 0.45;
const POINTER_GLOW = 0.12;
const PULSE_SPEED = 0.34;     // 等温线波纹扩散速度 px/ms
const PULSE_LIFE = 1800;
const PULSE_SIGMA = 30;

let ctx: CanvasRenderingContext2D | null = null;
let raf = 0;
let running = false;
let inView = true;
let reduced = false;
let lastT = 0;
let acc = 0;
let cssW = 0;
let cssH = 0;

const pointer = { x: -9999, y: -9999, ax: -9999, ay: -9999, amp: 0, inside: false };
const pulses: Array<{ x: number; y: number; born: number }> = [];

const frac = (a: number, b: number, v: number) => {
  const d = b - a;
  return Math.max(0, Math.min(1, d === 0 ? 0.5 : (v - a) / d));
};

function hash2(ix: number, iy: number): number {
  let h = Math.imul(ix, 374761393) + Math.imul(iy, 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}
const smoothstep = (t: number) => t * t * (3 - 2 * t);

function valueNoise(x: number, y: number): number {
  const ix = Math.floor(x), iy = Math.floor(y);
  const fx = smoothstep(x - ix), fy = smoothstep(y - iy);
  const a = hash2(ix, iy), b = hash2(ix + 1, iy), c = hash2(ix, iy + 1), d = hash2(ix + 1, iy + 1);
  return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
}
const fbm = (x: number, y: number) => valueNoise(x, y) * 0.55 + valueNoise(x * 2.1, y * 2.1) * 0.28 + valueNoise(x * 4.3, y * 4.3) * 0.17;

function fieldValue(x: number, y: number, t: number): number {
  let v = 0.34 + fbm(x * 0.0016 + t * 0.000006, y * 0.0016 - t * 0.000004) * 0.34;
  for (const isl of ISLANDS) {
    const cx = (isl.x + 0.05 * Math.sin(t * 0.00013 + isl.phase)) * cssW;
    const cy = (isl.y + 0.05 * Math.cos(t * 0.00011 + isl.phase)) * cssH;
    const d2 = (x - cx) ** 2 + (y - cy) ** 2;
    v += isl.amp * Math.exp(-d2 / (2 * isl.sigma * isl.sigma));
  }
  if (pointer.amp > 0.01) {
    const d2 = (x - pointer.ax) ** 2 + (y - pointer.ay) ** 2;
    v += POINTER_AMP * pointer.amp * Math.exp(-d2 / (2 * POINTER_SIGMA * POINTER_SIGMA));
  }
  const now = performance.now();
  for (const p of pulses) {
    const age = now - p.born;
    const ring = age * PULSE_SPEED;
    const d = Math.hypot(x - p.x, y - p.y);
    v += 0.5 * Math.exp(-age / 700) * Math.exp(-((d - ring) ** 2) / (2 * PULSE_SIGMA * PULSE_SIGMA));
  }
  return Math.max(0, Math.min(1, v));
}

function cellSegments(field: Float32Array, stride: number, i: number, j: number, v: number) {
  const f0 = field[j * stride + i]!;            // 左上
  const f1 = field[j * stride + i + 1]!;        // 右上
  const f2 = field[(j + 1) * stride + i + 1]!;  // 右下
  const f3 = field[(j + 1) * stride + i]!;      // 左下
  let idx = 0;
  if (f0 > v) idx |= 8;
  if (f1 > v) idx |= 4;
  if (f2 > v) idx |= 2;
  if (f3 > v) idx |= 1;
  if (idx === 0 || idx === 15) return;
  const x = i * CELL, y = j * CELL;
  const top = () => [x + CELL * frac(f0, f1, v), y] as const;
  const right = () => [x + CELL, y + CELL * frac(f1, f2, v)] as const;
  const bottom = () => [x + CELL * frac(f3, f2, v), y + CELL] as const;
  const left = () => [x, y + CELL * frac(f0, f3, v)] as const;
  const seg = (a: readonly number[], b: readonly number[]) => { ctx!.moveTo(a[0], a[1]); ctx!.lineTo(b[0], b[1]); };
  switch (idx) {
    case 1: case 14: seg(left(), bottom()); break;
    case 2: case 13: seg(bottom(), right()); break;
    case 3: case 12: seg(left(), right()); break;
    case 4: case 11: seg(top(), right()); break;
    case 6: case 9: seg(top(), bottom()); break;
    case 7: case 8: seg(left(), top()); break;
    case 5: seg(left(), top()); seg(bottom(), right()); break;
    case 10: seg(top(), right()); seg(left(), bottom()); break;
  }
}

function resize() {
  const canvas = canvasRef.value;
  if (!canvas || !canvas.parentElement) return;
  const w = canvas.parentElement.clientWidth;
  const h = canvas.parentElement.clientHeight;
  if (!w || !h) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  cssW = w;
  cssH = h;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function drawFrame(t: number) {
  if (!ctx || !cssW || !cssH) return;
  // 指尖热穹：一层随指针的暖色淡辉光（先画，垫在等温线下面）
  if (pointer.amp > 0.02 && pointer.ax > -999) {
    const g = ctx.createRadialGradient(pointer.ax, pointer.ay, 0, pointer.ax, pointer.ay, 220);
    g.addColorStop(0, `rgba(214, 120, 46, ${(POINTER_GLOW * pointer.amp).toFixed(3)})`);
    g.addColorStop(1, 'rgba(214, 120, 46, 0)');
    ctx.fillStyle = g;
    ctx.fillRect(pointer.ax - 220, pointer.ay - 220, 440, 440);
  }
  const cols = Math.ceil(cssW / CELL);
  const rows = Math.ceil(cssH / CELL);
  const field = new Float32Array((cols + 1) * (rows + 1));
  for (let j = 0; j <= rows; j++) {
    for (let i = 0; i <= cols; i++) field[j * (cols + 1) + i] = fieldValue(i * CELL, j * CELL, t);
  }
  ctx.lineWidth = 1;
  for (const c of CONTOURS) {
    ctx.strokeStyle = c.color;
    ctx.beginPath();
    for (let j = 0; j < rows; j++) {
      for (let i = 0; i < cols; i++) cellSegments(field, cols + 1, i, j, c.v);
    }
    ctx.stroke();
  }
  // 点击涟漪：双层扩散圆环
  const now = performance.now();
  for (const p of pulses) {
    const age = now - p.born;
    const r = age * PULSE_SPEED;
    const a = Math.max(0, 1 - age / PULSE_LIFE);
    ctx.lineWidth = 2;
    ctx.strokeStyle = `rgba(214, 71, 50, ${(0.32 * a).toFixed(3)})`;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.lineWidth = 1;
    ctx.strokeStyle = `rgba(214, 120, 46, ${(0.2 * a).toFixed(3)})`;
    ctx.beginPath();
    ctx.arc(p.x, p.y, Math.max(0, r - 16), 0, Math.PI * 2);
    ctx.stroke();
  }
}

function frame() {
  raf = requestAnimationFrame(frame);
  if (!running || !inView || document.hidden) return;
  const canvas = canvasRef.value;
  if (canvas && (canvas.clientWidth !== cssW || canvas.clientHeight !== cssH)) resize();
  const now = performance.now();
  const dt = Math.min(50, now - lastT);
  lastT = now;
  acc += dt;
  if (acc < FRAME_MS) return;
  acc = 0;
  if (pointer.ax < -999) { pointer.ax = pointer.x; pointer.ay = pointer.y; }
  pointer.ax += (pointer.x - pointer.ax) * 0.1;
  pointer.ay += (pointer.y - pointer.ay) * 0.1;
  pointer.amp += ((pointer.inside ? 1 : 0) - pointer.amp) * 0.06;
  const life = now - PULSE_LIFE;
  while (pulses.length && pulses[0]!.born < life) pulses.shift();
  if (!ctx || !cssW || !cssH) return;
  ctx.clearRect(0, 0, cssW, cssH);
  drawFrame(now);
}

function start() {
  if (running || reduced) return;
  running = true;
  lastT = performance.now();
  acc = FRAME_MS;
  raf = requestAnimationFrame(frame);
}

function stop() {
  running = false;
  cancelAnimationFrame(raf);
}

function toLocal(event: PointerEvent) {
  const rect = canvasRef.value!.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

const onMove = (event: PointerEvent) => {
  const p = toLocal(event);
  pointer.x = p.x;
  pointer.y = p.y;
  pointer.inside = true;
};
const onLeave = () => { pointer.inside = false; };
const onDown = (event: PointerEvent) => {
  const p = toLocal(event);
  pulses.push({ x: p.x, y: p.y, born: performance.now() });
  if (pulses.length > 4) pulses.shift();
};
const onVisibility = () => { if (!document.hidden) lastT = performance.now(); };

let observer: IntersectionObserver | null = null;
// 容器 pointer-events-none，指针事件挂到英雄区（容器父级）才能收到
const heroTarget = () => wrapRef.value?.parentElement ?? null;

onMounted(() => {
  const canvas = canvasRef.value;
  if (!canvas) return;
  ctx = canvas.getContext('2d');
  resize();
  reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced) { drawFrame(4000); return; }
  start();
  const hero = heroTarget();
  hero?.addEventListener('pointermove', onMove);
  hero?.addEventListener('pointerleave', onLeave);
  hero?.addEventListener('pointerdown', onDown);
  window.addEventListener('resize', resize);
  document.addEventListener('visibilitychange', onVisibility);
  observer = new IntersectionObserver(entries => {
    inView = entries.some(entry => entry.isIntersecting);
  }, { threshold: 0.02 });
  if (hero) observer.observe(hero);
});

onBeforeUnmount(() => {
  stop();
  observer?.disconnect();
  const hero = heroTarget();
  hero?.removeEventListener('pointermove', onMove);
  hero?.removeEventListener('pointerleave', onLeave);
  hero?.removeEventListener('pointerdown', onDown);
  window.removeEventListener('resize', resize);
  document.removeEventListener('visibilitychange', onVisibility);
});
</script>

<template>
  <div ref="wrapRef" class="pointer-events-none absolute inset-0 overflow-hidden">
    <canvas ref="canvasRef" class="isotherm-canvas absolute inset-0 size-full" aria-hidden="true" />
  </div>
</template>
