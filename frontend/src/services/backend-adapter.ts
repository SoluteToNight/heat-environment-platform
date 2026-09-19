import type { Availability, Bbox, Catalog, CheckIn, CheckInBody, Coordinates, EnvironmentView, Layer, Product, Scene, Session, Variable, ViewItem } from './contracts';

interface WireScene { id: string; name: string; description?: string; center: Coordinates; bbox: Bbox; timezone?: string; tianditu_key?: string }
interface WirePoint { type?: string; coordinates: Coordinates }
interface WireSession { is_authenticated?: boolean; user?: { id?: string; username?: string; display_name?: string } | null }
interface WireCheckIn {
  id: string; scene_id?: string; alias?: string; created_at?: string; revision?: number;
  location?: WirePoint; exact_location?: WirePoint; public_location?: WirePoint;
  public_location_precision?: string; location_source?: string; horizontal_accuracy_m?: number | null;
  experienced_at?: string; time_source?: string; time_uncertainty_minutes?: number | null;
  thermal_sensation?: CheckInBody['thermal_sensation']; thermal_comfort?: string | null;
  setting?: CheckInBody['setting']; activity?: string | null; sun_exposure?: string | null; note?: string | null;
  visibility?: string; publication_status?: string; match_status?: CheckIn['match_status'];
}
interface WireLayer { layer_id: string; name: string; is_visible_default: boolean; attribution: string; type?: string }
interface WireProduct { product_id: string; variables: Array<{ code: string; name: string; unit: string; description: string; availability: Availability }>; times?: string[] }
interface WireView {
  view_id: string; requested_time: string; resolved_time: string; expires_at: string;
  variables: Array<{ variable: Variable; product_id: string; release_id: string; unit: string; availability: Availability; freshness: ViewItem['freshness']; reason_code?: string; provenance?: { model?: string; resolution?: string; receiver_height?: string; temporal_support?: string; attributions?: string[] } }>;
}
const scenes = new Map<string, Scene>();
const views = new Map<string, EnvironmentView>();
const legends: Record<Variable, Product['legend']> = {
  utci: { min: 15, max: 35, colors: ['#313695', '#4575b4', '#74add1', '#66bd63', '#a6d96a', '#fed976', '#fdae61', '#f46d43', '#d73027'] },
  air_temperature: { min: 0, max: 40, colors: ['#e4e9ba', '#ead18e', '#e9a365', '#cc6952'] },
  relative_humidity: { min: 0, max: 100, colors: ['#edf2d5', '#acd8c0', '#5aa9b6', '#3a658c'] },
  wind_speed: { min: 0, max: 15, colors: ['#e0edd7', '#a4c9b0', '#609d94', '#336d78'] },
  dew_point: { min: -10, max: 30, colors: ['#e7eed9', '#b4d2bc', '#79afa5', '#4d7c8a'] },
  solar_radiation: { min: 0, max: 1000, colors: ['#f4edc9', '#eed496', '#d7a063', '#ac664c'] },
  sun_visibility: { min: 0, max: 1, colors: ['#465b71', '#f3d59a'] },
  sky_factor: { min: 0, max: 1, colors: ['#465b71', '#aed7da'] },
  net_shortwave_background: { min: 0, max: 1000, colors: ['#f4edc9', '#eed496', '#d7a063', '#ac664c'] },
  local_downwelling_shortwave: { min: 0, max: 1000, colors: ['#f4edc9', '#ac664c'] },
};
const page = (items: unknown[], next_cursor: string | null = null) => ({ items, next_cursor });
// The backend paginates by offset, the frontend contract carries an opaque cursor.
const nextCursor = (url: URL, count: number) => {
  const limit = Number(url.searchParams.get('limit')) || 0;
  if (!limit || count < limit) return null;
  return String((Number(url.searchParams.get('offset')) || 0) + limit);
};

const normalizeSession = (value: WireSession): Session => ({
  authenticated: !!value.is_authenticated,
  user: value.user ? { user_id: value.user.username || value.user.id || '', alias: value.user.display_name || value.user.username || '市民' } : null,
});

const locationSources: CheckInBody['location_source'][] = ['manual_map', 'manual_coordinates', 'browser_geolocation'];

