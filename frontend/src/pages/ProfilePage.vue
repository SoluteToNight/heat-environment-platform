<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import SiteHeader from '../components/site/SiteHeader.vue';
import SiteFooter from '../components/site/SiteFooter.vue';
import AuthModal from '../components/AuthModal.vue';
import AppIcon from '../components/AppIcon.vue';
import { api, errorMessage } from '../services/api';
import type { CheckIn } from '../services/contracts';
import { localTime, sensationNames } from '../services/format';
import { useWorkspace } from '../stores/workspace';
import { navigate } from '../app/router';
import { vReveal } from '../app/reveal';

const store = useWorkspace();
const sessionChecked = ref(false);
const records = ref<CheckIn[]>([]);
const recordsLoading = ref(false);
const recordNotice = ref('');
const authOpen = ref(false);

const settingNames: Record<string, string> = { indoor: '室内', outdoor: '室外', mixed: '室内外混合', unknown: '场景未知' };

const alias = computed(() => store.session.user?.alias || store.session.user?.user_id || '未登录');
const avatarChar = computed(() => alias.value.slice(0, 1).toUpperCase());

const uniqueDays = computed(() => {
  const days = new Set(records.value.map(record => new Date(record.experienced_at).toDateString()));
  return days.size;
});

const outdoorShare = computed(() => {
  if (!records.value.length) return 0;
  const outdoor = records.value.filter(record => record.setting === 'outdoor').length;
  return Math.round((outdoor / records.value.length) * 100);
});

const latestTime = computed(() => {
  const times = records.value.map(record => Date.parse(record.experienced_at)).filter(Number.isFinite);
  return times.length ? new Date(Math.max(...times)).toISOString() : null;
});

const sensationStats = computed(() => {
  const order: Array<keyof typeof sensationNames> = ['cold', 'cool', 'neutral', 'warm', 'hot'];
  const counts = new Map(order.map(key => [key, 0]));
  for (const record of records.value) {
    const key = record.thermal_sensation as keyof typeof sensationNames;
    if (counts.has(key)) counts.set(key, (counts.get(key) || 0) + 1);
  }
  const max = Math.max(1, ...counts.values());
  const barClasses: Record<string, string> = { cold: 'bg-sensation-cold', cool: 'bg-sensation-cool', neutral: 'bg-sensation-neutral', warm: 'bg-sensation-warm', hot: 'bg-sensation-hot' };
  return order.map(key => ({
    key,
    name: sensationNames[key],
    count: counts.get(key) || 0,
    width: Math.round(((counts.get(key) || 0) / max) * 100),
    barClass: barClasses[key]!,
  }));
});

async function loadSession() {
  try {
    store.session = await api.session();
  } catch {
    store.session = { authenticated: false, user: null };
  } finally {
    sessionChecked.value = true;
  }
}

async function loadRecords() {
  if (!store.session.authenticated) {
    records.value = [];
    return;
  }
  recordsLoading.value = true;
  recordNotice.value = '';
  try {
    const res = await api.myRecords();
    records.value = res.items;
    if (res.next_cursor) recordNotice.value = `仅展示最近 ${res.items.length} 条，全部记录请在地图页「我的打卡」中查看。`;
  } catch (err) {
    recordNotice.value = errorMessage(err);
  } finally {
    recordsLoading.value = false;
  }
}

async function handleAuthSuccess() {
  await loadSession();
  await loadRecords();
}

onMounted(async () => {
  await loadSession();
  await loadRecords();
});
</script>

