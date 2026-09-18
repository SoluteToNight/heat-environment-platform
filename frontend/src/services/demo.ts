import type { CheckIn, CheckInBody, Coordinates, EnvironmentView, Layer, Product, PublicCheckIn, Scene, Session, Variable } from './contracts';
import { publicLocation } from './format';

export const demoScene: Scene = {
  scene_id: 'shanghai-demo', name: '滨江街区', description: '上海 · 概念演示场景', scene_version: 'synthetic-v1',
  bbox: [121.478, 31.225, 121.505, 31.244], timezone: 'Asia/Shanghai',
  initial_camera: { longitude: 121.4895, latitude: 31.2335, heading: 18, pitch: -48, range: 2050 },
  capabilities: { media_upload: false }, attribution: ['概念街区与环境数值均为合成演示，不代表真实观测'],
};
const anchor = new Date();
anchor.setUTCMinutes(0, 0, 0);
const times = Array.from({ length: 25 }, (_, index) => new Date(anchor.getTime() + (index - 8) * 3600_000).toISOString());
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
  const hour = (new Date(time).getUTCHours() + 8) % 24;
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
  await new Promise<void>((resolve, reject) => {
    const signal = init.signal;
    const onAbort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
    const timer = setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve(); }, 140);
    if (signal?.aborted) return onAbort();
    signal?.addEventListener('abort', onAbort, { once: true });
  });
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
    const resolved = times.reduce((best, current) => Math.abs(Date.parse(current) - Date.parse(requested)) < Math.abs(Date.parse(best) - Date.parse(requested)) ? current : best);
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
  if (pathname.startsWith('/check-ins/')) {
    const id = pathname.split('/')[2];
    const index = ownRecords.findIndex(record => record.check_in_id === id && recordOwners.get(record.check_in_id) === session.user!.user_id);
    if (index === -1) return failure(404, '记录不存在');
    const record = ownRecords[index]!;
    if (headers.get('If-Match') !== record.revision) return failure(412, '修订已变化');
    if (method === 'DELETE') { ownRecords.splice(index, 1); return new Response(null, { status: 204 }); }
    if (method === 'PATCH') { Object.assign(record, body, { revision: `"${Number(record.revision.replaceAll('"', '')) + 1}"`, match_status: 'pending' }); return response(record); }
  }
  if (pathname === '/exports') return failure(503, '演示模式不生成服务端导出任务，请使用专题地图导出。');
  return failure(404, '演示未提供此资源');
}
