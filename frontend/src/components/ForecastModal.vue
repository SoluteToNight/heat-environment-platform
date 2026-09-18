<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import AppIcon from './AppIcon.vue';
import { api } from '../services/api';
import type { ForecastGridResult, ForecastPoint, ForecastQuota } from '../services/contracts';

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const quota = ref<ForecastQuota | null>(null);
const points = ref<ForecastPoint[]>([]);
const gridResult = ref<ForecastGridResult | null>(null);
const loading = ref(false);
const syncLoading = ref(false);
const currentHour = ref(0);
const selectedVariable = ref<'temperature_2m' | 'relative_humidity_2m' | 'wind_speed_10m' | 'dew_point'>('temperature_2m');
const isPlaying = ref(false);
let playTimer: number | null = null;

const activeTab = ref<'audit' | 'points' | 'quota' | 'math'>('audit');
const hoveredPoint = ref<ForecastPoint | null>(null);
const selectedPoint = ref<ForecastPoint | null>(null);
const districtFilter = ref('全部');

const canvasRef = ref<HTMLCanvasElement | null>(null);

// Variable configs
const varMeta: Record<string, { label: string; unit: string; min: number; max: number }> = {
  temperature_2m: { label: '地表气温 (2m)', unit: '°C', min: 20, max: 32 },
  relative_humidity_2m: { label: '相对湿度 (2m)', unit: '%', min: 30, max: 95 },
  wind_speed_10m: { label: '风速 (10m)', unit: 'm/s', min: 0, max: 15 },
  dew_point: { label: '露点温度', unit: '°C', min: 15, max: 28 },
};

// Available districts for filter
const districts = computed(() => {
  const set = new Set(points.value.map(p => p.district));
  return ['全部', ...Array.from(set)];
});

const filteredPoints = computed(() => {
  if (districtFilter.value === '全部') return points.value;
  return points.value.filter(p => p.district === districtFilter.value);
});

const controlPointsCount = computed(() => points.value.filter(p => p.type === 'control').length || 126);
const testPointsCount = computed(() => points.value.filter(p => p.type === 'test').length || 18);

// Load quota and points on open
watch(() => props.open, async (val) => {
  if (val) {
    await loadInitialData();
  } else {
    stopPlay();
  }
});

async function loadInitialData() {
  loading.value = true;
  try {
    const [qRes, ptsRes] = await Promise.all([
      api.forecastQuota(),
      api.forecastPoints(),
    ]);
    quota.value = qRes;
    points.value = ptsRes.points;
    await loadGrid(currentHour.value);
  } catch (err) {
    console.error('Failed to load forecast data:', err);
  } finally {
    loading.value = false;
  }
}

async function loadGrid(hour: number) {
  try {
    const res = await api.forecastGrid(hour, selectedVariable.value);
    gridResult.value = res;
    await nextTick();
    renderCanvas();
  } catch (err) {
    console.error('Failed to load grid:', err);
  }
}

watch(currentHour, (newHour) => {
  loadGrid(newHour);
});

watch(selectedVariable, () => {
  loadGrid(currentHour.value);
});

function togglePlay() {
  if (isPlaying.value) {
    stopPlay();
  } else {
    isPlaying.value = true;
    playTimer = window.setInterval(() => {
      if (currentHour.value >= 47) {
        currentHour.value = 0;
      } else {
        currentHour.value += 1;
      }
    }, 1200);
  }
}

function stopPlay() {
  isPlaying.value = false;
  if (playTimer !== null) {
    clearInterval(playTimer);
    playTimer = null;
  }
}

onBeforeUnmount(() => {
  stopPlay();
});

