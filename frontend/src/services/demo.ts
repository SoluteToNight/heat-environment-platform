import type { CheckIn, CheckInBody, Coordinates, DecisionSupportResponse, EnvironmentView, ExtremeHotspotItem, ExtremeRegionsResponse, Layer, ModelEvaluationResponse, Product, PublicCheckIn, ReportReceipt, Scene, SectorGuideline, Session, Variable, WeatherAlerts, WeatherPoint, WeatherReading } from './contracts';
import { publicLocation } from './format';
import forecast24hSummaryFixture from './fixtures/heat_perception/real_24h_validation_summary.json';
import extremeRegionsFixture from './fixtures/heat_perception/spatial_extreme_hotspots.json';
import modelEvaluationFixture from './fixtures/heat_perception/model_evaluation.json';
import decisionSupportFixture from './fixtures/heat_perception/decision_support.json';

function calculateUtciApprox(ta: number, rh: number, va: number, rad: number): number {
  const vp = (rh / 100.0) * 6.112 * Math.exp((17.67 * ta) / (ta + 243.5));
  let utci = ta + 0.33 * vp - 0.70 * va - 4.0;
  utci += rad * 0.015;
  return Math.round(utci * 10) / 10;
}

function customInversionDemo(body: Record<string, number>) {
  const ta = body.air_temperature_c ?? 32;
  const rh = body.relative_humidity_pct ?? 60;
  const v = body.wind_speed_10m_ms ?? 2.0;
  const rad = body.net_solar_radiation_wm2 ?? 350;
  const green = body.green_fraction ?? 0.15;
  const water = body.water_fraction ?? 0.05;
  const bldg = body.building_fraction ?? 0.20;

  const utci = calculateUtciApprox(ta, rh, v, rad);
  const logit0 = -9.263 + 0.284 * utci;
  const p0 = 1.0 / (1.0 + Math.exp(-logit0));

  const logit1 = -8.115 + 0.276 * utci - 2.145 * green - 1.832 * water + 1.250 * bldg;
  const p1 = 1.0 / (1.0 + Math.exp(-logit1));
  const deltaP = p1 - p0;
  const mitPct = p0 > 0.001 ? Math.max(0, -deltaP / p0 * 100) : 0;

  let risk = '低风险 (舒适)';
  if (p1 >= 0.75) risk = '极高风险 (红色)';
  else if (p1 >= 0.50) risk = '高风险 (橙色)';
  else if (p1 >= 0.25) risk = '中等风险 (黄色)';

  let stress = '无热应激';
  if (utci >= 38) stress = '极度热应激';
  else if (utci >= 32) stress = '高度热应激';
  else if (utci >= 26) stress = '中度热应激';

  return {
    calculated_utci_c: utci,
    utci_stress_level: stress,
    p_hot_base: Math.round(p0 * 1000) / 1000,
    p_hot_enhanced: Math.round(p1 * 1000) / 1000,
    delta_p: Math.round(deltaP * 1000) / 1000,
    environmental_mitigation_pct: Math.round(mitPct * 10) / 10,
    risk_level: risk,
  };
}

/** 演示数据文件是后端入库前的原始产物，这里补齐服务端实际下发的包装结构 */
function extremeRegionsDemo(leadHour: number): ExtremeRegionsResponse {
  return {
    lead_hour: leadHour,
    top_extreme_hotspots: extremeRegionsFixture.slice(0, 10) as ExtremeHotspotItem[],
    total_identified_hotspots: extremeRegionsFixture.length,
  };
}

function decisionSupportDemo(): DecisionSupportResponse {
  const sectors: Record<string, SectorGuideline> = {};
  for (const [sector, measures] of Object.entries(decisionSupportFixture.sector_guidelines)) sectors[sector] = { instructions: measures };
  return {
    valid_period: `${decisionSupportFixture.evaluated_at} 起 ${decisionSupportFixture.forecast_horizon_hours} 小时`,
    max_utci_c: decisionSupportFixture.peak_utci,
    overall_risk_level: decisionSupportFixture.overall_risk_category,
    active_alerts: decisionSupportFixture.active_alerts.map(alert => ({
      level: alert.alert_level,
      title: alert.alert_title,
      trigger_period: alert.time_window,
      message: alert.impact_description,
    })),
    sector_guidelines: sectors,
  };
}

