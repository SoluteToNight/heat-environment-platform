/**
 * heatRisk.ts — 热暴露风险图层的数据契约、风险分级与配色纯函数
 *
 * 数据来源（后端已发布产品，前端只做展示与组织）：
 * - /forecast/24h/multitemporal：M0/M1 主观偏热概率回归模型 4 时相（09/14/18/22 时）× 497 个 1km 网格反演；
 * - /forecast/24h/grid：同网格的行政区、下垫面构成与机制分区属性（用于 join 与详情解读）；
 * - /forecast/24h/extreme_regions：主观热感知极值热点 Top10（峰值时相）。
 *
 * 综合风险分级规则与后端 heat_perception_service.evaluate_risk_level 保持一致：
 * 极高：UTCI≥38°C 或 P(hot)≥0.70；高：≥32 或 ≥0.50；中：≥26 或 ≥0.30；其余为低。
 */

export type RiskLevel = 'low' | 'moderate' | 'high' | 'extreme';
export type HeatRiskStyle = 'level' | 'probability' | 'mitigation';

export interface HeatRiskPhaseValue {
  hour: number;
  phase: string;
  target_time: string;
  utci_c: number;
  p_base: number;
  p_enhanced: number;
  delta_p: number;
  rel_mitigation_pct: number;
  risk_level: RiskLevel;
}

export interface HeatRiskGrid {
  grid_id: string;
  district_name: string;
  quadrant: string;
  green_fraction: number | null;
  water_fraction: number | null;
  building_fraction: number | null;
  /** Polygon 外环坐标 [lon, lat][]（两份 GeoJSON 中同网格几何一致） */
  ring: number[][];
  phases: Partial<Record<number, HeatRiskPhaseValue>>;
}

export interface HeatRiskHotspot {
  rank: number;
  grid_id: string;
  name: string;
  lon: number;
  lat: number;
  utci_c: number | null;
  p_enhanced: number | null;
}

export interface HeatRiskDataset {
  grids: HeatRiskGrid[];
  hotspots: HeatRiskHotspot[];
  /** 峰值时相的预报目标时间（用于说明热点适用时段） */
  peak_target_time: string | null;
}

export interface HeatRiskPresentation {
  enabled: boolean;
  phase: number;
  style: HeatRiskStyle;
}

type GeoJsonFeature = { properties: Record<string, unknown>; geometry: { type: string; coordinates: number[][][] } };

/** 反演时相元数据（与 forecast_24h_multitemporal_grids.geojson 的 hour/phase 对应） */
export const HEAT_RISK_PHASES = [
  { hour: 9, key: 'morning_09h', label: '09 时', tag: '清晨' },
  { hour: 14, key: 'peak_14h', label: '14 时', tag: '午后峰值' },
  { hour: 18, key: 'evening_18h', label: '18 时', tag: '傍晚' },
  { hour: 22, key: 'night_22h', label: '22 时', tag: '夜间' },
] as const;

export const HEAT_RISK_DEFAULT_PHASE = 14;

export const RISK_STYLE_META: Array<{ id: HeatRiskStyle; label: string; hint: string }> = [
  { id: 'level', label: '风险等级', hint: '客观 UTCI 与主观偏热概率联合分级' },
  { id: 'probability', label: '偏热概率', hint: 'M1 回归模型输出的主观“感觉偏热”概率 P(hot)' },
  { id: 'mitigation', label: '环境缓解', hint: '下垫面使偏热概率相对纯气象基准的变化 ΔP' },
];

export interface RiskLevelMeta { label: string; color: string; action: string; threshold: string }

export const RISK_LEVELS: Record<RiskLevel, RiskLevelMeta> = {
  low: { label: '低风险', color: '#4e9e7f', action: '适宜正常户外活动', threshold: 'UTCI < 26°C 且 P(hot) < 30%' },
  moderate: { label: '中风险', color: '#e5c05b', action: '注意补水与遮阳', threshold: 'UTCI ≥ 26°C 或 P(hot) ≥ 30%' },
  high: { label: '高风险', color: '#df8a4b', action: '减少午间暴晒', threshold: 'UTCI ≥ 32°C 或 P(hot) ≥ 50%' },
  extreme: { label: '极高风险', color: '#cd4a4a', action: '避免长时间外出', threshold: 'UTCI ≥ 38°C 或 P(hot) ≥ 70%' },
};

