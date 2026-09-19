<script setup lang="ts">
import SiteHeader from '../components/site/SiteHeader.vue';
import SiteFooter from '../components/site/SiteFooter.vue';
import AppIcon from '../components/AppIcon.vue';
import { navigate } from '../app/router';
import { vReveal } from '../app/reveal';

const dataSources = [
  { icon: 'globe', name: '天地图', desc: '国家地理信息公共服务平台，提供矢量与影像底图服务。', tag: '底图' },
  { icon: 'weather', name: 'ECMWF / Open-Meteo', desc: '数值模式气象背景场，驱动气温、湿度、风速与露点的逐时估算。', tag: '气象' },
  { icon: 'clock', name: '和风天气', desc: '48 小时逐时预报接入，支持供应商切换与配额管理。', tag: '预报' },
  { icon: 'building', name: 'OpenStreetMap', desc: '核心区约 8000 栋建筑轮廓与层高，生成三维体块与路网水绿要素。', tag: '三维' },
  { icon: 'pin', name: '公众体感打卡', desc: '五级热感觉 UGC 数据，经 200 m 网格脱敏后进入分析链路。', tag: '众包' },
  { icon: 'database', name: 'PostgreSQL / PostGIS', desc: '双 schema 组织业务数据与空间底座，支撑空间查询与插值。', tag: '存储' },
];

const methods = [
  { title: 'UTCI 通用热气候指数', desc: '综合气温、湿度、风速与辐射，换算为等效体感温度，图例固定 15–35 °C 区间。' },
  { title: '太阳辐射物理降尺度', desc: '由建筑三维体块推算阴影、天空可视度与短波辐射载荷，落到街区尺度。' },
  { title: '空间平差与审计', desc: '以 144 个控制点校验网格估计，公布 MAE / RMSE 与残差明细，让插值可追溯。' },
  { title: 'p(热) 暴露反演', desc: '以逻辑回归融合环境因子与绿地、水面、建筑占比，估计「感到热」的概率并分级。' },
];

const principles = [
  { icon: 'eye', title: '缺失不等于零', desc: '数据缺测的位置留白并给出 reason_code，绝不以 0 值冒充观测。' },
  { icon: 'sun', title: '光影只是演示', desc: '三维屏幕光影用于直观感受，不作为任何科学读数与结论依据。' },
  { icon: 'shield', title: '隐私优先', desc: '公开打卡坐标一律脱敏至 200 m 网格，精确位置永不出库。' },
];

const techStack = ['FastAPI', 'PostgreSQL + PostGIS', 'Vue 3', 'TypeScript', 'CesiumJS', 'Tailwind CSS', 'Pinia', 'Vitest'];

const quickFacts = [
  { value: '16', unit: '区', label: '行政边界' },
  { value: '8000', unit: '栋', label: '三维建筑' },
  { value: '144', unit: '点', label: '平差控制' },
  { value: '48', unit: 'h', label: '预报同化' },
];
</script>

