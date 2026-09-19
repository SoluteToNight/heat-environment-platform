<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import AppIcon from '../AppIcon.vue';
import { api } from '../../services/api';
import { sensationNames } from '../../services/format';
import type { Coordinates, PublicCheckIn, UtciReading, WeatherAlert, WeatherAlerts } from '../../services/contracts';

const props = defineProps<{ coords: Coordinates | null; reading: UtciReading | null; detailed?: boolean }>();

// —— 热暴露风险：由当前 UTCI 热应激等级推导（大卡同源算法，不重复造数） ——
const risk = computed(() => {
  if (!props.reading) return null;
  const zh = props.reading.stressZh;
  if (zh.includes('极强') || zh.includes('很强')) return { label: '极高', color: '#d64732', note: '热暴露风险极高，尽量避免午间外出。' };
  if (zh.includes('强')) return { label: '高', color: '#e58d3c', note: '热暴露风险高，外出请注意补水与遮阳。' };
  if (zh.includes('中度')) return { label: '中', color: '#d9a514', note: '体感偏热，户外活动请适度安排。' };
  return { label: '低', color: '#3f9d6d', note: '当前体感舒适，无高温暴露风险。' };
});

// —— 官方气象预警：与风险同区展示，折叠为图标、可展开详情 ——
const alertsLoading = ref(false);
const alertsFailed = ref(false);
const alertsData = ref<WeatherAlerts | null>(null);
const alertsExpanded = ref(false);
let alertsAbort: AbortController | null = null;

const alerts = computed(() => alertsData.value?.alerts ?? []);
const visibleIcons = computed(() => alerts.value.slice(0, 3));

const alertsHint = computed(() => {
  if (alertsFailed.value) return '预警查询失败';
  if (!alertsData.value || !alertsData.value.available) {
    switch (alertsData.value?.reason_code) {
      case 'not_configured': return '预警服务未配置';
      case 'quota_exhausted': return '预警查询已达今日限额';
      default: return '预警服务暂不可用';
    }
  }
  return '无生效预警';
});

function warningIcon(typeName: string): string {
  const t = typeName.toLowerCase();
  if (t.includes('高温')) return 'thermo-sun';
  if (t.includes('寒潮') || t.includes('低温')) return 'thermo-cold';
  if (t.includes('台风')) return 'tornado';
  if (t.includes('大风') || t.includes('台风')) return 'wind';
  if (t.includes('暴雨') || t.includes('大雨') || t.includes('降水')) return 'rain';
  if (t.includes('雷电') || t.includes('雷暴')) return 'lightning';
  if (t.includes('暴雪') || t.includes('雨雪') || t.includes('结冰')) return 'snow';
  if (t.includes('冰雹')) return 'hail';
  if (t.includes('雾') || t.includes('霾') || t.includes('沙尘')) return 'fog';
  if (t.includes('雪')) return 'snowflake';
  return 'alert';
}

function fmtTime(value: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
}

// —— 附近热感受：定位周边 ~3 km、近 24 小时的公开打卡（坐标已网格脱敏） ——
const NEARBY_DEGREE = 0.025; // ≈ 2.5–3 km
const nearbyLoading = ref(false);
const nearbyFailed = ref(false);
const nearbyRecords = ref<PublicCheckIn[]>([]);
let nearbyAbort: AbortController | null = null;

const sensationColors: Record<PublicCheckIn['thermal_sensation'], string> = {
  cold: '#4575b4', cool: '#74add1', neutral: '#6da38b', warm: '#e58d3c', hot: '#d64732',
};

const sensationStats = computed(() => {
  const counts = new Map<PublicCheckIn['thermal_sensation'], number>();
  for (const record of nearbyRecords.value) {
    counts.set(record.thermal_sensation, (counts.get(record.thermal_sensation) ?? 0) + 1);
  }
  const order: PublicCheckIn['thermal_sensation'][] = ['hot', 'warm', 'neutral', 'cool', 'cold'];
  return order.filter(key => counts.has(key)).map(key => ({
    key, name: sensationNames[key], count: counts.get(key)!, color: sensationColors[key],
    share: Math.round(((counts.get(key) ?? 0) / nearbyRecords.value.length) * 100),
  }));
});

