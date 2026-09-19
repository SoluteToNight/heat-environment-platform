<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import SiteHeader from '../components/site/SiteHeader.vue';
import SiteFooter from '../components/site/SiteFooter.vue';
import AppIcon from '../components/AppIcon.vue';
import HeatField from '../components/site/HeatField.vue';
import UtciCard from '../components/site/UtciCard.vue';
import NearbyHeatCard from '../components/site/NearbyHeatCard.vue';
import TiltCard from '../components/site/TiltCard.vue';
import { vReveal } from '../app/reveal';
import { vCount } from '../app/countup';
import { navigate } from '../app/router';
import type { Coordinates, UtciReading } from '../services/contracts';

const heroStats = [
  { value: 16, suffix: ' 区', label: '行政边界覆盖' },
  { value: 8000, suffix: ' +', label: '核心区 3D 建筑' },
  { value: 144, suffix: ' 点', label: '空间平差控制' },
  { value: 48, suffix: ' h', label: '预报逐时同化' },
  { value: 200, suffix: ' m', label: '体感隐私网格' },
];

const districts = ['黄浦', '浦东', '徐汇', '长宁', '静安', '普陀', '虹口', '杨浦', '闵行', '宝山', '嘉定', '金山', '松江', '青浦', '奉贤', '崇明'];

const perspectives = [
  {
    key: 'objective',
    icon: 'gauge',
    tone: 'accent' as const,
    title: '客观的城',
    subtitle: '物理观测与数值估算',
    points: [
      { title: '微气候背景场同化', desc: 'ECMWF / 和风气象逐时发布，覆盖气温、湿度、风速与露点。' },
      { title: '太阳辐射物理降尺度', desc: '建筑阴影、天空可视度与短波辐射，还原街区真实热载荷。' },
      { title: '144 点空间平差', desc: '控制点审计与残差检验，让城市网格估计有据可查。' },
    ],
    chips: ['UTCI 指数', '辐射载荷', '空间插值'],
  },
  {
    key: 'subjective',
    icon: 'heart',
    tone: 'terracotta' as const,
    title: '主观的人',
    subtitle: '公众体感与热舒适投票',
    points: [
      { title: '街头体感打卡', desc: '五级热感觉投票，一分钟记录此刻此地的真实感受。' },
      { title: '200 m 网格脱敏', desc: '所有公开展示坐标经网格隐私处理，位置安全无虞。' },
      { title: '逐时环境匹配', desc: '打卡与环境场自动匹配，沉淀主客观差异证据链。' },
    ],
    chips: ['打卡 UGC', '热舒适', '众包数据'],
  },
];

const capabilities = [
  { icon: 'weather', title: '实时微气候场', desc: '气温、湿度、风速、露点逐时发布，支持“现在”估计与历史回放。' },
  { icon: 'sun', title: '太阳辐射与阴影', desc: '三维建筑阴影模拟与天空系数，量化街头真实辐射暴露。' },
  { icon: 'clock', title: '48 小时预报', desc: '多源预报与本地平差融合，提前预知明天哪条街最热。' },
  { icon: 'pin', title: '公众体感打卡', desc: '地图点选即记录，五级热感觉汇入城市热暴露众包图谱。' },
  { icon: 'sliders', title: '热暴露决策看板', desc: '主客观耦合反演 p(热) 风险，输出分级高温应急建议。' },
  { icon: 'building', title: '三维城市漫游', desc: 'Cesium 3D 建筑与光影演示，从街区尺度走进城市热环境。' },
];

const steps = [
  { title: '数据接入', desc: '气象供应商自动同步，空间底座一次装载。' },
  { title: '物理降尺度', desc: '辐射与微气候推算到街区与建筑尺度。' },
  { title: '主客耦合', desc: '体感打卡与环境场逐时匹配、联合反演。' },
  { title: '决策发布', desc: '风险分级看板与专题图一键导出。' },
];

const cardCoords = ref<Coordinates | null>(null);
const utciReading = ref<UtciReading | null>(null);
// 双卡集群：任一时刻一卡详细（大）、另一卡简略（小，压住大卡底边并悬出）；同一张卡在两个槽位间平滑移动缩放
const expandedCard = ref<'utci' | 'nearby'>('utci');

