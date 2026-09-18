import type { Catalog, CheckIn, CheckInBody, Coordinates, EnvironmentView, ExportResult, FeatureDetail, ForecastGridResult, ForecastPoint, ForecastQuota, Layer, Page, Place, PointResult, PublicCheckIn, Scene, SeriesResult, Session, Status, TimeSelection, Variable } from './contracts';
import { normalizeBackendResponse } from './backend-adapter';

export const isDemo = (new URLSearchParams(location.search).get('mode') || import.meta.env.VITE_DATA_MODE || 'demo') === 'demo';
const base = (import.meta.env.VITE_API_BASE || '/api/v1').replace(/\/$/, '');
let csrfToken = '';
const etags = new Map<string, { etag: string; data: unknown }>();
export class ApiError extends Error {
  constructor(public status: number, message: string, public code = '', public retryAfter: number | null = null) { super(message); }
}
export function errorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return '登录已失效，草稿已保留，请重新登录。';
    if (error.status === 412) return '记录已在其他窗口更新。本地修改已保留，请重新加载后比较。';
    if (error.status === 410) return '当前视图已到期，正在重新准备数据。';
    if (error.status === 429) return `操作较频繁，请${error.retryAfter ? `在 ${error.retryAfter} 秒后` : '稍后'}重试。`;
    return error.message;
  }
  return error instanceof Error ? error.message : '暂时无法完成，请稍后重试。';
}
export function aborted(error: unknown) { return error instanceof DOMException && error.name === 'AbortError'; }
export async function request<T>(path: string, options: RequestInit = {}, conditional = false): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  if (csrfToken && options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrfToken);
  if (conditional && etags.has(path)) headers.set('If-None-Match', etags.get(path)!.etag);
  const timeout = AbortSignal.timeout(20000);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  const init = { ...options, headers, signal, credentials: 'same-origin' as const, cache: 'no-store' as const };
  let response: Response;
  try {
    response = isDemo ? await (await import('./demo')).demoFetch(path, init) : await fetch(base + path, init);
  } catch (error) {
    if (aborted(error)) throw error;
    throw new Error('服务暂不可达，请检查连接后重试。');
  }
  if (response.status === 304) return etags.get(path)!.data as T;
  if (response.status === 204) return undefined as T;
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const retry = response.headers.get('Retry-After');
    const seconds = retry ? (Number.isFinite(Number(retry)) ? Number(retry) : Math.max(0, Math.ceil((Date.parse(retry) - Date.now()) / 1000))) : null;
    throw new ApiError(response.status, payload?.error?.message || '服务暂不可用', payload?.error?.code, seconds);
  }
  if (!payload || !('data' in payload)) throw new Error('接口响应格式不符合约定，请联系服务维护者。');
  if (path.startsWith('/auth/') && payload.data?.csrf_token) csrfToken = payload.data.csrf_token;
  const data = isDemo ? payload.data : normalizeBackendResponse(path, payload.data, base);
  if (conditional && response.headers.get('ETag')) etags.set(path, { etag: response.headers.get('ETag')!, data });
  return data as T;
}
const query = (params: Record<string, string | number | undefined>) => new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined).map(([key, value]) => [key, String(value)])).toString();
const scenePath = (id: string) => `/scenes/${encodeURIComponent(id)}`;
const viewPath = (id: string) => `/environment/views/${encodeURIComponent(id)}`;
const write = (method: string, body?: unknown, headers?: HeadersInit): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body), headers });
export const api = {
  scenes: () => request<Page<Scene>>('/scenes'),
  scene: (id: string, signal?: AbortSignal) => request<Scene>(scenePath(id), { signal }),
  layers: (id: string, signal?: AbortSignal) => request<Page<Layer>>(`${scenePath(id)}/layers`, { signal }),
  catalog: (id: string, signal?: AbortSignal) => request<Catalog>(`${scenePath(id)}/environment/catalog`, { signal }, true),
  status: (id: string) => request<Status>(`${scenePath(id)}/status`, {}, true),
  places: (id: string, text: string, signal?: AbortSignal) => request<Page<Place>>(`${scenePath(id)}/places?${query({ q: text, limit: 20 })}`, { signal }),
  feature: (scene: string, id: string, layer: string, version: string) => request<FeatureDetail>(`${scenePath(scene)}/features/${encodeURIComponent(id)}?${query({ layer_id: layer, layer_version: version })}`),
  view: (scene: string, variables: Variable[], time: TimeSelection, signal?: AbortSignal) => request<EnvironmentView>(`${scenePath(scene)}/environment/views`, { ...write('POST', { variables, time_selection: time, release_selection: { mode: 'latest' } }), signal }),
  point: (view: string, coordinates: Coordinates, signal?: AbortSignal) => request<PointResult>(`${viewPath(view)}/point?${query({ longitude: coordinates[0], latitude: coordinates[1] })}`, { signal }),
  series: (view: string, coordinates: Coordinates, variable: Variable, start: string, end: string, signal?: AbortSignal) => view.startsWith('sp_')
    ? request<SeriesResult>(`/spatial/views/${encodeURIComponent(view)}/series?${query({ longitude: coordinates[0], latitude: coordinates[1], variable })}`, { signal })
    : request<SeriesResult>(`${viewPath(view)}/series?${query(isDemo ? { longitude: coordinates[0], latitude: coordinates[1], variable, start, end } : { longitude: coordinates[0], latitude: coordinates[1], variables: variable, start_time: start, end_time: end })}`, { signal }),
  spatialExportUrl: (view: string, coordinates: Coordinates, variable: Variable) => `${base}/spatial/views/${encodeURIComponent(view)}/export.csv?${query({ longitude: coordinates[0], latitude: coordinates[1], variable })}`,
  publicRecords: (params: Record<string, string | number>, signal?: AbortSignal) => {
    const { start, end, ...rest } = params;
    return request<Page<PublicCheckIn>>(`/check-ins?${query(isDemo ? params : { ...rest, start_time: start, end_time: end })}`, { signal });
  },
  aggregates: (params: Record<string, string | number>, signal?: AbortSignal) => request<Page<{ location: { coordinates: Coordinates }; count: number }>>(`/check-ins/aggregates?${query(params)}`, { signal }),
  myRecords: (cursor?: string) => request<Page<CheckIn>>(`/me/check-ins?${query({ cursor, limit: 50 })}`),
  create: (body: CheckInBody, key: string) => request<CheckIn>('/check-ins', write('POST', body, { 'Idempotency-Key': key })),
  edit: (id: string, body: CheckInBody, revision: string) => request<CheckIn>(`/check-ins/${encodeURIComponent(id)}`, write('PATCH', body, { 'If-Match': revision })),
  remove: (id: string, revision: string) => request<void>(`/check-ins/${encodeURIComponent(id)}`, write('DELETE', undefined, { 'If-Match': revision })),
  session: () => request<Session>('/auth/session'),
  login: (username: string, password: string) => request<Session>('/auth/login', write('POST', { username, password })),
  logout: async () => { await request<void>('/auth/logout', write('POST')); csrfToken = ''; },
  export: (body: unknown, key: string) => request<ExportResult>('/exports', write('POST', body, { 'Idempotency-Key': key })),
  exportStatus: (id: string) => request<ExportResult>(`/exports/${encodeURIComponent(id)}`),
  downloadUrl: (id: string) => `${base}/exports/${encodeURIComponent(id)}/download`,
  forecastQuota: () => request<ForecastQuota>('/forecast/quota'),
  forecastPoints: () => request<{ total_points: number; points: ForecastPoint[] }>('/forecast/points'),
  forecastGrid: (hour = 0, variable = 'temperature_2m', smooth = 0.08) => request<ForecastGridResult>(`/forecast/grid?${query({ hour, variable, smooth })}`),
  forecastAudit: (hour = 0, variable = 'temperature_2m') => request<{ audit_metrics: ForecastGridResult['audit_metrics']; control_points_summary: ForecastGridResult['control_points_summary'] }>(`/forecast/audit?${query({ hour, variable })}`),
  forecastSync: (force = false) => request<{ success: boolean; date: string; success_points: number }>('/forecast/sync?' + query({ force: String(force) }), write('POST')),
};
