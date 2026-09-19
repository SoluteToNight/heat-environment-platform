import { describe, expect, it } from 'vitest';
import {
  buildHeatRiskDataset,
  combineRiskLevel,
  createHeatRiskLattice,
  formatGridProperties,
  gridEntityName,
  HEAT_RISK_DEFAULT_PHASE,
  HEAT_RISK_STYLE_ALPHA,
  legendGradientCss,
  mitigationRgba,
  phaseMeta,
  probabilityColor,
  resolveHeatRiskCell,
  riskColor,
  RISK_LEVELS,
  RISK_LEVEL_ORDER,
  RISK_STYLE_META,
} from '../services/heatRisk';
import type { HeatRiskGrid } from '../services/heatRisk';

const RING = [[[121.2, 31.2], [121.21, 31.2], [121.21, 31.21], [121.2, 31.21], [121.2, 31.2]]];

function multiFeature(id: string, hour: number, overrides: Record<string, unknown> = {}) {
  return {
    properties: {
      grid_id: id,
      phase: `${hour}h`,
      target_time: `2026-09-18 ${String(hour).padStart(2, '0')}:00:00+08:00`,
      hour,
      utci_c: 35.2,
      p_base: 0.6,
      p_enhanced: 0.543,
      delta_p: -0.074,
      rel_mitigation_pct: 12.0,
      risk_level: 'high',
      ...overrides,
    },
    geometry: { type: 'Polygon', coordinates: RING },
  };
}

function spatialFeature(id: string, overrides: Record<string, unknown> = {}) {
  return {
    properties: {
      grid_id: id,
      district_name: '徐汇区',
      green_fraction: 0.19,
      water_fraction: 0.05,
      building_fraction: 0.31,
      quadrant: 'Q1_双高热点区',
      ...overrides,
    },
    geometry: { type: 'Polygon', coordinates: RING },
  };
}