export const demoScene: Scene = {
  scene_id: 'shanghai-demo', name: '滨江街区', description: '上海 · 概念演示场景', scene_version: 'synthetic-v1',
  bbox: [121.478, 31.225, 121.505, 31.244], timezone: 'Asia/Shanghai',
  initial_camera: { longitude: 121.4895, latitude: 31.2335, heading: 18, pitch: -48, range: 2050 },
  capabilities: { media_upload: false }, attribution: ['概念街区与环境数值均为合成演示，不代表真实观测'],
};
// 演示窗口对齐产品时间语义：昨日 00:00（上海）起 72 个整点，覆盖昨日/今日/明日三天。
const todayStart = Math.floor((Date.now() + 8 * 3600_000) / 86_400_000) * 86_400_000 - 8 * 3600_000;
const times = Array.from({ length: 72 }, (_, index) => new Date(todayStart + (index - 24) * 3600_000).toISOString());
export const demoProducts: Product[] = [
  { variable: 'air_temperature', name: '气温', unit: '°C', legend: { min: 24, max: 38, colors: ['#e4e9ba', '#ead18e', '#e9a365', '#cc6952'] }, definition: '近地气温；演示值不代表观测。' },
  { variable: 'relative_humidity', name: '相对湿度', unit: '%', legend: { min: 30, max: 100, colors: ['#edf2d5', '#acd8c0', '#5aa9b6', '#3a658c'] }, definition: '空气相对湿度。' },
  { variable: 'wind_speed', name: '风速', unit: 'm/s', legend: { min: 0, max: 8, colors: ['#e0edd7', '#a4c9b0', '#609d94', '#336d78'] }, definition: '背景风速，不表示街谷三维流场。' },
  { variable: 'dew_point', name: '露点', unit: '°C', legend: { min: 10, max: 30, colors: ['#e7eed9', '#b4d2bc', '#79afa5', '#4d7c8a'] }, definition: '露点温度。' },
  { variable: 'net_shortwave_background', name: '区域净短波', unit: 'W/m²', legend: { min: 0, max: 800, colors: ['#f4edc9', '#eed496', '#d7a063', '#ac664c'] }, definition: '小时平均区域净短波；不等同于局地下行短波。' },
  { variable: 'local_downwelling_shortwave', name: '局地下行短波', unit: 'W/m²', legend: { min: 0, max: 1000, colors: ['#f4edc9', '#ac664c'] }, definition: '当前演示不具备所需辐射分量。' },
].map(item => ({ ...item, variable: item.variable as Variable, times, product_id: `demo-${item.variable}`, availability: item.variable === 'local_downwelling_shortwave' ? 'unsupported' : 'available', reason_code: item.variable === 'local_downwelling_shortwave' ? 'missing_radiation_components' : undefined }));
const layers: Layer[] = ['buildings:建筑', 'canopy:树冠', 'water:水体', 'green:绿地', 'roads:道路', 'poi:地点', 'terrain:地形'].map(item => {
  const [id, name] = item.split(':');
  return { layer_id: id!, name: name!, layer_version: 'synthetic-v1', type: id!, default_visible: id !== 'terrain', availability: id === 'terrain' ? 'missing' : 'available', reason_code: id === 'terrain' ? 'terrain_missing' : undefined, assets: [{ type: 'demo' }], attribution: '合成演示几何' };
});
const places = [
  { place_id: 'park', name: '滨江绿地', description: '沿江步道 · 演示地点', location: { type: 'Point', coordinates: [121.4915, 31.2334] } },
  { place_id: 'square', name: '城市广场', description: '开放广场 · 演示地点', location: { type: 'Point', coordinates: [121.4865, 31.2345] } },
  { place_id: 'walk', name: '林荫步道', description: '街区步道 · 演示地点', location: { type: 'Point', coordinates: [121.4845, 31.231] } },
];
let session: Session = { authenticated: false, user: null };
const views = new Map<string, EnvironmentView>();
const ownRecords: CheckIn[] = [];
const recordOwners = new Map<string, string>();
const idempotency = new Map<string, { body: string; data: unknown }>();
const reportKeys = new Map<string, { reason: string; receipt: ReportReceipt }>();
const demoRecords: PublicCheckIn[] = [
  { check_in_id: 'sample-1', alias: '沿江散步的人', location: { type: 'Point', coordinates: [121.4915, 31.2334] }, experienced_at: new Date(Date.now() - 1200_000).toISOString(), thermal_sensation: 'warm', thermal_comfort: 'comfortable', setting: 'outdoor', activity: 'walking', sun_exposure: 'shade', note: '沿着树荫走，有风时会舒服一些。', public_location_precision: 'grid_200m' },
  { check_in_id: 'sample-2', alias: '城市漫步者', location: { type: 'Point', coordinates: [121.4865, 31.2345] }, experienced_at: new Date(Date.now() - 3300_000).toISOString(), thermal_sensation: 'hot', thermal_comfort: 'uncomfortable', setting: 'outdoor', activity: 'walking', sun_exposure: 'sun', note: '广场上日晒比较明显，想找个阴凉处休息。', public_location_precision: 'grid_200m' },
  { check_in_id: 'sample-3', alias: '午后路过', location: { type: 'Point', coordinates: [121.4845, 31.231] }, experienced_at: new Date(Date.now() - 5400_000).toISOString(), thermal_sensation: 'neutral', thermal_comfort: 'comfortable', setting: 'outdoor', activity: 'resting', sun_exposure: 'shade', note: '树下坐一会儿，感觉刚刚好。', public_location_precision: 'grid_200m' },
];
demoRecords.forEach(record => { record.location.coordinates = publicLocation(record as unknown as CheckInBody); });
function projected(record: CheckIn): PublicCheckIn {
  return { check_in_id: record.check_in_id, alias: record.alias, location: { type: 'Point', coordinates: publicLocation(record) }, experienced_at: record.experienced_at, thermal_sensation: record.thermal_sensation, thermal_comfort: record.thermal_comfort, setting: record.setting, activity: record.activity, sun_exposure: record.sun_exposure, note: record.note, public_location_precision: record.public_location_precision };
}
function valueAt(variable: Variable, time: string, coordinates: Coordinates) {
  const date = new Date(time);
  const hour = ((date.getUTCHours() + 8) % 24) + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600;
  const phase = Math.cos((hour - 14) * Math.PI / 12);
  const spatial = Math.sin((coordinates[0] - 121.48) * 650) * .7 + Math.cos((coordinates[1] - 31.23) * 550) * .3;
  const values: Record<Variable, number | null> = {
    utci: 28.5 + phase * 4.2 + spatial,
    air_temperature: 29.8 + phase * 3.4 + spatial,
    relative_humidity: 68 - phase * 13,
    wind_speed: 2.3 + spatial * .4,
    dew_point: 22.4 + spatial * .2,
    solar_radiation: Math.max(0, 600 * phase),
    net_shortwave_background: Math.max(0, 570 * phase),
    local_downwelling_shortwave: null,
    sun_visibility: null,
    sky_factor: null,
  };
  const value = values[variable];
  return value === null ? null : Math.round(value * 10) / 10;
}
const response = (data: unknown, status = 200) => new Response(JSON.stringify({ data, meta: { request_id: 'demo', server_time: new Date().toISOString() } }), { status, headers: { 'Content-Type': 'application/json' } });
const failure = (status: number, message: string) => new Response(JSON.stringify({ error: { code: 'demo_error', message, details: [] } }), { status });
const page = (items: unknown[]) => ({ items, next_cursor: null });
export async function demoFetch(path: string, init: RequestInit): Promise<Response> {
  const signal = init.signal;
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  // 仅对非环境探索接口做微小异步调度（如 5ms），环境探索视图与选点 0ms 瞬间响应
  const delay = path.includes('/environment/views') ? 0 : 5;
  if (delay > 0) {
    await new Promise<void>((resolve, reject) => {
      const onAbort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
      const timer = setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve(); }, delay);
      signal?.addEventListener('abort', onAbort, { once: true });
    });
  }
  const url = new URL(path, 'http://demo.local');
  const pathname = url.pathname;
  const method = init.method || 'GET';
  const body = init.body ? JSON.parse(String(init.body)) : undefined;
  const headers = new Headers(init.headers);
  if (pathname === '/auth/session') return response(session);
  if (pathname === '/auth/login') {
    if (!body.username?.trim() || !body.password) return failure(401, '请填写演示账号与密码');
    session = { authenticated: true, user: { user_id: `demo-${body.username}`, alias: body.username }, csrf_token: 'demo-only' };
    return response(session);
  }
  if (pathname === '/auth/logout') { session = { authenticated: false, user: null }; return new Response(null, { status: 204 }); }
  if (pathname === '/scenes') return response(page([demoScene]));
  if (pathname === `/scenes/${demoScene.scene_id}`) return response(demoScene);
  if (pathname.endsWith('/layers')) return response(page(layers));
  if (pathname.endsWith('/places')) return response(page(places.filter(place => !url.searchParams.get('q') || place.name.includes(url.searchParams.get('q')!))));
  if (pathname.endsWith('/catalog')) return response({ products: demoProducts });
  if (pathname.endsWith('/status')) return response({ release_ids: ['demo-release-v1'], freshness: 'fresh', update_state: 'idle' });
  if (pathname.endsWith('/environment/views') && method === 'POST') {
    const requested = body.time_selection.kind === 'now' ? new Date().toISOString() : body.time_selection.time;
    const requestedMs = Date.parse(requested);
    const firstMs = Date.parse(times[0]!);
    const lastMs = Date.parse(times.at(-1)!);
    const resolved = requestedMs >= firstMs && requestedMs <= lastMs
      ? requested
      : times.reduce((best, current) => Math.abs(Date.parse(current) - requestedMs) < Math.abs(Date.parse(best) - requestedMs) ? current : best);
    const view: EnvironmentView = {
      view_id: `demo-view-${crypto.randomUUID()}`, requested_time: requested, mode: body.time_selection.kind === 'now' ? 'current_estimate' : Date.parse(requested) > Date.now() ? 'forecast' : 'historical', expires_at: new Date(Date.now() + 86400_000).toISOString(),
      items: demoProducts.filter(product => body.variables.includes(product.variable)).map(product => ({
        variable: product.variable, product_id: product.product_id, release_id: 'demo-release-v1', unit: product.unit, availability: product.availability, freshness: 'fresh', reason_code: product.reason_code || null, requested_time: requested,
        resolved_time: resolved, interval_start: product.variable === 'net_shortwave_background' ? resolved : null, interval_end: product.variable === 'net_shortwave_background' ? new Date(Date.parse(resolved) + 3600_000).toISOString() : null,
        temporal_support: product.variable === 'net_shortwave_background' ? 'interval_mean' : 'instant', assets: [{ type: 'demo' }], legend: product.legend,
        provenance: { source: '前端合成演示', spatial_support: '概念网格，不代表实际分辨率', receiver_height: '未对应真实接收面', model_version: 'fixture-v1', omissions: ['无实测或科学计算成果'] },
      })),
    };
    views.set(view.view_id, view);
    return response(view);
  }
  if (pathname.startsWith('/environment/views/')) {
    const view = views.get(pathname.split('/')[3]!);
    if (!view) return failure(410, '视图已到期');
    const coordinates: Coordinates = [Number(url.searchParams.get('longitude')), Number(url.searchParams.get('latitude'))];
    const outside = coordinates[0] < demoScene.bbox[0] || coordinates[0] > demoScene.bbox[2] || coordinates[1] < demoScene.bbox[1] || coordinates[1] > demoScene.bbox[3];
    if (pathname.endsWith('/point')) return response({ view_id: view.view_id, location: { type: 'Point', coordinates }, items: view.items.map(item => ({ ...item, value: outside ? null : valueAt(item.variable, item.resolved_time!, coordinates), value_status: outside ? 'outside_coverage' : item.availability === 'available' ? 'valid' : 'no_data', reason_code: outside ? 'outside_coverage' : item.reason_code })) });
    if (pathname.endsWith('/series')) {
      const variable = url.searchParams.get('variable') as Variable;
      return response({ view_id: view.view_id, variable, unit: demoProducts.find(product => product.variable === variable)?.unit, points: times.filter(time => time >= url.searchParams.get('start')! && time < url.searchParams.get('end')!).map((time, index) => ({ time, value: outside || index === 7 ? null : valueAt(variable, time, coordinates), ...(variable === 'net_shortwave_background' ? { interval_start: time, interval_end: new Date(Date.parse(time) + 3600_000).toISOString() } : {}) })) });
    }
    return response(view);
  }
  if (pathname === '/check-ins' && method === 'GET') {
    const bbox = (url.searchParams.get('bbox') || demoScene.bbox.join(',')).split(',').map(Number);
    return response(page([...demoRecords, ...ownRecords.filter(record => record.visibility === 'public').map(projected)].filter(record => {
      const [longitude, latitude] = record.location.coordinates;
      return longitude >= bbox[0]! && longitude <= bbox[2]! && latitude >= bbox[1]! && latitude <= bbox[3]! && record.experienced_at >= (url.searchParams.get('start') || '') && record.experienced_at < (url.searchParams.get('end') || '9999');
    })));
  }
  // 首页公开端点：登录守卫（下方 `!session.authenticated`）之前，访客无需登录即可读取
  if (pathname === '/weather/point') return response(demoWeatherPoint());
  if (pathname === '/weather/alerts') return response(demoWeatherAlerts());
  // 热暴露决策看板的读接口在后端同样无鉴权，保持一致
  if (pathname === '/forecast/24h/summary') return response(forecast24hSummaryFixture);
  if (pathname === '/forecast/24h/extreme_regions') return response(extremeRegionsDemo(Number(url.searchParams.get('lead_hour')) || 5));
  if (pathname === '/forecast/24h/decision') return response(decisionSupportDemo());
  if (pathname === '/models/evaluation') return response(modelEvaluationFixture);
  if (pathname === '/forecast/custom_inversion') return response(customInversionDemo(body || {}));
  if (pathname === '/forecast/24h/grid' || pathname === '/forecast/24h/multitemporal') {
    const file = pathname.endsWith('multitemporal')
      ? '/data/heat_perception/forecast_24h_multitemporal_grids.geojson'
      : '/data/heat_perception/forecast_24h_spatial_grids.geojson';
    const res = await fetch(file).catch(() => null);
    if (res && res.ok) {
      const gj = await res.json();
      return response(gj);
    }
    return response({ type: 'FeatureCollection', features: [] });
  }
  if (!session.authenticated) return failure(401, '请先登录');
  if (pathname === '/me/check-ins') return response(page(ownRecords.filter(record => recordOwners.get(record.check_in_id) === session.user?.user_id)));
  if (pathname === '/check-ins' && method === 'POST') {
    const key = `${session.user!.user_id}:${headers.get('Idempotency-Key')}`;
    if (idempotency.has(key)) {
      const previous = idempotency.get(key)!;
      return previous.body === String(init.body) ? response(previous.data, 201) : failure(409, '同一提交键不能对应不同内容');
    }
    const record: CheckIn = { ...body, check_in_id: crypto.randomUUID(), revision: '"1"', alias: session.user!.alias, published_at: new Date().toISOString(), match_status: 'pending', publication_status: body.visibility === 'public' ? 'published' : 'private' };
    ownRecords.unshift(record);
    recordOwners.set(record.check_in_id, session.user!.user_id);
    idempotency.set(key, { body: String(init.body), data: record });
    return response(record, 201);
  }
  if (/^\/check-ins\/[^/]+\/reports$/.test(pathname)) {
    const reportedId = pathname.split('/')[2]!;
    const visible = [...demoRecords, ...ownRecords.filter(record => record.visibility === 'public').map(projected)].some(record => record.check_in_id === reportedId);
    if (!visible) return failure(404, '记录不存在或已不再公开');
    const reason = String(body?.reason || '').trim();
    if (!reason) return failure(422, '请填写举报理由');
    const key = `${session.user!.user_id}:${headers.get('Idempotency-Key')}`;
    const previous = reportKeys.get(key);
    if (previous) return previous.reason === reason ? response(previous.receipt, 201) : failure(409, '同一提交键不能对应不同内容');
    const receipt: ReportReceipt = { report_id: `demo-rep-${crypto.randomUUID()}`, check_in_id: reportedId, status: 'pending', created_at: new Date().toISOString() };
    reportKeys.set(key, { reason, receipt });
    return response(receipt, 201);
  }
  if (pathname.startsWith('/check-ins/')) {
    const id = pathname.split('/')[2];
    const index = ownRecords.findIndex(record => record.check_in_id === id && recordOwners.get(record.check_in_id) === session.user!.user_id);
    if (index === -1) return failure(404, '记录不存在');
    const record = ownRecords[index]!;
    if (headers.get('If-Match') !== record.revision) return failure(412, '修订已变化');
    if (method === 'DELETE') { ownRecords.splice(index, 1); return new Response(null, { status: 204 }); }
    if (method === 'PATCH') { Object.assign(record, body, { revision: `"${Number(record.revision.replaceAll('"', '')) + 1}"`, match_status: 'pending' }); return response(record); }
  }
  if (pathname === '/forecast/quota') {
    return response({
      budget_limit: 5000,
      hard_cutoff_limit: 4800,
      soft_warning_limit: 4000,
      total_used: 126,
      remaining_quota: 4874,
      remaining_safe_quota: 4674,
      usage_percentage: 2.52,
      is_blocked: false,
      is_warning: false,
      last_updated: new Date().toISOString(),
    });
  }
  if (pathname === '/forecast/points') {
    return response({
      total_points: 144,
      points: [
        { id: 'C01', name: '人民广场', district: '黄浦区', type: 'control', lon: 121.475, lat: 31.231, tag: '核心商圈' },
        { id: 'C02', name: '陆家嘴', district: '浦东新区', type: 'control', lon: 121.503, lat: 31.239, tag: '超高层CBD' },
        { id: 'C03', name: '徐家汇', district: '徐汇区', type: 'control', lon: 121.436, lat: 31.196, tag: '中心商业' },
        { id: 'C04', name: '五角场', district: '杨浦区', type: 'control', lon: 121.514, lat: 31.300, tag: '高校科创' },
        { id: 'T01', name: '静安寺', district: '静安区', type: 'test', lon: 121.448, lat: 31.223, tag: '盲测点' },
        { id: 'T02', name: '世博滨江', district: '浦东新区', type: 'test', lon: 121.492, lat: 31.189, tag: '盲测点' },
      ],
    });
  }
  if (pathname === '/forecast/sync') {
    return response({ success: true, date: '2026-09-18', success_points: 144 });
  }
  if (pathname === '/exports') return failure(503, '演示模式不生成服务端导出任务，请使用专题地图导出。');
  return failure(404, '演示未提供此资源');
}

