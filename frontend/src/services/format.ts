import type { CheckInBody, Coordinates, Mode, ViewItem } from './contracts';
import proj4 from 'proj4';

export const modeNames: Record<Mode, string> = { current_estimate: '当前估计', forecast: '未来预报', historical: '历史回看' };
export const sensationNames = { cold: '冷', cool: '凉', neutral: '中性', warm: '偏热', hot: '很热' };
export const matchNames = { pending: '环境待匹配', matched: '环境已匹配', unmatched: '暂无对应环境', failed: '环境匹配待重试' };
export function localTime(time: string | null | undefined, date = false) {
  if (!time) return '暂无有效时间';
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: date ? '2-digit' : undefined, day: date ? '2-digit' : undefined, hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(time));
}
export function effectiveTime(item?: ViewItem) {
  if (!item) return '尚未加载';
  if (item.temporal_support === 'unknown') return `${localTime(item.resolved_time, true)} · 时间统计口径待核验`;
  return item.temporal_support === 'interval_mean' ? `${localTime(item.interval_start, true)}–${localTime(item.interval_end, true)} 平均` : localTime(item.resolved_time, true);
}
export function datetimeLocal(time = new Date().toISOString()) {
  return new Date(new Date(time).getTime() + 8 * 3600_000).toISOString().slice(0, 16);
}
export function reasonText(reason?: string | null) {
  if (reason === 'outside_support_or_missing') return '超出插值支持范围或输入缺测';
  if (reason === 'outside_time_range') return '超出发布时段，请选择时间轴上的有效时刻';
  const reasons: Record<string, string> = { outside_coverage: '该位置无覆盖', no_data: '该时刻暂无数据', missing_radiation_components: '缺少直射、散射辐射输入', terrain_missing: '暂无地形数据', unsupported: '当前产品暂不支持', missing: '数据暂未发布' };
  return reasons[reason || ''] || '暂时无法提供此数据';
}
export function publicGrid(coordinates: Coordinates) {
  const utm = '+proj=utm +zone=51 +datum=WGS84 +units=m +no_defs';
  const [east, north] = proj4('EPSG:4326', utm, coordinates);
  const west = Math.floor(east / 200) * 200;
  const south = Math.floor(north / 200) * 200;
  const center = proj4(utm, 'EPSG:4326', [west + 100, south + 100]) as Coordinates;
  const corners = [[west, south], [west + 200, south], [west + 200, south + 200], [west, south + 200]].map(point => proj4(utm, 'EPSG:4326', point) as Coordinates);
  return { center, corners };
}
export function publicLocation(body: CheckInBody): Coordinates {
  return body.public_location_precision === 'grid_200m' ? publicGrid(body.location.coordinates).center : body.location.coordinates;
}