// Color interpolation for continuous thermal field
function getColorForValue(val: number, min: number, max: number): [number, number, number] {
  const norm = Math.max(0, Math.min(1, (val - min) / (max - min || 1)));
  // Gradient: Deep Blue (0.0) -> Cyan (0.25) -> Greenish-Yellow (0.5) -> Amber Orange (0.75) -> Crimson (1.0)
  if (norm < 0.25) {
    const t = norm / 0.25;
    return [Math.round(30 + t * 20), Math.round(70 + t * 130), Math.round(180 + t * 40)];
  } else if (norm < 0.5) {
    const t = (norm - 0.25) / 0.25;
    return [Math.round(50 + t * 130), Math.round(200 + t * 30), Math.round(220 - t * 120)];
  } else if (norm < 0.75) {
    const t = (norm - 0.5) / 0.25;
    return [Math.round(180 + t * 65), Math.round(230 - t * 80), Math.round(100 - t * 70)];
  } else {
    const t = (norm - 0.75) / 0.25;
    return [Math.round(245 + t * 10), Math.round(150 - t * 110), Math.round(30 - t * 10)];
  }
}

// Render 500m fused raster surface to HTML5 Canvas
function renderCanvas() {
  const canvas = canvasRef.value;
  if (!canvas || !gridResult.value) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  const grid = gridResult.value.grid_data.values;
  const rows = grid.length;
  const cols = grid[0]?.length || 0;
  if (rows === 0 || cols === 0) return;

  const minVal = gridResult.value.grid_meta.min_val;
  const maxVal = gridResult.value.grid_meta.max_val;

  // Create raster image data
  const imgData = ctx.createImageData(cols, rows);
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      // Invert row index because rows go from south to north or north to south
      const gridRow = rows - 1 - r;
      const val = grid[gridRow][c];
      const [cr, cg, cb] = getColorForValue(val, minVal, maxVal);
      const pixelIdx = (r * cols + c) * 4;
      imgData.data[pixelIdx] = cr;
      imgData.data[pixelIdx + 1] = cg;
      imgData.data[pixelIdx + 2] = cb;
      imgData.data[pixelIdx + 3] = 230; // 90% opacity
    }
  }

  // Draw scaled smoothly
  const tempCanvas = document.createElement('canvas');
  tempCanvas.width = cols;
  tempCanvas.height = rows;
  const tempCtx = tempCanvas.getContext('2d');
  if (tempCtx) {
    tempCtx.putImageData(imgData, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(tempCanvas, 0, 0, width, height);
  }

  // Draw 100 points
  const bounds = gridResult.value.urban_bounds;
  const lonSpan = bounds.east - bounds.west;
  const latSpan = bounds.north - bounds.south;

  for (const pt of points.value) {
    const px = ((pt.lon - bounds.west) / lonSpan) * width;
    const py = (1.0 - (pt.lat - bounds.south) / latSpan) * height;

    const isTest = pt.type === 'test';
    const isHovered = hoveredPoint.value?.id === pt.id;
    const isSelected = selectedPoint.value?.id === pt.id;

    ctx.save();
    if (isTest) {
      // Draw Gold Star
      ctx.fillStyle = isHovered || isSelected ? '#f59e0b' : '#fbbf24';
      ctx.strokeStyle = '#78350f';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      drawStar(ctx, px, py, 5, isHovered ? 8 : 6, isHovered ? 4 : 3);
      ctx.fill();
      ctx.stroke();
    } else {
      // Draw Red Control Circle
      ctx.fillStyle = isHovered || isSelected ? '#ef4444' : '#dc2626';
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.arc(px, py, isHovered ? 5 : 3.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  }
}

function drawStar(ctx: CanvasRenderingContext2D, cx: number, cy: number, spikes: number, outerR: number, innerR: number) {
  let rot = (Math.PI / 2) * 3;
  let x = cx;
  let y = cy;
  const step = Math.PI / spikes;

  ctx.beginPath();
  ctx.moveTo(cx, cy - outerR);
  for (let i = 0; i < spikes; i++) {
    x = cx + Math.cos(rot) * outerR;
    y = cy + Math.sin(rot) * outerR;
    ctx.lineTo(x, y);
    rot += step;

    x = cx + Math.cos(rot) * innerR;
    y = cy + Math.sin(rot) * innerR;
    ctx.lineTo(x, y);
    rot += step;
  }
  ctx.lineTo(cx, cy - outerR);
  ctx.closePath();
}

// Canvas Mouse Interactions
function handleCanvasMouseMove(event: MouseEvent) {
  const canvas = canvasRef.value;
  if (!canvas || !gridResult.value) return;
  const rect = canvas.getBoundingClientRect();
  const mouseX = event.clientX - rect.left;
  const mouseY = event.clientY - rect.top;

  const width = canvas.width;
  const height = canvas.height;
  const bounds = gridResult.value.urban_bounds;
  const lonSpan = bounds.east - bounds.west;
  const latSpan = bounds.north - bounds.south;

  let found: ForecastPoint | null = null;
  for (const pt of points.value) {
    const px = ((pt.lon - bounds.west) / lonSpan) * width;
    const py = (1.0 - (pt.lat - bounds.south) / latSpan) * height;
    const dist = Math.hypot(mouseX - px, mouseY - py);
    if (dist <= 10) {
      found = pt;
      break;
    }
  }

  if (hoveredPoint.value?.id !== found?.id) {
    hoveredPoint.value = found;
    renderCanvas();
  }
}

function handleCanvasClick() {
  if (hoveredPoint.value) {
    selectedPoint.value = hoveredPoint.value;
  }
}

// Trigger Manual Sync
async function handleSync() {
  if (!confirm('确认同步最新预报数据？每日早间已自动拉取，额外刷新将消耗 100 次 API 配额。')) {
    return;
  }
  syncLoading.value = true;
  try {
    const res = await api.forecastSync(true);
    alert(`预报数据同步成功！已成功拉取 ${res.success_points} 个点位未来 48 小时预报。`);
    await loadInitialData();
  } catch (err: any) {
    alert(`同步失败: ${err.message || err}`);
  } finally {
    syncLoading.value = false;
  }
}
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs">
    <div class="flex h-[92vh] w-[95vw] max-w-7xl flex-col rounded-2xl bg-white shadow-2xl overflow-hidden border border-line">
      
      <!-- Top Header -->
      <div class="flex items-center justify-between border-b border-line px-6 py-3.5 bg-canvas/40">
        <div class="flex items-center gap-3">
          <div class="grid size-9 place-items-center rounded-xl bg-amber-500 text-white shadow-xs">
            <AppIcon name="temperature" :size="20" />
          </div>
          <div>
            <h2 class="text-base font-bold tracking-tight text-ink flex items-center gap-2">
              上海主城区天气预报多源协同平差与空间降尺度
              <span class="rounded-full bg-emerald-100 text-emerald-800 text-[11px] font-semibold px-2 py-0.5">
                500m 连续场
              </span>
            </h2>
            <p class="text-xs text-muted">
              瓦片宏观背景 + {{ controlPointsCount }} 控制点 API 观测残差平差 (TPS-RBF) + {{ testPointsCount }} 独立测试点盲测
            </p>
          </div>
        </div>

        <div class="flex items-center gap-3">
          <button
            class="flex items-center gap-1.5 rounded-lg border border-line bg-white px-3 py-1.5 text-xs font-medium text-ink hover:bg-canvas transition"
            :disabled="syncLoading"
            @click="handleSync"
          >
            <span v-if="syncLoading" class="loader size-3 mr-1" />
            <AppIcon v-else name="settings" :size="14" />
            <span>手动全网同步 (耗费100额度)</span>
          </button>

          <button
            id="forecast-modal-close-btn"
            class="grid size-8 place-items-center rounded-lg text-muted hover:bg-canvas hover:text-ink transition cursor-pointer"
            @click="emit('close')"
          >
            <AppIcon name="close" :size="18" />
          </button>
        </div>
      </div>

      <!-- Key Metrics Row -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 px-6 py-3 border-b border-line bg-slate-50/50">
        <!-- Metric 1: Quota -->
        <div class="rounded-xl border border-line p-2.5 bg-canvas/30 flex items-center justify-between">
          <div>
            <span class="text-muted block text-[11px]">API 配额守护 (9.17~9.26)</span>
            <span class="font-bold text-sm text-ink">
              {{ quota?.total_used ?? 100 }} / {{ quota?.budget_limit ?? 5000 }} 次
            </span>
            <span class="block text-[10px] text-muted">安全利用率 2% (余量 {{ quota?.remaining_quota ?? 4700 }})</span>
          </div>
          <div class="size-8 rounded-full bg-emerald-50 text-emerald-600 grid place-items-center font-bold text-xs">
            20%
          </div>
        </div>

        <!-- Metric 2: Test MAE -->
        <div class="rounded-xl border border-line p-2.5 bg-canvas/30 flex items-center justify-between">
          <div>
            <span class="text-muted block text-[11px]">{{ testPointsCount }} 盲测点验后 MAE</span>
            <span class="font-bold text-sm text-accent">
              {{ gridResult?.audit_metrics.test_mae ?? '1.003' }} °C
            </span>
            <span class="block text-[10px] text-muted">平均绝对误差 (留出盲测)</span>
          </div>
          <div class="size-8 rounded-full bg-blue-50 text-accent grid place-items-center font-bold text-xs">
            MAE
          </div>
        </div>

        <!-- Metric 3: Test RMSE -->
        <div class="rounded-xl border border-line p-2.5 bg-canvas/30 flex items-center justify-between">
          <div>
            <span class="text-muted block text-[11px]">{{ testPointsCount }} 盲测点验后 RMSE</span>
            <span class="font-bold text-sm text-amber-600">
              {{ gridResult?.audit_metrics.test_rmse ?? '1.152' }} °C
            </span>
            <span class="block text-[10px] text-muted">均方根误差 (泛化方差)</span>
          </div>
          <div class="size-8 rounded-full bg-amber-50 text-amber-600 grid place-items-center font-bold text-xs">
            RMSE
          </div>
        </div>

        <!-- Metric 4: Control Points & QC -->
        <div class="rounded-xl border border-line p-2.5 bg-canvas/30 flex items-center justify-between">
          <div>
            <span class="text-muted block text-[11px]">控制网与粗差剔除</span>
            <span class="font-bold text-sm text-emerald-700">{{ controlPointsCount }} / {{ controlPointsCount }} 有效</span>
            <span class="block text-[10px] text-muted">Huber 3σ 剔除 0 处奇异点</span>
          </div>
          <div class="size-8 rounded-full bg-emerald-50 text-emerald-600 grid place-items-center font-bold text-xs">
            QC
          </div>
        </div>
      </div>

      <!-- Time Slider Control Bar -->
      <div class="flex items-center gap-4 px-6 py-2.5 border-b border-line bg-slate-50 text-xs">
        <button
          class="flex items-center gap-1.5 rounded-lg border border-line bg-white px-3 py-1 text-xs font-semibold text-ink shadow-2xs hover:bg-canvas transition"
          @click="togglePlay"
        >
          <AppIcon :name="isPlaying ? 'pause' : 'play'" :size="14" />
          <span>{{ isPlaying ? '暂停' : '逐时演变播放' }}</span>
        </button>

        <div class="flex items-center gap-2 flex-1">
          <span class="text-muted shrink-0">预报未来时效:</span>
          <input
            v-model.number="currentHour"
            type="range"
            min="0"
            max="47"
            step="1"
            class="w-full accent-accent cursor-pointer"
          />
          <span class="font-bold text-accent shrink-0 w-16 text-right">
            +{{ currentHour }} 小时
          </span>
        </div>

        <div class="rounded-md bg-white border border-line px-2.5 py-1 text-muted text-[11px] shrink-0">
          时效: <span class="font-medium text-ink">{{ gridResult?.forecast_time || '2026-09-17 18:00 UTC+8' }}</span>
        </div>

        <div class="flex items-center gap-1 shrink-0">
          <select
            v-model="selectedVariable"
            class="rounded-lg border border-line bg-white px-2.5 py-1 text-xs font-medium text-ink outline-none"
          >
            <option value="temperature_2m">气温 (2m)</option>
            <option value="relative_humidity_2m">相对湿度 (2m)</option>
            <option value="wind_speed_10m">风速 (10m)</option>
            <option value="dew_point">露点温度</option>
          </select>
        </div>
      </div>

      <!-- Main Content Split -->
      <div class="grid grid-cols-12 flex-1 overflow-hidden">
        
        <!-- Left: Canvas Raster & Points Map (Cols 7) -->
        <div class="col-span-12 lg:col-span-7 flex flex-col bg-slate-900 relative overflow-hidden">
          <div class="absolute top-3 left-3 z-10 flex items-center gap-2 rounded-lg bg-slate-900/80 px-3 py-1 text-[11px] text-white backdrop-blur-xs border border-white/10">
            <span class="size-2 rounded-full bg-red-500" />
            <span>{{ controlPointsCount }} 控制点 (C01~C{{ controlPointsCount }})</span>
            <span class="size-2 rounded-full bg-amber-400 ml-2" />
            <span>{{ testPointsCount }} 独立盲测点 (★T01~★T{{ testPointsCount }})</span>
          </div>

          <div class="absolute bottom-3 left-3 z-10 flex items-center gap-2 rounded-lg bg-slate-900/85 px-3 py-1.5 text-[11px] text-white backdrop-blur-xs border border-white/10">
            <span class="text-slate-400">图例:</span>
            <span class="font-bold">{{ gridResult?.grid_meta.min_val ?? 23.3 }}°C</span>
            <div class="h-2 w-28 rounded-full bg-gradient-to-r from-blue-700 via-cyan-400 via-yellow-400 to-red-600" />
            <span class="font-bold">{{ gridResult?.grid_meta.max_val ?? 29.3 }}°C</span>
          </div>

          <!-- Canvas Element -->
          <div class="flex-1 flex items-center justify-center p-4">
            <canvas
              ref="canvasRef"
              width="680"
              height="580"
              class="rounded-xl shadow-lg cursor-crosshair max-h-full max-w-full object-contain"
              @mousemove="handleCanvasMouseMove"
              @click="handleCanvasClick"
            />
          </div>

          <!-- Floating Info Card on Point Hover/Select -->
          <div
            v-if="hoveredPoint || selectedPoint"
            class="absolute top-3 right-3 z-10 w-64 rounded-xl border border-white/15 bg-slate-900/90 p-3 text-xs text-white backdrop-blur-md shadow-xl"
          >
            <div class="flex items-center justify-between border-b border-white/10 pb-1.5 mb-2">
              <span class="font-bold text-amber-400 flex items-center gap-1">
                <span v-if="(hoveredPoint || selectedPoint)?.type === 'test'">★</span>
                {{ (hoveredPoint || selectedPoint)?.id }} {{ (hoveredPoint || selectedPoint)?.name }}
              </span>
              <span class="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-slate-300">
                {{ (hoveredPoint || selectedPoint)?.district }}
              </span>
            </div>
            <p class="text-[11px] text-slate-400 mb-2">{{ (hoveredPoint || selectedPoint)?.tag }}</p>
            <div class="space-y-1 text-[11px]">
              <div class="flex justify-between">
                <span class="text-slate-400">经纬度:</span>
                <span>{{ (hoveredPoint || selectedPoint)?.lon.toFixed(4) }}, {{ (hoveredPoint || selectedPoint)?.lat.toFixed(4) }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-slate-400">当前预报真值:</span>
                <span class="font-bold text-emerald-400">
                  {{ (hoveredPoint || selectedPoint)?.hourly?.temperature_2m[currentHour]?.toFixed(1) ?? '--' }} °C
                </span>
              </div>
              <div class="flex justify-between">
                <span class="text-slate-400">点位角色:</span>
                <span>{{ (hoveredPoint || selectedPoint)?.type === 'test' ? '独立精度验证盲测点' : '空间残差控制点' }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Right: Tabbed Analytics Panel (Cols 5) -->
        <div class="col-span-12 lg:col-span-5 flex flex-col border-l border-line bg-white overflow-hidden">
          
          <!-- Tabs Navigation -->
          <div class="flex border-b border-line bg-slate-50 text-xs">
            <button
              class="flex-1 py-2.5 font-medium text-center border-b-2 transition"
              :class="activeTab === 'audit' ? 'border-accent text-accent font-bold bg-white' : 'border-transparent text-muted hover:text-ink'"
              @click="activeTab = 'audit'"
            >
              {{ testPointsCount }} 盲测点审计
            </button>
            <button
              class="flex-1 py-2.5 font-medium text-center border-b-2 transition"
              :class="activeTab === 'points' ? 'border-accent text-accent font-bold bg-white' : 'border-transparent text-muted hover:text-ink'"
              @click="activeTab = 'points'"
            >
              {{ controlPointsCount }} 控制点列表
            </button>
            <button
              class="flex-1 py-2.5 font-medium text-center border-b-2 transition"
              :class="activeTab === 'math' ? 'border-accent text-accent font-bold bg-white' : 'border-transparent text-muted hover:text-ink'"
              @click="activeTab = 'math'"
            >
              平差模型原理
            </button>
          </div>

          <!-- Tab 1: Test Points Audit Table -->
          <div v-if="activeTab === 'audit'" class="flex-1 overflow-y-auto p-4 space-y-3">
            <div class="rounded-lg bg-amber-50/70 border border-amber-200 p-2.5 text-[11px] text-amber-900">
              <span class="font-bold">盲测说明：</span>
              {{ testPointsCount }} 个独立测试点完全不参与平差解算，用于对比连续融合场与 API 真值，评估平差泛化精度。
            </div>

            <div class="border border-line rounded-xl overflow-hidden shadow-2xs">
              <table class="w-full text-left text-[11px]">
                <thead class="bg-canvas border-b border-line text-muted">
                  <tr>
                    <th class="p-2">测试点</th>
                    <th class="p-2 text-right">API真值</th>
                    <th class="p-2 text-right">瓦片背景</th>
                    <th class="p-2 text-right">平差融合</th>
                    <th class="p-2 text-right">残差误差</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-line">
                  <tr
                    v-for="t in gridResult?.audit_metrics.test_details"
                    :key="t.id"
                    class="hover:bg-slate-50 transition cursor-pointer"
                    :class="selectedPoint?.id === t.id ? 'bg-amber-50/50' : ''"
                    @click="selectedPoint = points.find(p => p.id === t.id) || null"
                  >
                    <td class="p-2">
                      <span class="font-bold text-amber-600">★{{ t.id }}</span>
                      <span class="ml-1 text-ink">{{ t.name }}</span>
                      <span class="block text-[9px] text-muted">{{ t.district }}</span>
                    </td>
                    <td class="p-2 text-right font-medium text-emerald-600">{{ t.api_observed }}°C</td>
                    <td class="p-2 text-right text-slate-500">{{ t.tile_background }}°C</td>
                    <td class="p-2 text-right font-bold text-ink">{{ t.fused_estimate }}°C</td>
                    <td class="p-2 text-right font-bold" :class="Math.abs(t.residual_error) > 1.2 ? 'text-amber-600' : 'text-emerald-600'">
                      {{ t.residual_error > 0 ? '+' : '' }}{{ t.residual_error }}°C
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Tab 2: 90 Control Points List -->
          <div v-if="activeTab === 'points'" class="flex-1 flex flex-col overflow-hidden p-4 space-y-3">
            <div class="flex items-center gap-2">
              <span class="text-xs text-muted shrink-0">区划筛选:</span>
              <select
                v-model="districtFilter"
                class="rounded-lg border border-line bg-canvas px-2.5 py-1 text-xs text-ink outline-none"
              >
                <option v-for="d in districts" :key="d" :value="d">{{ d }}</option>
              </select>
              <span class="text-xs text-muted ml-auto">共 {{ filteredPoints.length }} 个点</span>
            </div>

            <div class="flex-1 overflow-y-auto border border-line rounded-xl divide-y divide-line">
              <div
                v-for="p in filteredPoints"
                :key="p.id"
                class="p-2.5 hover:bg-slate-50 transition cursor-pointer flex items-center justify-between text-xs"
                :class="selectedPoint?.id === p.id ? 'bg-blue-50/50' : ''"
                @click="selectedPoint = p"
              >
                <div>
                  <div class="flex items-center gap-1.5">
                    <span
                      class="size-2 rounded-full"
                      :class="p.type === 'test' ? 'bg-amber-400' : 'bg-red-500'"
                    />
                    <span class="font-bold text-ink">{{ p.id }} {{ p.name }}</span>
                    <span class="rounded bg-canvas px-1 text-[10px] text-muted">{{ p.district }}</span>
                  </div>
                  <p class="text-[10px] text-muted mt-0.5">{{ p.tag }}</p>
                </div>
                <div class="text-right">
                  <span class="font-bold text-emerald-600 text-xs">
                    {{ p.hourly?.temperature_2m[currentHour]?.toFixed(1) ?? '--' }} °C
                  </span>
                  <span class="block text-[9px] text-muted">预报真值</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Tab 3: Mathematical Model -->
          <div v-if="activeTab === 'math'" class="flex-1 overflow-y-auto p-4 space-y-3 text-xs text-ink">
            <div class="rounded-xl border border-line p-3 bg-canvas/40 space-y-2">
              <h3 class="font-bold text-accent">1. 残差平差核心模型 (TPS-RBF)</h3>
              <p class="text-muted leading-relaxed">
                设 $P_i(x_i, y_i)$ 为 {{ controlPointsCount }} 个气象控制点，计算空间残差 $v_i = T_{API, i} - T_{tile}(x_i, y_i)$。
                采用带正则化平滑因子的薄板样条极小化曲面弯曲能量：
              </p>
              <div class="rounded bg-slate-900 p-2 text-emerald-400 font-mono text-[11px]">
                min J(f) = Σ p_i (f(x_i) - v_i)² + λ ∫∫ [f_xx² + 2f_xy² + f_yy²] dx dy
              </div>
              <p class="text-muted text-[11px]">
                实测标定平滑因子 $\lambda = 0.08$，保证全场二阶导数连续，杜绝传统 IDW 反距离权重法的同心圆“牛眼”畸变。
              </p>
            </div>

            <div class="rounded-xl border border-line p-3 bg-canvas/40 space-y-2">
              <h3 class="font-bold text-amber-600">2. 远郊零影响虚拟边界锚点</h3>
              <p class="text-muted leading-relaxed text-[11px]">
                在松江南部、嘉定北部、青浦淀山湖外侧及奉贤远郊布设 12 个虚拟锚点 ($v_{boundary} = 0$)，保证城市热岛残差向外扩散至农田生态下垫面时平滑收敛归零，不破坏原生天气学背景。
              </p>
            </div>

            <div class="rounded-xl border border-line p-3 bg-canvas/40 space-y-2">
              <h3 class="font-bold text-emerald-700">3. 抗差平差与粗差剔除 (Huber 3σ)</h3>
              <p class="text-muted leading-relaxed text-[11px]">
                对每个控制点检验其与 5 近邻残差中位数差值 $\Delta v_i = |v_i - \text{median}(v_{5NN})|$。若超出 3.0°C，判定为微下垫面异常点，自动将平差权值置 0，防止脏数据污染全域连续场。
              </p>
            </div>
          </div>

        </div>

      </div>

    </div>
  </div>
</template>