// 槽位移动缩放动画需要显式的位置与尺寸：ResizeObserver 实时测量，
// 部分内嵌浏览器不派发 RO 回调，因此另挂 watcher / 定时 / resize / 点击兜底测量
const clusterRef = ref<HTMLElement | null>(null);
const utciRootRef = ref<HTMLElement | null>(null);
const nearbyRootRef = ref<HTMLElement | null>(null);
const clusterWidth = ref(0);
const cardHeights = ref({ utci: 0, nearby: 0 });
const swapping = ref(false);
const SMALL_WIDTH = 240; // 简略态小卡宽度
const OVERLAP = 30;      // 小卡压住大卡底边的高度（只盖住边框区，不遮内容）
let clusterObserver: ResizeObserver | null = null;

function measureCards() {
  if (clusterRef.value) clusterWidth.value = clusterRef.value.clientWidth;
  if (utciRootRef.value) cardHeights.value.utci = utciRootRef.value.offsetHeight;
  if (nearbyRootRef.value) cardHeights.value.nearby = nearbyRootRef.value.offsetHeight;
}

onMounted(() => {
  measureCards();
  clusterObserver = new ResizeObserver(measureCards);
  if (clusterRef.value) clusterObserver.observe(clusterRef.value);
  if (utciRootRef.value) clusterObserver.observe(utciRootRef.value);
  if (nearbyRootRef.value) clusterObserver.observe(nearbyRootRef.value);
  window.addEventListener('resize', measureCards);
  // 定位、取数是异步的，卡片高度会在挂载后多次变化
  [200, 600, 1500, 3000].forEach(delay => window.setTimeout(measureCards, delay));
});
onBeforeUnmount(() => {
  clusterObserver?.disconnect();
  window.removeEventListener('resize', measureCards);
});

watch([expandedCard, utciReading, cardCoords], () => nextTick(measureCards));

// 卡片内部交互（如展开预警详情）也会改变高度，点击后延迟补测一次
function scheduleMeasure() { window.setTimeout(measureCards, 420); }

// 两段式切换：当前内容淡出 → 槽位交换（WAAPI 补间位置尺寸；部分内嵌浏览器 CSS transition 会冻结，故不用）→ 新内容淡入
interface SlotRect { left: string; top: string; width: string; height: string }

function captureSlotRects() {
  const map = new Map<HTMLElement, SlotRect>();
  document.querySelectorAll<HTMLElement>('.card-swap-slot').forEach(el => {
    map.set(el, { left: el.style.left, top: el.style.top, width: el.style.width, height: el.style.height });
  });
  return map;
}

function playSlotAnimation(before: Map<HTMLElement, SlotRect>) {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  for (const [el, from] of before) {
    const to = { left: el.style.left, top: el.style.top, width: el.style.width, height: el.style.height };
    const moved = from.left !== to.left || from.top !== to.top || from.width !== to.width || from.height !== to.height;
    if (!moved || !from.width || typeof el.animate !== 'function') continue;
    // 个别内嵌浏览器动画时钟可能冻结在第一帧，600ms 后强制取消、回落到正确的内联样式
    const animation = el.animate(
      [
        { left: from.left, top: from.top, width: from.width, height: from.height },
        { left: to.left, top: to.top, width: to.width, height: to.height },
      ],
      { duration: 430, easing: 'cubic-bezier(.22,.61,.36,1)' },
    );
    window.setTimeout(() => animation.cancel(), 600);
  }
}

function requestSwap(target: 'utci' | 'nearby') {
  if (target === expandedCard.value || swapping.value) return;
  const clusterEl = clusterRef.value;
  const before = captureSlotRects();
  const clusterFrom = clusterEl?.style.height ?? '';
  swapping.value = true;
  window.setTimeout(() => {
    expandedCard.value = target;
    nextTick(() => {
      measureCards();
      nextTick(() => {
        playSlotAnimation(before);
        if (clusterEl && clusterFrom && clusterFrom !== clusterEl.style.height && typeof clusterEl.animate === 'function') {
          const clusterAnimation = clusterEl.animate(
            [{ height: clusterFrom }, { height: clusterEl.style.height }],
            { duration: 430, easing: 'cubic-bezier(.22,.61,.36,1)' },
          );
          window.setTimeout(() => clusterAnimation.cancel(), 600);
        }
        window.setTimeout(() => { swapping.value = false; measureCards(); }, 240);
      });
    });
  }, 170);
}

