<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import AppIcon from '../AppIcon.vue';
import { api, errorMessage, isDemo } from '../../services/api';
import type { Coordinates, UtciReading, WeatherPoint, WeatherReading } from '../../services/contracts';

const emit = defineEmits<{ location: [coords: Coordinates]; reading: [reading: UtciReading] }>();

// 详细态（大卡：完整读数 + 48h 曲线）与简略态（重叠小卡：核心读数一行），数据两条态均持续加载
defineProps<{ detailed?: boolean }>();

const FALLBACK: Coordinates = [121.4737, 31.2304]; // 上海 · 人民广场

type Phase = 'locating' | 'loading' | 'ready' | 'error';

const phase = ref<Phase>('locating');
const errorMsg = ref('');
const fallbackUsed = ref(false);
const location = ref<Coordinates | null>(null);
const data = ref<WeatherPoint | null>(null);
const mode = ref<'sun' | 'shade'>('sun');
const selected = ref(0);
const hover = ref<number | null>(null);
const svgRef = ref<SVGSVGElement | null>(null);
let abortController: AbortController | null = null;
let geoTimer: ReturnType<typeof setTimeout> | null = null;

const window_ = computed(() => {
  if (!data.value) return [] as WeatherReading[];
  return data.value.hourly.slice(data.value.now_index, data.value.now_index + 48);
});
const activeIndex = computed(() => hover.value ?? Math.min(selected.value, Math.max(0, window_.value.length - 1)));
const active = computed(() => window_.value[activeIndex.value] ?? data.value?.current ?? null);
const seriesValue = (reading: WeatherReading) => (mode.value === 'sun' ? reading.utci_c : reading.utci_shade_c);