<template>
  <div class="site-page flex flex-col">
    <SiteHeader active="about" />

    <main class="flex-1">
      <!-- 页头 -->
      <section class="relative overflow-hidden border-b border-line">
        <div class="hero-grid-bg absolute inset-0" aria-hidden="true" />
        <div class="absolute -right-24 -top-24 size-96 rounded-full bg-green-soft blur-3xl opacity-70" aria-hidden="true" />
        <div class="relative mx-auto w-full max-w-6xl px-5 py-16 md:py-20">
          <p v-reveal class="text-xs font-semibold uppercase tracking-[0.25em] text-accent">关于平台 · About</p>
          <h1 v-reveal="80" class="mt-3 max-w-2xl text-3xl font-bold leading-tight tracking-tight text-ink md:text-[2.6rem]">
            用 GIS 回答一个问题：<span class="text-thermal">城市有多热，<br />人觉得有多热？</span>
          </h1>
          <p v-reveal="160" class="mt-5 max-w-2xl text-[15px] leading-7 text-muted">
            申城热境是《GIS 综合实习》选题 9「城市主客观热暴露差异及其影响机制的 GIS 分析」的成果平台。
            我们把客观微气候测算与公众主观体感放进同一套时空基准，在上海市域上观察两者的差异，
            并追问背后的机制——绿地、水体、建筑密度与太阳辐射如何塑造了不同街区的热体验。
          </p>
          <dl v-reveal="240" class="mt-10 grid max-w-2xl grid-cols-2 gap-6 sm:grid-cols-4">
            <div v-for="fact in quickFacts" :key="fact.label" class="border-l-2 border-accent/30 pl-4">
              <dt class="text-2xl font-bold tabular-nums tracking-tight text-ink">
                {{ fact.value }}<span class="ml-0.5 text-sm font-semibold text-muted">{{ fact.unit }}</span>
              </dt>
              <dd class="mt-1 text-[11px] text-muted">{{ fact.label }}</dd>
            </div>
          </dl>
        </div>
      </section>

      <!-- 数据来源 -->
      <section class="mx-auto w-full max-w-6xl px-5 py-16 md:py-20">
        <div v-reveal class="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.25em] text-accent">数据来源 · Data</p>
            <h2 class="mt-3 text-2xl font-bold tracking-tight text-ink md:text-3xl">每一条数据都可溯源</h2>
          </div>
          <p class="max-w-md text-xs leading-5 text-muted">地图页的「数据说明」面板会随帧展示当前数据的来源、时间口径与缺测原因。</p>
        </div>
        <div class="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          <article
            v-for="(source, index) in dataSources"
            :key="source.name"
            v-reveal="(index % 3) * 100"
            class="feature-card relative p-6"
          >
            <span class="absolute right-5 top-5 rounded-full bg-canvas px-2 py-0.5 text-[10px] font-medium text-muted">{{ source.tag }}</span>
            <span class="grid size-10 place-items-center rounded-lg bg-green-soft text-accent">
              <AppIcon :name="source.icon" :size="20" />
            </span>
            <h3 class="mt-4 text-[15px] font-bold tracking-tight text-ink">{{ source.name }}</h3>
            <p class="mt-2 text-xs leading-5 text-muted">{{ source.desc }}</p>
          </article>
        </div>
      </section>

      <!-- 方法 -->
      <section class="border-y border-line bg-white/60">
        <div class="mx-auto w-full max-w-6xl px-5 py-16 md:py-20">
          <div v-reveal class="max-w-2xl">
            <p class="text-xs font-semibold uppercase tracking-[0.25em] text-accent">方法体系 · Methods</p>
            <h2 class="mt-3 text-2xl font-bold tracking-tight text-ink md:text-3xl">客观测算有据，主观融合有度</h2>
          </div>
          <div class="mt-10 grid gap-5 md:grid-cols-2">
            <article
              v-for="(method, index) in methods"
              :key="method.title"
              v-reveal="(index % 2) * 110"
              class="flex gap-4 rounded-2xl border border-line bg-white p-6 shadow-xs"
            >
              <span class="step size-8 shrink-0 text-[13px]">{{ index + 1 }}</span>
              <div>
                <h3 class="text-[15px] font-bold tracking-tight text-ink">{{ method.title }}</h3>
                <p class="mt-2 text-xs leading-5 text-muted">{{ method.desc }}</p>
              </div>
            </article>
          </div>
        </div>
      </section>

      <!-- 展示原则 -->
      <section class="mx-auto w-full max-w-6xl px-5 py-16 md:py-20">
        <div v-reveal class="rounded-3xl bg-ink px-8 py-12 text-white md:px-12">
          <p class="text-xs font-semibold uppercase tracking-[0.25em] text-white/60">展示原则 · Principles</p>
          <h2 class="mt-3 text-2xl font-bold tracking-tight md:text-3xl">诚实的地图，比漂亮的地图更重要</h2>
          <div class="mt-10 grid gap-8 md:grid-cols-3">
            <div v-for="principle in principles" :key="principle.title">
              <span class="grid size-10 place-items-center rounded-lg bg-white/10 text-emerald-300">
                <AppIcon :name="principle.icon" :size="20" />
              </span>
              <h3 class="mt-4 text-[15px] font-bold">{{ principle.title }}</h3>
              <p class="mt-2 text-xs leading-6 text-white/70">{{ principle.desc }}</p>
            </div>
          </div>
        </div>
      </section>

      <!-- 技术栈与课程 -->
      <section class="mx-auto w-full max-w-6xl px-5 pb-24">
        <div class="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
          <div v-reveal class="rounded-2xl border border-line bg-white p-8 shadow-xs">
            <p class="text-xs font-semibold uppercase tracking-[0.25em] text-accent">技术栈 · Stack</p>
            <div class="mt-5 flex flex-wrap gap-2.5">
              <span
                v-for="tech in techStack"
                :key="tech"
                class="rounded-lg border border-line bg-canvas px-3.5 py-1.5 text-xs font-medium text-ink transition-colors hover:border-accent hover:text-accent"
              >{{ tech }}</span>
            </div>
            <p class="mt-6 text-xs leading-6 text-muted">
              前端只展示已发布结果，供应商密钥只存在于服务端；接口遵循幂等写入与乐观并发控制，
              OpenAPI 即唯一契约。
            </p>
          </div>
          <div v-reveal="120" class="rounded-2xl border border-line bg-white p-8 shadow-xs">
            <p class="text-xs font-semibold uppercase tracking-[0.25em] text-accent">课程信息 · Course</p>
            <h3 class="mt-4 text-lg font-bold tracking-tight text-ink">《GIS 综合实习》选题 9</h3>
            <p class="mt-2 text-xs leading-6 text-muted">城市主客观热暴露差异及其影响机制的 GIS 分析 —— 面向上海市的热暴露时空可视分析平台。</p>
            <button class="button-primary mt-6 w-full justify-center text-xs" @click="navigate('explore')">
              进入地图开始探索
              <AppIcon name="next" :size="15" />
            </button>
          </div>
        </div>
      </section>
    </main>

    <SiteFooter />
  </div>
</template>