export const RISK_LEVEL_ORDER: RiskLevel[] = ['low', 'moderate', 'high', 'extreme'];

/** 与后端 evaluate_risk_level 一致的联合分级（utci 单位 °C，p 为 0–1） */
export function combineRiskLevel(utci: number, pHot: number): RiskLevel {
  if (utci >= 38.0 || pHot >= 0.70) return 'extreme';
  if (utci >= 32.0 || pHot >= 0.50) return 'high';
  if (utci >= 26.0 || pHot >= 0.30) return 'moderate';
  return 'low';
}

/* ------------------------------- 配色 ------------------------------- */

type Rgb = [number, number, number];

function hexToRgb(hex: string): Rgb {
  const value = hex.replace('#', '');
  const full = value.length === 3 ? value.split('').map(ch => ch + ch).join('') : value;
  return [parseInt(full.slice(0, 2), 16), parseInt(full.slice(2, 4), 16), parseInt(full.slice(4, 6), 16)];
}

export function mixHex(a: string, b: string, t: number): string {
  const ca = hexToRgb(a);
  const cb = hexToRgb(b);
  const clamped = Math.min(1, Math.max(0, t));
  const mixed = ca.map((channel, index) => Math.round(channel + (cb[index]! - channel) * clamped));
  return `#${mixed.map(channel => channel!.toString(16).padStart(2, '0')).join('')}`;
}

type RampStop = [number, string];

function colorAtRamp(stops: RampStop[], t: number): string {
  const value = Math.min(1, Math.max(0, t));
  const next = stops.findIndex(([position]) => position >= value);
  if (next <= 0) return stops[next === 0 ? 0 : stops.length - 1]![1];
  const [lowPos, lowColor] = stops[next - 1]!;
  const [highPos, highColor] = stops[next]!;
  const span = highPos - lowPos || 1;
  return mixHex(lowColor, highColor, (value - lowPos) / span);
}

/** M1 主观偏热概率 P(hot)：0（凉爽舒适）→ 1（普遍偏热）的连续色带 */
const PROBABILITY_RAMP: RampStop[] = [
  [0.00, '#3f8f7c'],
  [0.25, '#94bd6f'],
  [0.45, '#e3c567'],
  [0.65, '#df8a4b'],
  [0.80, '#cd4a4a'],
  [1.00, '#7c1f2d'],
];

export function probabilityColor(p: number): string {
  return colorAtRamp(PROBABILITY_RAMP, p);
}

/** 环境缓解 ΔP（百分点）混合渲染域：负值=绿地水体降温收益，正值=下垫面反而加剧 */
export const MITIGATION_DOMAIN: [number, number] = [-0.30, 0.15];
/** |ΔP| 达到该幅度（12 个百分点）即饱和显示 */
export const MITIGATION_FULL_SIGNAL = 0.12;
const MITIGATION_MAX_ALPHA = 0.85;

/**
 * ΔP 异常叠置编码（与环境色带混合渲染专用）：
 * ΔP≈0 完全透明露出客观底色；负值染蓝（降温收益）、正值染紫红（偏热加剧），
 * 不透明度随 |ΔP| 线性增长——底色始终可读，缓解信号只在有信号的地方浮现。
 */
export function mitigationRgba(deltaP: number): [number, number, number, number] {
  const [low, high] = MITIGATION_DOMAIN;
  const clamped = Math.min(high, Math.max(low, deltaP));
  if (clamped === 0) return [217, 212, 200, 0];
  const strength = Math.min(1, Math.abs(clamped) / MITIGATION_FULL_SIGNAL);
  const alpha = strength * MITIGATION_MAX_ALPHA;
  return clamped < 0 ? [29, 78, 216, alpha] : [190, 24, 93, alpha];
}

