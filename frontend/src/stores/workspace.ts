import { computed, ref, shallowRef } from 'vue';
import { defineStore } from 'pinia';
import { aborted, api, ApiError, errorMessage, isDemo } from '../services/api';
import type { Catalog, Coordinates, EnvironmentView, Layer, PointResult, PublicCheckIn, Scene, SeriesResult, Session, TimeSelection, Variable } from '../services/contracts';
import { buildHeatRiskDataset, HEAT_RISK_DEFAULT_PHASE, type HeatRiskDataset, type HeatRiskPresentation, type HeatRiskStyle } from '../services/heatRisk';

export interface PreparedFrame { commit: () => void; dispose: () => void }

interface HeatRiskState extends HeatRiskPresentation { loading: boolean; error: string; loaded: boolean }
export const useWorkspace = defineStore('workspace', () => {
  const scenes = ref<Scene[]>([]);
  const scene = shallowRef<Scene | null>(null);
  const layers = ref<Layer[]>([]);
  const catalog = shallowRef<Catalog>({ products: [] });
  const variable = ref<Variable>('air_temperature');
  const committedVariable = ref<Variable>('air_temperature');
  const view = shallowRef<EnvironmentView | null>(null);
  const point = shallowRef<PointResult | null>(null);
  const series = shallowRef<SeriesResult | null>(null);
  const selection = ref<{ coordinates: Coordinates; name: string } | null>(null);
  const session = ref<Session>({ authenticated: false, user: null });
  const records = ref<PublicCheckIn[]>([]);
  const recordError = ref('');
  const ugcHours = ref(24);
  const busy = ref(false);
  const pointBusy = ref(false);
  const seriesBusy = ref(false);
  const loading = ref(true);
  const message = ref('');
  const error = ref('');
  const expired = ref(false);
  const playing = ref(false);
  const timeSelection = ref<TimeSelection>({ kind: 'now' });
  const heatRisk = ref<HeatRiskState>({ enabled: false, phase: HEAT_RISK_DEFAULT_PHASE, style: 'probability', loading: false, error: '', loaded: false });
  const heatRiskDataset = shallowRef<HeatRiskDataset | null>(null);
  let heatRiskSequence = 0;
  const product = computed(() => catalog.value.products.find(item => item.variable === variable.value));
  const committedProduct = computed(() => catalog.value.products.find(item => item.variable === committedVariable.value));
  const activeItem = computed(() => view.value?.items.find(item => item.variable === committedVariable.value));
  const activeValue = computed(() => point.value?.items.find(item => item.variable === committedVariable.value));
  const times = computed(() => {
    const source = product.value?.times || [];
    if (source.length < 2) return source;
    const result: string[] = [];
    for (let index = 0; index < source.length - 1; index++) {
      const start = Date.parse(source[index]!);
      const end = Date.parse(source[index + 1]!);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) continue;
      const step = 15 * 60_000;
      for (let value = start; value < end; value += step) result.push(new Date(value).toISOString());
    }
    const last = source.at(-1);
    if (last) result.push(last);
    return [...new Set(result)];
  });
  const cache = new Map<string, EnvironmentView>();
  let sequence = 0;
  let pointSequence = 0;
  let sceneSequence = 0;
  let ugcSequence = 0;
  let requestController: AbortController | null = null;
  let pointController: AbortController | null = null;
  let sceneController: AbortController | null = null;
  let ugcController: AbortController | null = null;
  let prepare: ((view: EnvironmentView, variable: Variable) => Promise<PreparedFrame>) | null = null;
  let pollTimer: ReturnType<typeof setInterval> | undefined;
  let playTimer: ReturnType<typeof setTimeout> | undefined;
  let lastRelease = '';
  let currentBbox: string | undefined;
  const frameKey = (selection: TimeSelection, selectedVariable: Variable) => `${scene.value?.scene_id}/${selectedVariable}/${selection.kind === 'now' ? 'now' : selection.time}`;
  function bindRenderer(renderer: typeof prepare) { prepare = renderer; }
  async function initialize() {
    loading.value = true;
    error.value = '';
    try {
      const [sceneResult, sessionResult] = await Promise.allSettled([api.scenes(), api.session()]);
      if (sessionResult.status === 'fulfilled') session.value = sessionResult.value;
      if (sceneResult.status === 'rejected') throw sceneResult.reason;
      scenes.value = sceneResult.value.items;
      const requested = new URLSearchParams(location.search).get('scene_id');
      const initial = scenes.value.find(item => item.scene_id === requested) || scenes.value[0];
      if (!initial) throw new Error('暂无已发布场景。');
      await selectScene(initial.scene_id, true);
    } catch (problem) { error.value = errorMessage(problem); }
    finally { loading.value = false; }
  }
  async function selectScene(id: string, restoreLink = false) {
    stop();
    const ticket = ++sceneSequence;
    sequence++;
    pointSequence++;
    ugcSequence++;
    requestController?.abort();
    pointController?.abort();
    sceneController?.abort();
    ugcController?.abort();
    sceneController = new AbortController();
    loading.value = true;
    error.value = ''; message.value = ''; recordError.value = ''; expired.value = false; pointBusy.value = false;
    layers.value = []; catalog.value = { products: [] };
    view.value = null; point.value = null; series.value = null; selection.value = null; scene.value = null;
    records.value = []; cache.clear(); lastRelease = ''; currentBbox = undefined; busy.value = false;
    try {
      const result = await Promise.all([api.scene(id, sceneController.signal), api.layers(id, sceneController.signal), api.catalog(id, sceneController.signal)]);
      if (ticket !== sceneSequence) return;
      layers.value = result[1].items; catalog.value = result[2];
      const urlVariable = new URLSearchParams(location.search).get('variable');
      variable.value = catalog.value.products.find(item => item.variable === urlVariable && item.availability === 'available')?.variable || catalog.value.products.find(item => item.availability === 'available')?.variable || 'air_temperature';
      timeSelection.value = { kind: 'now' };
      const linkedTime = restoreLink ? new URLSearchParams(location.search).get('time') : null;
      if (linkedTime) {
        const supported = product.value?.times.find(time => Date.parse(time) === Date.parse(linkedTime));
        if (supported) timeSelection.value = { kind: 'at', time: supported };
        else message.value = '链接时刻不在当前产品的可用范围内，已返回现在。';
      }
      scene.value = result[0];
      void refreshRecords();
    } catch (problem) { if (ticket === sceneSequence && !aborted(problem)) error.value = errorMessage(problem); }
    finally { if (ticket === sceneSequence) loading.value = false; }
  }
  let pointDebounceTimer: ReturnType<typeof setTimeout> | undefined;
  async function switchView(next: TimeSelection = timeSelection.value) {
    if (!scene.value) return;
    const ticket = ++sequence;
    const selectedVariable = variable.value;
    requestController?.abort();
    pointController?.abort();
    pointSequence++;
    pointBusy.value = false;
    requestController = new AbortController();
    const key = frameKey(next, selectedVariable);
    const cached = expired.value ? undefined : cache.get(key);
    const isCached = !!cached && Date.parse(cached.expires_at) > Date.now();
    if (!isCached) {
      busy.value = true;
    }
    error.value = '';
    let frame: PreparedFrame | undefined;
    try {
      const nextView = isCached
        ? cached!
        : await api.view(scene.value.scene_id, catalog.value.products.map(item => item.variable), next, requestController.signal);
      if (ticket !== sequence) return;
      frame = await prepare?.(nextView, selectedVariable);
      if (ticket !== sequence) { frame?.dispose(); return; }
      frame?.commit();
      view.value = nextView; committedVariable.value = selectedVariable; timeSelection.value = next; expired.value = false;
      cache.set(key, nextView);
      if (cache.size > 256) cache.delete(cache.keys().next().value!);
      if (!playing.value) {
        const url = new URL(location.href);
        url.searchParams.set('scene_id', scene.value.scene_id);
        url.searchParams.set('variable', selectedVariable);
        if (next.kind === 'at') url.searchParams.set('time', next.time); else url.searchParams.delete('time');
        history.replaceState(null, '', url);
      }
      if (selection.value) {
        if (playing.value) {
          void queryPoint(true, false);
        } else {
          clearTimeout(pointDebounceTimer);
          pointDebounceTimer = setTimeout(() => {
            void queryPoint(false, false);
          }, 80);
        }
      }
      if (!playing.value && !isDemo) {
        scheduleNeighborPrefetch();
      }
    } catch (problem) {
      frame?.dispose();
      if (!aborted(problem) && ticket === sequence) { error.value = errorMessage(problem); stop(); }
    } finally { if (ticket === sequence) busy.value = false; }
  }
  function isTimeCached(time: string, checkVariable = variable.value): boolean {
    const key = frameKey({ kind: 'at', time }, checkVariable);
    const cached = expired.value ? undefined : cache.get(key);
    return !!cached && Date.parse(cached.expires_at) > Date.now();
  }
  async function chooseVariable(next: Variable) {
    stop(); variable.value = next;
    const available = product.value?.times || [];
    const selected = timeSelection.value.kind === 'at' ? Date.parse(timeSelection.value.time) : Date.now();
    if (available.length && (selected < Date.parse(available[0]!) || selected > Date.parse(available.at(-1)!))) {
      const nearest = available.reduce((best, time) => Math.abs(Date.parse(time) - selected) < Math.abs(Date.parse(best) - selected) ? time : best);
      await switchView({ kind: 'at', time: nearest });
    } else await switchView();
  }
  async function choosePoint(coordinates: Coordinates, name = '地图选点') {
    selection.value = { coordinates, name };
    await queryPoint(false, true);
  }
  async function queryPoint(playbackMode = false, coordinateChanged = false) {
    if (!view.value || !selection.value || expired.value) return;
    if (Date.parse(view.value.expires_at) <= Date.now()) { expired.value = true; await switchView(); return; }
    const ticket = ++pointSequence;
    pointController?.abort(); pointController = new AbortController();
    if (coordinateChanged) {
      point.value = null; series.value = null; pointBusy.value = true; seriesBusy.value = true;
    }
    const snapshot = view.value;
    const coordinates = selection.value.coordinates;
    const availableTimes = catalog.value.products.find(item => item.variable === committedVariable.value)?.times || [];
    try {
      const result = await api.point(snapshot.view_id, coordinates, pointController.signal);
      if (ticket !== pointSequence || view.value?.view_id !== result.view_id) return;
      point.value = result;
      pointBusy.value = false;
      if (coordinateChanged && availableTimes.length) {
        const values = await api.series(snapshot.view_id, coordinates, committedVariable.value, availableTimes[0]!, new Date(Date.parse(availableTimes.at(-1)!) + 3600_000).toISOString(), pointController.signal);
        if (ticket === pointSequence && view.value?.view_id === values.view_id) series.value = values;
      }
    } catch (problem) {
      if (ticket !== pointSequence || aborted(problem)) return;
      if (problem instanceof ApiError && problem.status === 410) { expired.value = true; void switchView(); }
      error.value = errorMessage(problem);
    } finally {
      if (ticket === pointSequence) {
        pointBusy.value = false;
        seriesBusy.value = false;
      }
    }
  }
  async function refreshRecords(bbox?: string) {
    if (!scene.value) return;
    currentBbox = bbox || currentBbox || scene.value.bbox.join(',');
    const ticket = ++ugcSequence;
    ugcController?.abort(); ugcController = new AbortController();
    const end = new Date();
    try {
      const result = await api.publicRecords({ scene_id: scene.value.scene_id, bbox: currentBbox, start: new Date(end.getTime() - ugcHours.value * 3600_000).toISOString(), end: end.toISOString(), limit: 200 }, ugcController.signal);
      if (ticket !== ugcSequence) return;
      records.value = result.items; recordError.value = result.next_cursor ? '记录较多，请缩小地图范围查看。' : '';
    } catch (problem) { if (!aborted(problem) && ticket === ugcSequence) { records.value = []; recordError.value = errorMessage(problem); } }
  }
  async function ensureHeatRiskData() {
    if (heatRisk.value.loaded || heatRisk.value.loading) return;
    const ticket = ++heatRiskSequence;
    heatRisk.value.loading = true;
    heatRisk.value.error = '';
    try {
      const [multitemporal, spatial, extreme] = await Promise.all([
        api.forecast24hMultitemporal(),
        api.forecast24hGrid(),
        api.forecast24hExtremeRegions().catch(() => null),
      ]);
      if (ticket !== heatRiskSequence) return;
      const dataset = buildHeatRiskDataset(multitemporal, spatial, (extreme as { top_extreme_hotspots?: Array<Record<string, unknown>> } | null)?.top_extreme_hotspots || []);
      heatRiskDataset.value = dataset;
      heatRisk.value.loaded = true;
      if (!dataset.grids.length) heatRisk.value.error = '未获取到模型反演网格，请稍后重试。';
    } catch (problem) {
      if (ticket === heatRiskSequence) heatRisk.value.error = errorMessage(problem);
    } finally {
      if (ticket === heatRiskSequence) heatRisk.value.loading = false;
    }
  }
  async function setHeatRiskEnabled(next: boolean) {
    heatRisk.value.enabled = next;
    if (next) await ensureHeatRiskData();
  }
  function setHeatRiskPhase(hour: number) { heatRisk.value.phase = hour; }
  function setHeatRiskStyle(style: HeatRiskStyle) { heatRisk.value.style = style; }
  async function refreshStatus() {
    if (document.hidden || !scene.value || busy.value) return;
    const id = scene.value.scene_id;
    const ticket = sceneSequence;
    try {
      const status = await api.status(id);
      if (ticket !== sceneSequence) return;
      const releases = status.release_ids.join(',');
      if (lastRelease && releases !== lastRelease) {
        const nextCatalog = await api.catalog(id);
        if (ticket !== sceneSequence) return;
        catalog.value = nextCatalog;
        cache.clear();
        if (timeSelection.value.kind === 'now' && !playing.value) await switchView({ kind: 'now' });
        else message.value = '有新的环境数据可用，点击“现在”查看。';
      }
      if (ticket !== sceneSequence) return;
      if (view.value && Date.parse(view.value.expires_at) <= Date.now()) {
        expired.value = true;
        await switchView();
      }
      if (ticket !== sceneSequence) return;
      if (status.freshness === 'stale' || status.update_state === 'failed') message.value = '数据更新延迟，当前显示已发布版本。';
      lastRelease = releases;
    } catch { if (ticket === sceneSequence) message.value = '暂时无法检查更新，已保留当前视图。'; }
  }
  function stop() {
    if (playing.value && view.value && scene.value) {
      const url = new URL(location.href);
      url.searchParams.set('scene_id', scene.value.scene_id);
      url.searchParams.set('variable', committedVariable.value);
      if (timeSelection.value.kind === 'at') url.searchParams.set('time', timeSelection.value.time); else url.searchParams.delete('time');
      history.replaceState(null, '', url);
    }
    playing.value = false;
    clearTimeout(playTimer);
  }
  let prefetchTimer: ReturnType<typeof setTimeout> | undefined;
  function prefetchNeighbors(centerIndex: number, radius = 3) {
    if (!scene.value || !times.value.length || isDemo) return;
    const timeList: string[] = [];
    for (let r = 1; r <= radius; r++) {
      if (centerIndex + r < times.value.length) timeList.push(times.value[centerIndex + r]!);
      if (centerIndex - r >= 0) timeList.push(times.value[centerIndex - r]!);
    }
    void prefetch(timeList, 0, timeList.length);
  }
  function scheduleNeighborPrefetch() {
    if (isDemo || playing.value || !scene.value || !times.value.length) return;
    clearTimeout(prefetchTimer);
    prefetchTimer = setTimeout(() => {
      if (isDemo || playing.value || !scene.value) return;
      const currentTime = activeItem.value?.resolved_time || (timeSelection.value.kind === 'at' ? timeSelection.value.time : view.value?.requested_time);
      let index = times.value.findIndex(time => time === currentTime);
      if (index === -1 && currentTime) {
        const targetMs = Date.parse(currentTime);
        index = times.value.reduce((best, time, i) => Math.abs(Date.parse(time) - targetMs) < Math.abs(Date.parse(times.value[best]!) - targetMs) ? i : best, 0);
      }
      if (index >= 0) {
        prefetchNeighbors(index, 3);
      }
    }, 150);
  }
  async function prefetch(timeList: string[], startIndex: number, count = 4) {
    if (!scene.value) return;
    const currentVar = variable.value;
    const sceneId = scene.value.scene_id;
    const variables = catalog.value.products.map(item => item.variable);
    for (let i = startIndex; i < Math.min(timeList.length, startIndex + count); i++) {
      const t = timeList[i];
      if (!t) continue;
      const key = frameKey({ kind: 'at', time: t }, currentVar);
      if (cache.has(key)) {
        const prefetchedView = cache.get(key);
        const targetItem = prefetchedView?.items.find(item => item.variable === currentVar);
        const asset = targetItem?.assets?.[0];
        if (typeof Image !== 'undefined' && asset?.url && (asset.type === 'image' || asset.type === 'xyz')) {
          const img = new Image();
          img.src = asset.url;
        }
        if (prepare && prefetchedView) {
          void prepare(prefetchedView, currentVar).catch(() => {});
        }
        continue;
      }
      try {
        const prefetchedView = await api.view(sceneId, variables, { kind: 'at', time: t });
        cache.set(key, prefetchedView);
        if (cache.size > 256) cache.delete(cache.keys().next().value!);
        const targetItem = prefetchedView.items.find(item => item.variable === currentVar);
        const asset = targetItem?.assets?.[0];
        if (typeof Image !== 'undefined' && asset?.url && (asset.type === 'image' || asset.type === 'xyz')) {
          const img = new Image();
          img.src = asset.url;
        }
        if (prepare && prefetchedView) {
          void prepare(prefetchedView, currentVar).catch(() => {});
        }
      } catch {
        // prefetch is silent background task
      }
    }
  }
  function play() {
    if (playing.value) return stop();
    if (!times.value.length) return;
    playing.value = true;
    const advance = async () => {
      if (!playing.value || !view.value) return;
      const currentTime = activeItem.value?.resolved_time || (timeSelection.value.kind === 'at' ? timeSelection.value.time : view.value?.requested_time);
      let index = times.value.findIndex(time => time === currentTime);
      if (index === -1 && currentTime) {
        const targetMs = Date.parse(currentTime);
        index = times.value.reduce((best, time, i) => Math.abs(Date.parse(time) - targetMs) < Math.abs(Date.parse(times.value[best]!) - targetMs) ? i : best, 0);
      }
      const nextIndex = index >= 0 && (index + 1) < times.value.length ? index + 1 : 0;
      const next = times.value[nextIndex];
      if (!next) return stop();
      await switchView({ kind: 'at', time: next });
      if (playing.value) {
        void prefetch(times.value, nextIndex + 1, 3);
        playTimer = setTimeout(advance, 650);
      }
    };
    void advance();
  }
  async function restoreVisibility() {
    if (document.hidden) { stop(); return; }
    try { session.value = await api.session(); } catch { session.value = { authenticated: false, user: null }; }
    await refreshStatus();
  }
  function startPolling() { clearInterval(pollTimer); pollTimer = setInterval(() => void refreshStatus(), 60_000); document.addEventListener('visibilitychange', restoreVisibility); void refreshStatus(); }
  function dispose() {
    sequence++; pointSequence++; sceneSequence++; ugcSequence++;
    requestController?.abort(); pointController?.abort(); sceneController?.abort(); ugcController?.abort();
    clearInterval(pollTimer); clearTimeout(prefetchTimer); stop(); document.removeEventListener('visibilitychange', restoreVisibility); prepare = null;
  }
  return { scenes, scene, layers, catalog, variable, committedVariable, view, point, series, selection, session, records, ugcHours, recordError, busy, pointBusy, seriesBusy, loading, message, error, expired, playing, timeSelection, heatRisk, heatRiskDataset, product, committedProduct, activeItem, activeValue, times, isDemo, isTimeCached, prefetchNeighbors, scheduleNeighborPrefetch, initialize, selectScene, bindRenderer, switchView, chooseVariable, choosePoint, queryPoint, refreshRecords, ensureHeatRiskData, setHeatRiskEnabled, setHeatRiskPhase, setHeatRiskStyle, refreshStatus, stop, play, startPolling, dispose };
});
