<script setup lang="ts">
import AppDialog from './AppDialog.vue';
import AppIcon from './AppIcon.vue';

defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();
</script>

<template>
  <AppDialog :open="open" title="数据来源与计算方法说明" wide @close="emit('close')">
    <div class="max-h-[65vh] space-y-5 overflow-y-auto pr-1 text-sm text-ink leading-relaxed">
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
          空间图层在 EPSG:32651 投影下布设多点采样网络，采用严格的 Delaunay 空间三角剖分连续插值生成透明栅格色带，不进行边界无限外推。缺失或无支撑区域显示为空，确保气象数据严谨可追溯。
        </p>
      </section>

      <section class="rounded-xl border border-line bg-canvas p-4">
        <h3 class="flex items-center gap-2 font-semibold text-accent">
          <AppIcon name="pin" :size="18" />
          2. UGC 体感数据与空间隐私机制
        </h3>
        <p class="mt-2 text-xs leading-6 text-muted">
          用户提交的主观热感知（冷、凉、中性、偏热、很热）打卡记录，遵循差分空间脱敏规则：在 EPSG:32651（UTM Zone 51N）投影坐标系中，按 200 米规则网格将原始坐标对齐至所在网格的几何中心点，再逆变换回 WGS84（EPSG:4326）予以公开展示与聚合统计。精确打卡坐标仅由本人登录后可见。
        </p>
      </section>

      <section class="rounded-xl border border-line bg-canvas p-4">
        <h3 class="flex items-center gap-2 font-semibold text-accent">
          <AppIcon name="layers" :size="18" />
          3. 城市多源空间地理底图
        </h3>
        <p class="mt-2 text-xs leading-6 text-muted">
          基础场景在线底图全面采用中国官方<strong>国家地理信息公共服务平台（天地图 Tianditu）</strong>高精度矢量瓦片及中文注记服务，场景要素（市域与区县行政区划边界、三维建筑轮廓与建筑高度、等级道路网络、主要地表水系、绿地公园及城市公共兴趣点 POI）由天地图及上海市公开地理信息成果转化入库，保存在 PostgreSQL/PostGIS 空间数据库中。
        </p>
      </section>

      <section class="rounded-xl border border-amber-200 bg-amber-50/70 p-4">
        <h3 class="flex items-center gap-2 font-semibold text-amber-800">
          <AppIcon name="info" :size="18" />
          4. 科学解释与使用边界声明
        </h3>
        <p class="mt-2 text-xs leading-6 text-amber-900">
          平台展示的客观指标为区域气象预报与地表微气象模拟估计，不等于微观街谷厘米级实测；主观体感为参与式自报评价，不作为流行病学确诊结论或个体医疗风险凭证。
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