const W = 320;
const H = 118;
const geometry = computed(() => {
  const values = window_.value.map(seriesValue);
  if (!values.length) return null;
  const min = Math.min(...values) - 1.2;
  const max = Math.max(...values) + 1.2;
  const pts = values.map((v, i) => [
    (i / (values.length - 1)) * (W - 16) + 8,
    H - 14 - ((v - min) / (max - min)) * (H - 34),
  ] as const);
  let line = `M ${pts[0]![0]},${pts[0]![1]}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1]!;
    const [x1, y1] = pts[i]!;
    const dx = (x1 - x0) / 2;
    line += ` C ${x0 + dx},${y0} ${x1 - dx},${y1} ${x1},${y1}`;
  }
  const peakIndex = values.reduce((best, v, i) => (v > values[best]! ? i : best), 0);
  const xLabels = [0, 12, 24, 36, values.length - 1].map(index => ({
    index,
    x: pts[index]![0]!,
    label: `${window_.value[index]!.time.slice(8, 10)}日${window_.value[index]!.time.slice(11, 13)}时`,
  }));
  return { line, area: `${line} L ${pts.at(-1)![0]},${H - 4} L ${pts[0]![0]},${H - 4} Z`, pts, peakIndex, xLabels, nowX: pts[0]![0]! };
});
const peakReading = computed(() => {
  if (!geometry.value || !window_.value.length) return null;
  return window_.value[geometry.value.peakIndex] ?? null;
});

function chipStyle(color: string) {
  const r = parseInt(color.slice(1, 3), 16);
  const g = parseInt(color.slice(3, 5), 16);
  const b = parseInt(color.slice(5, 7), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return { backgroundColor: color, color: luminance > 0.62 ? '#263b36' : '#ffffff' };
}

function locate() {
  phase.value = 'locating';
  errorMsg.value = '';
  // 演示模式固定为上海合成场景：打卡、场景等演示数据均以上海为锚，不请求真实定位
  if (isDemo || !('geolocation' in navigator)) return useFallback();
  geoTimer = setTimeout(() => useFallback(), 9000); // 定位失败/被拒时回退到默认城市
  navigator.geolocation.getCurrentPosition(
    position => {
      if (geoTimer) clearTimeout(geoTimer);
      geoTimer = null;
      fallbackUsed.value = false;
      location.value = [position.coords.longitude, position.coords.latitude];
      emit('location', location.value);
      void load();
    },
    () => {
      if (geoTimer) clearTimeout(geoTimer);
      geoTimer = null;
      useFallback();
    },
    { timeout: 8500, maximumAge: 600_000 },
  );
}

function useFallback() {
  fallbackUsed.value = true;
  location.value = FALLBACK;
  emit('location', location.value);
  void load();
}

async function load() {
  if (!location.value) return;
  abortController?.abort();
  abortController = new AbortController();
  phase.value = 'loading';
  errorMsg.value = '';
  try {
    data.value = await api.weatherPoint(location.value[0], location.value[1], abortController.signal);
    selected.value = 0;
    hover.value = null;
    emit('reading', {
      utciC: data.value.current.utci_c,
      stressZh: data.value.current.stress.zh,
      stressColor: data.value.current.stress.color,
    });
    phase.value = 'ready';
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') return;
    errorMsg.value = errorMessage(err);
    phase.value = 'error';
  }
}

function scrub(event: PointerEvent) {
  const svg = svgRef.value;
  if (!svg || !window_.value.length) return;
  const rect = svg.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  hover.value = Math.round(ratio * (window_.value.length - 1));
}

function pin() {
  if (hover.value !== null) selected.value = hover.value;
}

function fmtClock(time: string) {
  return time.slice(11, 16);
}

onMounted(locate);
onBeforeUnmount(() => {
  if (geoTimer) clearTimeout(geoTimer);
  abortController?.abort();
});
</script>

<template>
  <!-- 简略态：重叠小卡，点击由外层展开为详细态 -->
  <div v-if="!detailed" class="glass-card relative p-4">
    <div class="flex items-center gap-2">
      <span class="grid size-7 place-items-center rounded-lg bg-green-soft text-accent"><AppIcon name="gauge" :size="15" /></span>
      <p class="text-xs font-bold text-ink">此地实时体感</p>
      <AppIcon name="expand" :size="14" class="ml-auto shrink-0 text-muted" />
    </div>
    <template v-if="data && active">
      <div class="mt-2.5 flex items-end justify-between gap-2">
        <p class="text-[26px] font-bold leading-7 tracking-tight text-ink">
          {{ (mode === 'sun' ? active.utci_c : active.utci_shade_c).toFixed(1) }}<span class="ml-0.5 text-sm font-semibold text-muted">°C</span>
        </p>
        <span class="sensation-label border" :style="chipStyle(active.stress.color)">
          <span class="size-2 rounded-full" :style="{ backgroundColor: active.stress.color }" />
          {{ active.stress.zh }}
        </span>
      </div>
      <p class="mt-1.5 text-[11px] text-muted">
        气温 {{ active.air_temperature_c.toFixed(1) }}° · 湿度 {{ active.relative_humidity_pct }}% · 更新于 {{ fmtClock(data.current.time) }}
      </p>
    </template>
    <p v-else-if="phase === 'error'" class="mt-2.5 text-[11px] leading-4 text-muted">实时数据暂不可用，展开后可重试。</p>
    <p v-else class="mt-2.5 flex items-center gap-2 text-[11px] text-muted"><span class="loader size-3" /> 正在同步实时气象…</p>
  </div>

  <!-- 详细态：完整观测卡 -->
  <div v-else class="glass-card relative p-6">
    <template v-if="phase === 'locating' || phase === 'loading'">
      <div class="flex min-h-[19rem] flex-col items-center justify-center text-center" aria-busy="true">
        <span class="loader" />
        <p class="mt-4 text-xs font-medium text-ink">{{ phase === 'locating' ? '正在获取你的位置…' : '正在同步此地实时气象…' }}</p>
        <p class="mt-1 text-[11px] text-muted">{{ phase === 'locating' ? '拒绝授权将使用默认位置（上海）' : 'Open-Meteo · 官方 UTCI 多项式逐时计算' }}</p>
      </div>
    </template>

    <template v-else-if="phase === 'error'">
      <div class="flex min-h-[19rem] flex-col items-center justify-center text-center">
        <span class="grid size-11 place-items-center rounded-xl bg-[#f9e8de] text-terracotta"><AppIcon name="weather" :size="22" /></span>
        <p class="mt-4 text-sm font-semibold text-ink">实时体感数据暂不可用</p>
        <p class="status-warning mt-3 text-xs">{{ errorMsg }}</p>
        <div class="mt-4 flex gap-2">
          <button class="button text-xs py-1.5" @click="locate()"><AppIcon name="locate" :size="14" />重新定位</button>
          <button class="button-primary text-xs py-1.5" @click="load()"><AppIcon name="clock" :size="14" />重试</button>
        </div>
      </div>
    </template>

    <template v-else-if="data && active">
      <div class="flex items-center justify-between text-xs">
        <span class="flex items-center gap-1.5 font-medium text-ink">
          <span v-if="!isDemo" class="live-dot size-2 rounded-full bg-accent" />
          此地实时体感 · UTCI
        </span>
        <div class="flex items-center gap-1.5">
          <span class="rounded-full px-2 py-0.5 text-[10px] font-medium" :class="isDemo ? 'bg-canvas text-muted' : 'bg-green-soft text-accent'">
            {{ isDemo ? '演示合成' : '实时数据' }}
          </span>
          <button class="icon-button size-7" title="重新定位" aria-label="重新定位" @click="locate()">
            <AppIcon name="locate" :size="14" />
          </button>
        </div>
      </div>

      <p class="mt-2 text-[11px] text-muted">
        {{ Math.abs(data.location.latitude).toFixed(2) }}°{{ data.location.latitude >= 0 ? 'N' : 'S' }},
        {{ Math.abs(data.location.longitude).toFixed(2) }}°{{ data.location.longitude >= 0 ? 'E' : 'W' }}
        · 更新于 {{ fmtClock(data.current.time) }}
        <span v-if="fallbackUsed" class="text-terracotta">· 定位不可用，已用默认位置</span>
      </p>

      <div class="mt-3 flex items-end justify-between">
        <div>
          <p class="text-[11px] font-medium tracking-wide text-muted">{{ mode === 'sun' ? '阳光下体感' : '阴影处体感' }}<span v-if="activeIndex > 0" class="ml-1 text-terracotta">· {{ fmtClock(active.time) }}</span></p>
          <p class="mt-1 text-5xl font-bold tabular-nums tracking-tight text-ink">
            {{ (mode === 'sun' ? active.utci_c : active.utci_shade_c).toFixed(1) }}<span class="ml-1 text-lg font-semibold text-muted">°C</span>
          </p>
        </div>
        <span class="sensation-label mb-1 border" :style="chipStyle(active.stress.color)">
          <span class="size-2 rounded-full" :style="{ backgroundColor: active.stress.color }" />
          {{ active.stress.zh }}
        </span>
      </div>

      <div class="mt-3 grid grid-cols-4 gap-1.5 text-center">
        <div class="rounded-lg bg-canvas px-1 py-2">
          <p class="text-[10px] text-muted">气温</p>
          <p class="text-[13px] font-semibold tabular-nums text-ink">{{ active.air_temperature_c.toFixed(1) }}°</p>
        </div>
        <div class="rounded-lg bg-canvas px-1 py-2">
          <p class="text-[10px] text-muted">湿度</p>
          <p class="text-[13px] font-semibold tabular-nums text-ink">{{ active.relative_humidity_pct }}%</p>
        </div>
        <div class="rounded-lg bg-canvas px-1 py-2">
          <p class="text-[10px] text-muted">风速</p>
          <p class="text-[13px] font-semibold tabular-nums text-ink">{{ active.wind_speed_ms.toFixed(1) }}</p>
        </div>
        <div class="rounded-lg bg-canvas px-1 py-2">
          <p class="text-[10px] text-muted">辐射</p>
          <p class="text-[13px] font-semibold tabular-nums text-ink">{{ active.shortwave_radiation_wm2 }}</p>
        </div>
      </div>

      <!-- 48h 交互曲线：悬停/点按 scrub，点击固定 -->
      <div class="relative mt-4">
        <div class="absolute -top-1 right-0 z-10 flex overflow-hidden rounded-full border border-line bg-white text-[10px] font-medium">
          <button
            class="px-2.5 py-0.5 transition-colors"
            :class="mode === 'sun' ? 'bg-accent text-white' : 'text-muted hover:text-ink'"
            @click="mode = 'sun'"
          >阳光下</button>
          <button
            class="px-2.5 py-0.5 transition-colors"
            :class="mode === 'shade' ? 'bg-accent text-white' : 'text-muted hover:text-ink'"
            @click="mode = 'shade'"
          >阴影处</button>
        </div>
        <svg
          ref="svgRef"
          :viewBox="`0 0 ${W} ${H}`"
          class="w-full cursor-crosshair touch-none select-none"
          role="img"
          aria-label="未来 48 小时 UTCI 逐时曲线，悬停或点按查看具体时刻"
          @pointermove="scrub"
          @pointerleave="hover = null"
          @click="pin"
        >
          <defs>
            <linearGradient id="utci-line" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stop-color="#55a8dc" />
              <stop offset="55%" stop-color="#e58d3c" />
              <stop offset="100%" stop-color="#d64732" />
            </linearGradient>
            <linearGradient id="utci-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#176c53" stop-opacity="0.2" />
              <stop offset="100%" stop-color="#176c53" stop-opacity="0" />
            </linearGradient>
          </defs>
          <template v-if="geometry">
            <path :d="geometry.area" fill="url(#utci-fill)" />
            <line :x1="geometry.nowX" :x2="geometry.nowX" :y1="6" :y2="H - 6" stroke="#a5bfae" stroke-width="1" stroke-dasharray="3 3" />
            <text :x="geometry.nowX + 3" y="12" class="fill-[#64786f] text-[9px]">现在</text>
            <path :d="geometry.line" fill="none" stroke="url(#utci-line)" stroke-width="2.5" stroke-linecap="round" />
            <circle :cx="geometry.pts[geometry.peakIndex]![0]" :cy="geometry.pts[geometry.peakIndex]![1]" r="3.5" fill="#d64732" stroke="#fff" stroke-width="1.5" />
            <text
              :x="Math.min(geometry.pts[geometry.peakIndex]![0], W - 46)"
              :y="geometry.pts[geometry.peakIndex]![1] - 8"
              class="fill-[#d64732] text-[10px] font-semibold"
            >峰值 {{ peakReading ? seriesValue(peakReading).toFixed(1) : '' }}°C · {{ peakReading ? fmtClock(peakReading.time) : '' }}</text>
            <g v-if="activeIndex > 0 || hover !== null">
              <line :x1="geometry.pts[activeIndex]![0]" :x2="geometry.pts[activeIndex]![0]" :y1="8" :y2="H - 8" stroke="#176c53" stroke-width="1" stroke-opacity="0.5" />
              <circle :cx="geometry.pts[activeIndex]![0]" :cy="geometry.pts[activeIndex]![1]" r="4.5" fill="#176c53" stroke="#fff" stroke-width="2" />
            </g>
          </template>
        </svg>
        <div v-if="geometry" class="flex justify-between text-[10px] tabular-nums text-muted">
          <span v-for="label in geometry.xLabels" :key="label.index">{{ label.label }}</span>
        </div>
      </div>

      <p class="mt-3 border-t border-line/70 pt-2.5 text-[10px] leading-4 text-muted">
        {{ isDemo ? '演示模式：合成数据与近似公式，不代表真实观测。' : `来源 ${data.source.provider} · ${data.source.utci_model}` }}<br />
        坐标仅用于向天气服务商查询，不写入平台数据库。
      </p>
    </template>
  </div>
</template>
