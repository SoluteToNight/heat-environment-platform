<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import AppIcon from '../components/AppIcon.vue';
import AuthModal from '../components/AuthModal.vue';
import DataInfoModal from '../components/DataInfoModal.vue';
import DetailPanel from '../components/DetailPanel.vue';
import ExportModal from '../components/ExportModal.vue';
import ForecastModal from '../components/ForecastModal.vue';
import LayerPanel from '../components/LayerPanel.vue';
import MyCheckInsModal from '../components/MyCheckInsModal.vue';
import CheckInForm from '../features/check-ins/CheckInForm.vue';
import Timeline from '../features/environment/Timeline.vue';
import MapScene from '../features/scene/MapScene.vue';
import { api } from '../services/api';
import type { CheckIn, Coordinates, FeatureDetail, Place, PublicCheckIn } from '../services/contracts';
import { modeNames } from '../services/format';
import { useWorkspace } from '../stores/workspace';

const store = useWorkspace();

// Panels toggle
const leftPanelOpen = ref(window.innerWidth >= 1280);
const rightPanelOpen = ref(window.innerWidth >= 1280);
watch(leftPanelOpen, open => { if (open && window.innerWidth < 1280) rightPanelOpen.value = false; });
watch(rightPanelOpen, open => { if (open && window.innerWidth < 1280) leftPanelOpen.value = false; });

// Layer statuses
const layerStatuses = ref<Record<string, string>>({});

// Selections & inspection
const selectedRecord = ref<PublicCheckIn | null>(null);
const selectedFeature = ref<FeatureDetail | null>(null);

// POI Search
const searchQuery = ref('');
const searchResults = ref<Place[]>([]);
const searchLoading = ref(false);
const showSearchResults = ref(false);

// Modals
const checkInOpen = ref(false);
const editingCheckIn = ref<CheckIn | null>(null);
const checkInCoords = ref<Coordinates | null>(null);
const authOpen = ref(false);
const myCheckInsOpen = ref(false);
const exportOpen = ref(false);
const dataInfoOpen = ref(false);
const forecastOpen = ref(false);

function handleOpenForecastFromInfo() {
  dataInfoOpen.value = false;
  forecastOpen.value = true;
}

// Map ref
const mapRef = ref<InstanceType<typeof MapScene>>();

const activeLegend = computed(() => store.activeItem?.assets.length ? store.activeItem.legend : null);
function openExport() {
  if (store.view?.view_id.startsWith('sp_') && store.selection) {
    const link = document.createElement('a');
    link.href = api.spatialExportUrl(store.view.view_id, store.selection.coordinates, store.committedVariable);
    link.click();
    return;
  }
  exportOpen.value = true;
}
watch(() => store.scene, () => {
  selectedRecord.value = null;
  selectedFeature.value = null;
  layerStatuses.value = {};
});

onMounted(() => {
  store.initialize();
  store.startPolling();
});

onBeforeUnmount(() => {
  store.dispose();
});

let searchTimer: ReturnType<typeof setTimeout> | undefined;
function handleSearchInput() {
  clearTimeout(searchTimer);
  if (!searchQuery.value.trim() || !store.scene) {
    searchResults.value = [];
    showSearchResults.value = false;
    return;
  }
  searchLoading.value = true;
  searchTimer = setTimeout(async () => {
    try {
      const res = await api.places(store.scene!.scene_id, searchQuery.value.trim());
      searchResults.value = res.items;
      showSearchResults.value = true;
    } catch {
      searchResults.value = [];
    } finally {
      searchLoading.value = false;
    }
  }, 300);
}

function selectPlace(place: Place) {
  showSearchResults.value = false;
  searchQuery.value = place.name;
  store.choosePoint(place.location.coordinates, place.name);
  mapRef.value?.focus(place.location.coordinates);
  rightPanelOpen.value = true;
}