export function riskColor(level: RiskLevel): string {
  return RISK_LEVELS[level]?.color || '#b8beba';
}

/** 网格缺测时的中性色（数据缺失 ≠ 0，不着风险色） */
export const HEAT_RISK_NODATA_COLOR = '#c9cfcc';

/**
 * 各着色模式的网格不透明度：
 * 风险等级/偏热概率承载与 UTCI 同源的信息，与环境色带互斥显示，用较高不透明度保证色块纯净；
 * 环境缓解（ΔP）采用异常叠置混合渲染，信号强弱由色斑图自身的透明度表达，图层整体不透明。
 */
export const HEAT_RISK_STYLE_ALPHA: Record<HeatRiskStyle, number> = {
  level: 0.78,
  probability: 0.78,
  mitigation: 1,
};

export function legendGradientCss(kind: Extract<HeatRiskStyle, 'probability' | 'mitigation'>): string {
  if (kind === 'mitigation') {
    return 'linear-gradient(to right, rgba(29, 78, 216, 0.85), rgba(217, 212, 200, 0.05) 50%, rgba(190, 24, 93, 0.85))';
  }
  return `linear-gradient(to right, ${PROBABILITY_RAMP.map(([position, color]) => `${color} ${Math.round(position * 100)}%`).join(', ')})`;
}

export const MITIGATION_LEGEND_TICKS = [
  { value: MITIGATION_DOMAIN[0], label: '-30pp' },
  { value: 0, label: '0' },
  { value: MITIGATION_DOMAIN[1], label: '+15pp' },
];

/* --------------------------- 数据集组装 --------------------------- */

function toNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function phaseValue(hour: number, props: Record<string, unknown>): HeatRiskPhaseValue {
  const level = typeof props.risk_level === 'string' ? props.risk_level : undefined;
  return {
    hour,
    phase: typeof props.phase === 'string' ? props.phase : `${hour}h`,
    target_time: typeof props.target_time === 'string' ? props.target_time : '',
    utci_c: toNumber(props.utci_c) ?? NaN,
    p_base: toNumber(props.p_base) ?? NaN,
    p_enhanced: toNumber(props.p_enhanced) ?? NaN,
    delta_p: toNumber(props.delta_p) ?? NaN,
    rel_mitigation_pct: toNumber(props.rel_mitigation_pct) ?? 0,
    risk_level: (RISK_LEVEL_ORDER as string[]).includes(level || '') ? level as RiskLevel : 'moderate',
  };
}

/**
 * 组装热暴露风险数据集：
 * multitemporal 提供 4 时相模型反演值与几何；spatial 提供行政区/下垫面/机制分区（按 grid_id join）；
 * extreme 提供峰值时相 Top10 极值热点（demo 与后端字段名不同，此处做兼容取值）。
 */
