<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import AppIcon from './AppIcon.vue';
import { useWorkspace } from '../stores/workspace';
import { reasonText } from '../services/format';
import { HEAT_RISK_PHASES, legendGradientCss, MITIGATION_LEGEND_TICKS, RISK_LEVELS, RISK_LEVEL_ORDER, RISK_STYLE_META } from '../services/heatRisk';
const props = defineProps<{ statuses: Record<string, string> }>();
const emit = defineEmits<{ layer: [id: string, visible: boolean]; opacity: [value: number]; canopy: [value: number]; buildingOpacity: [value: number]; presentation: [mode: 'analysis' | 'context']; close: []; methods: [] }>();
const store = useWorkspace();
const visible = ref<Record<string, boolean>>({});
const opacity = ref(90);
const buildingOpacity = ref(100);
const presentation = ref<'analysis' | 'context'>('analysis');
function choosePresentation(mode: 'analysis' | 'context') {
  presentation.value = mode;
  opacity.value = mode === 'analysis' ? 90 : 0;
  buildingOpacity.value = 100;
  emit('presentation', mode);
}
const ugc = ref(true);
const shadows = ref(false);
const transparentTrees = ref(false);
const variableIcons: Record<string, string> = { utci: 'temperature', air_temperature: 'temperature', relative_humidity: 'drop', wind_speed: 'wind', dew_point: 'water', solar_radiation: 'sun', net_shortwave_background: 'sun', local_downwelling_shortwave: 'sun' };
const layerIcons: Record<string, string> = { buildings: 'building', canopy: 'tree', water: 'water', green: 'layers', terrain: 'layers', roads: 'next', poi: 'pin' };
const activeLegend = computed(() => store.activeItem?.assets.length ? store.activeItem.legend : null);
watch(() => store.layers, layers => { visible.value = Object.fromEntries(layers.map(layer => [layer.layer_id, layer.default_visible])); ugc.value = true; shadows.value = false; transparentTrees.value = false; opacity.value = 90; buildingOpacity.value = 100; presentation.value = 'analysis'; }, { immediate: true });
defineExpose({ visible: () => [...store.layers.filter(layer => visible.value[layer.layer_id]).map(layer => layer.name), ...(ugc.value ? ['公开体感'] : []), ...(shadows.value ? ['几何阴影'] : [])] });
</script>
<template>
  <div class="flex items-center justify-between"><h2 class="text-base font-semibold">探索环境</h2><button class="icon-button" aria-label="收起图层面板" @click="emit('close')"><AppIcon name="sliders" :size="17" /></button></div>
  <div class="mt-4 grid grid-cols-2 gap-1 rounded-lg bg-canvas p-1" role="group" aria-label="地图显示模式">
    <button class="min-h-10 rounded-md text-xs cursor-pointer" :class="presentation === 'analysis' ? 'bg-white text-accent shadow-sm' : 'text-muted'" :aria-pressed="presentation === 'analysis'" @click="choosePresentation('analysis')">热环境分析</button>
    <button class="min-h-10 rounded-md text-xs cursor-pointer" :class="presentation === 'context' ? 'bg-white text-accent shadow-sm' : 'text-muted'" :aria-pressed="presentation === 'context'" @click="choosePresentation('context')">城市背景</button>
  </div>
  <p class="mt-2 text-[11px] leading-5 text-muted">{{ opacity > 0 ? '地面颜色表达环境值；灰白建筑仅展示形态。' : '已隐藏环境色层，点击地图仍可查询环境值。' }}</p>
  <section class="mt-6"><div class="mb-3 flex items-center justify-between"><h3 class="section-title">环境变量</h3><span class="text-xs text-muted">{{ store.product?.unit }}</span></div><div class="grid grid-cols-2 gap-2"><button v-for="product in store.catalog.products" :key="product.variable" class="variable-button" :class="{ 'variable-active': store.variable === product.variable }" :disabled="product.availability !== 'available'" :aria-pressed="store.variable === product.variable" :title="product.availability !== 'available' ? reasonText(product.reason_code) : product.definition" @click="store.chooseVariable(product.variable)"><AppIcon :name="variableIcons[product.variable] || 'layers'" :size="19" /><span>{{ product.name }}</span><span v-if="product.availability !== 'available'" class="text-[11px]">暂不可用</span></button></div>
    <!-- 当前激活图例 -->
    <div v-if="activeLegend" class="mt-3.5 rounded-xl border border-line bg-canvas/70 p-3 text-xs">
      <div class="flex items-center justify-between font-medium text-ink">
        <span>{{ store.committedProduct?.name }} 图例</span>
        <span class="text-muted font-normal">{{ store.activeItem?.unit }}</span>
      </div>
      <div class="mt-2 h-3 w-full rounded-sm ring-1 ring-black/15" :style="{ background: `linear-gradient(to right, ${activeLegend.colors.join(', ')})` }" />
      <div class="mt-1 flex justify-between text-[11px] text-muted tabular-nums">
        <span>{{ activeLegend.min }}</span>
        <span>{{ ((activeLegend.min + activeLegend.max) / 2).toFixed(1) }}</span>
        <span>{{ activeLegend.max }}</span>
      </div>
      <p v-if="store.activeItem?.variable === 'utci'" class="mt-2 text-[11px] leading-5 text-muted">连续数值色带，非热应激等级。超出色标范围使用端点色；缺测不着色。</p>
    </div>
    <details class="mt-3"><summary class="text-xs text-muted cursor-pointer font-medium">显示微调</summary><label class="mt-2.5 flex items-center justify-between text-xs text-muted">环境色层不透明度<span>{{ opacity }}%</span></label><input v-model.number="opacity" class="mt-1.5 w-full" type="range" min="0" max="100" aria-label="环境色层不透明度" @input="emit('opacity', opacity / 100)" /><label class="mt-2.5 flex items-center justify-between text-xs text-muted">三维建筑不透明度<span>{{ buildingOpacity }}%</span></label><input v-model.number="buildingOpacity" class="mt-1.5 w-full" type="range" min="0" max="100" aria-label="三维建筑不透明度" @input="emit('buildingOpacity', buildingOpacity / 100)" /><label class="toggle-row mt-2.5"><span>树冠半透明</span><input v-model="transparentTrees" class="switch" type="checkbox" @change="emit('canopy', transparentTrees ? .35 : 1)" /></label></details></section>
  <section class="panel-section">
    <label class="toggle-row">
      <span class="flex items-center gap-2.5"><AppIcon name="flame" :size="16" class="text-terracotta" />热暴露风险<span class="text-[11px] text-muted">模型反演</span></span>
      <input class="switch" type="checkbox" :checked="store.heatRisk.enabled" :aria-pressed="store.heatRisk.enabled" @change="store.setHeatRiskEnabled(($event.target as HTMLInputElement).checked)" />
    </label>
    <p v-if="!store.heatRisk.enabled" class="mt-2.5 text-[11px] leading-5 text-muted">客观 UTCI × M1 主观偏热概率回归模型，1km 网格反演、平滑色斑渲染未来 24 小时热暴露风险。</p>
    <template v-if="store.heatRisk.enabled">
      <div v-if="store.heatRisk.loading" class="mt-3 flex items-center gap-2 text-xs text-muted"><span class="loader size-3" />正在加载模型反演网格…</div>
      <p v-else-if="store.heatRisk.error" class="mt-3 text-xs text-terracotta" role="alert">{{ store.heatRisk.error }}</p>
      <template v-else>
        <div class="mt-3 grid grid-cols-3 gap-1 rounded-lg bg-canvas p-1" role="group" aria-label="风险着色模式">
          <button v-for="style in RISK_STYLE_META" :key="style.id" class="min-h-9 rounded-md text-xs cursor-pointer" :class="store.heatRisk.style === style.id ? 'bg-white text-accent shadow-sm' : 'text-muted'" :aria-pressed="store.heatRisk.style === style.id" :title="style.hint" @click="store.setHeatRiskStyle(style.id)">{{ style.label }}</button>
        </div>
        <div class="mt-2 grid grid-cols-4 gap-1" role="group" aria-label="反演时相">
          <button v-for="phase in HEAT_RISK_PHASES" :key="phase.hour" class="min-h-9 rounded-md text-xs cursor-pointer border" :class="store.heatRisk.phase === phase.hour ? 'border-accent bg-accent/10 font-medium text-accent' : 'border-line text-muted'" :aria-pressed="store.heatRisk.phase === phase.hour" :title="phase.tag" @click="store.setHeatRiskPhase(phase.hour)">{{ phase.label }}</button>
        </div>
        <div v-if="store.heatRisk.style === 'level'" class="mt-3 rounded-xl border border-line bg-canvas/70 p-3 text-xs">
          <div class="flex items-center justify-between font-medium text-ink"><span>综合风险等级图例</span><span class="font-normal text-muted">联合分级</span></div>
          <div class="mt-2 space-y-1.5">
            <div v-for="level in RISK_LEVEL_ORDER" :key="level" class="flex items-start gap-2">
              <span class="mt-0.5 size-3 shrink-0 rounded-sm ring-1 ring-black/15" :style="{ background: RISK_LEVELS[level].color }" />
              <span class="w-14 shrink-0 font-medium text-ink">{{ RISK_LEVELS[level].label }}</span>
              <span class="text-[11px] leading-4 text-muted">{{ RISK_LEVELS[level].threshold }}</span>
            </div>
          </div>
          <p class="mt-2 text-[11px] leading-4 text-muted">满足任一阈值即入级：客观 UTCI（°C）或主观偏热概率 P(hot)。</p>
        </div>
        <div v-else class="mt-3 rounded-xl border border-line bg-canvas/70 p-3 text-xs">
          <div class="flex items-center justify-between font-medium text-ink">
            <span>{{ store.heatRisk.style === 'probability' ? '主观偏热概率 P(hot)' : '环境缓解量 ΔP' }}</span>
            <span class="font-normal text-muted">{{ store.heatRisk.style === 'probability' ? 'M1 回归模型' : 'M1 − M0' }}</span>
          </div>
          <div class="mt-2 h-3 w-full rounded-sm ring-1 ring-black/15" :style="{ background: legendGradientCss(store.heatRisk.style) }" />
          <div class="mt-1 flex justify-between text-[11px] text-muted tabular-nums">
            <template v-if="store.heatRisk.style === 'probability'"><span>0%</span><span>50%</span><span>100%</span></template>
            <template v-else><span v-for="tick in MITIGATION_LEGEND_TICKS" :key="tick.label">{{ tick.label }}</span></template>
          </div>
          <p class="mt-2 text-[11px] leading-4 text-muted">{{ store.heatRisk.style === 'probability' ? '“感觉偏热”的概率，由 UTCI、时间谐波与绿地/水体/建筑占比加权 Logistic 回归给出。' : '下垫面使偏热概率相对纯气象基准的变化：蓝色为环境降温收益，透明≈无作用（露出客观底色），紫红为偏热加剧；颜色越深幅度越大。' }}</p>
        </div>
        <p v-if="store.heatRisk.phase === 14 && store.heatRiskDataset?.hotspots.length" class="mt-2.5 text-[11px] leading-4 text-muted">已在地图标注 Top {{ store.heatRiskDataset.hotspots.length }} 主观偏热极值热点（14 时峰值）。</p>
        <p class="mt-2.5 text-[11px] leading-4 text-muted">{{ store.heatRisk.style === 'mitigation' ? '缓解模式与环境色带混合显示；其余模式隐藏环境色带以便读图，关闭后自动恢复。' : '开启期间隐藏环境色带以便读图，关闭后自动恢复；点击网格查看机制解读。' }}</p>
        <p class="mt-2 text-[11px] leading-4 text-muted">80 条真实打卡实证：AUC 0.931 / F1 0.92。</p>
      </template>
    </template>
  </section>
  <section class="panel-section"><h3 class="section-title mb-3">场景图层</h3><label v-for="layer in store.layers" :key="layer.layer_id" class="toggle-row" :class="layer.availability !== 'available' ? 'opacity-50' : ''"><span class="flex items-center gap-2.5"><AppIcon :name="layerIcons[layer.layer_id] || 'layers'" :size="16" class="text-muted" />{{ layer.name }}<span v-if="statuses[layer.layer_id] === 'loading'" class="loader size-3" /><span v-else-if="statuses[layer.layer_id] === 'failed'" class="text-xs text-terracotta">未加载</span><span v-else-if="layer.availability !== 'available'" class="text-xs">暂无</span></span><input v-model="visible[layer.layer_id]" class="switch" type="checkbox" :disabled="layer.availability !== 'available'" @change="emit('layer', layer.layer_id, visible[layer.layer_id]!)" /></label><label class="toggle-row"><span class="flex items-center gap-2.5"><AppIcon name="sun" :size="16" class="text-muted" />太阳阴影<span class="text-[11px] text-muted">模拟</span></span><input v-model="shadows" class="switch" type="checkbox" @change="emit('layer', 'shadows', shadows)" /></label></section>
  <section class="panel-section"><label class="toggle-row"><h3 class="section-title">城市里的体感</h3><input v-model="ugc" class="switch" type="checkbox" @change="emit('layer', 'ugc', ugc)" /></label><div class="mt-3 grid grid-cols-3 rounded-lg bg-canvas p-1"><button v-for="option in [{ hours: 3, name: '近 3 小时' }, { hours: 24, name: '近 24 小时' }, { hours: 168, name: '近 7 天' }]" :key="option.hours" class="min-h-10 rounded-md text-xs" :class="store.ugcHours === option.hours ? 'bg-white text-accent shadow-sm' : 'text-muted'" :aria-pressed="store.ugcHours === option.hours" @click="store.ugcHours = option.hours; store.refreshRecords()">{{ option.name }}</button></div><p class="mt-3 text-xs leading-6 text-muted">按实际体验时间筛选</p></section>
  <button class="mt-6 flex min-h-11 w-full items-center justify-between border-t border-line pt-4 text-xs text-muted" @click="emit('methods')"><span class="flex items-center gap-2"><AppIcon name="info" :size="15" />数据与方法</span><AppIcon name="external" :size="14" /></button>
</template>
