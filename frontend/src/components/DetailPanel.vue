<script setup lang="ts">
import { computed, ref } from 'vue';
import AppIcon from './AppIcon.vue';
import SeriesChart from '../features/environment/SeriesChart.vue';
import { useWorkspace } from '../stores/workspace';
import { effectiveTime, localTime, modeNames, reasonText, sensationNames } from '../services/format';
import type { Coordinates, FeatureDetail, PublicCheckIn } from '../services/contracts';
const props = defineProps<{ record: PublicCheckIn | null; feature: FeatureDetail | null }>();
const emit = defineEmits<{ close: []; checkin: []; point: [coordinates: Coordinates]; record: [record: PublicCheckIn]; export: [] }>();
const store = useWorkspace();
const longitude = ref('');
const latitude = ref('');
const coordinateError = ref('');
const extraValues = computed(() => store.point?.items.filter(item => item.variable !== store.committedVariable && item.availability === 'available').slice(0, 4) || []);
const title = (variable: string) => store.catalog.products.find(item => item.variable === variable)?.name || variable;
const overflow = computed(() => store.activeValue?.value != null && store.activeItem ? store.activeValue.value > store.activeItem.legend.max ? '↑ 超过图例上限' : store.activeValue.value < store.activeItem.legend.min ? '↓ 低于图例下限' : '' : '');
function queryCoordinates() {
  const point: Coordinates = [Number(longitude.value), Number(latitude.value)];
  if (!longitude.value || !latitude.value || !point.every(Number.isFinite) || Math.abs(point[0]) > 180 || Math.abs(point[1]) > 90) { coordinateError.value = '请输入合法经纬度。'; return; }
  coordinateError.value = ''; emit('point', point);
}
</script>
<template>
  <div class="flex items-center justify-between"><h2 class="text-base font-semibold">地点详情</h2><button class="icon-button" aria-label="收起地点详情" @click="emit('close')"><AppIcon name="close" :size="17" /></button></div>
  <template v-if="record"><section class="mt-5 rounded-xl border border-line bg-canvas p-4"><div class="flex items-center justify-between"><span class="font-medium">{{ record.alias }}</span><span class="sensation-label" :class="`label-${record.thermal_sensation}`">{{ sensationNames[record.thermal_sensation] }}</span></div><p class="mt-3 text-sm leading-7">{{ record.note || '没有补充描述' }}</p><p class="mt-3 text-xs text-muted">{{ localTime(record.experienced_at, true) }} · 实际体验</p><p class="mt-2 text-xs text-muted">{{ record.public_location_precision === 'grid_200m' ? '位置以约 200 米网格中心展示' : '用户选择公开精确位置' }}</p></section></template>
  <section v-if="feature" class="mt-5 rounded-xl border border-line bg-canvas/50 p-4">
    <div class="flex items-center justify-between">
      <h3 class="section-title text-base">{{ feature.name }}</h3>
      <span class="rounded bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent">
        {{ feature.type === 'layer_buildings' || feature.type === 'buildings' ? '三维建筑' : feature.type }}
      </span>
    </div>
    <div class="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
      <div>
        <span class="text-muted">建筑高度：</span>
        <strong class="font-medium text-ink">{{ feature.height_m === null ? '未知' : `${feature.height_m} m` }}</strong>
      </div>
      <div v-if="feature.levels != null">
        <span class="text-muted">楼层层数：</span>
        <strong class="font-medium text-ink">{{ feature.levels }} 层</strong>
      </div>
      <div v-if="feature.properties?.area_m2">
        <span class="text-muted">占地面积：</span>
        <strong class="font-medium text-ink">{{ Math.round(Number(feature.properties.area_m2)) }} ㎡</strong>
      </div>
    </div>
    <p v-if="feature.height_source" class="mt-2 text-xs text-muted">{{ feature.height_source }}</p>
    <details class="mt-3 text-xs">
      <summary class="cursor-pointer text-muted hover:text-ink">对象属性 ({{ Object.keys(feature.properties).length }})</summary>
      <dl class="mt-2 max-h-40 space-y-1.5 overflow-y-auto pr-1">
        <div v-for="(value, key) in feature.properties" :key="key" class="flex justify-between gap-2 break-all text-[11px]">
          <dt class="text-muted">{{ key }}</dt>
          <dd class="text-right font-mono text-ink">{{ String(value) }}</dd>
        </div>
      </dl>
    </details>
  </section>
  <template v-if="store.selection"><section class="mt-5"><div class="flex items-center gap-2 text-muted"><AppIcon name="pin" :size="15" /><span class="text-xs">已选位置</span></div><h3 class="mt-2 text-xl font-semibold">{{ store.selection.name }}</h3><p class="mt-1 text-xs tabular-nums text-muted">{{ store.selection.coordinates[0].toFixed(5) }}° E &nbsp; {{ store.selection.coordinates[1].toFixed(5) }}° N</p><div v-if="store.point?.elevation_m != null || store.point?.slope_deg != null" class="mt-2.5 flex items-center gap-4 rounded-lg border border-line bg-canvas px-3 py-1.5 text-xs text-muted"><span v-if="store.point.elevation_m != null">地面海拔：<strong class="font-medium text-ink">{{ store.point.elevation_m }} m</strong></span><span v-if="store.point.slope_deg != null">地形坡度：<strong class="font-medium text-ink">{{ store.point.slope_deg }}°</strong></span></div></section><section class="metric-card mt-5"><div class="flex items-center justify-between"><span class="text-sm">{{ title(store.committedVariable) }}</span><span class="text-xs text-muted">{{ store.view ? modeNames[store.view.mode] : '待加载' }}</span></div><div class="mt-3 flex items-baseline gap-2"><span v-if="store.pointBusy" class="my-2 h-11 w-32 animate-pulse rounded-lg bg-line" /><strong v-else class="text-[48px] leading-none font-medium tracking-tight text-accent">{{ store.activeValue?.value == null ? '—' : store.activeValue.value.toFixed(store.committedVariable === 'relative_humidity' || store.committedVariable.includes('shortwave') ? 0 : 1) }}</strong><span class="text-xl text-muted">{{ store.activeItem?.unit }}</span></div><p class="mt-4 text-xs text-muted">{{ store.activeValue?.value === null ? reasonText(store.activeValue.reason_code || store.activeValue.value_status) : effectiveTime(store.activeItem) }}</p><p v-if="overflow" class="mt-2 text-xs text-terracotta">{{ overflow }}</p><p v-if="store.expired" class="mt-2 text-xs text-terracotta">视图已到期，读数暂停更新</p></section><div class="mt-5 grid grid-cols-2 gap-x-5 gap-y-4"><div v-for="item in extraValues" :key="item.variable"><p class="text-xs text-muted">{{ title(item.variable) }}</p><p class="mt-1.5 text-lg font-medium tabular-nums">{{ item.value != null ? (item.variable === 'relative_humidity' ? Math.round(item.value) : item.value.toFixed(1)) : '—' }} <span class="text-xs font-normal text-muted">{{ item.unit }}</span></p><p v-if="item.resolved_time !== store.activeItem?.resolved_time || item.temporal_support === 'interval_mean'" class="mt-1 text-[11px] text-muted">{{ effectiveTime(item) }}</p></div></div><section v-if="store.series" class="panel-section"><SeriesChart :series="store.series" :current="store.activeItem?.resolved_time" :times="store.times" @choose="time => store.switchView({ kind: 'at', time })" /><button class="text-button mt-2" @click="emit('export')">导出环境表格<AppIcon name="external" :size="13" /></button></section><section v-else-if="store.seriesBusy" class="panel-section"><div class="h-32 rounded-xl bg-canvas border border-line flex items-center justify-center text-xs text-muted animate-pulse">正在生成逐时趋势曲线...</div></section><button class="button-primary mt-5 w-full justify-center" @click="emit('checkin')"><AppIcon name="plus" :size="17" />记录此处体感</button></template>
  <div v-else class="mt-6 rounded-xl bg-canvas px-5 py-6"><AppIcon name="pin" :size="27" class="text-accent" /><h3 class="mt-4 text-lg font-medium">从一个地点开始</h3><p class="mt-2 text-sm leading-7 text-muted">点选地图或搜索地点，查看这里的环境与体感。</p></div>
  <section class="panel-section"><div class="flex items-center justify-between"><h3 class="section-title">附近的感受</h3><span class="text-xs text-muted">{{ store.records.length }} 条</span></div><p v-if="store.view?.mode === 'forecast'" class="mt-2 text-xs text-muted">近期实际提交的体验</p><div v-if="store.recordError" class="mt-3 text-xs text-terracotta">{{ store.recordError }}</div><p v-else-if="!store.records.length" class="mt-4 text-sm leading-6 text-muted">这个范围还没有公开记录。分享你的第一份感受。</p><button v-for="item in store.records.slice(0, 3)" :key="item.check_in_id" class="record-card" @click="emit('record', item)"><div class="flex items-center justify-between gap-2"><span class="flex items-center gap-2 text-xs font-medium"><span class="sensation-dot" :class="`sensation-${item.thermal_sensation}`" />{{ sensationNames[item.thermal_sensation] }}</span><span class="text-[11px] text-muted">{{ localTime(item.experienced_at) }}</span></div><p class="mt-2 line-clamp-2 text-xs leading-6 text-muted">{{ item.note || '一份来自城市的体感记录' }}</p></button></section>
  <details class="panel-section text-xs"><summary class="text-muted">坐标查询</summary><form class="mt-3 space-y-3" @submit.prevent="queryCoordinates"><label class="field-label">经度<input v-model="longitude" class="input" required type="number" step="any" placeholder="121.49" /></label><label class="field-label">纬度<input v-model="latitude" class="input" required type="number" step="any" placeholder="31.23" /></label><button class="button w-full justify-center" :disabled="!store.view">查询此处环境</button><p v-if="coordinateError" role="alert">{{ coordinateError }}</p></form></details>
  <details v-if="store.activeItem" class="panel-section text-xs"><summary class="text-muted">来源与尺度</summary><dl class="mt-3 space-y-3 leading-6"><div><dt class="text-muted">来源</dt><dd>{{ store.activeItem.provenance.source }}</dd></div><div><dt class="text-muted">空间支持</dt><dd>{{ store.activeItem.provenance.spatial_support }}</dd></div><div><dt class="text-muted">接收高度</dt><dd>{{ store.activeItem.provenance.receiver_height }}</dd></div><div><dt class="text-muted">数据版本</dt><dd class="break-all">{{ store.activeItem.release_id }}</dd></div><div><dt class="text-muted">省略项</dt><dd>{{ store.activeItem.provenance.omissions.join('；') || '无说明' }}</dd></div></dl></details>
</template>