export function buildHeatRiskDataset(
  multitemporal: { features?: GeoJsonFeature[] } | null | undefined,
  spatial: { features?: GeoJsonFeature[] } | null | undefined,
  extremeHotspots: Array<Record<string, unknown>> | null | undefined,
): HeatRiskDataset {
  const spatialById = new Map<string, Record<string, unknown>>();
  for (const feature of spatial?.features || []) {
    const id = String(feature.properties?.grid_id ?? '');
    if (id) spatialById.set(id, feature.properties || {});
  }

  const grids = new Map<string, HeatRiskGrid>();
  let peakTargetTime: string | null = null;
  for (const feature of multitemporal?.features || []) {
    const props = feature.properties || {};
    const id = String(props.grid_id ?? '');
    const hour = toNumber(props.hour);
    if (!id || hour == null || feature.geometry?.type !== 'Polygon') continue;
    let grid = grids.get(id);
    if (!grid) {
      const extra = spatialById.get(id) || {};
      grid = {
        grid_id: id,
        district_name: typeof extra.district_name === 'string' ? extra.district_name : '',
        quadrant: typeof extra.quadrant === 'string' ? extra.quadrant : '',
        green_fraction: toNumber(extra.green_fraction),
        water_fraction: toNumber(extra.water_fraction),
        building_fraction: toNumber(extra.building_fraction),
        ring: feature.geometry.coordinates[0] || [],
        phases: {},
      };
      grids.set(id, grid);
    }
    grid.phases[hour] = phaseValue(hour, props);
    if (hour === HEAT_RISK_DEFAULT_PHASE) peakTargetTime = grid.phases[hour]!.target_time || null;
  }

  const hotspots: HeatRiskHotspot[] = (extremeHotspots || []).map((raw, index) => ({
    rank: toNumber(raw.rank) ?? index + 1,
    grid_id: String(raw.grid_id ?? ''),
    name: (raw.district_name as string) || (raw.district as string) || '未知行政区',
    lon: toNumber(raw.lon) ?? toNumber(raw.longitude) ?? NaN,
    lat: toNumber(raw.lat) ?? toNumber(raw.latitude) ?? NaN,
    utci_c: toNumber(raw.utci_c) ?? toNumber(raw.utci_spatial_c),
    p_enhanced: toNumber(raw.p_enhanced) ?? toNumber(raw.p_hot_spatial),
  })).filter(item => Number.isFinite(item.lon) && Number.isFinite(item.lat));

  return { grids: [...grids.values()], hotspots, peak_target_time: peakTargetTime };
}

export function phaseMeta(hour: number) {
  return HEAT_RISK_PHASES.find(item => item.hour === hour) || HEAT_RISK_PHASES[1]!;
}

/* ------------------------- 网格晶格与坐标反解 ------------------------- */

export interface HeatRiskLattice {
  minRow: number; maxRow: number; minCol: number; maxCol: number;
  /** lon = lonA + lonB × col（col 为 grid_id 中的列号） */
  lonA: number; lonB: number;
  /** lat = latA + latB × row（row 随纬度递减） */
  latA: number; latB: number;
  cells: Map<string, HeatRiskGrid>;
}

const GRID_ID_PATTERN = /^r(-?\d+)_c(-?\d+)$/;

function ringCenter(ring: number[][]): [number, number] | null {
  if (!ring || ring.length < 3) return null;
  let lon = 0;
  let lat = 0;
  for (const point of ring) {
    lon += point[0]!;
    lat += point[1]!;
  }
  return [lon / ring.length, lat / ring.length];
}

/** 将 497 个规则网格组织成 (row, col) 晶格，并线性拟合行列→经纬度映射，供平滑渲染与点击反解共用 */
export function createHeatRiskLattice(dataset: HeatRiskDataset): HeatRiskLattice | null {
  const cells = new Map<string, HeatRiskGrid>();
  let minRow = Infinity;
  let maxRow = -Infinity;
  let minCol = Infinity;
  let maxCol = -Infinity;
  let west: { col: number; lon: number } | null = null;
  let east: { col: number; lon: number } | null = null;
  let north: { row: number; lat: number } | null = null;
  let south: { row: number; lat: number } | null = null;
  for (const grid of dataset.grids) {
    const match = GRID_ID_PATTERN.exec(grid.grid_id);
    const center = ringCenter(grid.ring);
    if (!match || !center) continue;
    const row = Number(match[1]);
    const col = Number(match[2]);
    cells.set(`${row}_${col}`, grid);
    minRow = Math.min(minRow, row);
    maxRow = Math.max(maxRow, row);
    minCol = Math.min(minCol, col);
    maxCol = Math.max(maxCol, col);
    if (!west || col < west.col) west = { col, lon: center[0] };
    if (!east || col > east.col) east = { col, lon: center[0] };
    if (!north || row < north.row) north = { row, lat: center[1] };
    if (!south || row > south.row) south = { row, lat: center[1] };
  }
  if (!cells.size || !west || !east || !north || !south) return null;
  const lonB = east.col > west.col ? (east.lon - west.lon) / (east.col - west.col) : 0.01;
  const latB = south.row > north.row ? (south.lat - north.lat) / (south.row - north.row) : -0.01;
  return {
    minRow, maxRow, minCol, maxCol,
    lonA: west.lon - lonB * west.col,
    lonB,
    latA: north.lat - latB * north.row,
    latB,
    cells,
  };
}