<template>
  <div class="site-page flex flex-col">
    <SiteHeader active="profile" />
    <AuthModal :open="authOpen" @close="authOpen = false" @success="handleAuthSuccess" />

    <main class="mx-auto w-full max-w-6xl flex-1 px-5 pb-24 pt-12">
      <div v-reveal class="max-w-2xl">
        <p class="text-xs font-semibold uppercase tracking-[0.25em] text-accent">个人中心 · Profile</p>
        <h1 class="mt-3 text-3xl font-bold tracking-tight text-ink md:text-4xl">你的体感足迹</h1>
        <p class="mt-4 text-sm leading-6 text-muted">每一次街头打卡都是一份城市热观测样本。这里汇总你的贡献，也守护你的位置隐私。</p>
      </div>

      <!-- 加载骨架 -->
      <template v-if="!sessionChecked">
        <div class="mt-10 space-y-5" aria-busy="true">
          <div class="h-36 animate-pulse rounded-2xl bg-white/70" />
          <div class="grid gap-4 sm:grid-cols-4">
            <div v-for="i in 4" :key="i" class="h-24 animate-pulse rounded-2xl bg-white/70" />
          </div>
          <div class="h-64 animate-pulse rounded-2xl bg-white/70" />
        </div>
      </template>

      <!-- 未登录 -->
      <template v-else-if="!store.session.authenticated">
        <div v-reveal class="glass-card mx-auto mt-12 max-w-lg p-10 text-center">
          <span class="mx-auto grid size-16 place-items-center rounded-2xl bg-green-soft text-accent">
            <AppIcon name="user" :size="30" />
          </span>
          <h2 class="mt-5 text-xl font-bold tracking-tight text-ink">登录后查看你的热感足迹</h2>
          <p class="mt-3 text-sm leading-6 text-muted">
            登录即可管理体感打卡记录、查看个人热感觉分布与参与统计。<br />还没有记录？去地图上留下第一份体感吧。
          </p>
          <div class="mt-7 flex flex-wrap items-center justify-center gap-3">
            <button class="button-primary px-6 py-2.5 text-sm" @click="authOpen = true">
              <AppIcon name="user" :size="16" />
              立即登录
            </button>
            <button class="button px-6 py-2.5 text-sm" @click="navigate('explore')">
              先去地图逛逛
              <AppIcon name="next" :size="15" />
            </button>
          </div>
        </div>
      </template>

      <!-- 已登录 -->
      <template v-else>
        <!-- 用户卡 -->
        <section v-reveal class="relative mt-10 overflow-hidden rounded-2xl border border-line bg-white shadow-xs">
          <div class="h-20 bg-gradient-to-r from-accent via-[#2d8a6b] to-[#4aa183]">
            <svg class="h-full w-full opacity-25" viewBox="0 0 600 80" preserveAspectRatio="none" aria-hidden="true">
              <path d="M0 60 C 80 20 140 70 220 40 S 380 10 460 45 S 560 70 600 30 V 80 H 0 Z" fill="#ffffff" />
            </svg>
          </div>
          <div class="flex flex-col gap-5 px-7 pb-7 sm:flex-row sm:items-end sm:justify-between">
            <div class="flex items-end gap-4">
              <span class="-mt-9 grid size-20 shrink-0 place-items-center rounded-2xl border-4 border-white bg-canvas text-2xl font-bold text-accent shadow-sm">
                {{ avatarChar }}
              </span>
              <div class="pb-1">
                <div class="flex flex-wrap items-center gap-2">
                  <h2 class="text-xl font-bold tracking-tight text-ink">{{ alias }}</h2>
                  <span class="inline-flex items-center gap-1 rounded-full bg-green-soft px-2 py-0.5 text-[11px] font-medium text-accent">
                    <span class="size-1.5 rounded-full bg-accent" />
                    已登录
                  </span>
                </div>
                <p class="mt-1 text-xs text-muted">账号 ID：{{ store.session.user?.user_id }} · 上海热环境观测志愿者</p>
              </div>
            </div>
            <button class="button-primary shrink-0 text-xs py-2.5" @click="navigate('explore')">
              <AppIcon name="pin" :size="15" />
              去地图打卡
            </button>
          </div>
        </section>

        <!-- 统计 -->
        <section class="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div v-for="(stat, index) in [
            { icon: 'pin', label: '打卡总数', value: String(records.length), suffix: records.length >= 50 ? '+' : '' },
            { icon: 'calendar', label: '记录天数', value: String(uniqueDays), suffix: ' 天' },
            { icon: 'sun', label: '室外观测占比', value: String(outdoorShare), suffix: ' %' },
            { icon: 'clock', label: '最近打卡', value: latestTime ? localTime(latestTime, true) : '暂无', suffix: '' },
          ]" :key="stat.label" v-reveal="index * 90" class="metric-card">
            <div class="flex items-center justify-between">
              <p class="text-xs text-muted">{{ stat.label }}</p>
              <AppIcon :name="stat.icon" :size="16" class="text-accent/70" />
            </div>
            <p class="mt-2 text-2xl font-bold tabular-nums tracking-tight text-ink">{{ stat.value }}<span class="text-sm font-semibold text-muted">{{ stat.suffix }}</span></p>
          </div>
        </section>

        <div class="mt-6 grid gap-6 lg:grid-cols-[1.5fr_1fr]">
          <!-- 左列 -->
          <div class="space-y-6">
            <!-- 热感觉分布 -->
            <section v-reveal class="rounded-2xl border border-line bg-white p-7 shadow-xs">
              <div class="flex items-center justify-between">
                <h3 class="section-title">热感觉分布</h3>
                <span class="text-[11px] text-muted">基于 {{ records.length }} 条记录</span>
              </div>
              <div v-if="records.length" class="mt-5 space-y-3.5">
                <div v-for="item in sensationStats" :key="item.key" class="flex items-center gap-3">
                  <span class="flex w-14 shrink-0 items-center gap-1.5 text-xs text-muted">
                    <span class="sensation-dot" :class="`sensation-${item.key}`" />
                    {{ item.name }}
                  </span>
                  <div class="h-3 flex-1 overflow-hidden rounded-full bg-canvas">
                    <div
                      class="h-full rounded-full transition-[width] duration-700"
                      :class="item.barClass"
                      :style="{ width: `${item.width}%` }"
                    />
                  </div>
                  <span class="w-8 shrink-0 text-right text-xs font-semibold tabular-nums text-ink">{{ item.count }}</span>
                </div>
              </div>
              <div v-else class="mt-5 rounded-xl border border-dashed border-line bg-canvas/60 p-8 text-center">
                <p class="text-sm font-medium text-ink">还没有打卡记录</p>
                <p class="mt-1.5 text-xs text-muted">第一次打卡后，这里会出现你的热感觉画像。</p>
                <button class="text-button mx-auto mt-4" @click="navigate('explore')">
                  去记录第一条体感
                  <AppIcon name="next" :size="14" />
                </button>
              </div>
            </section>

            <!-- 最近记录 -->
            <section v-reveal class="rounded-2xl border border-line bg-white p-7 shadow-xs">
              <div class="flex items-center justify-between">
                <h3 class="section-title">最近记录</h3>
                <button class="text-button" :disabled="recordsLoading" @click="loadRecords()">
                  <AppIcon name="clock" :size="14" />
                  刷新
                </button>
              </div>
              <p v-if="recordNotice" class="status-warning mt-4">{{ recordNotice }}</p>
              <div v-if="recordsLoading" class="mt-5 py-8 text-center">
                <span class="loader mx-auto size-6" />
                <p class="mt-3 text-xs text-muted">正在加载记录…</p>
              </div>
              <ul v-else-if="records.length" class="mt-5 space-y-3">
                <li v-for="record in records.slice(0, 6)" :key="record.check_in_id" class="rounded-xl border border-line bg-canvas/50 p-4 transition hover:border-accent">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="sensation-label" :class="`label-${record.thermal_sensation}`">
                      <span class="sensation-dot mr-1" :class="`sensation-${record.thermal_sensation}`" />
                      {{ sensationNames[record.thermal_sensation] }}
                    </span>
                    <span class="text-xs text-muted">{{ settingNames[record.setting] || record.setting }}</span>
                    <span class="ml-auto text-[11px] tabular-nums text-muted">{{ localTime(record.experienced_at, true) }}</span>
                  </div>
                  <p class="mt-2 text-sm leading-relaxed text-ink">{{ record.note || '（未填写补充说明）' }}</p>
                </li>
              </ul>
              <div v-else class="mt-5 py-8 text-center text-muted">
                <AppIcon name="pin" :size="28" class="mx-auto mb-3 text-line" />
                <p class="text-xs">暂无公开记录</p>
              </div>
            </section>
          </div>

          <!-- 右列 -->
          <div class="space-y-6">
            <section v-reveal class="rounded-2xl border border-line bg-white p-7 shadow-xs">
              <span class="grid size-10 place-items-center rounded-lg bg-green-soft text-accent">
                <AppIcon name="flame" :size="20" />
              </span>
              <h3 class="mt-4 section-title">参与指南</h3>
              <ol class="mt-4 space-y-3.5">
                <li v-for="(tip, index) in [
                  '在地图上点选你所在的位置，或使用定位。',
                  '选择此刻的热感觉与舒适度，可补充场景与文字。',
                  '提交后系统将自动与气象环境场匹配。',
                ]" :key="tip" class="flex gap-3 text-xs leading-5 text-muted">
                  <span class="step size-5 shrink-0 text-[10px]">{{ index + 1 }}</span>
                  {{ tip }}
                </li>
              </ol>
              <button class="button mt-5 w-full justify-center text-xs" @click="navigate('explore')">
                <AppIcon name="pin" :size="15" />
                打开探索地图
              </button>
            </section>

            <section v-reveal="120" class="rounded-2xl border border-emerald-200 bg-[#eef6f0] p-7">
              <span class="grid size-10 place-items-center rounded-lg bg-white text-accent">
                <AppIcon name="shield" :size="20" />
              </span>
              <h3 class="mt-4 section-title">隐私承诺</h3>
              <p class="mt-3 text-xs leading-6 text-muted">
                你的精确位置仅用于本地提交。对外展示前，所有打卡坐标都会被归并到
                <strong class="font-semibold text-ink">200 m × 200 m 网格</strong>，
                他人无法从公开数据还原你的真实位置。
              </p>
            </section>

            <section v-reveal="200" class="rounded-2xl border border-line bg-white p-7 shadow-xs">
              <span class="grid size-10 place-items-center rounded-lg bg-[#f9e8de] text-terracotta">
                <AppIcon name="heart" :size="20" />
              </span>
              <h3 class="mt-4 section-title">为什么值得打卡？</h3>
              <p class="mt-3 text-xs leading-6 text-muted">
                每一份体感都会与同时刻的微气候场匹配，成为「主观热暴露」研究的公共样本——
                你的感受，正在让城市降温决策更有依据。
              </p>
            </section>
          </div>
        </div>
      </template>
    </main>

    <SiteFooter />
  </div>
</template>