function normalizeOwnerCheckIn(value: WireCheckIn): CheckIn {
  const point = value.exact_location || value.public_location || value.location;
  if (!value.id || !point || point.coordinates.length !== 2) throw new Error('个人打卡记录缺少标识或坐标。');
  return {
    scene_id: value.scene_id || 'scene_shanghai',
    location: { type: 'Point', coordinates: [point.coordinates[0], point.coordinates[1]] },
    location_source: locationSources.includes(value.location_source as CheckInBody['location_source']) ? value.location_source as CheckInBody['location_source'] : 'manual_coordinates',
    horizontal_accuracy_m: value.horizontal_accuracy_m ?? null,
    experienced_at: value.experienced_at || '',
    time_source: 'user_selected',
    time_uncertainty_minutes: value.time_uncertainty_minutes ?? null,
    thermal_sensation: value.thermal_sensation || 'neutral',
    thermal_comfort: (value.thermal_comfort ?? null) as CheckInBody['thermal_comfort'],
    setting: value.setting || 'unknown',
    activity: value.activity ?? null,
    sun_exposure: value.sun_exposure ?? null,
    note: value.note ?? null,
    visibility: value.visibility === 'private' ? 'private' : 'public',
    public_location_precision: value.public_location_precision === 'exact' ? 'exact' : 'grid_200m',
    check_in_id: value.id,
    revision: String(value.revision ?? 1),
    alias: value.alias || '我',
    published_at: value.created_at ?? null,
    match_status: value.match_status || 'pending',
    publication_status: value.publication_status || 'pending',
  };
}

export function normalizeScene(value: WireScene): Scene {
  if (!value.id || !Array.isArray(value.center) || value.center.length !== 2 || !Array.isArray(value.bbox)) throw new Error('场景接口缺少标识、中心或范围。');
  const scene: Scene = {
    scene_id: value.id, name: value.name, description: value.description || '', scene_version: 'unversioned',
    bbox: value.bbox, timezone: value.timezone || 'Asia/Shanghai',
    initial_camera: { longitude: value.center[0], latitude: value.center[1], heading: 0, pitch: -50, range: 2500 },
    capabilities: { media_upload: false }, attribution: ['场景资源版本以各图层来源为准'],
    tianditu_key: value.tianditu_key,
  };
  scenes.set(scene.scene_id, scene);
  return scene;
}

export function normalizeCatalog(products: WireProduct[]): Catalog {
  return { products: products.flatMap(product => product.variables.filter(variable => Object.hasOwn(legends, variable.code)).map(variable => ({
    variable: variable.code as Variable, name: variable.name, unit: variable.unit, definition: variable.description,
    product_id: product.product_id, availability: variable.availability, times: product.times || [],
    reason_code: variable.availability === 'available' ? undefined : 'unsupported', legend: legends[variable.code as Variable],
  }))) };
}

export function normalizeLayers(items: WireLayer[], sceneId: string, apiBase: string): Layer[] {
  const scene = scenes.get(sceneId);
  if (!scene) throw new Error('图层加载前必须先读取场景目录。');
  // 默认静态矢量边界改为整个上海市全域边界
  const shanghaiBbox = scene.bbox.join(',');
  return items.map(layer => {
    if (layer.layer_id === 'layer_dem') {
      return {
        layer_id: layer.layer_id,
        name: layer.name,
        type: 'dem',
        layer_version: '12.5m',
        default_visible: layer.is_visible_default,
        availability: 'available',
        attribution: layer.attribution,
        assets: [{
          type: 'image',
          format: 'dem-hillshade',
          url: '/layers/shanghai_dem_hillshade.png',
          bbox: [120.83553985560039, 30.68558848098437, 122.06241214881048, 31.880612398115716],
          attribution: layer.attribution
        }],
      };
    }
    if (layer.type === '3dtiles') {
      return {
        layer_id: layer.layer_id,
        name: layer.name,
        type: layer.layer_id.replace(/^layer_/, ''),
        layer_version: 'unversioned',
        default_visible: layer.is_visible_default,
        availability: 'available',
        attribution: layer.attribution,
        assets: [{
          type: '3dtiles',
          format: 'cesium-osm-buildings',
          attribution: layer.attribution,
        }],
      };
    }
    const layerBbox = shanghaiBbox;
    const limit = layer.layer_id === 'layer_admin' ? '50' : '200';
    return {
      layer_id: layer.layer_id, name: layer.name, type: layer.layer_id.replace(/^layer_/, ''),
      layer_version: 'unversioned', default_visible: layer.is_visible_default, availability: 'available', attribution: layer.attribution,
      assets: [{
        type: 'geojson',
        format: 'platform-features',
        url: `${apiBase}/scenes/${encodeURIComponent(sceneId)}/features?${new URLSearchParams({ layer_id: layer.layer_id, bbox: layerBbox, limit })}`,
        attribution: layer.attribution
      }],
    };
  });
}