function handleMapPick(items: Array<{ name: string; coordinates: Coordinates; featureId?: string; layerId?: string; height?: number; elevation_m?: number; levels?: number; properties?: Record<string, unknown>; record?: PublicCheckIn }>) {
  if (!items.length) return;
  const first = items[0]!;
  if (first.record) {
    selectedRecord.value = first.record;
    selectedFeature.value = null;
  } else if (first.featureId) {
    selectedFeature.value = {
      feature_id: first.featureId,
      name: first.name,
      type: first.layerId || 'feature',
      height_m: first.height ?? null,
      elevation_m: first.elevation_m ?? null,
      levels: first.levels ?? null,
      height_source: (first.properties?.height_source as string) || null,
      properties: first.properties || {},
    };
    selectedRecord.value = null;
  } else {
    selectedRecord.value = null;
    selectedFeature.value = null;
  }
  store.choosePoint(first.coordinates, first.name || '地图点选位置');
  rightPanelOpen.value = true;
}

function openCheckInModal(coords?: Coordinates) {
  const fallbackCoords: Coordinates = store.scene?.initial_camera
    ? [store.scene.initial_camera.longitude, store.scene.initial_camera.latitude]
    : [121.4737, 31.2304];
  checkInCoords.value = coords || store.selection?.coordinates || fallbackCoords;
  editingCheckIn.value = null;
  checkInOpen.value = true;
}

function handleEditCheckIn(record: CheckIn) {
  myCheckInsOpen.value = false;
  editingCheckIn.value = record;
  checkInOpen.value = true;
}

async function handleCaptureMap() {
  try {
    const dataUrl = await mapRef.value?.capture();
    if (dataUrl) {
      const link = document.createElement('a');
      link.href = dataUrl;
      link.download = `上海热环境专题地图-${Date.now()}.png`;
      link.click();
    }
  } catch (err) {
    alert(err instanceof Error ? err.message : '地图截图失败');
  }
}
</script>

