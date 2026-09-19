<script setup lang="ts">
import AppIcon from '../AppIcon.vue';
import { navigate, routeHref } from '../../app/router';

const pageLinks = [
  { name: 'home' as const, label: '网站首页' },
  { name: 'explore' as const, label: '探索地图' },
  { name: 'profile' as const, label: '个人中心' },
  { name: 'about' as const, label: '关于平台' },
];

const dataLinks = [
  { label: '天地图 · 国家地理信息公共服务平台', href: 'https://www.tianditu.gov.cn' },
  { label: 'Open-Meteo · ECMWF 气象背景场', href: 'https://open-meteo.com' },
  { label: '和风天气 · 48 小时预报', href: 'https://www.qweather.com' },
  { label: 'OpenStreetMap · 建筑与路网', href: 'https://www.openstreetmap.org' },
];

const year = new Date().getFullYear();
</script>

<template>
  <footer class="border-t border-line bg-[#0f2019] text-white/75">
    <div class="mx-auto grid w-full max-w-6xl gap-10 px-5 py-12 md:grid-cols-[1.4fr_1fr_1.2fr]">
      <div>
        <div class="flex items-center gap-2.5">
          <span class="grid size-9 place-items-center rounded-xl bg-accent text-white">
            <AppIcon name="temperature" :size="20" />
          </span>
          <div>
            <p class="text-sm font-bold text-white">申城热境</p>
            <p class="text-[11px] text-white/55">Shanghai Urban Heat Observatory</p>
          </div>
        </div>
        <p class="mt-4 max-w-sm text-xs leading-6 text-white/60">
          融合客观微气候、太阳辐射与公众主观体感打卡，绘制城市主客观热暴露差异图谱，为街区降温与高温应急提供空间决策支持。
        </p>
        <div class="mt-4 flex items-center gap-1.5 text-[11px] text-white/50">
          <span class="live-dot size-1.5 rounded-full bg-emerald-400" />
          气象数据自动同步发布中
        </div>
      </div>

      <div>
        <p class="text-xs font-semibold uppercase tracking-wider text-white/85">页面导航</p>
        <ul class="mt-4 space-y-2.5 text-xs">
          <li v-for="link in pageLinks" :key="link.name">
            <a class="text-white/60 transition-colors hover:text-white" :href="routeHref(link.name)">{{ link.label }}</a>
          </li>
        </ul>
      </div>

      <div>
        <p class="text-xs font-semibold uppercase tracking-wider text-white/85">数据来源</p>
        <ul class="mt-4 space-y-2.5 text-xs">
          <li v-for="link in dataLinks" :key="link.label">
            <a class="text-white/60 transition-colors hover:text-white" :href="link.href" target="_blank" rel="noopener noreferrer">{{ link.label }}</a>
          </li>
        </ul>
      </div>
    </div>

    <div class="border-t border-white/10">
      <div class="mx-auto flex w-full max-w-6xl flex-col gap-1.5 px-5 py-4 text-[11px] text-white/45 md:flex-row md:items-center md:justify-between">
        <p>© {{ year }} 申城热境 · 《GIS 综合实习》选题 9 —— 城市主客观热暴露差异及其影响机制的 GIS 分析</p>
        <p>底图版权归 © <a class="underline underline-offset-2 hover:text-white" href="https://www.tianditu.gov.cn" target="_blank" rel="noopener noreferrer">天地图 Tianditu</a> 所有</p>
      </div>
    </div>
  </footer>
</template>
