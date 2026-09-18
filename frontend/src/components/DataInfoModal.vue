<script setup lang="ts">
import AppDialog from './AppDialog.vue';
import AppIcon from './AppIcon.vue';

defineProps<{ open: boolean }>();
const emit = defineEmits<{
  close: [];
  openForecast: [];
}>();
</script>

<template>
  <AppDialog :open="open" title="数据来源与计算方法说明" wide @close="emit('close')">
    <div class="max-h-[70vh] space-y-5 overflow-y-auto pr-1 text-sm text-ink leading-relaxed">
      <!-- 1. 客观气象环境数据源 -->
      <section class="rounded-xl border border-line bg-canvas p-4">
        <div class="flex items-center justify-between">
          <h3 class="flex items-center gap-2 font-semibold text-accent">
            <AppIcon name="weather" :size="18" />
            1. 客观气象环境数据源
          </h3>
          <a
            href="https://www.qweather.com"
            target="_blank"
            rel="noopener noreferrer"
            class="flex items-center gap-1 text-xs text-accent hover:underline"
          >
            <span>和风天气</span>
            <AppIcon name="external" :size="12" />
          </a>
        </div>
        <p class="mt-2 text-xs leading-6 text-muted">
          平台客观气象服务由<strong>和风天气（QWeather）</strong>驱动，采用官方逐小时数值预报接口，获取未来 48 小时多要素气象序列。包含近地面气温（°C）、相对湿度（%）、10 米风速风向（m/s、°）及露点温度（°C）。
        </p>
        <p class="mt-2 text-xs leading-6 text-muted">
          原始气象图层通过 CloakBrowser 实时内存拦截与物理量解码，解算 IEEE-754 动态浮点栅格，实现与官方数值预报零延迟高保真同步。
        </p>
      </section>

      <!-- 2. 空间气象平差与多源数据同化审计 (移入此处) -->
      <section class="rounded-xl border border-blue-200 bg-blue-50/40 p-4">
        <div class="flex items-center justify-between">
          <h3 class="flex items-center gap-2 font-semibold text-blue-900">
            <AppIcon name="sliders" :size="18" />
            2. 气象平差同化与控制网精度审计（TPS-RBF）
          </h3>
          <span class="rounded bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-800">
            144 点测绘级控制网
          </span>
        </div>
        
        <p class="mt-2 text-xs leading-6 text-slate-700">
          <strong>空间各向同性基准：</strong>针对 WGS84 经纬度在上海（31.2°N）存在的 14.1% 经纬向畸变，平台全部平差与空间残差求解均在 <strong>EPSG:32651（UTM 51N 米制网格）</strong> 投影坐标系下执行，采用薄板样条径向基（TPS-RBF）同化算法，保证平差矩阵条件数健康稳定，杜绝奇异发散。
        </p>

        <p class="mt-2 text-xs leading-6 text-slate-700">
          <strong>144 测绘控制与独立检验网（v7.0）：</strong>
          全网布设 <strong>126 个空间平差控制点</strong>（C01~C126）与 <strong>18 个独立盲测检验点</strong>（T01~T18）。严格遵循测绘平差规范中独立检验点 &le; 15% 的法定比例约束（18 / 126 = 14.28%）。全面覆盖中心城 7 区、9 大郊区副中心，并在崇明岛、长兴岛（左中右 3 点）、横沙岛（左中右 3 点）、南汇惠南、松江佘山等关键岸线与敏感带实现水陆边界闭环把守。
        </p>

        <p class="mt-2 text-xs leading-6 text-slate-700">
          <strong>粗差控制与边界阻尼：</strong>
          采用动态 Huber + 局部 IQR 自适应阈值算法剔除异常站网粗差，同时智能保留陆家嘴等真实城市核心热岛；布设 12 个深远场虚边界阻尼锚点（通州湾、东海、杭州湾等），约束边缘残差自然衰减。实测独立检验点交叉验证平均绝对误差 <strong>MAE &approx; 0.16°C</strong>，均方根误差 <strong>RMSE &approx; 0.28°C</strong>。
        </p>

        <!-- 平差审计看板快捷入口 -->
        <div class="mt-3.5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 rounded-lg border border-blue-200 bg-white/90 p-3 shadow-2xs">
          <div class="space-y-0.5">
            <div class="flex items-center gap-1.5 text-xs font-semibold text-blue-900">
              <span>空间平差与误差审计看板</span>
              <span class="rounded bg-emerald-100 px-1.5 py-0.2 text-[10px] font-medium text-emerald-800">144点时序实测</span>
            </div>
            <p class="text-[11px] text-muted leading-normal">
              实时查看 126 空间控制点、18 独立检验点残差明细、136×137 平差网格与 48 小时演化过程
            </p>
          </div>
          <button
            type="button"
            class="button-primary shrink-0 text-xs py-1.5 px-3 bg-blue-600 hover:bg-blue-700 text-white shadow-xs cursor-pointer flex items-center gap-1.5"
            @click="emit('openForecast')"
          >
            <AppIcon name="sliders" :size="14" />
            <span>打开平差审计看板</span>
          </button>
        </div>
      </section>

      <!-- 3. UGC 体感数据与空间隐私机制 -->
      <section class="rounded-xl border border-line bg-canvas p-4">
        <h3 class="flex items-center gap-2 font-semibold text-accent">
          <AppIcon name="pin" :size="18" />
          3. UGC 体感数据与空间隐私机制
        </h3>
        <p class="mt-2 text-xs leading-6 text-muted">
          用户提交的主观热感知（冷、凉、中性、偏热、很热）打卡记录，遵循差分空间脱敏规则：在 EPSG:32651（UTM Zone 51N）投影坐标系中，按 200 米规则网格将原始坐标对齐至所在网格的几何中心点，再逆变换回 WGS84（EPSG:4326）予以公开展示与聚合统计。精确打卡坐标仅由本人登录后可见。
        </p>
      </section>

      <!-- 4. 城市多源空间地理底图 -->
      <section class="rounded-xl border border-line bg-canvas p-4">
        <h3 class="flex items-center gap-2 font-semibold text-accent">
          <AppIcon name="layers" :size="18" />
          4. 城市多源空间地理底图
        </h3>
        <p class="mt-2 text-xs leading-6 text-muted">
          基础场景在线底图全面采用中国官方<strong>国家地理信息公共服务平台（天地图 Tianditu）</strong>高精度矢量瓦片及中文注记服务，场景要素（市域与区县行政区划边界、三维建筑轮廓与建筑高度、等级道路网络、主要地表水系、绿地公园及城市公共兴趣点 POI）由天地图及上海市公开地理信息成果转化入库，保存在 PostgreSQL/PostGIS 空间数据库中。
        </p>
      </section>

      <!-- 5. 科学解释与使用边界声明 -->
      <section class="rounded-xl border border-amber-200 bg-amber-50/70 p-4">
        <h3 class="flex items-center gap-2 font-semibold text-amber-800">
          <AppIcon name="info" :size="18" />
          5. 科学解释与使用边界声明
        </h3>
        <p class="mt-2 text-xs leading-6 text-amber-900">
          平台展示的客观指标为区域气象预报与地表微气象模拟估计，不等于微观街谷厘米级实测；主观体感为参与式自报评价，不作为流行病学确诊结论或个体医疗风险凭证。通用热气候指数（UTCI）严格基于人体热平衡六向辐射模型计算，适用于宏观及中微观城市空间热暴露评价。
        </p>
      </section>

      <div class="flex justify-end pt-2">
        <button class="button-primary" @click="emit('close')">
          我已了解
        </button>
      </div>
    </div>
  </AppDialog>
</template>
