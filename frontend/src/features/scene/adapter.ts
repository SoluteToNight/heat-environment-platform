import type * as CesiumTypes from 'cesium';
import type { Coordinates, EnvironmentView, Layer, PublicCheckIn, Scene, Variable } from '../../services/contracts';
import type { PreparedFrame } from '../../stores/workspace';
import { publicGrid, sensationNames } from '../../services/format';

declare global { interface Window { Cesium: typeof CesiumTypes; CESIUM_BASE_URL: string } }
let runtimePromise: Promise<typeof CesiumTypes> | undefined;
function loadRuntime() {
  if (runtimePromise) return runtimePromise;
  runtimePromise = new Promise<typeof CesiumTypes>((resolve, reject) => {
    window.CESIUM_BASE_URL = '/cesium/';
    const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = '/cesium/Widgets/widgets.css'; document.head.append(link);
    const script = document.createElement('script'); script.src = '/cesium/Cesium.js';
    const fail = () => { clearTimeout(timeout); script.remove(); runtimePromise = undefined; reject(new Error('三维资源加载失败或超时，可重试或通过地点和坐标查询。')); };
    const timeout = setTimeout(fail, 20000);
    script.onload = () => { if (!window.Cesium) return fail(); clearTimeout(timeout); resolve(window.Cesium); };
    script.onerror = fail;
    document.head.append(script);
  });
  return runtimePromise;
}
async function fetchIonToken(): Promise<string | null> {
  try {
    const res = await fetch('/api/cesium-token', { cache: 'no-store' });
    if (res.ok) {
      const data = await res.json();
      return typeof data?.token === 'string' && data.token.trim() ? data.token.trim() : null;
    }
  } catch {
    // ignore
  }
  return null;
}
export interface MapPick {
  name: string;
  coordinates: Coordinates;
  featureId?: string;
  layerId?: string;
  height?: number;
  elevation_m?: number;
  levels?: number;
  properties?: Record<string, unknown>;
  record?: PublicCheckIn;
}
export interface MapCallbacks { pick: (items: MapPick[]) => void; viewport: (bbox: string) => void; error: (message: string) => void; layerStatus: (id: string, status: string) => void }
export class SceneAdapter {
  private constructor(private cesium: typeof CesiumTypes, private viewer: CesiumTypes.Viewer, private config: Scene, private callbacks: MapCallbacks) {}
  private groups = new Map<string, CesiumTypes.CustomDataSource>();
  private primitives = new Map<string, CesiumTypes.Cesium3DTileset>();
  private rasterLayers = new Map<string, CesiumTypes.ImageryLayer>();
  private environment: CesiumTypes.CustomDataSource | CesiumTypes.ImageryLayer | null = null;
  private handler?: CesiumTypes.ScreenSpaceEventHandler;
  private removers: Array<() => void> = [];
  private marker?: CesiumTypes.Entity;
  private draft?: CesiumTypes.Entity;
  private destroyed = false;
  private opacity = .75;
  private canopyOpacity = 1;
  private demo = false;
  private requestId = 0;
  private terrainProvider?: CesiumTypes.TerrainProvider;
  private buildingEntities = new Map<string, CesiumTypes.Entity>();
  private buildingAccessTime = new Map<string, number>();
  private buildingApiUrl?: string;
  private buildingUpdateTimer?: ReturnType<typeof setTimeout>;
  private buildingAbortController?: AbortController;
  private buildingVisible = true;
  private buildingOpacity = 0.20;
  private clusterListenerAttached = false;
  static async create(element: HTMLElement, config: Scene, layers: Layer[], callbacks: MapCallbacks) {
    const [cesium, token] = await Promise.all([loadRuntime(), fetchIonToken()]);
    if (token) {
      cesium.Ion.defaultAccessToken = token;
    }
    cesium.CreditDisplay.cesiumCredit = new cesium.Credit('');
    // 上海采用统一平原基准面，使用纯椭球面（EllipsoidTerrainProvider），
    // 避免加载带地表起伏的外部世界地形导致平原建筑被起伏地皮吞噬截断
    const initialTerrain: CesiumTypes.TerrainProvider = new cesium.EllipsoidTerrainProvider();
    const viewer = new cesium.Viewer(element, {
      animation: false, timeline: false, baseLayerPicker: false, geocoder: false, homeButton: false,
      sceneModePicker: false, selectionIndicator: false, infoBox: false, navigationHelpButton: false,
      fullscreenButton: false, baseLayer: false, terrainProvider: initialTerrain,
      requestRenderMode: true, maximumRenderTimeChange: Infinity, shadows: false,
      contextOptions: { webgl: { preserveDrawingBuffer: true, alpha: false } },
    });
    if ((viewer.cesiumWidget.creditContainer as HTMLElement)) {
      (viewer.cesiumWidget.creditContainer as HTMLElement).style.display = 'none';
    }
    // Use native device pixel ratio up to 2.0x for razor-sharp rendering on High-DPI screens
    viewer.resolutionScale = Math.max(1.0, Math.min(window.devicePixelRatio || 1.0, 2.0));
    viewer.scene.backgroundColor = cesium.Color.fromCssColorString('#e5ebe5');
    viewer.scene.globe.baseColor = cesium.Color.fromCssColorString('#e5e9df');
    if (viewer.scene.skyBox) viewer.scene.skyBox.show = false;
    if (viewer.scene.skyAtmosphere) viewer.scene.skyAtmosphere.show = false;
    if (viewer.scene.sun) viewer.scene.sun.show = false;
    if (viewer.scene.moon) viewer.scene.moon.show = false;
    viewer.clock.shouldAnimate = false;
    viewer.shadowMap.darkness = .7;
    viewer.scene.light.intensity = 1.8;
    viewer.scene.postProcessStages.fxaa.enabled = true;
    viewer.scene.globe.enableLighting = false;
    viewer.scene.globe.depthTestAgainstTerrain = false;
    // Lower maximumScreenSpaceError from default 2.0 to 1.33 to trigger higher-resolution map tiles & sharper vector details
    viewer.scene.globe.maximumScreenSpaceError = 1.33;
    viewer.scene.globe.tileCacheSize = 300;
    viewer.scene.screenSpaceCameraController.minimumZoomDistance = 100;
    viewer.scene.screenSpaceCameraController.maximumZoomDistance = 300000;
    const adapter = new SceneAdapter(cesium, viewer, config, callbacks);
    adapter.terrainProvider = initialTerrain;
    adapter.demo = layers.some(layer => layer.assets.some(asset => asset.type === 'demo'));
    if (!adapter.demo) {
      const tiandituKey = config.tianditu_key || (import.meta as any).env?.VITE_TIANDITU_KEY || '';
      const basemap = new cesium.UrlTemplateImageryProvider({
        url: `https://t{s}.tianditu.gov.cn/DataServer?T=vec_w&x={x}&y={y}&l={z}&tk=${tiandituKey}`,
        subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'],
        tilingScheme: new cesium.WebMercatorTilingScheme(),
        maximumLevel: 18,
        credit: new cesium.Credit('© 国家地理信息公共服务平台 天地图 Tianditu', true),
      });
      const imagery = viewer.imageryLayers.addImageryProvider(basemap);
      imagery.saturation = 0.8;
      imagery.brightness = 1.0;
      imagery.contrast = 1.05;

      const annotation = new cesium.UrlTemplateImageryProvider({
        url: `https://t{s}.tianditu.gov.cn/DataServer?T=cva_w&x={x}&y={y}&l={z}&tk=${tiandituKey}`,
        subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'],
        tilingScheme: new cesium.WebMercatorTilingScheme(),
        maximumLevel: 18,
      });
      const annotationLayer = viewer.imageryLayers.addImageryProvider(annotation);
      annotationLayer.alpha = 1.0;

      let failCount = 0;
      let reported = false;
      const reportFail = (tileError: any) => {
        if (tileError && typeof tileError === 'object') {
          if ((tileError.timesRetried || 0) < 3) {
            tileError.retry = true;
            return;
          }
          // Only trigger broken warning if root/macro levels (level <= 6) fail permanently
          if (tileError.level !== undefined && tileError.level > 6) {
            return;
          }
        }
        failCount++;
        if (failCount >= 10 && !reported && !adapter.destroyed) {
          reported = true;
          callbacks.layerStatus('basemap', 'failed');
        }
      };
      adapter.removers.push(basemap.errorEvent.addEventListener(reportFail));
      adapter.removers.push(annotation.errorEvent.addEventListener(reportFail));
    }
    adapter.reset(); adapter.bindPicking();
    const lost = (event: Event) => { event.preventDefault(); callbacks.error('三维显示已中断。可重建场景，或使用地点列表与坐标查询。'); };
    viewer.canvas.addEventListener('webglcontextlost', lost);
    adapter.removers.push(() => viewer.canvas.removeEventListener('webglcontextlost', lost));
    adapter.removers.push(viewer.scene.renderError.addEventListener(() => callbacks.error('三维绘制失败，可重建场景或使用地点查询。')));
    if (adapter.demo) adapter.createDemo();
    void Promise.allSettled(layers.map(layer => adapter.loadLayer(layer)));
    return adapter;
  }
  private color(value: string, alpha = 1) { return this.cesium.Color.fromCssColorString(value).withAlpha(alpha); }
  private local(east: number, north: number, height = 0) {
    return this.cesium.Cartesian3.fromDegrees(121.488 + east / 95300, 31.2335 + north / 111000, height);
  }
  private group(id: string) {
    let group = this.groups.get(id);
    if (!group) { group = new this.cesium.CustomDataSource(id); this.groups.set(id, group); void this.viewer.dataSources.add(group); }
    return group;
  }
  private polygon(group: CesiumTypes.CustomDataSource, positions: CesiumTypes.Cartesian3[], color: string, height = 0, name = '', properties: Record<string, unknown> = {}) {
    return group.entities.add({ name, properties, polygon: { hierarchy: new this.cesium.PolygonHierarchy(positions), material: this.color(color), height: .2, extrudedHeight: height || undefined, shadows: this.cesium.ShadowMode.ENABLED, outline: false } });
  }
  private rectangle(group: CesiumTypes.CustomDataSource, east: number, north: number, width: number, depth: number, color: string, height = 0, name = '') {
    return this.polygon(group, [[east, north], [east + width, north], [east + width, north + depth], [east, north + depth]].map(point => this.local(point[0]!, point[1]!)), color, height, name, { layer_id: group.name, height_m: height });
  }
  private createDemo() {
    const cesium = this.cesium;
    const ground = this.group('ground');
    this.rectangle(ground, -1500, -1300, 2900, 2600, '#e2e6db');
    const bank = (north: number) => 470 + Math.sin(north / 620) * 155;
    const river = this.group('water');
    const riverEdge = Array.from({ length: 25 }, (_, index) => { const north = -1600 + index * 140; return this.local(bank(north), north); });
    this.polygon(river, [...riverEdge, this.local(2300, 1800), this.local(2300, -1600)], '#a9c5c5');
    const green = this.group('green');
    const innerEdge = Array.from({ length: 25 }, (_, index) => { const north = 1760 - index * 140; return this.local(bank(north) - 165, north); });
    this.polygon(green, [...riverEdge, ...innerEdge], '#bacfa7');
    const roads = this.group('roads');
    for (let column = 0; column < 7; column++) this.rectangle(roads, -1420 + column * 285, -1350, 22, 2700, '#f6f4e9');
    for (let row = 0; row < 10; row++) this.rectangle(roads, -1450, -1350 + row * 280, 1860, 25, '#f6f4e9');
    roads.entities.add({ polyline: { positions: Array.from({ length: 30 }, (_, index) => { const north = -1400 + index * 100; return this.local(bank(north) - 50, north, 1); }), width: 9, material: this.color('#f0e6cd') } });
    const buildings = this.group('buildings');
    for (let row = 0; row < 9; row++) {
      for (let column = 0; column < 6; column++) {
        const east = -1360 + column * 285;
        const north = -1270 + row * 280;
        if (row === 4 && column >= 3) { this.rectangle(green, east - 10, north - 15, 240, 200, '#c1d0af'); continue; }
        for (let block = 0; block < 3; block++) {
          const height = 24 + ((row * 17 + column * 13 + block * 11) % 7) * 13;
          this.rectangle(buildings, east + (block % 2) * 104, north + Math.floor(block / 2) * 98, 63 + ((row + block) % 3) * 10, 60 + ((column + block) % 3) * 12, block === 2 ? '#e9e9de' : '#faf9ef', height, '街区建筑');
        }
      }
    }
    this.rectangle(buildings, -175, 330, 80, 95, '#faf9ef', 185, '概念塔楼');
    this.rectangle(buildings, -75, 365, 64, 68, '#f4f5ed', 128, '概念塔楼');
    const canopy = this.group('canopy');
    for (let index = 0; index < 210; index++) {
      let east: number; let north: number;
      if (index < 115) { north = -1350 + index * 25; east = bank(north) - 90 - (index % 3) * 26; }
      else { north = -1210 + Math.floor((index - 115) / 7) * 180; east = -1400 + ((index - 115) % 7) * 273; }
      canopy.entities.add({ name: '街区树冠', position: this.local(east, north, 9), properties: { layer_id: 'canopy', height_m: 13 }, ellipsoid: { radii: new cesium.Cartesian3(12 + index % 4, 12, 9), material: this.color(['#799a68', '#88a775', '#709363'][index % 3]!), shadows: cesium.ShadowMode.ENABLED } });
    }
    const poi = this.group('poi');
    [[390, 0, '滨江绿地'], [-200, 180, '城市广场'], [-600, -500, '林荫步道']].forEach(([east, north, name]) => {
      poi.entities.add({ position: this.local(Number(east), Number(north), 8), label: { text: String(name), font: '14px "Microsoft YaHei", sans-serif', fillColor: this.color('#35564a'), outlineColor: this.color('#ffffff'), outlineWidth: 5, style: cesium.LabelStyle.FILL_AND_OUTLINE, disableDepthTestDistance: Infinity, distanceDisplayCondition: new cesium.DistanceDisplayCondition(0, 6000) } });
    });
  }
  private async loadLayer(layer: Layer) {
    if (layer.availability !== 'available') { this.callbacks.layerStatus(layer.layer_id, 'missing'); return; }
    this.callbacks.layerStatus(layer.layer_id, 'loading');
    let partial = false;
    try {
      for (const asset of layer.assets) {
        if (this.destroyed) return;
        if (asset.type === 'demo') { this.showLayer(layer.layer_id, layer.default_visible); continue; }
        if (asset.format === 'dynamic-buildings' || (layer.type === 'buildings' && !this.demo)) {
          this.buildingVisible = layer.default_visible;
          const group = this.group('layer_buildings');
          group.show = layer.default_visible;
          if (asset.url) {
            this.buildingApiUrl = asset.url.split('?')[0];
            void this.refreshViewportBuildings();
          }
          continue;
        }
        if (asset.type === '3dtiles') {
          let tiles: CesiumTypes.Cesium3DTileset;
          if (asset.format === 'cesium-osm-buildings' || (!asset.url && layer.type === 'buildings')) {
            tiles = await this.cesium.createOsmBuildingsAsync({ defaultColor: this.color('#ffffff', 0.20) });
          } else if (asset.url) {
            tiles = await this.cesium.Cesium3DTileset.fromUrl(asset.url);
          } else {
            continue;
          }
          if (this.destroyed) { tiles.destroy(); return; }
          tiles.show = layer.default_visible;
          tiles.shadows = this.cesium.ShadowMode.ENABLED;
          this.viewer.scene.primitives.add(tiles);
          this.primitives.set(layer.layer_id, tiles);
        } else if (!asset.url) {
          continue;
        } else if (asset.type === 'geojson') {
          let data: string | object = asset.url;
          if (asset.format === 'platform-features') {
            const response = await fetch(asset.url, { signal: AbortSignal.timeout(20000), credentials: 'same-origin' });
            if (!response.ok) throw new Error('图层接口请求失败');
            const payload = await response.json();
            if (!Array.isArray(payload.data)) throw new Error('图层接口返回格式不正确');
            partial = payload.data.length >= 200;
            data = { type: 'FeatureCollection', features: payload.data.map((feature: { id: string; geometry: object; properties: Record<string, unknown> }) => ({ type: 'Feature', id: feature.id, geometry: feature.geometry, properties: { ...feature.properties, layer_id: layer.layer_id } })) };
          }
          if (this.destroyed) return;
          const source = await this.cesium.GeoJsonDataSource.load(data, {
            clampToGround: true,
            fill: this.color(layer.type === 'water' ? '#8fb5b5' : layer.type === 'green' ? '#9fc08f' : '#b4c9a3', layer.type === 'admin' ? .05 : 0.35),
            stroke: this.color(layer.type === 'admin' ? '#4a6b57' : '#9bb098'),
            strokeWidth: layer.type === 'admin' ? 2 : 1,
            credit: layer.attribution,
          });
          if (this.destroyed) return;
          source.show = layer.default_visible;
          source.entities.values.forEach(entity => {
            if (!entity.properties) entity.properties = new this.cesium.PropertyBag();
            if (!entity.properties.hasProperty('layer_id')) entity.properties.addProperty('layer_id', layer.layer_id);
            if (entity.polygon && layer.type === 'admin') {
              entity.polygon.outline = new this.cesium.ConstantProperty(true);
              entity.polygon.outlineColor = new this.cesium.ConstantProperty(this.color('#3b5945', 0.9));
              entity.polygon.outlineWidth = new this.cesium.ConstantProperty(2);
            }
            if (entity.polyline && layer.type === 'roads') {
              entity.polyline.width = new this.cesium.ConstantProperty(2);
              entity.polyline.material = new this.cesium.ColorMaterialProperty(this.color('#f9f7ed', .85));
            }
          });
          this.groups.set(layer.layer_id, source); await this.viewer.dataSources.add(source);
        } else if (asset.type === 'terrain') {
          const terrain = await this.cesium.CesiumTerrainProvider.fromUrl(asset.url);
          if (this.destroyed) return;
          this.terrainProvider = terrain;
          if (layer.default_visible) this.viewer.terrainProvider = terrain;
        } else if (asset.type === 'xyz' || asset.type === 'image') {
          const provider = asset.type === 'xyz' ? new this.cesium.UrlTemplateImageryProvider({ url: asset.url, credit: asset.attribution, minimumLevel: asset.minimum_level, maximumLevel: asset.maximum_level }) : await this.cesium.SingleTileImageryProvider.fromUrl(asset.url, { rectangle: asset.bbox ? this.cesium.Rectangle.fromDegrees(...asset.bbox) : undefined, credit: asset.attribution });
          if (this.destroyed) return;
          const image = this.viewer.imageryLayers.addImageryProvider(provider);
          image.show = layer.default_visible;
          if (layer.layer_id === 'layer_dem') {
            image.alpha = 0.85;
          }
          this.rasterLayers.set(layer.layer_id, image);
        }
      }
      if (!this.destroyed) { this.callbacks.layerStatus(layer.layer_id, partial ? 'partial' : 'ready'); this.render(); }
    } catch { if (!this.destroyed) this.callbacks.layerStatus(layer.layer_id, 'failed'); }
  }
  async prepare(view: EnvironmentView, variable: Variable): Promise<PreparedFrame> {
    const cesium = this.cesium;
    const item = view.items.find(value => value.variable === variable);
    let source: CesiumTypes.CustomDataSource | CesiumTypes.ImageryLayer | null = null;
    const asset = item?.assets[0];
    if (item?.availability === 'available' && asset) {
      if (asset.type === 'demo') {
        source = new cesium.CustomDataSource('environment');
        const hour = (new Date(item.resolved_time!).getUTCHours() + 8) % 24;
        for (let row = 0; row < 19; row++) for (let column = 0; column < 20; column++) {
          const east = -1450 + column * 100; const north = -1300 + row * 140;
          if (east > 465 + Math.sin(north / 620) * 155) continue;
          const fraction = Math.min(.98, Math.max(.02, .44 + Math.sin(column / 3 + row / 5) * .25 + Math.cos((hour - 14) * Math.PI / 12) * .17));
          const scaled = fraction * (item.legend.colors.length - 1); const index = Math.floor(scaled);
          const color = cesium.Color.lerp(this.color(item.legend.colors[index]!), this.color(item.legend.colors[Math.min(index + 1, item.legend.colors.length - 1)]!), scaled - index, new cesium.Color()).withAlpha(this.opacity);
          source.entities.add({ polygon: { hierarchy: new cesium.PolygonHierarchy([[east, north], [east + 100, north], [east + 100, north + 140], [east, north + 140]].map(point => this.local(point[0]!, point[1]!))), height: .6, material: color, shadows: cesium.ShadowMode.DISABLED } });
        }
      } else if (asset.type === 'geojson' && asset.url) {
        source = await cesium.GeoJsonDataSource.load(asset.url, { clampToGround: true });
      } else if ((asset.type === 'image' || asset.type === 'xyz') && asset.url) {
        const provider = asset.type === 'image' ? await cesium.SingleTileImageryProvider.fromUrl(asset.url, { rectangle: asset.bbox ? cesium.Rectangle.fromDegrees(...asset.bbox) : undefined }) : new cesium.UrlTemplateImageryProvider({ url: asset.url, minimumLevel: asset.minimum_level, maximumLevel: asset.maximum_level });
        source = new cesium.ImageryLayer(provider, { alpha: this.opacity, show: false });
        source.minificationFilter = cesium.TextureMinificationFilter.LINEAR;
        source.magnificationFilter = cesium.TextureMagnificationFilter.LINEAR;
        this.viewer.imageryLayers.add(source);
        if (asset.type === 'xyz') {
          source.show = true; source.alpha = 0;
          await this.waitForTiles();
          source.show = false; source.alpha = this.opacity;
        }
      } else { throw new Error('当前环境图层格式暂不支持，已保留上一视图。'); }
    }
    if (this.destroyed) { if (source instanceof cesium.ImageryLayer && !source.isDestroyed()) source.destroy(); throw new Error('场景已关闭'); }
    const prepared = source;
    let committed = false;
    return {
      commit: () => {
        if (this.destroyed) return;
        if (this.environment instanceof cesium.ImageryLayer) this.viewer.imageryLayers.remove(this.environment, true);
        else if (this.environment) this.viewer.dataSources.remove(this.environment, true);
        if (prepared instanceof cesium.ImageryLayer) {
          prepared.show = true;
          this.viewer.imageryLayers.raiseToTop(prepared);
        } else if (prepared) {
          void this.viewer.dataSources.add(prepared);
        }
        this.environment = prepared; committed = true;
        this.viewer.clock.currentTime = cesium.JulianDate.fromIso8601(view.requested_time); this.render();
      },
      dispose: () => { if (!committed && !this.destroyed && prepared instanceof cesium.ImageryLayer) this.viewer.imageryLayers.remove(prepared, true); },
    };
  }
  private waitForTiles() {
    return new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => { remove(); reject(new Error('地图资源加载超时，请重试。')); }, 15000);
      const remove = this.viewer.scene.postRender.addEventListener(() => {
        if (this.viewer.scene.globe.tilesLoaded) { clearTimeout(timer); remove(); resolve(); }
      });
      this.render();
    });
  }
  private bindPicking() {
    const cesium = this.cesium;
    this.handler = new cesium.ScreenSpaceEventHandler(this.viewer.canvas);
    let down: CesiumTypes.Cartesian2 | undefined;
    this.handler.setInputAction((event: { position: CesiumTypes.Cartesian2 }) => { down = cesium.Cartesian2.clone(event.position); }, cesium.ScreenSpaceEventType.LEFT_DOWN);
    this.handler.setInputAction((event: { position: CesiumTypes.Cartesian2 }) => {
      if (down && cesium.Cartesian2.distance(down, event.position) > 6) return;
      const ray = this.viewer.camera.getPickRay(event.position);
      const ground = ray && this.viewer.scene.globe.pick(ray, this.viewer.scene);
      if (!ground) { this.callbacks.error('未找到地面交点，请切换俯视后重选。'); return; }
      const position = cesium.Cartographic.fromCartesian(ground);
      const coordinates: Coordinates = [cesium.Math.toDegrees(position.longitude), cesium.Math.toDegrees(position.latitude)];
      const items: MapPick[] = [];
      const seen = new Set<string>();
      for (const picked of this.viewer.scene.drillPick(event.position, 5)) {
        if (picked && typeof (picked as { getProperty?: (name: string) => unknown }).getProperty === 'function') {
          const tileFeature = picked as CesiumTypes.Cesium3DTileFeature;
          const name = (tileFeature.getProperty('name') as string) || (tileFeature.getProperty('cesium#estimatedHeight') ? `街区建筑 (${Math.round(Number(tileFeature.getProperty('cesium#estimatedHeight')))}m)` : '街区建筑');
          const height = Number(tileFeature.getProperty('cesium#estimatedHeight') || tileFeature.getProperty('height')) || undefined;
          const featureId = String(tileFeature.getProperty('id') || tileFeature.getProperty('osm_id') || 'osm_building');
          if (!seen.has(featureId)) {
            seen.add(featureId);
            items.push({ name, coordinates, featureId, layerId: 'layer_buildings', height });
          }
          continue;
        }
        const entity = picked.id as CesiumTypes.Entity | undefined;
        if (!entity?.properties || seen.has(entity.id)) continue;
        seen.add(entity.id);
        const properties = entity.properties.getValue(this.viewer.clock.currentTime);
        if (properties.record) items.push({ name: properties.record.alias, coordinates: properties.record.location.coordinates, record: properties.record });
        else if (properties.layer_id) {
          items.push({
            name: (properties.name as string) || entity.name || '地图对象',
            coordinates,
            featureId: String(properties.feature_id || entity.id),
            layerId: properties.layer_id,
            height: typeof properties.height_m === 'number' ? properties.height_m : undefined,
            elevation_m: properties.layer_id === 'layer_buildings' ? undefined : (typeof properties.elevation_m === 'number' ? properties.elevation_m : undefined),
            levels: typeof properties.levels === 'number' ? properties.levels : undefined,
            properties: properties as Record<string, unknown>,
          });
        }
      }
      items.sort((a, b) => {
        const priority = (item: MapPick) => {
          if (item.record) return 3;
          if (item.layerId === 'layer_buildings' || item.layerId === 'buildings') return 2;
          if (item.layerId === 'layer_roads' || item.layerId === 'layer_water' || item.layerId === 'layer_green') return 1;
          return 0;
        };
        return priority(b) - priority(a);
      });
      items.push({ name: '查询此处环境', coordinates });
      this.callbacks.pick(items);
    }, cesium.ScreenSpaceEventType.LEFT_CLICK);
    this.removers.push(this.viewer.camera.moveEnd.addEventListener(() => {
      const rectangle = this.viewer.camera.computeViewRectangle();
      if (!rectangle) return;
      const bbox = [Math.max(this.config.bbox[0], cesium.Math.toDegrees(rectangle.west)), Math.max(this.config.bbox[1], cesium.Math.toDegrees(rectangle.south)), Math.min(this.config.bbox[2], cesium.Math.toDegrees(rectangle.east)), Math.min(this.config.bbox[3], cesium.Math.toDegrees(rectangle.north))];
      if (bbox[0]! < bbox[2]! && bbox[1]! < bbox[3]!) this.callbacks.viewport(bbox.join(','));
      this.scheduleViewportBuildingsUpdate();
    }));
  }
  showLayer(id: string, visible: boolean) {
    if (id === 'layer_buildings' || id === 'buildings') {
      this.buildingVisible = visible;
      if (this.groups.has('layer_buildings')) this.groups.get('layer_buildings')!.show = visible;
      if (this.groups.has('buildings')) this.groups.get('buildings')!.show = visible;
      if (visible && this.buildingEntities.size === 0) {
        void this.refreshViewportBuildings();
      }
    }
    if (this.groups.has(id)) this.groups.get(id)!.show = visible;
    if (this.primitives.has(id)) this.primitives.get(id)!.show = visible;
    if (this.rasterLayers.has(id)) this.rasterLayers.get(id)!.show = visible;
    if (id === 'terrain') this.viewer.terrainProvider = visible && this.terrainProvider ? this.terrainProvider : new this.cesium.EllipsoidTerrainProvider();
    if (id === 'shadows') this.viewer.shadows = visible;
    this.render();
  }
  setOpacity(value: number) {
    this.opacity = value;
    const environment = this.environment;
    if (environment instanceof this.cesium.ImageryLayer) environment.alpha = value;
    else environment?.entities.values.forEach(entity => {
      const material = entity.polygon?.material as CesiumTypes.ColorMaterialProperty;
      const color = material?.color?.getValue(this.viewer.clock.currentTime);
      if (color) entity.polygon!.material = new this.cesium.ColorMaterialProperty(color.withAlpha(value));
    });
    this.render();
  }
  setCanopyOpacity(value: number) {
    this.canopyOpacity = value;
    this.groups.get('canopy')?.entities.values.forEach(entity => {
      const graphic = entity.ellipsoid || entity.polygon;
      const material = graphic?.material as CesiumTypes.ColorMaterialProperty;
      const color = material?.color?.getValue(this.viewer.clock.currentTime);
      if (color && graphic) graphic.material = new this.cesium.ColorMaterialProperty(color.withAlpha(this.canopyOpacity));
    }); this.render();
  }
  setBuildingOpacity(value: number) {
    this.buildingOpacity = value;
    const cesium = this.cesium;
    const color = this.color('#ffffff', value);
    this.buildingEntities.forEach(entity => {
      if (entity.polygon) {
        entity.polygon.material = new cesium.ColorMaterialProperty(color);
      }
    });
    this.render();
  }
  setRecords(records: PublicCheckIn[]) {
    const group = this.group('ugc');
    group.entities.removeAll();
    group.clustering.enabled = true;
    group.clustering.pixelRange = 50;
    group.clustering.minimumClusterSize = 3;

    if (!this.clusterListenerAttached) {
      this.clusterListenerAttached = true;
      group.clustering.clusterEvent.addEventListener((clusteredEntities, cluster) => {
        // 关闭 Cesium 默认简陋的无背景白字 label
        cluster.label.show = false;
        cluster.billboard.show = true;
        cluster.billboard.id = cluster.label.id;
        cluster.billboard.verticalOrigin = this.cesium.VerticalOrigin.CENTER;
        cluster.billboard.disableDepthTestDistance = Infinity;

        const count = clusteredEntities.length;
        // 统计热感主导类型（暖色/冷绿色自适应光晕与底色）
        let warmCount = 0;
        clusteredEntities.forEach(ent => {
          const rec = ent.properties?.record?.getValue?.(this.viewer.clock.currentTime) || ent.properties?.record;
          const s = rec?.thermal_sensation;
          if (s === 'hot' || s === 'warm') warmCount++;
        });
        const isWarm = warmCount >= count / 2;
        const mainColor = isWarm ? '#e65100' : '#1b7a63';
        const gradColor = isWarm ? '#f57c00' : '#2e9e82';
        const haloFill = isWarm ? 'rgba(230, 81, 0, 0.22)' : 'rgba(27, 122, 99, 0.22)';

        const size = count < 10 ? 46 : count < 50 ? 52 : 58;
        const rOuter = size / 2 - 2;
        const rInner = size / 2 - 8;
        const fontSize = count < 10 ? 15 : count < 100 ? 13 : 11;

        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
          <defs>
            <filter id="shadow_${count}" x="-30%" y="-30%" width="160%" height="160%">
              <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#000000" flood-opacity="0.32"/>
            </filter>
            <linearGradient id="grad_${count}" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="${gradColor}"/>
              <stop offset="100%" stop-color="${mainColor}"/>
            </linearGradient>
          </defs>
          <circle cx="${size / 2}" cy="${size / 2}" r="${rOuter}" fill="${haloFill}"/>
          <circle cx="${size / 2}" cy="${size / 2}" r="${rInner}" fill="url(#grad_${count})" stroke="#ffffff" stroke-width="2.5" filter="url(#shadow_${count})"/>
          <text x="${size / 2}" y="${size / 2 + 5}" text-anchor="middle" fill="#ffffff" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', PingFang SC, Microsoft YaHei, sans-serif" font-size="${fontSize}" font-weight="700">${count}</text>
        </svg>`;

        cluster.billboard.image = `data:image/svg+xml,${encodeURIComponent(svg)}`;
        cluster.billboard.width = size;
        cluster.billboard.height = size;
      });
    }

    records.forEach(record => {
      const color = { cold: '#3b6e8c', cool: '#3d8b80', neutral: '#4e825a', warm: '#d97724', hot: '#c0392b' }[record.thermal_sensation];
      const sensationChar = sensationNames[record.thermal_sensation].slice(-1);
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="44" height="50" viewBox="0 0 44 50">
        <defs>
          <filter id="p_shadow" x="-30%" y="-20%" width="160%" height="150%">
            <feDropShadow dx="0" dy="2.5" stdDeviation="2.5" flood-color="#000000" flood-opacity="0.35"/>
          </filter>
        </defs>
        <path d="M22 47 C14 36 6 28 6 18 A16 16 0 1 1 38 18 C38 28 30 36 22 47 Z" fill="${color}" stroke="#ffffff" stroke-width="2.5" filter="url(#p_shadow)"/>
        <circle cx="22" cy="18" r="9.5" fill="#ffffff" fill-opacity="0.22"/>
        <text x="22" y="23" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif" font-size="13" font-weight="700" fill="#ffffff">${sensationChar}</text>
      </svg>`;
      group.entities.add({
        position: this.cesium.Cartesian3.fromDegrees(...record.location.coordinates, 18),
        properties: { record },
        billboard: {
          image: `data:image/svg+xml,${encodeURIComponent(svg)}`,
          width: 34,
          height: 38,
          verticalOrigin: this.cesium.VerticalOrigin.BOTTOM,
          disableDepthTestDistance: Infinity,
        },
      });
    });
    this.render();
  }
  select(coordinates: Coordinates, draft = false, coarse = false) {
    const cesium = this.cesium;
    if (draft && this.draft) this.viewer.entities.remove(this.draft);
    if (!draft && this.marker) this.viewer.entities.remove(this.marker);
    const entity = this.viewer.entities.add({ position: cesium.Cartesian3.fromDegrees(...coordinates, 5), point: { pixelSize: 13, color: this.color('#176c53'), outlineColor: cesium.Color.WHITE, outlineWidth: 4, disableDepthTestDistance: Infinity } });
    if (draft) this.draft = entity; else this.marker = entity;
    const privacy = this.group('privacy'); privacy.entities.removeAll();
    if (draft && coarse) { const grid = publicGrid(coordinates); this.polygon(privacy, grid.corners.map(point => cesium.Cartesian3.fromDegrees(...point, 3)), '#8cbfa4'); privacy.entities.values.forEach(item => { item.polygon!.material = new cesium.ColorMaterialProperty(this.color('#176c53', .2)); }); }
    this.render();
  }
  clearDraft() { if (this.draft) this.viewer.entities.remove(this.draft); this.group('privacy').entities.removeAll(); this.render(); }
  reset(top = false) {
    const camera = this.config.initial_camera;
    this.viewer.camera.lookAt(this.cesium.Cartesian3.fromDegrees(camera.longitude, camera.latitude), new this.cesium.HeadingPitchRange(this.cesium.Math.toRadians(camera.heading), this.cesium.Math.toRadians(top ? -89.9 : camera.pitch), camera.range));
    this.viewer.camera.lookAtTransform(this.cesium.Matrix4.IDENTITY); this.render();
  }
  flyToOverview() {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.viewer.camera.flyTo({
      destination: this.cesium.Cartesian3.fromDegrees(121.50, 31.25, 160000),
      orientation: {
        heading: 0,
        pitch: this.cesium.Math.toRadians(-89),
        roll: 0
      },
      duration: reduced ? 0 : 0.8
    });
    this.render();
  }
  north() { this.viewer.camera.setView({ orientation: { heading: 0, pitch: this.viewer.camera.pitch, roll: 0 } }); this.render(); }
  zoom(inward: boolean) { const distance = this.viewer.camera.positionCartographic.height * .25; if (inward) this.viewer.camera.zoomIn(distance); else this.viewer.camera.zoomOut(distance); this.render(); }
  focus(coordinates: Coordinates) {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.viewer.camera.flyToBoundingSphere(new this.cesium.BoundingSphere(this.cesium.Cartesian3.fromDegrees(...coordinates), 300), { duration: reduced ? 0 : .7, offset: new this.cesium.HeadingPitchRange(this.viewer.camera.heading, this.cesium.Math.toRadians(-48), 1700) });
    this.select(coordinates); this.render();
  }
  async capture() {
    if (this.destroyed) throw new Error('地图尚未就绪');
    const ticket = ++this.requestId;
    await this.waitForTiles();
    if (ticket !== this.requestId || this.destroyed) throw new Error('导出已取消');
    this.viewer.render();
    return this.viewer.canvas.toDataURL('image/png');
  }
  render() { if (!this.destroyed) this.viewer.scene.requestRender(); }
  private scheduleViewportBuildingsUpdate() {
    if (this.buildingUpdateTimer) clearTimeout(this.buildingUpdateTimer);
    this.buildingUpdateTimer = setTimeout(() => {
      void this.refreshViewportBuildings();
    }, 250);
  }
  private async refreshViewportBuildings() {
    if (this.destroyed || this.demo || !this.buildingVisible || !this.buildingApiUrl) return;
    const rectangle = this.viewer.camera.computeViewRectangle();
    if (!rectangle) return;
    const cesium = this.cesium;
    const west = Math.max(this.config.bbox[0], cesium.Math.toDegrees(rectangle.west));
    const south = Math.max(this.config.bbox[1], cesium.Math.toDegrees(rectangle.south));
    const east = Math.min(this.config.bbox[2], cesium.Math.toDegrees(rectangle.east));
    const north = Math.min(this.config.bbox[3], cesium.Math.toDegrees(rectangle.north));
    if (west >= east || south >= north) return;

    const cameraHeight = this.viewer.camera.positionCartographic.height;
    // 保护全域热暴露场着色：高空（> 3200m）时密集微细白模破坏热力色带连续性；
    // 此时隐藏建筑图层，保持热力图平滑纯净，杜绝全域零散杂斑
    if (cameraHeight > 3200) {
      if (this.groups.has('layer_buildings')) {
        this.groups.get('layer_buildings')!.show = false;
      }
      return;
    }
    // 进入中近景街区视角（<= 3200m）时恢复建筑可见（若用户开启了建筑图层）
    if (this.buildingVisible && this.groups.has('layer_buildings')) {
      this.groups.get('layer_buildings')!.show = true;
    }

    const isFar = cameraHeight > 1800;
    const minHeight = isFar ? 20 : undefined;
    const limit = 3000;

    this.buildingAbortController?.abort();
    this.buildingAbortController = new AbortController();

    const params = new URLSearchParams({
      layer_id: 'layer_buildings',
      bbox: `${west.toFixed(4)},${south.toFixed(4)},${east.toFixed(4)},${north.toFixed(4)}`,
      limit: String(limit),
    });
    if (minHeight !== undefined) {
      params.set('min_height', String(minHeight));
    }

    try {
      const response = await fetch(`${this.buildingApiUrl}?${params}`, {
        signal: this.buildingAbortController.signal,
        credentials: 'same-origin',
      });
      if (!response.ok || this.destroyed) return;
      const payload = await response.json();
      if (!Array.isArray(payload?.data)) return;

      const group = this.group('layer_buildings');
      const now = Date.now();

      for (const item of payload.data) {
        if (!item?.geometry || !item.id) continue;
        this.buildingAccessTime.set(item.id, now);
        if (this.buildingEntities.has(item.id)) continue;

        const props = (item.properties || {}) as Record<string, unknown>;
        const geom = item.geometry as { type: string; coordinates: any };
        let rings: number[][][] = [];
        if (geom.type === 'Polygon' && Array.isArray(geom.coordinates)) {
          rings = geom.coordinates;
        } else if (geom.type === 'MultiPolygon' && Array.isArray(geom.coordinates) && Array.isArray(geom.coordinates[0])) {
          rings = geom.coordinates[0];
        }
        if (!rings.length || !rings[0] || rings[0].length < 3) continue;

        const outerPositions = rings[0].map(pt => cesium.Cartesian3.fromDegrees(pt[0]!, pt[1]!));
        const holes = rings.slice(1).map(ring => new cesium.PolygonHierarchy(ring.map(pt => cesium.Cartesian3.fromDegrees(pt[0]!, pt[1]!))));
        const hierarchy = new cesium.PolygonHierarchy(outerPositions, holes);

        const explicitHeight = typeof props.height_m === 'number' && props.height_m > 0
          ? props.height_m
          : typeof props.height === 'number' && props.height > 0
            ? props.height
            : typeof props.levels === 'number' && props.levels > 0
              ? props.levels * 3.5
              : 12;

        // 去掉 DEM 高程基准：由于现有 12.5m DEM 未剔除建筑物高度（实为 DSM），
        // 若将其作为建筑地基标高会导致底面抬升与高度重复叠加。建筑统一以平原地表（0m）为基准拉伸。
        const baseElevation = 0;
        const extrudedHeight = explicitHeight;
        const buildingName = typeof props.name === 'string' && props.name.trim() ? props.name.trim() : '街区建筑';

        const entity = group.entities.add({
          name: buildingName,
          properties: {
            feature_id: item.id,
            layer_id: 'layer_buildings',
            name: buildingName,
            building: props.building,
            height_m: Math.round(explicitHeight * 10) / 10,
            elevation_m: null,
            levels: typeof props.levels === 'number' ? props.levels : null,
            area_m2: typeof props.area_m2 === 'number' ? Math.round(props.area_m2) : null,
            volume_m3: typeof props.volume_m3 === 'number' ? Math.round(props.volume_m3) : null,
            height_source: (props.height_source as string) || 'OSM 建筑物理净高 (平原基准，已剥离未滤波DEM)',
          },
          polygon: {
            hierarchy: new cesium.ConstantProperty(hierarchy),
            height: new cesium.ConstantProperty(baseElevation),
            extrudedHeight: new cesium.ConstantProperty(extrudedHeight),
            material: new cesium.ColorMaterialProperty(this.color('#ffffff', this.buildingOpacity)),
            outline: new cesium.ConstantProperty(true),
            outlineColor: new cesium.ConstantProperty(this.color('#94a3b8', 0.25)),
            shadows: new cesium.ConstantProperty(cesium.ShadowMode.ENABLED),
          },
        });

        this.buildingEntities.set(item.id, entity);
      }

      // LRU Eviction: maintain <= 6000 entities for smoother navigation
      if (this.buildingEntities.size > 6000) {
        const toEvictCount = this.buildingEntities.size - 4500;
        const sortedEntries = Array.from(this.buildingAccessTime.entries()).sort((a, b) => a[1] - b[1]);
        for (let i = 0; i < toEvictCount && i < sortedEntries.length; i++) {
          const [id] = sortedEntries[i]!;
          const ent = this.buildingEntities.get(id);
          if (ent) {
            group.entities.remove(ent);
            this.buildingEntities.delete(id);
          }
          this.buildingAccessTime.delete(id);
        }
      }

      this.render();
    } catch {
      // Abort or network hiccup, ignore
    }
  }
  destroy() {
    this.destroyed = true;
    this.requestId++;
    if (this.buildingUpdateTimer) clearTimeout(this.buildingUpdateTimer);
    this.buildingAbortController?.abort();
    this.buildingEntities.clear();
    this.buildingAccessTime.clear();
    this.handler?.destroy();
    this.removers.forEach(remove => remove());
    this.viewer.destroy();
  }
}