function weatherStress(utci: number): WeatherReading['stress'] {
  if (utci >= 46) return { zh: '极强热应激', en: 'Extreme heat stress', color: '#d73027' };
  if (utci >= 38) return { zh: '很强热应激', en: 'Very strong heat stress', color: '#f46d43' };
  if (utci >= 32) return { zh: '强热应激', en: 'Strong heat stress', color: '#fdae61' };
  if (utci >= 26) return { zh: '中度热应激', en: 'Moderate heat stress', color: '#fee090' };
  if (utci >= 9) return { zh: '无热应激', en: 'No thermal stress', color: '#abd9e9' };
  if (utci >= 0) return { zh: '轻度冷应激', en: 'Slight cold stress', color: '#74add1' };
  if (utci >= -13) return { zh: '中度冷应激', en: 'Moderate cold stress', color: '#4575b4' };
  return { zh: '强/极强冷应激', en: 'Strong/Extreme cold stress', color: '#313695' };
}

function demoWeatherPoint(): WeatherPoint {
  const pad = (n: number) => String(n).padStart(2, '0');
  const start = new Date();
  start.setMinutes(0, 0, 0);
  const hourly: WeatherReading[] = [];
  for (let i = 0; i < 72; i++) {
    const t = new Date(start.getTime() + i * 3600_000);
    const h = t.getHours();
    const day = Math.floor(i / 24);
    const solar = Math.max(0, Math.round(760 * Math.sin((Math.PI * (h - 6)) / 13)));
    const ta = 26.4 + 5.1 * Math.exp(-((h - 14.2) ** 2) / 16) + day * 0.8;
    const rh = Math.max(38, Math.min(88, Math.round(78 - 26 * Math.exp(-((h - 15) ** 2) / 30))));
    const wind = Math.round((2.2 + 0.9 * Math.sin(h / 3.4) + day * 0.2) * 10) / 10;
    const utci = Math.round((ta + 2.6 + (solar / 650) * 3.4 - wind * 0.35) * 10) / 10;
    hourly.push({
      time: `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}T${pad(t.getHours())}:00`,
      air_temperature_c: Math.round(ta * 10) / 10,
      relative_humidity_pct: rh,
      wind_speed_ms: wind,
      shortwave_radiation_wm2: solar,
      tmrt_c: Math.round((ta + (solar / 650) * 7.5) * 10) / 10,
      utci_c: utci,
      utci_shade_c: Math.round((ta + 0.4 - wind * 0.3) * 10) / 10,
      stress: weatherStress(utci),
    });
  }
  const current = hourly[0]!;
  const peak = hourly.slice(0, 48).reduce((best, r) => (r.utci_c > best.utci_c ? r : best));
  return {
    location: { longitude: 121.47, latitude: 31.23, grid_rounded: true },
    timezone: 'Asia/Shanghai',
    utc_offset_seconds: 28800,
    source: { provider: 'Open-Meteo（演示合成）', utci_model: '演示近似公式，不代表真实观测', fetched_at: new Date().toISOString() },
    now_index: 0,
    current,
    hourly,
    peak: { utci_c: peak.utci_c, time: peak.time },
  };
}

