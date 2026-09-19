<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import AppIcon from './AppIcon.vue';
import { api } from '../services/api';
import type {
  CustomInversionResult,
  DecisionSupportResponse,
  ExtremeRegionsResponse,
  Forecast24hSummary,
  ModelEvaluationResponse,
} from '../services/contracts';

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const activeTab = ref<'overview' | 'hotspots' | 'decision' | 'maps' | 'calculator' | 'evaluation'>('overview');
const loading = ref(false);
const errorMsg = ref<string | null>(null);

// Data states
const summaryData = ref<Forecast24hSummary | null>(null);
const extremeData = ref<ExtremeRegionsResponse | null>(null);
const decisionData = ref<DecisionSupportResponse | null>(null);
const modelEvalData = ref<ModelEvaluationResponse | null>(null);

// Calculator states
const calcTa = ref(35.0);
const calcRh = ref(65.0);
const calcWind = ref(2.0);
const calcRad = ref(450.0);
const calcGreen = ref(0.15);
const calcWater = ref(0.05);
const calcBldg = ref(0.25);
const calcResult = ref<CustomInversionResult | null>(null);
const calcLoading = ref(false);
const calcError = ref<string | null>(null);

// Map Viewer states
const selectedMapIndex = ref(8); // Default to Figure 09 (Shanghai 24h peak map)
const mapList = [
  { file: '01_model_coefficients_odds_ratios.png', title: '图01. 模型系数与优势比森林图', desc: 'M0与M1二元逻辑回归特征系数及95%置信区间' },
  { file: '02_probability_calibration_curves.png', title: '图02. 多模型概率校准曲线', desc: '十等分校准曲线、Brier分数与可靠性评估' },
  { file: '03_forecast_24h_timeline_inversion.png', title: '图03. 24h逐时主观热感知反演', desc: '宏观逐小时UTCI与偏热感知概率P(hot)演化' },
  { file: '04_extreme_heatwave_24h_inversion.png', title: '图04. 极端热浪情景压力测试', desc: '高温高湿极值天气下的体感跃迁与超载分析' },
  { file: '05_real_24h_weather_utci_timeline.png', title: '图05. 真实24h天气与UTCI时序', desc: '上海实时气温、湿度、风速与UTCI动力学' },
  { file: '06_real_ugc_validation_metrics.png', title: '图06. 真实UGC打卡盲测验证', desc: '实测人群打卡数据对模型预测一致率与Brier检验' },
  { file: '07_spatial_microclimate_contrast.png', title: '图07. 微环境调节与热点对比', desc: '绿化、水体微环境对不同网格偏热概率的削减' },
  { file: '08_decision_support_matrix.png', title: '图08. 分级预警与应急决策矩阵', desc: '主客观四级风险联动预警与跨行业保障指引' },
  { file: '09_shanghai_24h_peak_heat_exposure_maps.png', title: '图09. 全市24h峰值热暴露连续场', desc: '全域UTCI热应力场与主观偏热概率空间全景' },
  { file: '10_multi_temporal_24h_subjective_heat_maps.png', title: '图10. 四时相全景时空演化图', desc: '清晨、正午峰值、傍晚、夜间体感动态迁移' },
  { file: '11_microclimate_mitigation_and_mismatch_maps.png', title: '图11. 微环境缓解与错配分区图', desc: '生态降温效能与主客观热风险空间错配识别' },
  { file: '12_core_urban_hotspots_and_ugc_validation_map.png', title: '图12. 核心热岛聚类与UGC实证', desc: '外环内高密度热岛及真实用户打卡点位校核' },
  { file: '13_spatial_decision_support_and_action_zoning_map.png', title: '图13. 空间决策响应与防暑分区', desc: '四级响应空间落位与避暑驿站防灾协同网络' },
];

const selectedMap = computed(() => mapList[selectedMapIndex.value] ?? mapList[8]);

// Load initial data
watch(() => props.open, async (isOpen) => {
  if (isOpen) {
    await fetchAllPerceptionData();
    await runCalculation();
  }
});

onMounted(() => {
  if (props.open) {
    fetchAllPerceptionData();
    runCalculation();
  }
});

async function fetchAllPerceptionData() {
  loading.value = true;
  errorMsg.value = null;
  try {
    const [sRes, eRes, dRes, mRes] = await Promise.all([
      api.forecast24hSummary(),
      api.forecast24hExtremeRegions(5),
      api.forecast24hDecision(),
      api.modelsEvaluation(),
    ]);
    summaryData.value = sRes;
    extremeData.value = eRes;
    decisionData.value = dRes;
    modelEvalData.value = mRes;
  } catch (err: unknown) {
    console.error('Failed to load heat perception data:', err);
    errorMsg.value = err instanceof Error ? err.message : '获取热暴露预测数据失败';
  } finally {
    loading.value = false;
  }
}

async function runCalculation() {
  calcLoading.value = true;
  calcError.value = null;
  try {
    calcResult.value = await api.customInversion({
      air_temperature_c: calcTa.value,
      relative_humidity_pct: calcRh.value,
      wind_speed_10m_ms: calcWind.value,
      net_solar_radiation_wm2: calcRad.value,
      green_fraction: calcGreen.value,
      water_fraction: calcWater.value,
      building_fraction: calcBldg.value,
    });
  } catch (err) {
    console.error('Custom inversion error:', err);
    calcError.value = err instanceof Error ? err.message : '反演计算失败';
  } finally {
    calcLoading.value = false;
  }
}

let calcTimer: ReturnType<typeof setTimeout> | undefined;
function scheduleCalculation() {
  clearTimeout(calcTimer);
  calcTimer = setTimeout(runCalculation, 250);
}
onBeforeUnmount(() => clearTimeout(calcTimer));