const hotShare = computed(() => {
  const hotish = nearbyRecords.value.filter(record => record.thermal_sensation === 'hot' || record.thermal_sensation === 'warm').length;
  return nearbyRecords.value.length ? Math.round((hotish / nearbyRecords.value.length) * 100) : 0;
});

const latestRecord = computed(() => {
  return [...nearbyRecords.value].sort((a, b) => b.experienced_at.localeCompare(a.experienced_at))[0] ?? null;
});

function fmtAgo(value: string) {
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 60_000));
  if (!Number.isFinite(minutes)) return '';
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return fmtTime(value);
}

async function loadAlerts() {
  if (!props.coords) return;
  alertsAbort?.abort();
  alertsAbort = new AbortController();
  alertsLoading.value = true;
  alertsFailed.value = false;
  try {
    alertsData.value = await api.weatherAlerts(props.coords[0], props.coords[1], alertsAbort.signal);
    if (!alerts.value.length) alertsExpanded.value = false;
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') return;
    alertsFailed.value = true;
    alertsExpanded.value = false;
  } finally {
    alertsLoading.value = false;
  }
}

// 首页无场景上下文，场景标识取自公开目录并缓存（演示模式同样返回上海场景）
let sceneIdPromise: Promise<string | null> | null = null;
function resolveSceneId(): Promise<string | null> {
  if (!sceneIdPromise) {
    sceneIdPromise = api.scenes().then(page => page.items[0]?.scene_id ?? null).catch(() => null);
  }
  return sceneIdPromise;
}

async function loadNearby() {
  if (!props.coords) return;
  nearbyAbort?.abort();
  nearbyAbort = new AbortController();
  nearbyLoading.value = true;
  nearbyFailed.value = false;
  try {
    const sceneId = await resolveSceneId();
    if (!sceneId) throw new Error('scene unavailable');
    const [lon, lat] = props.coords;
    const bbox = [lon - NEARBY_DEGREE, lat - NEARBY_DEGREE, lon + NEARBY_DEGREE, lat + NEARBY_DEGREE].map(value => value.toFixed(4)).join(',');
    const end = new Date().toISOString();
    const start = new Date(Date.now() - 86_400_000).toISOString();
    const page = await api.publicRecords({ scene_id: sceneId, bbox, start, end, limit: 50 }, nearbyAbort.signal);
    nearbyRecords.value = page.items;
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') return;
    nearbyFailed.value = true;
  } finally {
    nearbyLoading.value = false;
  }
}

watch(() => props.coords, () => {
  alertsExpanded.value = false;
  void loadAlerts();
  void loadNearby();
}, { immediate: true, deep: true });
</script>