/** 经纬度 → 所在网格（用于点击查询；无数据覆盖返回 null） */
export function resolveHeatRiskCell(lattice: HeatRiskLattice, lon: number, lat: number): HeatRiskGrid | null {
  const col = Math.round((lon - lattice.lonA) / lattice.lonB);
  const row = Math.round((lat - lattice.latA) / lattice.latB);
  if (row < lattice.minRow || row > lattice.maxRow || col < lattice.minCol || col > lattice.maxCol) return null;
  return lattice.cells.get(`${row}_${col}`) || null;
}

/* --------------------------- 展示文案 --------------------------- */

const percent = (value: number | null, digits = 1) => value == null || !Number.isFinite(value) ? '缺测' : `${(value * 100).toFixed(digits)}%`;

export function riskLevelLabel(level: RiskLevel): string {
  return RISK_LEVELS[level]?.label || '未知';
}

/** 网格点击详情的中文键值对（下划线前缀为展示专用字段，详情面板会过滤） */
export function formatGridProperties(grid: HeatRiskGrid, hour: number): Record<string, unknown> {
  const value = grid.phases[hour];
  const meta = phaseMeta(hour);
  const level: RiskLevel = value?.risk_level || 'moderate';
  const props: Record<string, unknown> = {
    layer_id: 'heat_risk',
    行政区: grid.district_name || '未标注',
    综合风险等级: riskLevelLabel(level),
    '客观 UTCI': value ? `${value.utci_c.toFixed(1)} °C` : '缺测',
    '主观偏热概率 P(hot)': value ? percent(value.p_enhanced) : '缺测',
    '纯气象基准概率 P₀（M0）': value ? percent(value.p_base) : '缺测',
    '环境缓解量 ΔP': value ? `${value.delta_p >= 0 ? '+' : ''}${(value.delta_p * 100).toFixed(1)} 个百分点` : '缺测',
    相对缓解幅度: value ? `${value.rel_mitigation_pct.toFixed(1)} %` : '缺测',
    绿地覆盖率: percent(grid.green_fraction),
    水体覆盖率: percent(grid.water_fraction),
    建筑覆盖率: percent(grid.building_fraction),
    机制分区: grid.quadrant || '未标注',
    反演时相: value?.target_time ? `${meta.label}（${value.target_time.replace('+08:00', '北京时')}）` : meta.label,
    网格编号: grid.grid_id,
    _accent_color: RISK_LEVELS[level].color,
    _summary: gridSummary(grid, value, level),
  };
  return props;
}

function gridSummary(grid: HeatRiskGrid, value: HeatRiskPhaseValue | undefined, level: RiskLevel): string {
  if (!value) return '该网格在当前时相缺测，不着风险色。';
  const deltaText = value.delta_p <= -0.005
    ? `绿地与水体使偏热概率较纯气象基准降低 ${(Math.abs(value.delta_p) * 100).toFixed(1)} 个百分点`
    : value.delta_p >= 0.005
      ? `局地下垫面使偏热概率较纯气象基准升高 ${(value.delta_p * 100).toFixed(1)} 个百分点`
      : '下垫面对偏热概率无明显调节作用';
  const district = grid.district_name ? `${grid.district_name}的` : '';
  return `该${district}1km 网格客观 UTCI ${value.utci_c.toFixed(1)}°C、主观偏热概率 ${(value.p_enhanced * 100).toFixed(0)}%，综合评级「${riskLevelLabel(level)}」；${deltaText}。`;
}

/** 图层实体名（拾取详情标题） */
export function gridEntityName(grid: HeatRiskGrid): string {
  return `热暴露风险网格 · ${grid.district_name || grid.grid_id}`;
}