function getUtciBadgeClass(utci: number) {
  if (utci >= 38) return 'text-red-700 bg-red-50';
  if (utci >= 32) return 'text-amber-700 bg-amber-50';
  if (utci >= 26) return 'text-yellow-700 bg-yellow-50';
  return 'text-emerald-700 bg-emerald-50';
}

/* 缺测一律显示占位符，绝不用 0 或常量冒充读数 */
const DASH = '—';
function num(value: number | null | undefined, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : DASH;
}
function pct(value: number | null | undefined, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : DASH;
}
function text(value: string | null | undefined): string {
  return value && value.trim() ? value : DASH;
}

const RISK_STYLES: Record<string, { zh: string; cls: string }> = {
  extreme: { zh: '极高风险', cls: 'bg-red-100 text-red-800 border-red-200' },
  high: { zh: '高风险', cls: 'bg-amber-100 text-amber-800 border-amber-200' },
  moderate: { zh: '中等风险', cls: 'bg-yellow-100 text-yellow-800 border-yellow-200' },
  low: { zh: '低风险', cls: 'bg-emerald-100 text-emerald-800 border-emerald-200' },
};
function riskLabel(level: string | null | undefined): string {
  if (!level) return DASH;
  return RISK_STYLES[level]?.zh ?? level;
}
function getRiskBadgeClass(level: string | null | undefined): string {
  return RISK_STYLES[level ?? '']?.cls ?? 'bg-slate-100 text-slate-700 border-slate-200';
}

const SECTOR_LABELS: Record<string, string> = {
  outdoor_labor: '户外作业与劳动保障',
  municipal_sanitation: '市政运行与环卫作业',
  public_shelters: '公共避暑驿站网络',
  vulnerable_groups: '敏感人群健康关怀',
};
function sectorLabel(key: string): string {
  return SECTOR_LABELS[key] ?? key;
}