function demoWeatherAlerts(): WeatherAlerts {
  const today = new Date();
  const iso = (hour: number, minute = 0) => {
    const t = new Date(today.getFullYear(), today.getMonth(), today.getDate(), hour, minute);
    return `${t.getFullYear()}-${pad2(t.getMonth() + 1)}-${pad2(t.getDate())}T${pad2(t.getHours())}:${pad2(t.getMinutes())}+08:00`;
  };
  const pad2 = (n: number) => String(n).padStart(2, '0');
  return {
    available: true,
    reason_code: null,
    update_time: iso(today.getHours(), Math.max(0, today.getMinutes() - 25)),
    source: 'QWeather（演示合成）',
    fetched_at: new Date().toISOString(),
    alerts: [
      {
        title: '上海中心气象台发布高温橙色预警[II级/较重]',
        type_name: '高温',
        level: '橙色',
        severity_color: '#ff6a4d',
        text: '受副热带高压影响，预计今天中心城区、浦东、闵行等地最高气温将达 37℃ 以上，户外活动请注意防暑降温、及时补水。',
        pub_time: iso(9, 5),
        start_time: iso(10),
        end_time: iso(18),
        status: '预警中',
      },
      {
        title: '上海中心气象台发布雷电黄色预警[III级/较重]',
        type_name: '雷电',
        level: '黄色',
        severity_color: '#ffd21e',
        text: '预计今天午后到傍晚本市大部地区将发生雷电活动，并伴有 1 小时 30-50 毫米的短时强降水和 7-9 级雷雨大风。',
        pub_time: iso(11, 30),
        start_time: iso(12),
        end_time: iso(20),
        status: '预警中',
      },
    ],
  };
}
