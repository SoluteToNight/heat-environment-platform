<script setup lang="ts">
import { computed } from 'vue';
import AppIcon from '../AppIcon.vue';
import { useWorkspace } from '../../stores/workspace';
import { navigate, routeHref, type SiteRouteName } from '../../app/router';

const props = defineProps<{ active: SiteRouteName }>();
const store = useWorkspace();

const links: Array<{ name: SiteRouteName; label: string }> = [
  { name: 'home', label: '首页' },
  { name: 'explore', label: '探索地图' },
  { name: 'profile', label: '个人中心' },
  { name: 'about', label: '关于平台' },
];

const loginLabel = computed(() => (store.session.authenticated ? store.session.user?.alias || '已登录' : '登录'));
</script>

<template>
  <header class="site-header">
    <div class="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-5">
      <button class="flex shrink-0 items-center gap-2.5 text-left" title="返回网站首页" @click="navigate('home')">
        <span class="grid size-9 place-items-center rounded-xl bg-accent text-white shadow-xs">
          <AppIcon name="temperature" :size="20" />
        </span>
        <span>
          <span class="block text-sm font-bold tracking-tight text-ink">申城热境</span>
          <span class="block text-[11px] text-muted">上海城市热环境可视分析平台</span>
        </span>
      </button>

      <nav class="hidden items-center gap-1 md:flex" aria-label="站点导航">
        <a
          v-for="link in links"
          :key="link.name"
          class="site-nav-link"
          :class="{ 'is-active': props.active === link.name }"
          :href="routeHref(link.name)"
        >{{ link.label }}</a>
      </nav>

      <div class="flex shrink-0 items-center gap-2">
        <a
          class="hidden items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium text-muted transition-colors hover:bg-green-soft hover:text-accent sm:inline-flex"
          :href="routeHref('profile')"
        >
          <AppIcon name="user" :size="15" />
          <span class="max-w-24 truncate">{{ loginLabel }}</span>
        </a>
        <button class="button-primary text-xs py-2" @click="navigate('explore')">
          进入地图
          <AppIcon name="next" :size="15" />
        </button>
      </div>
    </div>
  </header>
</template>