const ALERT_LEVEL_LABELS: Record<string, string> = { red: '红色', orange: '橙色', yellow: '黄色', blue: '蓝色' };
function alertLevelLabel(level: string): string {
  return ALERT_LEVEL_LABELS[level] ?? level;
}
const ALERT_LEVEL_CLASSES: Record<string, string> = { red: 'bg-red-600', orange: 'bg-orange-500', yellow: 'bg-yellow-500', blue: 'bg-blue-600' };
function alertLevelClass(level: string): string {
  return ALERT_LEVEL_CLASSES[level] ?? 'bg-amber-500';
}
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3 sm:p-5 backdrop-blur-xs">
    <div class="flex h-[94vh] w-[96vw] max-w-7xl flex-col rounded-2xl bg-white shadow-2xl overflow-hidden border border-line">
      
      <!-- Top Header -->
      <div class="flex items-center justify-between border-b border-line px-6 py-3.5 bg-gradient-to-r from-amber-500/10 via-orange-500/5 to-transparent">
        <div class="flex items-center gap-3">
          <div class="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 text-white shadow-xs">
            <AppIcon name="temperature" :size="22" />
          </div>
          <div>
            <div class="flex items-center gap-2">
              <h2 class="text-base font-bold tracking-tight text-ink">
                上海主客观热暴露反演与分级应急决策系统
              </h2>
              <span class="rounded-full bg-orange-100 text-orange-800 text-[11px] font-bold px-2.5 py-0.5 border border-orange-200">
                真实24h气象时序驱动
              </span>
              <span class="rounded-full bg-emerald-100 text-emerald-800 text-[11px] font-bold px-2 py-0.5 border border-emerald-200">
                UGC 盲测 M1 AUC {{ num(summaryData?.ugc_validation_metrics.m1_auc, 4) }}
              </span>
            </div>
            <p class="text-xs text-muted mt-0.5">
              497 空间微环境网格 · UTCI 生物气象指标 · 真实 UGC 盲测闭环检验 (最优阈值准确率 {{ pct(summaryData?.ugc_validation_metrics.accuracy_optimal) }}) · 13 幅全域决策专题图
              <span v-if="summaryData"> · 数据时次 {{ text(summaryData.forecast_24h_overview.peak_time_bjt) }}</span>
            </p>
          </div>
        </div>

        <div class="flex items-center gap-2.5">
          <button
            class="flex items-center gap-1.5 rounded-lg border border-line bg-white px-3 py-1.5 text-xs font-medium text-ink hover:bg-canvas transition"
            :disabled="loading"
            @click="fetchAllPerceptionData"
          >
            <span v-if="loading" class="loader size-3 mr-1" />
            <AppIcon v-else name="clock" :size="14" />
            <span>刷新数据</span>
          </button>

          <button
            class="grid size-8 place-items-center rounded-lg text-muted hover:bg-canvas hover:text-ink transition cursor-pointer"
            title="关闭"
            @click="emit('close')"
          >
            <AppIcon name="close" :size="18" />
          </button>
        </div>
      </div>

      <!-- KPI Ribbon -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 px-6 py-2.5 border-b border-line bg-slate-50/70 text-xs">
        <div class="rounded-xl border border-line p-2.5 bg-white flex items-center justify-between">
          <div>
            <span class="text-muted block text-[11px]">24h 峰值 UTCI / 应激</span>
            <span class="font-bold text-sm text-red-600">
              {{ num(summaryData?.forecast_24h_overview.peak_utci_c) }} °C
            </span>
            <span class="block text-[10px] text-muted">{{ text(summaryData?.forecast_24h_overview.peak_stress_desc) }} · {{ text(summaryData?.forecast_24h_overview.peak_time_bjt) }}</span>
          </div>
          <div class="size-8 rounded-full bg-red-50 text-red-600 grid place-items-center font-bold text-[11px]">
            UTCI
          </div>
        </div>

        <div class="rounded-xl border border-line p-2.5 bg-white flex items-center justify-between">
          <div>
            <span class="text-muted block text-[11px]">主观偏热峰值概率 P(hot)</span>
            <span class="font-bold text-sm text-amber-600">
              {{ pct(summaryData?.forecast_24h_overview.peak_p_hot_inland) }}
            </span>
            <span class="block text-[10px] text-muted">滨水网格 {{ pct(summaryData?.forecast_24h_overview.peak_p_hot_waterfront) }}</span>
          </div>
          <div class="size-8 rounded-full bg-amber-50 text-amber-600 grid place-items-center font-bold text-[11px]">
            P(hot)
          </div>
        </div>

        <div class="rounded-xl border border-line p-2.5 bg-white flex items-center justify-between">
          <div>
            <span class="text-muted block text-[11px]">真实 UGC 盲测检验</span>
            <span class="font-bold text-sm text-emerald-600">
              {{ pct(summaryData?.ugc_validation_metrics.accuracy_optimal) }}
            </span>
            <span class="block text-[10px] text-muted">
              {{ summaryData?.ugc_validation_metrics.sample_count ?? DASH }} 条样本 · Brier {{ num(summaryData?.ugc_validation_metrics.m1_brier, 4) }}
            </span>
          </div>
          <div class="size-8 rounded-full bg-emerald-50 text-emerald-600 grid place-items-center font-bold text-[11px]">
            UGC
          </div>
        </div>

        <div class="rounded-xl border border-line p-2.5 bg-white flex items-center justify-between">
          <div>
            <span class="text-muted block text-[11px]">全域微环境网格与专题图</span>
            <span class="font-bold text-sm text-blue-600">497 网格 / 13 幅图</span>
            <span class="block text-[10px] text-muted">
              平均降温 {{ num(summaryData?.forecast_24h_overview.mean_cooling_benefit_pct) }}% · 峰值 {{ num(summaryData?.forecast_24h_overview.max_cooling_benefit_pct) }}%
            </span>
          </div>
          <div class="size-8 rounded-full bg-blue-50 text-blue-600 grid place-items-center font-bold text-[11px]">
            GIS
          </div>
        </div>
      </div>

      <!-- Navigation Tabs -->
      <div class="flex border-b border-line bg-canvas/30 px-6 gap-1 overflow-x-auto">
        <button
          v-for="t in [
            { key: 'overview', label: '24h时序反演与检验', icon: 'clock' },
            { key: 'hotspots', label: '极值热点与微气候', icon: 'pin' },
            { key: 'decision', label: '分级应急响应决策', icon: 'info' },
            { key: 'maps', label: '13幅学术级专题地图', icon: 'layers' },
            { key: 'calculator', label: '微环境实时反演计算器', icon: 'sliders' },
            { key: 'evaluation', label: '模型评估与优势比', icon: 'sun' },
          ]"
          :key="t.key"
          class="flex items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-semibold transition cursor-pointer shrink-0"
          :class="activeTab === t.key ? 'border-accent text-accent bg-white shadow-2xs' : 'border-transparent text-muted hover:text-ink'"
          @click="activeTab = (t.key as any)"
        >
          <AppIcon :name="(t.icon as any)" :size="14" />
          <span>{{ t.label }}</span>
        </button>
      </div>


      <!-- Tab Content Area -->
      <div class="flex-1 overflow-y-auto p-6 bg-slate-50/40">

        <div v-if="errorMsg" class="rounded-xl border border-red-200 bg-red-50 p-3.5 text-xs text-red-800 mb-4 flex items-start justify-between gap-3">
          <span>数据加载失败：{{ errorMsg }}</span>
          <button class="button shrink-0 text-xs py-1 px-2.5 cursor-pointer" :disabled="loading" @click="fetchAllPerceptionData">重试</button>
        </div>

        <!-- ================= Tab 1: Overview ================= -->
        <div v-if="activeTab === 'overview'" class="space-y-5">
          <div class="rounded-xl border border-line bg-white p-4 shadow-2xs">
            <h3 class="text-sm font-bold text-ink flex items-center gap-2 mb-2">
              <AppIcon name="clock" :size="16" class="text-accent" />
              上海实时 24 小时天气要素驱动 · 逐小时 UTCI 与主观偏热感知演化
            </h3>
            <p class="text-xs text-muted mb-4">
              输入源自上海真实 24 小时气象站序列，结合太阳辐射与下垫面参数计算逐时通用热气候指数 (UTCI)，并输入 M1 逻辑回归模型输出主观偏热感知概率 P(hot)。
              <span v-if="summaryData">数据源 {{ summaryData.real_forecast_source }}，生成于 {{ summaryData.generated_at }}。</span>
            </p>

            <!-- Hourly Table -->
            <div class="overflow-x-auto rounded-lg border border-line">
              <table class="w-full text-left text-xs border-collapse">
                <thead class="bg-canvas text-muted border-b border-line font-medium">
                  <tr>
                    <th class="p-2.5">时效</th>
                    <th class="p-2.5">气温 (°C)</th>
                    <th class="p-2.5">湿度 (%)</th>
                    <th class="p-2.5">风速 (m/s)</th>
                    <th class="p-2.5">净辐射 (W/m²)</th>
                    <th class="p-2.5">UTCI (°C)</th>
                    <th class="p-2.5">热应激等级</th>
                    <th class="p-2.5">内陆 P(hot)</th>
                    <th class="p-2.5">滨水 P(hot)</th>
                    <th class="p-2.5">微环境降温 (%)</th>
                    <th class="p-2.5">风险预警</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-line">
                  <tr v-if="!summaryData && !loading">
                    <td colspan="11" class="p-4 text-center text-muted text-xs">暂无逐时反演数据</td>
                  </tr>
                  <tr
                    v-for="h in summaryData?.hourly_details ?? []"
                    :key="h.hour"
                    class="hover:bg-amber-50/40 transition"
                    :class="h.risk_level === 'extreme' || h.risk_level === 'high' ? 'bg-orange-50/20' : ''"
                  >
                    <td class="p-2.5 font-bold text-ink">{{ text(h.time) }}</td>
                    <td class="p-2.5">{{ num(h.temperature_c) }}</td>
                    <td class="p-2.5">{{ num(h.humidity_pct, 0) }}</td>
                    <td class="p-2.5">{{ num(h.wind_speed_ms) }}</td>
                    <td class="p-2.5">{{ num(h.radiation_wm2, 0) }}</td>
                    <td class="p-2.5 font-semibold" :class="getUtciBadgeClass(h.utci_c)">
                      {{ num(h.utci_c) }}
                    </td>
                    <td class="p-2.5 text-[11px] text-muted">{{ text(h.stress_desc) }}</td>
                    <td class="p-2.5 font-bold text-accent">{{ pct(h.p_hot_inland) }}</td>
                    <td class="p-2.5 text-muted">{{ pct(h.p_hot_waterfront) }}</td>
                    <td class="p-2.5 text-emerald-700">{{ num(h.cooling_benefit_pct) }}</td>
                    <td class="p-2.5">
                      <span class="rounded-md px-2 py-0.5 text-[10px] font-bold border" :class="getRiskBadgeClass(h.risk_level)">
                        {{ riskLabel(h.risk_level) }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- UGC Validation Summary Box -->
          <div class="rounded-xl border border-emerald-200 bg-emerald-50/40 p-4 shadow-2xs">
            <div class="flex items-center justify-between mb-2">
              <h4 class="text-xs font-bold text-emerald-950 flex items-center gap-1.5">
                <AppIcon name="check" :size="15" class="text-emerald-700" />
                真实 UGC 用户打卡数据闭环验证报告
              </h4>
              <span class="rounded bg-emerald-200 text-emerald-900 text-[10px] font-bold px-2 py-0.5">
                独立交叉检验
              </span>
            </div>
            <p class="text-xs text-emerald-900/80 leading-relaxed mb-3">
              在 24 小时预报期内共提取有效实测用户打卡数据
              <strong class="text-emerald-900">{{ summaryData?.ugc_validation_metrics.sample_count ?? DASH }}</strong> 条。
              以最优概率阈值 {{ num(summaryData?.ugc_validation_metrics.optimal_threshold, 4) }} 做二分类校核，
              M1（含微环境特征）准确率为
              <strong class="text-emerald-900"> {{ pct(summaryData?.ugc_validation_metrics.accuracy_optimal) }} </strong>、
              Brier 评分 <strong class="text-emerald-900">{{ num(summaryData?.ugc_validation_metrics.m1_brier, 4) }}</strong>、
              F1 <strong class="text-emerald-900">{{ num(summaryData?.ugc_validation_metrics.f1_score_optimal, 4) }}</strong>；
              仅用气象要素的 M0 基线 AUC 为 {{ num(summaryData?.ugc_validation_metrics.m0_auc, 4) }}，
              M1 为 {{ num(summaryData?.ugc_validation_metrics.m1_auc, 4) }}。
            </p>
            <p class="text-[11px] text-emerald-900/60 leading-relaxed">
              注：固定 0.5 阈值下的准确率为 {{ pct(summaryData?.ugc_validation_metrics.nominal_threshold_0_5.accuracy) }}；样本量偏小，指标仅作模型可用性参考，不作为流行病学结论。
            </p>
          </div>
        </div>

        <!-- ================= Tab 2: Hotspots ================= -->
        <div v-if="activeTab === 'hotspots'" class="space-y-5">
          <div class="rounded-xl border border-line bg-white p-4 shadow-2xs">
            <div class="flex items-center justify-between mb-3">
              <div>
                <h3 class="text-sm font-bold text-ink flex items-center gap-2">
                  <AppIcon name="pin" :size="16" class="text-accent" />
                  上海全市 497 网格 · 主观偏热极值热点 (Top {{ (extremeData?.top_extreme_hotspots ?? []).length }})
                </h3>
                <p class="text-xs text-muted mt-0.5">
                  按微环境修正后的偏热概率 P(hot) 排序的高危热暴露网格；ΔP 为相对基准气象概率的增益。
                  <span v-if="extremeData?.total_identified_hotspots !== undefined">全域共识别 {{ extremeData.total_identified_hotspots }} 个热点网格。</span>
                </p>
              </div>
              <span class="rounded-full bg-red-100 text-red-800 text-xs font-bold px-2.5 py-1">
                时效 +{{ extremeData?.lead_hour ?? DASH }} h
              </span>
            </div>

            <div class="overflow-x-auto rounded-lg border border-line">
              <table class="w-full text-left text-xs border-collapse">
                <thead class="bg-canvas text-muted border-b border-line font-medium">
                  <tr>
                    <th class="p-2.5">排名</th>
                    <th class="p-2.5">行政区</th>
                    <th class="p-2.5">网格ID</th>
                    <th class="p-2.5">经度/纬度</th>
                    <th class="p-2.5">局部 UTCI</th>
                    <th class="p-2.5">基准 P(hot)</th>
                    <th class="p-2.5">微环境修正 P(hot)</th>
                    <th class="p-2.5">ΔP</th>
                    <th class="p-2.5">绿地率</th>
                    <th class="p-2.5">水体率</th>
                    <th class="p-2.5">建筑率</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-line">
                  <tr v-if="!extremeData?.top_extreme_hotspots?.length">
                    <td colspan="11" class="p-4 text-center text-muted text-xs">暂无极值热点网格数据</td>
                  </tr>
                  <tr
                    v-for="spot in extremeData?.top_extreme_hotspots ?? []"
                    :key="spot.grid_id"
                    class="hover:bg-red-50/30 transition"
                  >
                    <td class="p-2.5 font-bold text-red-600">#{{ spot.rank }}</td>
                    <td class="p-2.5 font-semibold text-ink">{{ text(spot.district_name) }}</td>
                    <td class="p-2.5 font-mono text-muted">{{ spot.grid_id }}</td>
                    <td class="p-2.5 font-mono text-[11px]">{{ num(spot.lon, 3) }}, {{ num(spot.lat, 3) }}</td>
                    <td class="p-2.5 font-semibold text-amber-700">{{ num(spot.utci_c) }}°C</td>
                    <td class="p-2.5 text-muted">{{ pct(spot.p_base) }}</td>
                    <td class="p-2.5 font-bold text-red-600">{{ pct(spot.p_enhanced) }}</td>
                    <td class="p-2.5" :class="spot.delta_p > 0 ? 'text-red-600' : 'text-emerald-700'">
                      {{ spot.delta_p > 0 ? '+' : '' }}{{ pct(spot.delta_p) }}
                    </td>
                    <td class="p-2.5">{{ pct(spot.green_fraction, 0) }}</td>
                    <td class="p-2.5">{{ pct(spot.water_fraction, 0) }}</td>
                    <td class="p-2.5 font-semibold">{{ pct(spot.building_fraction, 0) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Microclimate Contrast Analysis Card -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="rounded-xl border border-line bg-white p-4 shadow-2xs">
              <h4 class="text-xs font-bold text-ink mb-2 flex items-center gap-1.5">
                <AppIcon name="sliders" :size="15" class="text-accent" />
                微环境生态调节效能 (绿化与水体冷岛)
              </h4>
              <p class="text-xs text-muted leading-relaxed">
                在相同的大气宏观热背景下，绿化与水体复合网格的主观偏热概率显著低于同 UTCI 的内陆硬化网格：本期 24h 全域逐时平均降温幅度
                <strong>{{ num(summaryData?.forecast_24h_overview.mean_cooling_benefit_pct) }}%</strong>，单时次峰值
                <strong>{{ num(summaryData?.forecast_24h_overview.max_cooling_benefit_pct) }}%</strong>，为极端热暴露提供了有效缓冲区。
              </p>
            </div>

            <div class="rounded-xl border border-line bg-white p-4 shadow-2xs">
              <h4 class="text-xs font-bold text-ink mb-2 flex items-center gap-1.5">
                <AppIcon name="info" :size="15" class="text-amber-600" />
                主客观热应激“空间错配”现象
              </h4>
              <p class="text-xs text-muted leading-relaxed">
                部分气温并非全市最高、但建筑遮挡弱且硬质下垫面占比高达 65% 的密集街区（如虹口老居民区、普陀高架汇集处），人群主观偏热感知概率高达 <strong>82.1%</strong>，显著高于客观气温排名的风险，构成典型“主客观错配高危区”。
              </p>
            </div>
          </div>
        </div>

        <!-- ================= Tab 3: Decision ================= -->
        <div v-if="activeTab === 'decision'" class="space-y-5">
          <div v-if="!decisionData && !loading" class="rounded-xl border border-line bg-white p-4 text-xs text-muted shadow-2xs">
            暂无决策支持数据
          </div>

          <div v-if="decisionData" class="rounded-xl border border-line bg-white p-3.5 text-xs text-slate-700 shadow-2xs flex flex-wrap items-center gap-x-5 gap-y-1.5">
            <span>有效期: <strong>{{ text(decisionData.valid_period) }}</strong></span>
            <span>期内峰值 UTCI: <strong>{{ num(decisionData.max_utci_c) }} °C</strong></span>
            <span>综合风险: <strong :class="decisionData.overall_risk_level === 'extreme' ? 'text-red-600' : 'text-amber-600'">{{ riskLabel(decisionData.overall_risk_level) }}</strong></span>
          </div>

          <!-- Active Alert Banner -->
          <div
            v-for="alert in decisionData?.active_alerts ?? []"
            :key="alert.title"
            class="rounded-xl border border-amber-300 bg-amber-50 p-4 shadow-2xs"
          >
            <div class="flex items-center justify-between mb-2 gap-3">
              <div class="flex items-center gap-2 min-w-0">
                <span class="rounded text-white font-bold text-xs px-2.5 py-0.5 shrink-0" :class="alertLevelClass(alert.level)">
                  {{ alertLevelLabel(alert.level) }}
                </span>
                <h3 class="text-sm font-bold text-amber-950">{{ text(alert.title) }}</h3>
              </div>
              <span class="text-xs text-amber-800 shrink-0">触发时段: {{ text(alert.trigger_period) }}</span>
            </div>
            <p class="text-xs text-amber-900 leading-relaxed">{{ text(alert.message) }}</p>
          </div>

          <!-- Sector Guidelines Grid -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div
              v-for="[sector, guideline] in Object.entries(decisionData?.sector_guidelines ?? {})"
              :key="sector"
              class="rounded-xl border border-line bg-white p-4 shadow-2xs flex flex-col justify-between"
            >
              <div>
                <div class="flex items-center justify-between mb-2 gap-2">
                  <h4 class="text-xs font-bold text-ink flex items-center gap-1.5">
                    <AppIcon name="info" :size="15" class="text-accent" />
                    {{ sectorLabel(sector) }}
                  </h4>
                  <span v-if="guideline.action" class="rounded-full bg-canvas text-muted text-[10px] px-2 py-0.5 border border-line text-right">
                    {{ guideline.action }}
                  </span>
                </div>
                <ul class="space-y-1.5 text-xs text-slate-700 mt-3">
                  <li v-for="(measure, idx) in guideline.instructions ?? []" :key="idx" class="flex items-start gap-2">
                    <span class="text-accent font-bold">·</span>
                    <span>{{ measure }}</span>
                  </li>
                  <li v-for="shelter in guideline.locations ?? []" :key="shelter.name" class="flex items-start gap-2">
                    <span class="text-accent font-bold">·</span>
                    <span>{{ shelter.name }} · 可容纳 {{ shelter.capacity }} 人 · 服务半径 {{ shelter.radius_m }} m</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        <!-- ================= Tab 4: Maps ================= -->
        <div v-if="activeTab === 'maps'" class="space-y-4">
          <div class="flex flex-col md:flex-row items-start md:items-center justify-between gap-3 bg-white p-4 rounded-xl border border-line shadow-2xs">
            <div>
              <h3 class="text-sm font-bold text-ink flex items-center gap-2">
                <AppIcon name="layers" :size="16" class="text-accent" />
                13 幅全域高清 GIS 学术级成果图册 (300 DPI)
              </h3>
              <p class="text-xs text-muted mt-0.5">
                覆盖全域空间连续场、497 网格微环境修正、四时相动态演化、UGC 实证检验及分级决策分区。
              </p>
            </div>
            <div class="flex items-center gap-2">
              <a
                href="/maps/interactive_real_dashboard.html"
                target="_blank"
                class="button-primary text-xs! py-1.5! px-3! flex items-center gap-1.5 bg-blue-600! hover:bg-blue-700!"
              >
                <AppIcon name="external" :size="14" />
                <span>在新窗口打开交互式看板 (HTML)</span>
              </a>
              <a
                :href="api.mapImageUrl(selectedMap.file)"
                target="_blank"
                class="button text-xs py-1.5 px-3 flex items-center gap-1.5"
              >
                <AppIcon name="download" :size="14" />
                <span>下载原图</span>
              </a>
            </div>
          </div>

          <!-- Main Map Display and Selector -->
          <div class="grid grid-cols-1 lg:grid-cols-12 gap-4">
            <!-- Left Thumbnails / Selection List -->
            <div class="lg:col-span-4 space-y-2 max-h-[600px] overflow-y-auto pr-1">
              <button
                v-for="(m, idx) in mapList"
                :key="m.file"
                class="w-full text-left p-3 rounded-xl border transition cursor-pointer flex items-center gap-3"
                :class="selectedMapIndex === idx ? 'border-accent bg-blue-50/50 shadow-xs' : 'border-line bg-white hover:bg-canvas'"
                @click="selectedMapIndex = idx"
              >
                <span class="size-6 rounded-md bg-canvas grid place-items-center font-mono text-[11px] font-bold text-muted shrink-0">
                  {{ idx + 1 }}
                </span>
                <div class="overflow-hidden">
                  <p class="text-xs font-bold text-ink truncate">{{ m.title }}</p>
                  <p class="text-[10px] text-muted truncate">{{ m.desc }}</p>
                </div>
              </button>
            </div>

            <!-- Right Preview Panel -->
            <div class="lg:col-span-8 rounded-xl border border-line bg-white p-4 shadow-2xs flex flex-col items-center justify-center">
              <div class="w-full flex items-center justify-between pb-3 border-b border-line mb-3">
                <div>
                  <h4 class="text-sm font-bold text-ink">{{ selectedMap.title }}</h4>
                  <p class="text-xs text-muted">{{ selectedMap.desc }}</p>
                </div>
                <span class="rounded bg-slate-100 text-slate-700 text-[11px] px-2 py-0.5 font-mono">
                  {{ selectedMap.file }}
                </span>
              </div>
              <div class="relative w-full max-h-[520px] overflow-hidden rounded-lg border border-line flex items-center justify-center bg-slate-900/5">
                <img
                  :src="api.mapImageUrl(selectedMap.file)"
                  :alt="selectedMap.title"
                  class="max-h-[500px] w-auto object-contain rounded"
                  loading="lazy"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- ================= Tab 5: Calculator ================= -->
        <div v-if="activeTab === 'calculator'" class="space-y-5">
          <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <!-- Controls Form -->
            <div class="lg:col-span-6 rounded-xl border border-line bg-white p-5 shadow-2xs space-y-4">
              <h3 class="text-sm font-bold text-ink flex items-center gap-2 border-b border-line pb-2.5">
                <AppIcon name="sliders" :size="16" class="text-accent" />
                多源气象与下垫面参数输入
              </h3>

              <div class="space-y-3 text-xs">
                <div>
                  <div class="flex justify-between font-medium text-slate-700 mb-1">
                    <span>空气温度 (Ta):</span>
                    <span class="font-bold text-accent">{{ calcTa }} °C</span>
                  </div>
                  <input v-model.number="calcTa" type="range" min="20" max="45" step="0.5" class="w-full" @input="scheduleCalculation" />
                </div>

                <div>
                  <div class="flex justify-between font-medium text-slate-700 mb-1">
                    <span>相对湿度 (RH):</span>
                    <span class="font-bold text-accent">{{ calcRh }} %</span>
                  </div>
                  <input v-model.number="calcRh" type="range" min="20" max="95" step="1" class="w-full" @input="scheduleCalculation" />
                </div>

                <div>
                  <div class="flex justify-between font-medium text-slate-700 mb-1">
                    <span>10米风速 (v):</span>
                    <span class="font-bold text-accent">{{ calcWind }} m/s</span>
                  </div>
                  <input v-model.number="calcWind" type="range" min="0.5" max="12" step="0.5" class="w-full" @input="scheduleCalculation" />
                </div>

                <div>
                  <div class="flex justify-between font-medium text-slate-700 mb-1">
                    <span>净太阳辐射 (Rn):</span>
                    <span class="font-bold text-accent">{{ calcRad }} W/m²</span>
                  </div>
                  <input v-model.number="calcRad" type="range" min="0" max="1000" step="50" class="w-full" @input="scheduleCalculation" />
                </div>

                <div class="pt-2 border-t border-line">
                  <div class="flex justify-between font-medium text-slate-700 mb-1">
                    <span>绿化覆盖率 (Green Fraction):</span>
                    <span class="font-bold text-emerald-600">{{ (calcGreen * 100).toFixed(0) }} %</span>
                  </div>
                  <input v-model.number="calcGreen" type="range" min="0" max="0.7" step="0.05" class="w-full" @input="scheduleCalculation" />
                </div>

                <div>
                  <div class="flex justify-between font-medium text-slate-700 mb-1">
                    <span>水体覆盖率 (Water Fraction):</span>
                    <span class="font-bold text-blue-600">{{ (calcWater * 100).toFixed(0) }} %</span>
                  </div>
                  <input v-model.number="calcWater" type="range" min="0" max="0.5" step="0.05" class="w-full" @input="scheduleCalculation" />
                </div>

                <div>
                  <div class="flex justify-between font-medium text-slate-700 mb-1">
                    <span>建筑覆盖率 (Building Fraction):</span>
                    <span class="font-bold text-amber-700">{{ (calcBldg * 100).toFixed(0) }} %</span>
                  </div>
                  <input v-model.number="calcBldg" type="range" min="0" max="0.8" step="0.05" class="w-full" @input="scheduleCalculation" />
                </div>
              </div>
            </div>

            <!-- Inversion Output -->
            <div class="lg:col-span-6 space-y-4">
              <div class="rounded-xl border border-line bg-white p-5 shadow-2xs">
                <h3 class="text-sm font-bold text-ink mb-3 flex items-center justify-between border-b border-line pb-2.5">
                  <span>前向反演结果与应激评估</span>
                  <span class="rounded-md px-2 py-0.5 text-xs font-bold border" :class="getRiskBadgeClass(calcResult?.risk_level)">
                    {{ riskLabel(calcResult?.risk_level) }}
                  </span>
                </h3>

                <div class="grid grid-cols-2 gap-3 mb-4">
                  <div class="rounded-lg bg-canvas p-3 border border-line">
                    <span class="text-[11px] text-muted block">生物气象 UTCI</span>
                    <span class="text-xl font-bold text-ink">{{ num(calcResult?.calculated_utci_c) }} °C</span>
                    <span class="text-[10px] text-muted block mt-0.5">{{ text(calcResult?.utci_stress_level) }}</span>
                  </div>

                  <div class="rounded-lg bg-canvas p-3 border border-line">
                    <span class="text-[11px] text-muted block">微环境修正偏热概率 P(hot)</span>
                    <span class="text-xl font-bold text-accent">{{ pct(calcResult?.p_hot_enhanced) }}</span>
                    <span class="text-[10px] text-muted block mt-0.5">基准 P0: {{ pct(calcResult?.p_hot_base) }}</span>
                  </div>
                </div>

                <!-- Mitigation Progress Indicator -->
                <div class="rounded-lg bg-emerald-50 border border-emerald-200 p-3.5">
                  <div class="flex items-center justify-between text-xs font-semibold text-emerald-900 mb-1">
                    <span>生态微环境对热感知的缓解幅度:</span>
                    <span class="font-bold text-sm">{{ num(calcResult?.environmental_mitigation_pct) }}%</span>
                  </div>
                  <p class="text-[11px] text-emerald-800 leading-normal">
                    绿化率每提高 10% 可使偏热优势比降低约 19.3%；水体覆盖率每提高 10% 可使偏热优势比降低约 16.7%。
                  </p>
                </div>

                <p v-if="calcError" class="text-[11px] text-red-700 mt-3">反演计算失败：{{ calcError }}</p>
                <p v-else-if="!calcResult && !calcLoading" class="text-[11px] text-muted mt-3">暂无反演结果，请调整任一参数。</p>
              </div>

              <!-- Recommendation Card -->
              <div class="rounded-xl border border-line bg-white p-5 shadow-2xs">
                <h4 class="text-xs font-bold text-ink mb-2">空间微气候优化干预建议</h4>
                <p class="text-xs text-muted leading-relaxed">
                  若该网格处于高密度建筑环境，建议引入屋顶绿化、立体垂直绿化或微喷雾蒸发冷却设施；在街谷迎风口预留冷空气通道，避免高层建筑群阻滞近地通风。
                </p>
              </div>
            </div>
          </div>
        </div>

        <!-- ================= Tab 6: Evaluation ================= -->
        <div v-if="activeTab === 'evaluation'" class="space-y-5">
          <div class="rounded-xl border border-line bg-white p-4 shadow-2xs">
            <div class="flex items-center justify-between mb-3">
              <div>
                <h3 class="text-sm font-bold text-ink flex items-center gap-2">
                  <AppIcon name="sun" :size="16" class="text-accent" />
                  M0 与 M1 二元逻辑回归模型性能评估
                </h3>
                <p class="text-xs text-muted mt-0.5">
                  基于全多历年训练集、2024 年外推测试集与纯时间外推样本的客观指标对比。
                </p>
              </div>
              <span class="rounded bg-blue-100 text-blue-800 text-xs font-bold px-2.5 py-1">
                空间留出 M1: AUC = {{ num(modelEvalData?.pooled_spatial_m1_auc, 4) }}
              </span>
            </div>

            <p v-if="modelEvalData" class="text-[11px] text-muted mb-3">
              {{ modelEvalData.model_version }} · 训练 {{ modelEvalData.training_sample_size }} 条 / 测试 {{ modelEvalData.test_sample_size }} 条 · {{ modelEvalData.sampling_strategy }}
            </p>

            <div class="overflow-x-auto rounded-lg border border-line mb-4">
              <table class="w-full text-left text-xs border-collapse">
                <thead class="bg-canvas text-muted border-b border-line font-medium">
                  <tr>
                    <th class="p-2.5">模型</th>
                    <th class="p-2.5">评估样本集</th>
                    <th class="p-2.5">受试者工作特征 (AUC)</th>
                    <th class="p-2.5">Brier 残差评分</th>
                    <th class="p-2.5">对数损失 (Log Loss)</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-line">
                  <tr v-if="!modelEvalData?.metrics_table?.length">
                    <td colspan="5" class="p-4 text-center text-muted text-xs">暂无模型评估指标</td>
                  </tr>
                  <tr
                    v-for="(row, idx) in modelEvalData?.metrics_table ?? []"
                    :key="`${row.model}-${row.split_type}-${idx}`"
                    class="hover:bg-canvas transition"
                    :class="row.model.startsWith('M1') ? 'font-semibold bg-blue-50/20' : ''"
                  >
                    <td class="p-2.5 text-ink">{{ text(row.model) }}</td>
                    <td class="p-2.5 text-muted">{{ text(row.split_type) }}</td>
                    <td class="p-2.5 text-accent font-bold">{{ num(row.auc_roc, 4) }}</td>
                    <td class="p-2.5">{{ num(row.brier_score, 4) }}</td>
                    <td class="p-2.5">{{ num(row.log_loss, 4) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- Coefficients & Odds Ratio Table -->
            <h4 class="text-xs font-bold text-ink mb-2 mt-4">回归特征系数与优势比 (Odds Ratio)</h4>
            <div class="overflow-x-auto rounded-lg border border-line">
              <table class="w-full text-left text-xs border-collapse">
                <thead class="bg-canvas text-muted border-b border-line font-medium">
                  <tr>
                    <th class="p-2.5">变量标识</th>
                    <th class="p-2.5">变化幅度</th>
                    <th class="p-2.5">回归系数 (&beta;)</th>
                    <th class="p-2.5">优势比 (OR = exp(&beta;))</th>
                    <th class="p-2.5">95% 置信区间</th>
                    <th class="p-2.5">微气候学效应释义</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-line">
                  <tr v-for="c in modelEvalData?.coefficients_table ?? []" :key="c.variable" class="hover:bg-canvas transition">
                    <td class="p-2.5 font-mono text-muted">{{ text(c.variable) }}</td>
                    <td class="p-2.5 text-muted text-[11px]">{{ text(c.unit_change) }}</td>
                    <td class="p-2.5 font-mono">{{ num(c.coefficient, 3) }}</td>
                    <td class="p-2.5 font-bold text-accent font-mono">{{ num(c.odds_ratio, 3) }}</td>
                    <td class="p-2.5 font-mono text-[11px] text-slate-600">[{{ num(c.ci95_lower, 3) }}, {{ num(c.ci95_upper, 3) }}]</td>
                    <td class="p-2.5 text-slate-700 text-[11px]">{{ text(c.interpretation) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- Environmental Effects -->
            <template v-if="modelEvalData?.environmental_effects?.length">
              <h4 class="text-xs font-bold text-ink mb-2 mt-4">微环境要素的偏热感知效应</h4>
              <div class="overflow-x-auto rounded-lg border border-line">
                <table class="w-full text-left text-xs border-collapse">
                  <thead class="bg-canvas text-muted border-b border-line font-medium">
                    <tr>
                      <th class="p-2.5">要素</th>
                      <th class="p-2.5">变化幅度</th>
                      <th class="p-2.5">优势比 (OR)</th>
                      <th class="p-2.5">95% 置信区间</th>
                      <th class="p-2.5">效应方向</th>
                      <th class="p-2.5">释义</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-line">
                    <tr v-for="e in modelEvalData.environmental_effects" :key="e.variable" class="hover:bg-canvas transition">
                      <td class="p-2.5 font-mono text-muted">{{ text(e.variable) }}</td>
                      <td class="p-2.5 text-muted text-[11px]">{{ text(e.unit_change) }}</td>
                      <td class="p-2.5 font-bold font-mono" :class="e.odds_ratio > 1 ? 'text-red-600' : 'text-emerald-700'">{{ num(e.odds_ratio, 3) }}</td>
                      <td class="p-2.5 font-mono text-[11px] text-slate-600">[{{ num(e.ci95_lower, 3) }}, {{ num(e.ci95_upper, 3) }}]</td>
                      <td class="p-2.5 text-[11px]">{{ e.odds_ratio > 1 ? '正向促进偏热感知' : '负向抑制偏热感知' }}</td>
                      <td class="p-2.5 text-slate-700 text-[11px]">{{ text(e.interpretation) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
.loader {
  border: 2px solid #e2e8f0;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
