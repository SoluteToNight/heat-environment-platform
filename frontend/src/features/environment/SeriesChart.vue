<script setup lang="ts">
import { computed, ref } from 'vue';
import type { SeriesResult } from '../../services/contracts';
import { localTime } from '../../services/format';
const props = defineProps<{ series: SeriesResult; current?: string | null; times: string[] }>();
const emit = defineEmits<{ choose: [time: string] }>();
const table = ref(false);
const selected = ref<number | null>(null);
const valid = computed(() => props.series.points.map(point => point.value).filter((value): value is number => value !== null));
const minimum = computed(() => Math.floor(Math.min(...valid.value, 0 === valid.value.length ? 0 : Infinity) - 1));
const maximum = computed(() => Math.ceil(Math.max(...valid.value, valid.value.length ? -Infinity : 1) + 1));
const x = (index: number) => 25 + index * 240 / Math.max(1, props.series.points.length - 1);
const y = (value: number) => 103 - (value - minimum.value) / (maximum.value - minimum.value) * 80;
const segments = computed(() => {
  const paths: string[] = []; let path = '';
  props.series.points.forEach((point, index) => {
    if (point.value === null) { if (path) paths.push(path); path = ''; return; }
    path += `${path ? ' L' : 'M'}${x(index)},${y(point.value)}`;
  });
  if (path) paths.push(path); return paths;
});
const currentX = computed(() => {
  if (!props.current || !props.series.points.length) return null;
  const target = Date.parse(props.current);
  const first = Date.parse(props.series.points[0]?.time || '');
  const last = Date.parse(props.series.points.at(-1)?.time || '');
  if (!Number.isFinite(target) || !Number.isFinite(first) || !Number.isFinite(last) || last <= first) return null;
  if (target < first || target > last) return null;
  const ratio = (target - first) / (last - first);
  return 25 + ratio * 240;
});
const matchedPointTime = computed(() => {
  if (!props.current || !props.series.points.length) return '';
  const exact = props.series.points.find(p => p.time === props.current);
  if (exact) return exact.time;
  const target = Date.parse(props.current);
  if (!Number.isFinite(target)) return '';
  const best = props.series.points.reduce((closest, p) => Math.abs(Date.parse(p.time) - target) < Math.abs(Date.parse(closest.time) - target) ? p : closest, props.series.points[0]!);
  return best?.time || '';
});
</script>
<template>
  <div class="flex items-center justify-between"><h3 class="section-title">逐时变化 <span class="ml-1 text-xs font-normal text-muted">{{ series.unit }}</span></h3><button class="text-button" @click="table = !table">{{ table ? '查看图表' : '数据表' }}</button></div>
  <div v-if="!table" class="relative mt-2">
    <svg viewBox="0 0 280 138" role="img" :aria-label="`逐时变化，单位 ${series.unit}，缺测处断线`" class="w-full overflow-visible">
      <g v-for="fraction in [0, .5, 1]" :key="fraction"><line x1="25" x2="268" :y1="23 + fraction * 80" :y2="23 + fraction * 80" stroke="#e4e9e2" stroke-dasharray="3 4" /><text x="0" :y="27 + fraction * 80" fill="#67776d" font-size="10">{{ Math.round(maximum - fraction * (maximum - minimum)) }}</text></g>
      <template v-if="series.points.some(point => point.interval_start)">
        <rect v-for="(point, index) in series.points.filter(point => point.value !== null)" :key="point.time" :x="x(series.points.indexOf(point)) - 3" :y="y(point.value!)" :height="103 - y(point.value!)" width="6" rx="1" fill="#93b4a0" />
      </template>
      <path v-for="(path, index) in segments" v-else :key="index" :d="path" fill="none" stroke="#367b60" stroke-width="2" />
      <line v-if="currentX !== null" :x1="currentX" :x2="currentX" y1="20" y2="105" stroke="#176c53" stroke-width="1.5" stroke-dasharray="2 2" opacity="0.85" />
      <template v-for="(point, index) in series.points" :key="point.time">
        <g v-if="point.value !== null" @mouseenter="selected = index" @mouseleave="selected = null">
          <circle :cx="x(index)" :cy="y(point.value)" :r="point.time === current ? 4 : 2" fill="#176c53" />
          <circle :cx="x(index)" :cy="y(point.value)" r="9" fill="transparent" />
        </g>
      </template>
      <text x="25" y="132" fill="#67776d" font-size="11">{{ localTime(series.points[0]?.time, true) }}</text><text x="265" y="132" text-anchor="end" fill="#67776d" font-size="11">{{ localTime(series.points.at(-1)?.time, true) }}</text>
    </svg>
    <p v-if="selected !== null" class="absolute right-0 top-0 rounded bg-white px-2 text-xs shadow-sm">{{ localTime(series.points[selected]?.time) }} · {{ series.points[selected]?.value }} {{ series.unit }}</p>
    <label class="mt-3 flex items-center justify-between text-xs text-muted">查看时刻<select class="max-w-36 rounded border border-line bg-white px-2 py-2 text-ink" :value="matchedPointTime || ''" @change="emit('choose', ($event.target as HTMLSelectElement).value)"><option value="" disabled>选择时间</option><option v-for="point in series.points" :key="point.time" :value="point.time" :disabled="point.value === null">{{ localTime(point.time, true) }}</option></select></label>
  </div>
  <div v-else class="mt-3 max-h-60 overflow-auto"><table class="w-full text-left text-xs"><thead class="sticky top-0 bg-white"><tr><th class="py-2">上海时间</th><th>值（{{ series.unit }}）</th></tr></thead><tbody><tr v-for="point in series.points" :key="point.time" class="border-t border-line"><td class="py-2">{{ localTime(point.time, true) }}<template v-if="point.interval_end">–{{ localTime(point.interval_end) }} 平均</template></td><td>{{ point.value ?? '缺测' }}</td></tr></tbody></table></div>
</template>