describe('heat exposure risk grading (mirrors backend evaluate_risk_level)', () => {
  it('should grade by the stricter of UTCI and P(hot)', () => {
    expect(combineRiskLevel(39.0, 0.1)).toBe('extreme');
    expect(combineRiskLevel(30.0, 0.85)).toBe('extreme');
    expect(combineRiskLevel(38.0, 0.69)).toBe('extreme');
    expect(combineRiskLevel(33.0, 0.55)).toBe('high');
    expect(combineRiskLevel(26.0, 0.31)).toBe('moderate');
    expect(combineRiskLevel(20.0, 0.1)).toBe('low');
  });

  it('should expose ordered levels with colors, labels and thresholds', () => {
    expect(RISK_LEVEL_ORDER).toEqual(['low', 'moderate', 'high', 'extreme']);
    for (const level of RISK_LEVEL_ORDER) {
      expect(RISK_LEVELS[level].color).toMatch(/^#[0-9a-f]{6}$/);
      expect(RISK_LEVELS[level].label).toBeTruthy();
      expect(RISK_LEVELS[level].threshold).toBeTruthy();
      expect(riskColor(level)).toBe(RISK_LEVELS[level].color);
    }
  });
});

describe('risk color ramps', () => {
  it('should map P(hot) endpoints from teal-green to deep maroon and stay inside ramp', () => {
    expect(probabilityColor(0)).toBe('#3f8f7c');
    expect(probabilityColor(1)).toBe('#7c1f2d');
    const red = (hex: string) => parseInt(hex.slice(1, 3), 16);
    expect(red(probabilityColor(0.9))).toBeGreaterThan(red(probabilityColor(0.2)));
    expect(probabilityColor(-1)).toBe(probabilityColor(0));
    expect(probabilityColor(2)).toBe(probabilityColor(1));
  });

  it('should encode ΔP as an anomaly overlay: transparent at zero, blue cooling, magenta worsening', () => {
    expect(mitigationRgba(0)[3]).toBe(0);
    const [coolR, coolG, coolB, coolA] = mitigationRgba(-0.30);
    expect([coolR, coolG, coolB]).toEqual([29, 78, 216]);
    expect(coolA).toBeCloseTo(0.85);
    const [warmR, warmG, warmB, warmA] = mitigationRgba(0.15);
    expect([warmR, warmG, warmB]).toEqual([190, 24, 93]);
    expect(warmA).toBeCloseTo(0.85);
    expect(mitigationRgba(-5)).toEqual(mitigationRgba(-0.30));
    expect(mitigationRgba(5)).toEqual(mitigationRgba(0.15));
    expect(mitigationRgba(-0.08)[3]).toBeGreaterThan(mitigationRgba(-0.02)[3]);
    expect(mitigationRgba(-0.08)[3]).toBeLessThan(mitigationRgba(-0.30)[3]);
  });

  it('should build legend gradients for continuous modes', () => {
    expect(legendGradientCss('probability')).toContain('linear-gradient(to right, #3f8f7c 0%');
    expect(legendGradientCss('mitigation')).toContain('rgba(29, 78, 216, 0.85)');
    expect(legendGradientCss('mitigation')).toContain('rgba(190, 24, 93, 0.85)');
  });

  it('should encode mitigation signal inside the raster and keep exclusive modes semi-opaque', () => {
    // 缓解模式透明度由色斑图像素携带（ΔP≈0 全透明），图层整体不透明；
    // 风险等级/偏热概率为互斥地毯，靠图层不透明度控制
    expect(HEAT_RISK_STYLE_ALPHA.mitigation).toBe(1);
    expect(HEAT_RISK_STYLE_ALPHA.probability).toBe(HEAT_RISK_STYLE_ALPHA.level);
    expect(HEAT_RISK_STYLE_ALPHA.probability).toBeLessThan(1);
  });
});

describe('buildHeatRiskDataset', () => {
  const multitemporal = {
    features: [
      multiFeature('g1', 9, { risk_level: 'high', p_enhanced: 0.61 }),
      multiFeature('g1', 14, { risk_level: 'extreme', p_enhanced: 0.82, utci_c: 38.9 }),
      multiFeature('g1', 18, { risk_level: 'low', p_enhanced: 0.08 }),
      multiFeature('g1', 22, { risk_level: 'low', p_enhanced: 0.05 }),
    ],
  };
  const spatial = { features: [spatialFeature('g1')] };

  it('should merge four phases per grid and join district attributes', () => {
    const dataset = buildHeatRiskDataset(multitemporal, spatial, []);
    expect(dataset.grids).toHaveLength(1);
    const grid = dataset.grids[0]!;
    expect(grid.grid_id).toBe('g1');
    expect(grid.district_name).toBe('徐汇区');
    expect(grid.quadrant).toBe('Q1_双高热点区');
    expect(grid.green_fraction).toBeCloseTo(0.19);
    expect(Object.keys(grid.phases).map(Number).sort((a, b) => a - b)).toEqual([9, 14, 18, 22]);
    expect(grid.phases[14]!.risk_level).toBe('extreme');
    expect(grid.phases[14]!.p_enhanced).toBeCloseTo(0.82);
    expect(grid.ring[0]).toEqual([121.2, 31.2]);
    expect(dataset.peak_target_time).toContain('14:00:00+08:00');
  });

  it('should normalize hotspots from both demo and backend field names', () => {
    const dataset = buildHeatRiskDataset(multitemporal, spatial, [
      { rank: 1, grid_id: 'g1', district_name: '松江区', lon: 121.1, lat: 31.05, utci_c: 37.2, p_enhanced: 0.85 },
      { rank: 2, grid_id: 'g2', district: '浦东新区', longitude: 121.52, latitude: 31.38, utci_spatial_c: 36.8, p_hot_spatial: 0.84 },
      { rank: 3, grid_id: 'g3', district_name: '未知位置' },
    ]);
    expect(dataset.hotspots).toHaveLength(2);
    expect(dataset.hotspots[0]).toMatchObject({ rank: 1, name: '松江区', lon: 121.1, utci_c: 37.2, p_enhanced: 0.85 });
    expect(dataset.hotspots[1]).toMatchObject({ rank: 2, name: '浦东新区', lon: 121.52, lat: 31.38, utci_c: 36.8, p_enhanced: 0.84 });
  });

  it('should tolerate empty payloads', () => {
    const dataset = buildHeatRiskDataset({ features: [] }, null, null);
    expect(dataset.grids).toHaveLength(0);
    expect(dataset.hotspots).toHaveLength(0);
    expect(dataset.peak_target_time).toBeNull();
  });
});

describe('grid lattice and coordinate resolution', () => {
  const ringAround = (lon: number, lat: number): number[][] => [
    [lon - 0.005, lat - 0.005], [lon + 0.005, lat - 0.005], [lon + 0.005, lat + 0.005], [lon - 0.005, lat + 0.005], [lon - 0.005, lat - 0.005],
  ];
  const gridAt = (row: number, col: number, pEnhanced: number): HeatRiskGrid => ({
    grid_id: `r${String(row).padStart(3, '0')}_c${String(col).padStart(3, '0')}`,
    district_name: '测试区', quadrant: '', green_fraction: 0.1, water_fraction: 0.1, building_fraction: 0.1,
    ring: ringAround(120.9 + col * 0.01, 31.0 - row * 0.01),
    phases: { 14: { hour: 14, phase: 'peak_14h', target_time: '2026-09-18 14:00:00+08:00', utci_c: 36, p_base: 0.6, p_enhanced: pEnhanced, delta_p: -0.05, rel_mitigation_pct: 8, risk_level: 'high' } },
  });
  const dataset = {
    grids: [gridAt(0, 0, 0.3), gridAt(0, 1, 0.5), gridAt(1, 0, 0.7), gridAt(1, 1, 0.9)],
    hotspots: [], peak_target_time: null,
  };

  it('should fit the lattice linear mapping from grid ids and ring centers', () => {
    const lattice = createHeatRiskLattice(dataset);
    expect(lattice).not.toBeNull();
    expect(lattice!.minRow).toBe(0);
    expect(lattice!.maxCol).toBe(1);
    expect(lattice!.lonB).toBeCloseTo(0.01);
    expect(lattice!.latB).toBeCloseTo(-0.01);
    expect(lattice!.lonA).toBeCloseTo(120.9);
    expect(lattice!.latA).toBeCloseTo(31.0);
  });

  it('should resolve coordinates back to their grid', () => {
    const lattice = createHeatRiskLattice(dataset)!;
    expect(resolveHeatRiskCell(lattice, 120.906, 30.994)?.grid_id).toBe('r001_c001');
    expect(resolveHeatRiskCell(lattice, 120.901, 31.004)?.grid_id).toBe('r000_c000');
    expect(resolveHeatRiskCell(lattice, 120.5, 30.5)).toBeNull();
    expect(resolveHeatRiskCell(lattice, 120.9, 31.5)).toBeNull();
  });

  it('should tolerate empty datasets', () => {
    expect(createHeatRiskLattice({ grids: [], hotspots: [], peak_target_time: null })).toBeNull();
  });
});

describe('grid detail formatting', () => {  const dataset = buildHeatRiskDataset({ features: [multiFeature('g1', 14)] }, { features: [spatialFeature('g1')] }, []);

  it('should produce Chinese keys and a mechanism summary for a populated phase', () => {
    const grid = dataset.grids[0]!;
    const props = formatGridProperties(grid, HEAT_RISK_DEFAULT_PHASE);
    // adapter 通用拾取分支要求 layer_id，缺失会导致点击网格无详情
    expect(props.layer_id).toBe('heat_risk');
    expect(props['行政区']).toBe('徐汇区');
    expect(props['综合风险等级']).toBe(RISK_LEVELS.high.label);
    expect(props['客观 UTCI']).toContain('35.2');
    expect(props['主观偏热概率 P(hot)']).toContain('54.3%');
    expect(props['环境缓解量 ΔP']).toContain('-7.4');
    expect(props['机制分区']).toBe('Q1_双高热点区');
    expect(props['_accent_color']).toBe(RISK_LEVELS.high.color);
    expect(String(props['_summary'])).toContain('偏热概率');
    expect(String(props['_summary'])).toContain('降低 7.4 个百分点');
  });

  it('should mark missing phases as no-data instead of zero', () => {
    const grid = dataset.grids[0]!;
    const props = formatGridProperties(grid, 22);
    expect(props['客观 UTCI']).toBe('缺测');
    expect(props['主观偏热概率 P(hot)']).toBe('缺测');
    expect(String(props['_summary'])).toContain('缺测');
  });

  it('should name grid entities after their district', () => {
    expect(gridEntityName(dataset.grids[0]!)).toBe('热暴露风险网格 · 徐汇区');
    expect(phaseMeta(HEAT_RISK_DEFAULT_PHASE).hour).toBe(14);
    expect(RISK_STYLE_META.map(item => item.id)).toEqual(['level', 'probability', 'mitigation']);
  });
});