<template>
  <!-- 简略态：重叠小卡，点击由外层展开为详细态 -->
  <div v-if="!detailed" class="glass-card relative p-4">
    <div class="flex items-center gap-2">
      <span class="grid size-7 place-items-center rounded-lg bg-green-soft text-accent"><AppIcon name="locate" :size="15" /></span>
      <p class="text-xs font-bold text-ink">附近热况</p>
      <AppIcon name="expand" :size="14" class="ml-auto shrink-0 text-muted" />
    </div>
    <div class="mt-2.5 flex items-center gap-2">
      <span
        v-if="reading && risk"
        class="rounded-full px-2 py-0.5 text-[10px] font-bold"
        :style="{ backgroundColor: `${risk.color}1f`, color: risk.color }"
      >风险{{ risk.label }}</span>
      <span v-if="alertsLoading" class="loader size-3" />
      <span v-else-if="alerts.length" class="flex -space-x-1">
        <span
          v-for="(alert, index) in visibleIcons"
          :key="alert.title + index"
          class="grid size-6 place-items-center rounded-lg border bg-white"
          :style="{ borderColor: alert.severity_color, zIndex: visibleIcons.length - index }"
          :title="`${alert.type_name}${alert.level}预警`"
        >
          <AppIcon :name="warningIcon(alert.type_name)" :size="12" :style="{ color: alert.severity_color }" />
        </span>
      </span>
      <span v-else-if="alertsData?.available" class="text-[10px] font-medium text-accent">无生效预警</span>
      <span v-else-if="!alertsLoading" class="text-[10px] text-muted">{{ alertsHint }}</span>
    </div>
    <p class="mt-1.5 text-[11px] leading-4.5 text-muted">
      {{ nearbyLoading ? '正在读取附近打卡…' : nearbyFailed ? '附近打卡暂不可用' : nearbyRecords.length ? `附近 ${nearbyRecords.length} 人打卡 · ${hotShare}% 偏热` : '附近暂无公开打卡' }}
    </p>
  </div>

  <!-- 详细态：完整附近热况卡 -->
  <div v-else class="glass-card p-4">
    <header class="flex items-center gap-2">
      <span class="grid size-7 place-items-center rounded-lg bg-green-soft text-accent">
        <AppIcon name="locate" :size="15" />
      </span>
      <div class="min-w-0">
        <p class="text-xs font-bold text-ink">附近热况</p>
        <p class="text-[10px] leading-3.5 text-muted">以你的位置为中心 · 约 3 公里</p>
      </div>
      <span v-if="coords" class="live-dot ml-auto" aria-hidden="true" />
    </header>

    <!-- 热暴露风险：当前 UTCI 等级 + 官方预警 -->
    <section class="mt-3.5 border-t border-line/70 pt-3" aria-label="热暴露风险">
      <div class="flex items-center gap-2">
        <span class="text-[10px] font-semibold tracking-wide text-muted">热暴露风险</span>
        <template v-if="risk">
          <span
            class="rounded-full px-2 py-0.5 text-[10px] font-bold"
            :style="{ backgroundColor: `${risk.color}1f`, color: risk.color }"
          >{{ risk.label }}</span>
          <AppIcon name="flame" :size="13" :style="{ color: risk.color }" class="ml-auto" />
        </template>
      </div>
      <p v-if="reading" class="mt-1.5 text-[11px] leading-4.5 text-muted">
        此地当前 UTCI <span class="font-bold tabular-nums text-ink">{{ reading.utciC.toFixed(1) }}°C</span>（{{ reading.stressZh }}）· {{ risk?.note }}
      </p>
      <p v-else class="mt-1.5 text-[11px] leading-4.5 text-muted">等待定位与实时气象…</p>

      <!-- 官方预警：折叠为彩色图标，点击展开详情 -->
      <button
        class="mt-2.5 flex w-full items-center gap-2 text-left"
        :disabled="alertsLoading || !alerts.length"
        :aria-expanded="alertsExpanded"
        @click="alertsExpanded = !alertsExpanded"
      >
        <template v-if="alertsLoading">
          <span class="loader size-3" />
          <span class="text-[11px] text-muted">官方预警查询中…</span>
        </template>
        <template v-else-if="alerts.length">
          <span class="flex -space-x-1">
            <span
              v-for="(alert, index) in visibleIcons"
              :key="alert.title + index"
              class="grid size-6.5 place-items-center rounded-lg border bg-white"
              :style="{ borderColor: alert.severity_color, zIndex: visibleIcons.length - index }"
              :title="`${alert.type_name}${alert.level}预警`"
            >
              <AppIcon :name="warningIcon(alert.type_name)" :size="13" :style="{ color: alert.severity_color }" />
            </span>
          </span>
          <span class="text-[11px] font-semibold text-ink">{{ alerts.length }} 条官方预警生效中</span>
          <AppIcon :name="alertsExpanded ? 'down' : 'up'" :size="13" class="ml-auto text-muted" />
        </template>
        <template v-else>
          <span class="grid size-6.5 place-items-center rounded-lg" :class="alertsData?.available ? 'bg-green-soft text-accent' : 'bg-canvas text-muted'">
            <AppIcon :name="alertsData?.available ? 'shield' : 'info'" :size="13" />
          </span>
          <span class="text-[11px]" :class="alertsFailed || !alertsData?.available ? 'text-muted' : 'text-accent'">{{ alertsHint }}</span>
        </template>
      </button>

      <div v-if="alertsExpanded && alerts.length" class="mt-2.5 space-y-2 border-t border-line/70 pt-2.5">
        <article
          v-for="(alert, index) in alerts"
          :key="alert.title + index"
          class="rounded-xl border border-line bg-white/80 p-2.5"
          :style="{ borderLeft: `3px solid ${alert.severity_color}` }"
        >
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="grid size-5 place-items-center rounded" :style="{ backgroundColor: `${alert.severity_color}22`, color: alert.severity_color }">
              <AppIcon :name="warningIcon(alert.type_name)" :size="12" />
            </span>
            <span class="text-[11px] font-bold text-ink">{{ alert.type_name }}{{ alert.level }}预警</span>
            <span
              v-if="alert.status"
              class="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
              :style="{ backgroundColor: `${alert.severity_color}1f`, color: alert.severity_color }"
            >{{ alert.status }}</span>
          </div>
          <p class="mt-1.5 text-[11px] leading-4.5 text-ink">{{ alert.title }}</p>
          <p class="mt-1 text-[10.5px] leading-4 text-muted">{{ alert.text }}</p>
          <p class="mt-1.5 text-[10px] tabular-nums text-muted">
            发布 {{ fmtTime(alert.pub_time) }}<template v-if="alert.end_time"> · 至 {{ fmtTime(alert.end_time) }}</template>
          </p>
        </article>
        <p class="text-[10px] text-muted">来源：{{ alertsData?.source }}{{ alertsData?.update_time ? ` · 更新于 ${fmtTime(alertsData.update_time)}` : '' }}</p>
      </div>
    </section>

    <!-- 附近热感受：周边公开打卡聚合 -->
    <section class="mt-3.5 border-t border-line/70 pt-3" aria-label="附近热感受">
      <div class="flex items-baseline gap-2">
        <span class="text-[10px] font-semibold tracking-wide text-muted">附近热感受</span>
        <span class="text-[10px] text-muted/80">近 24 小时 · 公开记录</span>
        <AppIcon name="heart" :size="13" class="ml-auto text-terracotta" />
      </div>

      <template v-if="nearbyLoading">
        <p class="mt-2 flex items-center gap-2 text-[11px] text-muted"><span class="loader size-3" /> 正在读取附近打卡…</p>
      </template>
      <template v-else-if="nearbyFailed">
        <p class="mt-2 text-[11px] text-muted">附近打卡暂不可用，请稍后重试。</p>
      </template>
      <template v-else-if="nearbyRecords.length">
        <p class="mt-2 text-[11px] leading-4.5 text-muted">
          附近 <span class="font-bold tabular-nums text-ink">{{ nearbyRecords.length }}</span> 人打卡，其中
          <span class="font-bold" style="color: #e58d3c">{{ hotShare }}%</span> 觉得偏热或很热。
        </p>
        <div class="mt-2 space-y-1.5">
          <div v-for="stat in sensationStats" :key="stat.key" class="flex items-center gap-2">
            <span class="w-7 shrink-0 text-[10px] font-medium" :style="{ color: stat.color }">{{ stat.name }}</span>
            <span class="h-1.5 flex-1 overflow-hidden rounded-full bg-canvas">
              <span class="block h-full rounded-full transition-all duration-500" :style="{ width: `${Math.max(6, stat.share)}%`, backgroundColor: stat.color }" />
            </span>
            <span class="w-4 shrink-0 text-right text-[10px] tabular-nums text-muted">{{ stat.count }}</span>
          </div>
        </div>
        <p v-if="latestRecord" class="mt-2.5 border-t border-line/70 pt-2 text-[10.5px] leading-4 text-muted">
          <AppIcon name="sparkles" :size="11" class="mr-1 inline text-accent" />{{ fmtAgo(latestRecord.experienced_at) }} ·
          {{ latestRecord.alias }} 觉得「<span class="font-semibold" :style="{ color: sensationColors[latestRecord.thermal_sensation] }">{{ sensationNames[latestRecord.thermal_sensation] }}</span>」
        </p>
      </template>
      <template v-else>
        <p class="mt-2 text-[11px] leading-4.5 text-muted">附近暂无公开打卡。打开探索地图，记录第一条真实体感吧。</p>
      </template>
      <p class="mt-2 text-[9.5px] leading-3.5 text-muted/70">打卡坐标经 200 m 网格脱敏，仅展示公开记录。</p>
    </section>
  </div>
</template>