export function normalizeView(value: WireView): EnvironmentView {
  const view: EnvironmentView = {
    view_id: value.view_id, requested_time: value.requested_time, expires_at: value.expires_at,
    mode: value.variables.some(item => item.provenance?.temporal_support === 'hourly_forecast') || Date.parse(value.resolved_time) > Date.now() ? 'forecast' : 'historical',
    items: value.variables.map(item => ({
      ...item, requested_time: value.requested_time, resolved_time: value.resolved_time,
      interval_start: null, interval_end: null, temporal_support: 'instant', assets: [],
      reason_code: item.reason_code || null, legend: legends[item.variable],
      provenance: {
        source: [item.provenance?.model || item.product_id, ...(item.provenance?.attributions || [])].join('；'),
        spatial_support: item.provenance?.resolution || '未提供空间支持范围',
        receiver_height: item.provenance?.receiver_height || '未声明接收高度', model_version: item.release_id,
        omissions: ['当前接口仅提供位置读数，未发布环境栅格色带。'],
      },
    })),
  };
  views.set(view.view_id, view);
  if (views.size > 16) views.delete(views.keys().next().value!);
  return view;
}

export function normalizeBackendResponse(path: string, data: unknown, apiBase: string): unknown {
  const url = new URL(path, 'http://local');
  const pathname = url.pathname;
  if (pathname === '/scenes' && Array.isArray(data)) return page(data.map(normalizeScene));
  if (/^\/scenes\/[^/]+$/.test(pathname) && data && 'id' in Object(data)) return normalizeScene(data as WireScene);
  if (pathname.endsWith('/layers') && Array.isArray(data)) return page(normalizeLayers(data, decodeURIComponent(pathname.split('/')[2]!), apiBase));
  if (pathname.endsWith('/catalog') && Array.isArray(data)) return normalizeCatalog(data);
  if (pathname.endsWith('/status') && data && 'active_releases' in Object(data)) {
    const status = data as { active_releases: string[]; freshness: string; update_state: string };
    return { ...status, release_ids: status.active_releases };
  }
  if (pathname.endsWith('/environment/views') && data) {
    if (Array.isArray((data as WireView).variables)) return normalizeView(data as WireView);
    if (typeof data === 'object' && data !== null && 'view_id' in data) {
      views.set((data as EnvironmentView).view_id, data as EnvironmentView);
      if (views.size > 64) views.delete(views.keys().next().value!);
    }
  }
  if (pathname.endsWith('/point') && data && 'readings' in Object(data)) {
    const result = data as { view_id: string; lon: number; lat: number; elevation_m?: number | null; slope_deg?: number | null; readings: Array<{ variable: Variable; value: number | null; value_status: string; reason_code: string | null }> };
    const view = views.get(result.view_id);
    if (!view) throw new Error('点查询缺少对应视图，请重新选择时刻。');
    return {
      view_id: result.view_id,
      location: { type: 'Point', coordinates: [result.lon, result.lat] },
      elevation_m: result.elevation_m,
      slope_deg: result.slope_deg,
      items: result.readings.map(reading => ({ ...view.items.find(item => item.variable === reading.variable), ...reading }))
    };
  }
  if (pathname.endsWith('/series') && data && 'steps' in Object(data)) {
    const result = data as { view_id: string; steps: Array<{ time: string; values: Record<string, number | null> }> };
    const variable = url.searchParams.get('variables') || url.searchParams.get('variable') || 'air_temperature';
    return { view_id: result.view_id, variable, unit: views.get(result.view_id)?.items.find(item => item.variable === variable)?.unit || '', points: result.steps.map(step => ({ time: step.time, value: step.values[variable] ?? null })) };
  }
  if ((pathname === '/auth/login' || pathname === '/auth/session') && data && typeof data === 'object') return normalizeSession(data as WireSession);
  if (pathname === '/me/check-ins' && Array.isArray(data)) return page((data as WireCheckIn[]).map(normalizeOwnerCheckIn), nextCursor(url, data.length));
  if (pathname === '/check-ins' && Array.isArray(data)) {
    return page((data as WireCheckIn[]).map(item => ({
      ...item,
      check_in_id: item.id,
      alias: item.alias || `市民 (${String(item.id).slice(-4)})`,
    })), nextCursor(url, data.length));
  }
  if (data && typeof data === 'object' && 'exact_location' in Object(data)) return normalizeOwnerCheckIn(data as WireCheckIn);
  return data;
}
