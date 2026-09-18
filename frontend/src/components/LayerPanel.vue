<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import AppIcon from './AppIcon.vue';
import { useWorkspace } from '../stores/workspace';
import { reasonText } from '../services/format';
const props = defineProps<{ statuses: Record<string, string> }>();
const emit = defineEmits<{ layer: [id: string, visible: boolean]; opacity: [value: number]; canopy: [value: number]; buildingOpacity: [value: number]; close: []; methods: [] }>();
const store = useWorkspace();
const visible = ref<Record<string, boolean>>({});
const opacity = ref(75);
const buildingOpacity = ref(88);
const ugc = ref(true);
const shadows = ref(false);
const transparentTrees = ref(false);
const variableIcons: Record<string, string> = { utci: 'temperature', air_temperature: 'temperature', relative_humidity: 'drop', wind_speed: 'wind', dew_point: 'water', solar_radiation: 'sun', net_shortwave_background: 'sun', local_downwelling_shortwave: 'sun' };
const layerIcons: Record<string, string> = { buildings: 'building', canopy: 'tree', water: 'water', green: 'layers', terrain: 'layers', roads: 'next', poi: 'pin' };
const activeLegend = computed(() => store.activeItem?.assets.length ? store.activeItem.legend : null);
watch(() => store.layers, layers => { visible.value = Object.fromEntries(layers.map(layer => [layer.layer_id, layer.default_visible])); ugc.value = true; shadows.value = false; transparentTrees.value = false; opacity.value = 75; buildingOpacity.value = 88; }, { immediate: true });
defineExpose({ visible: () => [...store.layers.filter(layer => visible.value[layer.layer_id]).map(layer => layer.name), ...(ugc.value ? ['公开体感'] : []), ...(shadows.value ? ['几何阴影'] : [])] });
</script>
<template>
  <div class="flex items-center justify-between"><h2 class="text-base font-semibold">探索环境</h2><button class="icon-button" aria-label="收起图层面板" @click="emit('close')"><AppIcon name="sliders" :size="17" /></button></div>
  <section class="mt-6"><div class="mb-3 flex items-center justify-between"><h3 class="section-title">环境变量</h3><span class="text-xs text-muted">{{ store.product?.unit }}</span></div><div class="grid grid-cols-2 gap-2"><button v-for="product in store.catalog.products" :key="product.variable" class="variable-button" :class="{ 'variable-active': store.variable === product.variable }" :disabled="product.availability !== 'available'" :aria-pressed="store.variable === product.variable" :title="product.availability !== 'available' ? reasonText(product.reason_code) : product.definition" @click="store.chooseVariable(product.variable)"><AppIcon :name="variableIcons[product.variable] || 'layers'" :size="19" /><span>{{ product.name }}</span><span v-if="product.availability !== 'available'" class="text-[11px]">暂不可用</span></button></div>
    <!-- 当前激活图例 -->
    <div v-if="activeLegend" class="mt-3.5 rounded-xl border border-line bg-canvas/70 p-3 text-xs">
      <div class="flex items-center justify-between font-medium text-ink">
        <span>{{ store.committedProduct?.name }} 图例</span>
        <span class="text-muted font-normal">{{ store.activeItem?.unit }}</span>
      </div>
      <div class="mt-2 h-2.5 w-full rounded-sm" :style="{ background: `linear-gradient(to right, ${activeLegend.colors.join(', ')})` }" />
      <div class="mt-1 flex justify-between text-[11px] text-muted tabular-nums">
        <span>{{ activeLegend.min }}</span>
        <span>{{ ((activeLegend.min + activeLegend.max) / 2).toFixed(1) }}</span>
        <span>{{ activeLegend.max }}</span>
      </div>
    </div>
    <details class="mt-3" open><summary class="text-xs text-muted cursor-pointer font-medium">显示设置</summary><label class="mt-2.5 flex items-center justify-between text-xs text-muted">色带透明度<span>{{ opacity }}%</span></label><input v-model.number="opacity" class="mt-1.5 w-full" type="range" min="0" max="100" aria-label="环境色带透明度" @input="emit('opacity', opacity / 100)" /><label class="mt-2.5 flex items-center justify-between text-xs text-muted">三维建筑不透明度<span>{{ buildingOpacity }}%</span></label><input v-model.number="buildingOpacity" class="mt-1.5 w-full" type="range" min="0" max="100" aria-label="三维建筑不透明度" @input="emit('buildingOpacity', buildingOpacity / 100)" /><label class="toggle-row mt-2.5"><span>树冠半透明</span><input v-model="transparentTrees" class="switch" type="checkbox" @change="emit('canopy', transparentTrees ? .35 : 1)" /></label></details></section>
  <section class="panel-section"><h3 class="section-title mb-3">场景图层</h3><label v-for="layer in store.layers" :key="layer.layer_id" class="toggle-row" :class="layer.availability !== 'available' ? 'opacity-50' : ''"><span class="flex items-center gap-2.5"><AppIcon :name="layerIcons[layer.layer_id] || 'layers'" :size="16" class="text-muted" />{{ layer.name }}<span v-if="statuses[layer.layer_id] === 'loading'" class="loader size-3" /><span v-else-if="statuses[layer.layer_id] === 'failed'" class="text-xs text-terracotta">未加载</span><span v-else-if="layer.availability !== 'available'" class="text-xs">暂无</span></span><input v-model="visible[layer.layer_id]" class="switch" type="checkbox" :disabled="layer.availability !== 'available'" @change="emit('layer', layer.layer_id, visible[layer.layer_id]!)" /></label><label class="toggle-row"><span class="flex items-center gap-2.5"><AppIcon name="sun" :size="16" class="text-muted" />太阳阴影<span class="text-[11px] text-muted">模拟</span></span><input v-model="shadows" class="switch" type="checkbox" @change="emit('layer', 'shadows', shadows)" /></label></section>
  <section class="panel-section"><label class="toggle-row"><h3 class="section-title">城市里的体感</h3><input v-model="ugc" class="switch" type="checkbox" @change="emit('layer', 'ugc', ugc)" /></label><div class="mt-3 grid grid-cols-3 rounded-lg bg-canvas p-1"><button v-for="option in [{ hours: 3, name: '近 3 小时' }, { hours: 24, name: '近 24 小时' }, { hours: 168, name: '近 7 天' }]" :key="option.hours" class="min-h-10 rounded-md text-xs" :class="store.ugcHours === option.hours ? 'bg-white text-accent shadow-sm' : 'text-muted'" :aria-pressed="store.ugcHours === option.hours" @click="store.ugcHours = option.hours; store.refreshRecords()">{{ option.name }}</button></div><p class="mt-3 text-xs leading-6 text-muted">按实际体验时间筛选</p></section>
  <button class="mt-6 flex min-h-11 w-full items-center justify-between border-t border-line pt-4 text-xs text-muted" @click="emit('methods')"><span class="flex items-center gap-2"><AppIcon name="info" :size="15" />数据与方法</span><AppIcon name="external" :size="14" /></button>
</template>
