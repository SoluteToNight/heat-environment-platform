<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useWorkspace } from '../../stores/workspace';
import { SceneAdapter, type MapPick } from './adapter';
import AppIcon from '../../components/AppIcon.vue';
import type { Coordinates } from '../../services/contracts';
const store = useWorkspace();
const emit = defineEmits<{ ready: []; pick: [items: MapPick[]]; layerStatus: [id: string, status: string] }>();
const container = ref<HTMLElement>();
const failed = ref('');
const loading = ref(false);
const waiting = computed(() => store.loading || loading.value);
const failure = computed(() => failed.value || (!store.loading && !store.scene ? store.error || '暂无可加载场景。' : ''));
let adapter: SceneAdapter | undefined;
let generation = 0;
async function mount() {
  const ticket = ++generation;
  adapter?.destroy(); adapter = undefined; store.bindRenderer(null);
  loading.value = false; failed.value = '';
  if (!container.value || !store.scene) return;
  loading.value = true;
  try {
    const next = await SceneAdapter.create(container.value, store.scene, store.layers, { pick: items => emit('pick', items), viewport: bbox => void store.refreshRecords(bbox), error: message => { failed.value = message; }, layerStatus: (id, status) => emit('layerStatus', id, status) });
    if (ticket !== generation) { next.destroy(); return; }
    adapter = next;
    (window as any).__sceneAdapter = next;
    (window as any).__cesiumViewer = (next as any).viewer;
    adapter.setRecords(store.records);
    store.bindRenderer((view, variable) => next.prepare(view, variable));
    syncHeatRisk();
  } catch (error) { if (ticket === generation) failed.value = error instanceof Error ? error.message : '无法启动三维地图'; }
  finally { if (ticket === generation) { loading.value = false; emit('ready'); } }
}
function syncHeatRisk() {
  adapter?.applyHeatRisk(
    { enabled: store.heatRisk.enabled, phase: store.heatRisk.phase, style: store.heatRisk.style },
    store.heatRiskDataset,
  );
}
watch(() => store.records, records => adapter?.setRecords(records));
watch(() => [store.heatRisk.enabled, store.heatRisk.phase, store.heatRisk.style, store.heatRiskDataset], syncHeatRisk);
watch(() => store.selection, selection => { if (selection) adapter?.select(selection.coordinates); });
watch([container, () => store.scene], () => void mount(), { flush: 'post' });
onBeforeUnmount(() => { generation++; adapter?.destroy(); store.bindRenderer(null); });
defineExpose({
  reset: () => adapter?.reset(), top: () => adapter?.reset(true), overview: () => adapter?.flyToOverview(), north: () => adapter?.north(), zoom: (inward: boolean) => adapter?.zoom(inward),
  focus: (point: Coordinates) => adapter?.focus(point), showLayer: (id: string, visible: boolean) => adapter?.showLayer(id, visible),
  opacity: (value: number) => adapter?.setOpacity(value), canopyOpacity: (value: number) => adapter?.setCanopyOpacity(value),
  buildingOpacity: (value: number) => adapter?.setBuildingOpacity(value),
  presentation: (mode: 'analysis' | 'context') => adapter?.setPresentation(mode),
  draft: (point: Coordinates, coarse: boolean) => adapter?.select(point, true, coarse), clearDraft: () => adapter?.clearDraft(),
  capture: async () => { if (!adapter || failed.value) throw new Error('地图尚未就绪，无法导出。'); return adapter.capture(); },
});
</script>
<template>
  <div ref="container" class="absolute inset-0" role="region" aria-label="三维地图：拖动平移，滚轮缩放，按住中键倾斜。可使用外部地图工具和地点搜索。" tabindex="0" />
  <div v-if="waiting && !failure" class="pointer-events-none absolute inset-0 grid place-content-center bg-canvas/80 text-center" role="status">
    <span class="loader mx-auto mb-4" /><p class="text-sm text-muted">正在准备街区场景</p>
  </div>
  <div v-if="failure" class="absolute inset-0 flex flex-col items-center justify-center bg-canvas/95 px-10 text-center" role="alert">
    <AppIcon name="layers" :size="36" /><h2 class="mt-5 text-xl">{{ store.scene ? '继续探索，无需三维地图' : '场景加载失败' }}</h2><p class="mt-3 max-w-sm text-sm leading-7 text-muted">{{ failure }}</p>
    <button class="button mt-5" @click="store.scene ? mount() : store.initialize()">重新加载场景</button><p class="mt-3 text-xs text-muted">搜索地点，或在地点详情中输入坐标。</p>
  </div>
</template>