<template>
  <div class="map-workspace flex h-screen w-screen flex-col overflow-hidden bg-canvas text-ink antialiased select-none">
    <!-- Top Navigation Header -->
    <header class="z-20 flex h-16 shrink-0 items-center justify-between border-b border-line bg-white px-5 shadow-xs">
      <div class="flex items-center gap-4">
        <div class="flex items-center gap-2">
          <div class="grid size-9 place-items-center rounded-lg bg-accent text-white shadow-xs">
            <AppIcon name="temperature" :size="20" />
          </div>
          <div>
            <h1 class="text-sm font-bold tracking-tight text-ink sm:text-base">上海 · 热环境探索</h1>
            <p class="hidden text-xs text-muted sm:block">城市热暴露时空可视分析</p>
          </div>
        </div>

        <!-- Scene selector -->
        <div v-if="store.scenes.length > 1" class="hidden md:block">
          <select
            class="input text-xs py-1.5 px-2.5 max-w-40"
            :value="store.scene?.scene_id"
            @change="store.selectScene(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="sc in store.scenes" :key="sc.scene_id" :value="sc.scene_id">
              {{ sc.name }}
            </option>
          </select>
        </div>

        <!-- Places Search Input -->
        <div class="relative hidden lg:block w-64">
          <div class="flex items-center rounded-lg border border-line bg-canvas px-3 py-1.5 text-xs focus-within:border-accent">
            <AppIcon name="search" :size="14" class="text-muted mr-2" />
            <input
              v-model="searchQuery"
              type="text"
              placeholder="搜索上海地点、POI..."
              class="w-full bg-transparent outline-none"
              @input="handleSearchInput"
              @focus="showSearchResults = searchResults.length > 0"
            />
            <span v-if="searchLoading" class="loader size-3" />
          </div>

          <!-- Search autocomplete list -->
          <div
            v-if="showSearchResults && searchResults.length"
            class="absolute left-0 top-full mt-1.5 w-80 max-h-64 overflow-y-auto rounded-xl border border-line bg-white p-1.5 shadow-lg z-50"
          >
            <button
              v-for="p in searchResults"
              :key="p.place_id"
              class="flex w-full items-start gap-2 rounded-lg p-2 text-left text-xs hover:bg-canvas transition"
              @click="selectPlace(p)"
            >
              <AppIcon name="pin" :size="14" class="text-accent mt-0.5 shrink-0" />
              <div>
                <p class="font-medium text-ink">{{ p.name }}</p>
                <p class="text-[10px] text-muted truncate">{{ p.description }}</p>
              </div>
            </button>
          </div>
        </div>
      </div>

      <!-- Header Center: Operational Mode status -->
      <button
        v-if="store.view"
        type="button"
        class="hidden xl:flex items-center gap-2 rounded-full border border-line bg-canvas px-3.5 py-1 text-xs hover:bg-white hover:shadow-2xs transition cursor-pointer"
        title="点击查看数据来源、计算方法与 144 点空间平差审计"
        @click="dataInfoOpen = true"
      >
        <span class="size-2 rounded-full" :class="store.view.mode === 'forecast' ? 'bg-amber-500' : 'bg-accent'" />
        <span class="font-medium">{{ modeNames[store.view.mode] }}</span>
        <span class="text-muted">· {{ store.view.mode === 'forecast' ? '和风天气 48h 数值同化' : (store.activeItem?.provenance.source.split('（')[0].split('(')[0] || '数据说明') }}</span>
        <span v-if="store.activeItem?.freshness === 'stale'" class="rounded bg-amber-100 px-1 text-[10px] text-amber-800">
          已过期
        </span>
      </button>

      <!-- Header Right: Action buttons -->
      <div class="flex items-center gap-2">
        <button
          class="button-primary text-xs py-1.5 px-3"
          @click="openCheckInModal()"
        >
          <AppIcon name="plus" :size="15" />
          <span class="hidden sm:inline">记录体感</span>
        </button>

        <button
          class="button text-xs py-1.5 px-2.5"
          @click="myCheckInsOpen = true"
        >
          <AppIcon name="bookmark" :size="15" />
          <span class="hidden md:inline">我的打卡</span>
        </button>

        <button
          class="button text-xs py-1.5 px-2.5"
          @click="openExport"
        >
          <AppIcon name="download" :size="15" />
          <span class="hidden md:inline">数据导出</span>
        </button>

        <button
          class="icon-button"
          title="数据说明与方法"
          @click="dataInfoOpen = true"
        >
          <AppIcon name="info" :size="16" />
        </button>

        <button
          class="button text-xs py-1.5 px-3"
          :class="store.session.authenticated ? 'border-accent text-accent font-semibold' : ''"
          @click="authOpen = true"
        >
          <AppIcon name="pin" :size="15" />
          <span>{{ store.session.authenticated ? (store.session.user?.alias || '已登录') : '登录' }}</span>
        </button>
      </div>
    </header>

    <!-- Main 3-Column Workspace -->
    <div class="relative flex flex-1 overflow-hidden">
      <!-- Left Control Panel -->
      <aside
        class="z-10 flex h-full shrink-0 flex-col border-r border-line bg-white transition-all duration-200"
        :class="leftPanelOpen ? 'w-64 p-5 overflow-y-auto' : 'w-0 p-0 border-r-0 overflow-hidden'"
      >
        <div v-if="leftPanelOpen" class="space-y-4">
          <LayerPanel
            :statuses="layerStatuses"
            @close="leftPanelOpen = false"
            @layer="(id, visible) => mapRef?.showLayer(id, visible)"
            @opacity="(val) => mapRef?.opacity(val)"
            @canopy="(val) => mapRef?.canopyOpacity(val)"
            @building-opacity="(val) => mapRef?.buildingOpacity(val)"
            @methods="dataInfoOpen = true"
          />
        </div>
      </aside>

      <!-- Collapse Toggle Button: Left Panel -->
      <button
        class="absolute left-0 top-4 z-20 grid size-8 place-items-center rounded-r-lg border border-l-0 border-line bg-white text-muted shadow-xs transition hover:text-ink"
        :style="{ left: leftPanelOpen ? '16rem' : '0' }"
        :title="leftPanelOpen ? '收起左侧控制栏' : '展开左侧控制栏'"
        @click="leftPanelOpen = !leftPanelOpen"
      >
        <AppIcon :name="leftPanelOpen ? 'left' : 'right'" :size="16" />
      </button>

      <!-- Central Map Area & Overlays -->
      <main class="scene-stage relative flex-1 bg-[#e5ebe5] overflow-hidden">
        <!-- Core Map View Component Container -->
        <MapScene
          ref="mapRef"
          @ready="store.switchView()"
          @pick="handleMapPick"
          @layer-status="(id, status) => (layerStatuses[id] = status)"
        />

        <section v-if="store.scene" class="scene-heading">
          <div class="flex items-center gap-2 text-xs text-muted"><span class="scene-dot" />{{ store.isDemo ? '合成演示场景' : '上海 · 城市空间' }}</div>
          <h2 class="mt-2 text-xl font-semibold tracking-tight">{{ store.isDemo ? store.scene.name : '从街区，感知城市温度' }}</h2>
          <p class="mt-2 text-xs text-muted">点选地点，探索天气与真实体感</p>
          <p v-if="layerStatuses.basemap === 'failed'" class="mt-2 text-xs text-terracotta" role="status">在线天地图底图部分瓦片未加载，请检查网络或天地图Key。</p>
          <details v-if="!store.isDemo" class="mt-3 text-xs text-muted"><summary>当前数据范围</summary><p class="mt-2 max-w-64 leading-6">{{ store.activeItem?.assets.length ? store.activeItem.provenance.spatial_support : '环境为位置读数，暂无空间色带。' }} 空白区域表示无覆盖或缺测，不表示零值。</p></details>
        </section>

        <!-- Top Right Map Tool Controls -->
        <div class="map-toolbox absolute right-4 top-4 z-10 flex flex-col gap-1.5">
          <button class="icon-button shadow-xs" title="复位街区视角" aria-label="复位街区视角" @click="mapRef?.reset()">
            <AppIcon name="compass" :size="16" />
          </button>
          <button class="icon-button shadow-xs text-accent" title="上海全域总览" aria-label="上海全域总览" @click="mapRef?.overview()">
            <AppIcon name="expand" :size="16" />
          </button>
          <button class="icon-button shadow-xs" title="俯视正射" aria-label="俯视正射" @click="mapRef?.top()">
            <AppIcon name="focus" :size="16" />
          </button>
          <button class="icon-button shadow-xs" title="指北针重置" aria-label="指北针重置" @click="mapRef?.north()">
            <AppIcon name="north" :size="16" />
          </button>
          <button class="icon-button shadow-xs" title="放大视角" aria-label="放大视角" @click="mapRef?.zoom(true)">
            <AppIcon name="plus" :size="16" />
          </button>
          <button class="icon-button shadow-xs" title="缩小视角" aria-label="缩小视角" @click="mapRef?.zoom(false)">
            <AppIcon name="minus" :size="16" />
          </button>
          <button class="icon-button shadow-xs text-accent" title="截图导出当前专题地图" aria-label="截图导出当前专题地图" @click="handleCaptureMap">
            <AppIcon name="download" :size="16" />
          </button>
        </div>

        <!-- Top Center Warning & Error Banners -->
        <div v-if="store.message || store.error" class="absolute left-1/2 top-4 z-10 -translate-x-1/2 space-y-2">
          <div v-if="store.message" class="rounded-full border border-amber-200 bg-amber-50/95 px-4 py-1.5 text-xs text-amber-800 shadow-md backdrop-blur-xs">
            {{ store.message }}
          </div>
          <div v-if="store.error" class="rounded-full border border-red-200 bg-red-50/95 px-4 py-1.5 text-xs text-red-800 shadow-md backdrop-blur-xs">
            {{ store.error }}
          </div>
        </div>

        <!-- Floating Corner Legend (Visible only when left TOC panel is collapsed) -->
        <div
          v-if="!leftPanelOpen && activeLegend"
          class="absolute bottom-6 left-6 z-20 w-48 rounded-xl border border-line bg-white/95 p-2.5 text-xs shadow-lg backdrop-blur-md transition-all"
        >
          <div class="flex items-center justify-between font-medium text-ink">
            <span>{{ store.committedProduct?.name }}</span>
            <span class="text-muted text-[10px]">{{ store.activeItem?.unit }}</span>
          </div>
          <div class="mt-1.5 h-2 w-full rounded-sm" :style="{ background: `linear-gradient(to right, ${activeLegend.colors.join(', ')})` }" />
          <div class="mt-1 flex justify-between text-[10px] text-muted tabular-nums">
            <span>{{ activeLegend.min }}</span>
            <span>{{ ((activeLegend.min + activeLegend.max) / 2).toFixed(1) }}</span>
            <span>{{ activeLegend.max }}</span>
          </div>
        </div>

        <!-- Clean Spatio-temporal Timeline Controller -->
        <Timeline />
      </main>

      <!-- Collapse Toggle Button: Right Panel -->
      <button
        class="absolute right-0 top-4 z-20 grid size-8 place-items-center rounded-l-lg border border-r-0 border-line bg-white text-muted shadow-xs transition hover:text-ink"
        :style="{ right: rightPanelOpen ? '20rem' : '0' }"
        :title="rightPanelOpen ? '收起右侧详情栏' : '展开右侧详情栏'"
        @click="rightPanelOpen = !rightPanelOpen"
      >
        <AppIcon :name="rightPanelOpen ? 'right' : 'left'" :size="16" />
      </button>

      <!-- Right Detail Panel -->
      <aside
        class="z-10 flex h-full shrink-0 flex-col border-l border-line bg-white transition-all duration-200"
        :class="rightPanelOpen ? 'w-80 p-5 overflow-y-auto' : 'w-0 p-0 border-l-0 overflow-hidden'"
      >
        <div v-if="rightPanelOpen" class="space-y-4">
          <DetailPanel
            :record="selectedRecord"
            :feature="selectedFeature"
            @close="rightPanelOpen = false"
            @checkin="openCheckInModal(store.selection?.coordinates)"
            @record="(rec) => { selectedRecord = rec; selectedFeature = null; store.choosePoint(rec.location.coordinates, rec.alias); mapRef?.focus(rec.location.coordinates); }"
            @export="openExport"
          />
        </div>
      </aside>
    </div>

    <footer class="z-20 shrink-0 border-t border-line bg-white px-4 py-2 text-xs text-muted" aria-label="数据来源">
      <strong v-if="store.isDemo" class="mr-2 text-terracotta">演示模式：合成场景与数值，不代表真实观测。</strong>
      {{ store.scene?.attribution.join('；') }} <span v-if="!store.isDemo"> · © <a href="https://www.tianditu.gov.cn" target="_blank" rel="noopener noreferrer">国家地理信息公共服务平台 天地图 Tianditu</a></span>
    </footer>

    <!-- Modals -->
    <CheckInForm
      :open="checkInOpen"
      :coordinates="checkInCoords"
      :editing="editingCheckIn"
      @close="checkInOpen = false"
      @login="authOpen = true"
      @saved="() => { store.refreshRecords(); myCheckInsOpen = true; }"
      @preview="(coords, coarse) => mapRef?.draft(coords, coarse)"
      @pick="() => { checkInOpen = false; }"
    />

    <MyCheckInsModal
      :open="myCheckInsOpen"
      @close="myCheckInsOpen = false"
      @edit="handleEditCheckIn"
      @deleted="store.refreshRecords()"
    />

    <AuthModal
      :open="authOpen"
      @close="authOpen = false"
      @success="store.refreshRecords()"
    />

    <ExportModal
      :open="exportOpen"
      @close="exportOpen = false"
    />

    <DataInfoModal
      :open="dataInfoOpen"
      @close="dataInfoOpen = false"
      @open-forecast="handleOpenForecastFromInfo"
    />

    <ForecastModal
      :open="forecastOpen"
      @close="forecastOpen = false"
    />
  </div>
</template>