function cardStyle(card: 'utci' | 'nearby') {
  const width = clusterWidth.value || 448;
  if (expandedCard.value === card) {
    return { left: '0px', top: '0px', width: `${width}px`, height: `${cardHeights.value[card]}px` };
  }
  return {
    left: `${width > 420 ? -14 : 12}px`,
    top: `${cardHeights.value[expandedCard.value] - OVERLAP}px`,
    width: `${SMALL_WIDTH}px`,
    height: `${cardHeights.value[card]}px`,
  };
}
</script>

<template>
  <div class="site-page flex flex-col">
    <SiteHeader active="home" />

    <main class="flex-1">
      <!-- Hero：交互式城市热场 -->
      <section class="relative cursor-crosshair overflow-hidden">
        <HeatField />
        <div class="absolute -left-32 -top-32 size-[26rem] rounded-full bg-green-soft blur-3xl opacity-70" aria-hidden="true" />
        <div class="absolute -bottom-40 right-[-8rem] size-[30rem] rounded-full bg-[#fdeadd] blur-3xl opacity-70" aria-hidden="true" />

        <div class="relative mx-auto flex min-h-[calc(100svh-4rem)] w-full max-w-6xl flex-col justify-center px-5 pb-24 pt-16">
          <div class="grid items-center gap-14 lg:grid-cols-[1.05fr_0.95fr]">
            <div>
              <p v-reveal class="flex items-center gap-3 font-mono text-[11px] uppercase tracking-[0.35em] text-accent/80">
                <span class="h-px w-8 bg-accent/40" aria-hidden="true" />
                Shanghai Urban Heat Observatory
              </p>
              <h1 v-reveal="80" class="mt-6 text-5xl font-bold leading-[1.08] tracking-tight text-ink sm:text-6xl lg:text-[4.1rem]">
                同一座城，<br />
                <span class="text-thermal">两种温度</span>。
              </h1>
              <p v-reveal="160" class="mt-6 max-w-xl text-[15px] leading-7 text-muted">
                气象站与辐射模型测得城市的客观炎热，街头巷尾的人却各有体感。
                申城热境把<strong class="font-semibold text-ink">客观微气候场</strong>与<strong class="font-semibold text-ink">公众主观打卡</strong>
                融进同一张三维地图，让热暴露差异看得见、量得出、用得上。
              </p>
              <p v-reveal="210" class="mt-4 flex items-center gap-2 text-xs text-muted/80">
                <AppIcon name="focus" :size="14" class="text-terracotta" />
                移动光标，感受指尖的热岛效应；点击荡开一圈等温线。
              </p>
              <div v-reveal="260" class="mt-8 flex flex-wrap items-center gap-3">
                <button class="button-primary px-6 py-3 text-sm" @click="navigate('explore')">
                  进入探索地图
                  <AppIcon name="next" :size="16" />
                </button>
                <button class="button px-6 py-3 text-sm" @click="navigate('about')">
                  数据与方法
                  <AppIcon name="book" :size="16" />
                </button>
              </div>
              <dl v-reveal="330" class="mt-12 grid max-w-xl grid-cols-3 gap-x-6 gap-y-5 sm:grid-cols-5">
                <div v-for="stat in heroStats" :key="stat.label">
                  <dt class="text-2xl font-bold tabular-nums tracking-tight text-ink">
                    <span v-count="stat.value">0</span><span class="text-sm font-semibold text-muted">{{ stat.suffix }}</span>
                  </dt>
                  <dd class="mt-1 text-[11px] leading-4 text-muted">{{ stat.label }}</dd>
                </div>
              </dl>
            </div>

            <!-- 双卡集群（重叠构图）：同一张卡在详细大卡与简略小卡两个槽位间平滑移动缩放；小卡只压住大卡底边，不遮内容 -->
            <div v-reveal="200" class="relative mx-auto w-full max-w-md lg:max-w-none">
              <TiltCard class="w-full lg:ml-auto lg:max-w-md">
                <div
                  ref="clusterRef"
                  class="relative"
                  :style="{ height: `${cardHeights[expandedCard]}px` }"
                  @click.capture="scheduleMeasure"
                >
                  <!-- 实时体感卡 -->
                  <div class="card-swap-slot" :class="expandedCard === 'utci' ? 'z-10' : 'z-20'" :style="cardStyle('utci')">
                    <div
                      class="block transition-opacity duration-200"
                      :class="[swapping ? 'opacity-0' : 'opacity-100', expandedCard === 'utci' ? 'site-float-slow' : 'site-float']"
                    >
                      <div ref="utciRootRef">
                        <UtciCard :detailed="expandedCard === 'utci'" @location="cardCoords = $event" @reading="utciReading = $event" />
                      </div>
                    </div>
                    <button
                      v-if="expandedCard === 'utci'"
                      class="absolute -top-3 right-4 z-30 inline-flex items-center gap-1 rounded-full border border-line bg-white px-2.5 py-1 text-[10px] font-semibold text-muted shadow-sm transition hover:text-ink"
                      aria-label="收起实时体感卡，展开附近热况"
                      @click="requestSwap('nearby')"
                    >收起<AppIcon name="down" :size="12" /></button>
                    <div
                      v-else
                      class="absolute -inset-1.5 cursor-pointer rounded-2xl outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                      role="button"
                      tabindex="0"
                      aria-label="展开实时体感详情"
                      @click="requestSwap('utci')"
                      @keydown.enter.prevent="requestSwap('utci')"
                    />
                  </div>

                  <!-- 附近热况卡 -->
                  <div class="card-swap-slot" :class="expandedCard === 'nearby' ? 'z-10' : 'z-20'" :style="cardStyle('nearby')">
                    <div
                      class="block transition-opacity duration-200"
                      :class="[swapping ? 'opacity-0' : 'opacity-100', expandedCard === 'nearby' ? 'site-float-slow' : 'site-float']"
                    >
                      <div ref="nearbyRootRef">
                        <NearbyHeatCard :detailed="expandedCard === 'nearby'" :coords="cardCoords" :reading="utciReading" />
                      </div>
                    </div>
                    <button
                      v-if="expandedCard === 'nearby'"
                      class="absolute -top-3 right-4 z-30 inline-flex items-center gap-1 rounded-full border border-line bg-white px-2.5 py-1 text-[10px] font-semibold text-muted shadow-sm transition hover:text-ink"
                      aria-label="收起附近热况卡，展开实时体感"
                      @click="requestSwap('utci')"
                    >收起<AppIcon name="down" :size="12" /></button>
                    <div
                      v-else
                      class="absolute -inset-1.5 cursor-pointer rounded-2xl outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                      role="button"
                      tabindex="0"
                      aria-label="展开附近热况详情"
                      @click="requestSwap('nearby')"
                      @keydown.enter.prevent="requestSwap('nearby')"
                    />
                  </div>
                </div>
              </TiltCard>
            </div>
          </div>
        </div>

        <!-- 滚动指示 + 热感地平线 -->
        <div class="pointer-events-none absolute inset-x-0 bottom-0 z-10">
          <div class="mx-auto mb-4 flex w-fit flex-col items-center gap-2">
            <span class="font-mono text-[10px] tracking-[0.4em] text-muted/70">SCROLL</span>
            <span class="relative block h-9 w-px overflow-hidden bg-line">
              <span class="scroll-cue-line absolute inset-x-0 top-0 h-1/2 bg-accent" />
            </span>
          </div>
          <div class="h-[2px] w-full bg-gradient-to-r from-[#2b7bc000] via-[#e58d3c99] to-[#d6473200]" aria-hidden="true" />
        </div>
      </section>

      <!-- 区名跑马灯 -->
      <div class="site-marquee overflow-hidden border-b border-line bg-white/70 py-3.5" aria-hidden="true">
        <div class="site-marquee-track">
          <template v-for="copy in 2" :key="copy">
            <span
              v-for="district in districts"
              :key="`${copy}-${district}`"
              class="mx-5 flex items-center gap-2 whitespace-nowrap text-xs font-medium tracking-[0.3em] text-muted"
            >
              {{ district }}
              <AppIcon name="temperature" :size="12" class="text-line" />
            </span>
          </template>
        </div>
      </div>

      <!-- 双视角 -->
      <section class="mx-auto w-full max-w-6xl px-5 py-20 md:py-24">
        <div v-reveal class="flex items-center gap-4">
          <span class="font-mono text-xs font-semibold text-accent">01</span>
          <span class="h-px w-10 bg-accent/30" aria-hidden="true" />
          <p class="text-xs font-semibold uppercase tracking-[0.25em] text-accent">双视角 · Dual Perspective</p>
        </div>
        <div class="mt-4 grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
          <h2 v-reveal="60" class="text-3xl font-bold tracking-tight text-ink md:text-4xl">客观的城，主观的人</h2>
          <p v-reveal="120" class="max-w-md text-sm leading-6 text-muted">
            热暴露从来不只是温度计的读数。平台并排呈现两条证据链，再让它们在同一个时空基准上对话。
          </p>
        </div>

        <div class="mt-12 grid gap-6 md:grid-cols-2">
          <article
            v-for="(perspective, index) in perspectives"
            :key="perspective.key"
            v-reveal="index * 120"
            class="feature-card relative overflow-hidden p-7"
          >
            <div
              class="absolute inset-x-0 top-0 h-1"
              :class="perspective.tone === 'accent' ? 'bg-accent' : 'bg-terracotta'"
            />
            <div class="flex items-center gap-3">
              <span
                class="grid size-11 place-items-center rounded-xl"
                :class="perspective.tone === 'accent' ? 'bg-green-soft text-accent' : 'bg-[#f9e8de] text-terracotta'"
              >
                <AppIcon :name="perspective.icon" :size="22" />
              </span>
              <div>
                <h3 class="text-lg font-bold tracking-tight text-ink">{{ perspective.title }}</h3>
                <p class="text-xs text-muted">{{ perspective.subtitle }}</p>
              </div>
            </div>
            <ul class="mt-6 space-y-4">
              <li v-for="point in perspective.points" :key="point.title" class="flex gap-3">
                <AppIcon name="check" :size="16" :class="perspective.tone === 'accent' ? 'mt-0.5 shrink-0 text-accent' : 'mt-0.5 shrink-0 text-terracotta'" />
                <div>
                  <p class="text-sm font-semibold text-ink">{{ point.title }}</p>
                  <p class="mt-1 text-xs leading-5 text-muted">{{ point.desc }}</p>
                </div>
              </li>
            </ul>
            <div class="mt-6 flex flex-wrap gap-2">
              <span
                v-for="chip in perspective.chips"
                :key="chip"
                class="rounded-full px-2.5 py-1 text-[11px] font-medium"
                :class="perspective.tone === 'accent' ? 'bg-green-soft text-accent' : 'bg-[#f9e8de] text-terracotta'"
              >{{ chip }}</span>
            </div>
          </article>
        </div>

        <!-- 耦合桥 -->
        <div v-reveal class="relative mt-6 overflow-hidden rounded-2xl bg-accent px-7 py-6 text-white md:px-10">
          <div class="absolute inset-y-0 right-0 w-1/2 bg-gradient-to-l from-[#d6473230] to-transparent" aria-hidden="true" />
          <div class="relative flex flex-col items-start gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p class="text-xs font-medium uppercase tracking-[0.25em] text-white/60">耦合分析 · Coupling</p>
              <p class="mt-1.5 text-lg font-bold tracking-tight">
                环境场 × 体感打卡 → p(热) 暴露反演 → 分级应急决策
              </p>
            </div>
            <button class="button-primary shrink-0 bg-white! text-accent! hover:bg-white/90!" @click="navigate('explore')">
              查看决策看板
              <AppIcon name="external" :size="15" />
            </button>
          </div>
        </div>
      </section>

      <!-- 平台能力 -->
      <section class="border-y border-line bg-white/60">
        <div class="mx-auto w-full max-w-6xl px-5 py-20 md:py-24">
          <div v-reveal class="flex items-center gap-4">
            <span class="font-mono text-xs font-semibold text-accent">02</span>
            <span class="h-px w-10 bg-accent/30" aria-hidden="true" />
            <p class="text-xs font-semibold uppercase tracking-[0.25em] text-accent">平台能力 · Capabilities</p>
          </div>
          <div class="mt-4 grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
            <h2 v-reveal="60" class="text-3xl font-bold tracking-tight text-ink md:text-4xl">从数据到街区，六个切面</h2>
            <p v-reveal="120" class="max-w-md text-sm leading-6 text-muted">
              每个能力都是一条完整链路：接入、计算、发布、可视化，全部在平台内闭环。
            </p>
          </div>
          <div class="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            <article
              v-for="(capability, index) in capabilities"
              :key="capability.title"
              v-reveal="(index % 3) * 100"
              class="feature-card group relative p-6"
            >
              <span class="absolute right-5 top-4 font-mono text-[11px] tabular-nums text-muted/50">0{{ index + 1 }}</span>
              <span class="grid size-10 place-items-center rounded-lg bg-green-soft text-accent transition-colors duration-300 group-hover:bg-accent group-hover:text-white">
                <AppIcon :name="capability.icon" :size="20" />
              </span>
              <h3 class="mt-4 text-[15px] font-bold tracking-tight text-ink">{{ capability.title }}</h3>
              <p class="mt-2 text-xs leading-5 text-muted">{{ capability.desc }}</p>
            </article>
          </div>
        </div>
      </section>

      <!-- 工作流程 -->
      <section class="mx-auto w-full max-w-6xl px-5 py-20 md:py-24">
        <div v-reveal class="flex items-center gap-4">
          <span class="font-mono text-xs font-semibold text-accent">03</span>
          <span class="h-px w-10 bg-accent/30" aria-hidden="true" />
          <p class="text-xs font-semibold uppercase tracking-[0.25em] text-accent">工作流程 · Workflow</p>
        </div>
        <h2 v-reveal="60" class="mt-4 text-3xl font-bold tracking-tight text-ink md:text-4xl">四步，从数据到决策</h2>
        <ol class="mt-12 grid gap-8 md:grid-cols-4 md:gap-5">
          <li v-for="(step, index) in steps" :key="step.title" v-reveal="index * 110" class="relative">
            <div class="hidden md:absolute md:left-11 md:top-5 md:h-px md:w-[calc(100%-2.75rem)] md:bg-gradient-to-r md:from-[#a5bfae] md:to-transparent" aria-hidden="true" />
            <div class="flex items-center gap-3 md:block">
              <span class="step relative z-10 size-9 text-sm">{{ index + 1 }}</span>
              <h3 class="text-[15px] font-bold text-ink md:mt-4">{{ step.title }}</h3>
            </div>
            <p class="mt-2 text-xs leading-5 text-muted md:mt-2.5">{{ step.desc }}</p>
          </li>
        </ol>
      </section>

      <!-- CTA -->
      <section class="mx-auto w-full max-w-6xl px-5 pb-24">
        <div v-reveal class="relative overflow-hidden rounded-3xl bg-accent px-8 py-14 text-center text-white md:py-16">
          <div class="absolute inset-x-0 top-0 h-1.5 bg-gradient-to-r from-[#2b7bc0] via-[#e58d3c] to-[#d64732]" aria-hidden="true" />
          <div class="absolute -right-10 -top-10 size-56 rounded-full bg-white/10 blur-2xl" aria-hidden="true" />
          <div class="absolute -bottom-16 -left-10 size-56 rounded-full bg-white/10 blur-2xl" aria-hidden="true" />
          <h2 class="relative text-3xl font-bold tracking-tight md:text-4xl">现在，去街头看看<br class="sm:hidden" />今天的城市温度</h2>
          <p class="relative mx-auto mt-4 max-w-xl text-sm leading-6 text-white/80">
            打开三维地图，查看任一街区的微气候与辐射暴露；也可以记录你此刻的体感，成为城市热图谱的一部分。
          </p>
          <div class="relative mt-8 flex flex-wrap items-center justify-center gap-3">
            <button class="rounded-lg bg-white px-7 py-3 text-sm font-semibold text-accent shadow-sm transition hover:bg-white/90" @click="navigate('explore')">
              进入探索地图
              <AppIcon name="next" :size="16" class="ml-1 inline" />
            </button>
            <button class="rounded-lg border border-white/40 px-7 py-3 text-sm font-semibold text-white transition hover:bg-white/10" @click="navigate('profile')">
              我的体感足迹
            </button>
          </div>
        </div>
      </section>
    </main>

    <SiteFooter />
  </div>
</template>
