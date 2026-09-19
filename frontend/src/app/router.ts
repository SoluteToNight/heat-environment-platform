import { ref } from 'vue';

export type SiteRouteName = 'home' | 'explore' | 'profile' | 'about';

const routeNames: SiteRouteName[] = ['home', 'explore', 'profile', 'about'];

function parse(): SiteRouteName {
  const rawHash = location.hash;
  const first = rawHash.replace(/^#\/?/, '').split('/')[0] || '';
  if (first === 'explore' || first === 'profile' || first === 'about') return first;
  if (rawHash === '' || rawHash === '#') {
    // 旧版深链（无 hash 且带 ?scene_id/?variable/?time）保持直达地图工作台；
    // 显式的 #/ 始终是首页，即使 URL 上残留地图查询参数。
    const params = new URLSearchParams(location.search);
    if (params.has('scene_id') || params.has('variable') || params.has('time')) return 'explore';
  }
  return 'home';
}

export const siteRoute = ref<SiteRouteName>(parse());

export function navigate(name: SiteRouteName) {
  if (siteRoute.value === name) {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    return;
  }
  location.hash = name === 'home' ? '#/' : `#/${name}`;
}

window.addEventListener('hashchange', () => {
  siteRoute.value = parse();
  window.scrollTo({ top: 0 });
});

export function routeHref(name: SiteRouteName) {
  return name === 'home' ? '#/' : `#/${name}`;
}
