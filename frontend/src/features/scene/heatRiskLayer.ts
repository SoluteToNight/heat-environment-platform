/**
 * heatRiskLayer.ts — 「热暴露风险」Cesium 图层（平滑色斑渲染）
 *
 * 将 M0/M1 主观偏热概率回归模型的 4 时相 1km 网格反演值，插值平滑为连续色斑面
 * （Canvas → SingleTileImageryProvider），按数据覆盖范围羽化边缘，避免网格马赛克观感。
 * 三种着色模式：
 * - level：客观 UTCI × 主观 P(hot) 联合分级（与后端 evaluate_risk_level 一致，像素级重新分级）
 * - probability：M1 模型 P(hot) 连续色带
 * - mitigation：环境缓解量 ΔP（M1 相对 M0 的偏热概率变化，负值即绿地水体收益）
 *
 * 点击查询按坐标反解所在网格（resolveHeatRiskCell），详情语义与网格一一对应；
 * 峰值时相叠加 Top10 主观偏热极值热点徽标。数据缺测区域不着色（数据缺失 ≠ 0）。
 */
import type * as CesiumTypes from 'cesium';
import {
  HEAT_RISK_NODATA_COLOR,
  HEAT_RISK_STYLE_ALPHA,
  combineRiskLevel,
  createHeatRiskLattice,
  formatGridProperties,
  gridEntityName,
  mitigationRgba,
  probabilityColor,
  resolveHeatRiskCell,
  riskColor,
  RISK_LEVELS,
} from '../../services/heatRisk';
import type { HeatRiskDataset, HeatRiskGrid, HeatRiskLattice, HeatRiskPresentation, HeatRiskStyle } from '../../services/heatRisk';

const CELL_PX = 6;
const BLUR_RADIUS = CELL_PX;
const BLUR_PASSES = 2;
const COVERAGE_GAIN = 1.25;
const NODATA_ALPHA = 0.3;

export interface HeatRiskLayerCallbacks { onRasterAdded?: () => void }

interface RasterPaint { dataUrl: string; rect: [number, number, number, number] }

function hexBytes(hex: string): [number, number, number] {
  const value = hex.replace('#', '');
  return [parseInt(value.slice(0, 2), 16), parseInt(value.slice(2, 4), 16), parseInt(value.slice(4, 6), 16)];
}

/** 滑动窗口箱式模糊（NaN 感知：缺测值不参与均值），水平+垂直各一次为一趟 */
function boxBlur(field: Float32Array, width: number, height: number, radius: number, passes: number) {
  const scratch = new Float32Array(field.length);
  const linePass = (src: Float32Array, dst: Float32Array, horizontal: boolean) => {
    const lines = horizontal ? height : width;
    const len = horizontal ? width : height;
    const at = horizontal ? (line: number, i: number) => line * width + i : (line: number, i: number) => i * width + line;
    for (let line = 0; line < lines; line++) {
      let sum = 0;
      let count = 0;
      for (let i = 0; i <= radius && i < len; i++) {
        const v = src[at(line, i)];
        if (Number.isFinite(v)) { sum += v; count++; }
      }
      for (let i = 0; i < len; i++) {
        dst[at(line, i)] = count ? sum / count : NaN;
        const add = i + radius + 1;
        const remove = i - radius;
        if (add < len) { const v = src[at(line, add)]; if (Number.isFinite(v)) { sum += v; count++; } }
        if (remove >= 0) { const v = src[at(line, remove)]; if (Number.isFinite(v)) { sum -= v; count--; } }
      }
    }
  };
  for (let pass = 0; pass < passes; pass++) {
    linePass(field, scratch, true);
    linePass(scratch, field, false);
  }
}

/** 将晶格值场绘制为平滑色斑图（覆盖羽化 + 值场平滑），返回 PNG dataURL 与地理范围 */
function paintHeatRiskRaster(lattice: HeatRiskLattice, dataset: HeatRiskDataset, phase: number, style: HeatRiskStyle): RasterPaint | null {
  if (typeof document === 'undefined') return null;
  const rows = lattice.maxRow - lattice.minRow + 1;
  const cols = lattice.maxCol - lattice.minCol + 1;
  const width = cols * CELL_PX;
  const height = rows * CELL_PX;
  const total = width * height;
  const pField = new Float32Array(total).fill(NaN);
  const utciField = new Float32Array(total).fill(NaN);
  const dpField = new Float32Array(total).fill(NaN);
  const coverage = new Float32Array(total);
  for (const [key, grid] of lattice.cells) {
    const value = grid.phases[phase];
    if (!value || !Number.isFinite(value.p_enhanced)) continue;
    const [row, col] = key.split('_').map(Number);
    const y0 = (row - lattice.minRow) * CELL_PX;
    const x0 = (col - lattice.minCol) * CELL_PX;
    for (let y = y0; y < y0 + CELL_PX && y < height; y++) {
      for (let x = x0; x < x0 + CELL_PX && x < width; x++) {
        const index = y * width + x;
        pField[index] = value.p_enhanced;
        utciField[index] = value.utci_c;
        dpField[index] = value.delta_p;
        coverage[index] = 1;
      }
    }
  }
  boxBlur(pField, width, height, BLUR_RADIUS, BLUR_PASSES);
  boxBlur(utciField, width, height, BLUR_RADIUS, BLUR_PASSES);
  boxBlur(dpField, width, height, BLUR_RADIUS, BLUR_PASSES);
  boxBlur(coverage, width, height, BLUR_RADIUS, BLUR_PASSES);

  const probabilityLut: [number, number, number][] = Array.from({ length: 65 }, (_, bin) => hexBytes(probabilityColor(bin / 64)));
  const mitigationLut: [number, number, number, number][] = Array.from({ length: 65 }, (_, bin) => mitigationRgba(-0.30 + (bin / 64) * 0.45));
  const levelColors = Object.fromEntries(Object.entries(RISK_LEVELS).map(([level, meta]) => [level, hexBytes(meta.color)])) as Record<string, [number, number, number]>;
  const nodata = hexBytes(HEAT_RISK_NODATA_COLOR);

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) return null;
  const image = context.createImageData(width, height);
  const pixels = image.data;
  for (let index = 0; index < total; index++) {
    const offset = index * 4;
    const coverageAlpha = Math.min(1, coverage[index] * COVERAGE_GAIN);
    if (coverageAlpha <= 0.02) { pixels[offset + 3] = 0; continue; }
    const p = pField[index];
    if (!Number.isFinite(p)) { pixels[offset + 3] = 0; continue; }
    let rgb: [number, number, number];
    let signalAlpha = 1;
    if (style === 'probability') {
      rgb = probabilityLut[Math.round(Math.min(1, Math.max(0, p)) * 64)]!;
    } else if (style === 'mitigation') {
      // 异常叠置：ΔP≈0 全透明露出底色，信号越强越不透明（蓝=降温收益，紫红=偏热加剧）
      const dp = dpField[index];
      const entry = mitigationLut[Math.round((Number.isFinite(dp) ? Math.min(1, Math.max(0, (dp + 0.30) / 0.45)) : 0.5) * 64)]!;
      rgb = [entry[0], entry[1], entry[2]];
      signalAlpha = entry[3];
    } else {
      const utci = utciField[index];
      const level = combineRiskLevel(Number.isFinite(utci) ? utci : 0, p);
      rgb = levelColors[level] || nodata;
    }
    pixels[offset] = rgb[0];
    pixels[offset + 1] = rgb[1];
    pixels[offset + 2] = rgb[2];
    pixels[offset + 3] = Math.round(Math.min(1, coverageAlpha * signalAlpha) * 255);
  }
  context.putImageData(image, 0, 0);

  const west = lattice.lonA + lattice.lonB * (lattice.minCol - 0.5);
  const east = lattice.lonA + lattice.lonB * (lattice.maxCol + 0.5);
  const edgeNorth = lattice.latA + lattice.latB * (lattice.minRow - 0.5);
  const edgeSouth = lattice.latA + lattice.latB * (lattice.maxRow + 0.5);
  const north = Math.max(edgeNorth, edgeSouth);
  const south = Math.min(edgeNorth, edgeSouth);
  return { dataUrl: canvas.toDataURL('image/png'), rect: [west, south, east, north] };
}

export class HeatRiskLayer {
  private destroyed = false;
  private hotspotSource: CesiumTypes.CustomDataSource;
  private rasterLayer: CesiumTypes.ImageryLayer | null = null;
  private rasterToken = 0;
  private lattice: HeatRiskLattice | null = null;
  private latticeDataset: HeatRiskDataset | null = null;
  private pres: HeatRiskPresentation | null = null;
  private visible = false;

  constructor(private cesium: typeof CesiumTypes, private viewer: CesiumTypes.Viewer, private callbacks: HeatRiskLayerCallbacks = {}) {
    this.hotspotSource = new cesium.CustomDataSource('heat-risk-hotspots');
    this.hotspotSource.show = false;
    void viewer.dataSources.add(this.hotspotSource);
  }

  update(dataset: HeatRiskDataset | null, pres: HeatRiskPresentation) {
    if (this.destroyed) return;
    this.pres = pres;
    if (!pres.enabled || !dataset || !dataset.grids.length) {
      this.setVisible(false);
      return;
    }
    if (this.latticeDataset !== dataset) {
      this.lattice = createHeatRiskLattice(dataset);
      this.latticeDataset = dataset;
      this.hotspotSource.entities.removeAll();
    }
    this.visible = true;
    void this.updateRaster(dataset, pres);
    this.updateHotspots(dataset, pres);
    this.render();
  }

  /** 经纬度 → 所在网格详情（图层可见且该网格当前时相有值时返回） */
  pickCell(coordinates: [number, number]): { name: string; properties: Record<string, unknown> } | null {
    if (!this.visible || !this.lattice || !this.pres) return null;
    const grid = resolveHeatRiskCell(this.lattice, coordinates[0], coordinates[1]);
    const value = grid?.phases[this.pres.phase];
    if (!grid || !value) return null;
    return { name: gridEntityName(grid), properties: formatGridProperties(grid, this.pres.phase) };
  }

  setVisible(visible: boolean) {
    if (this.destroyed) return;
    this.visible = visible;
    if (this.rasterLayer) this.rasterLayer.show = visible;
    this.hotspotSource.show = visible;
    this.render();
  }

  destroy() {
    this.destroyed = true;
    this.visible = false;
    this.lattice = null;
    this.latticeDataset = null;
    if (this.rasterLayer) {
      this.viewer.imageryLayers.remove(this.rasterLayer, true);
      this.rasterLayer = null;
    }
    this.viewer.dataSources.remove(this.hotspotSource, true);
  }

  private render() {
    if (!this.destroyed) this.viewer.scene.requestRender();
  }

  private async updateRaster(dataset: HeatRiskDataset, pres: HeatRiskPresentation) {
    if (!this.lattice) return;
    const token = ++this.rasterToken;
    const paint = paintHeatRiskRaster(this.lattice, dataset, pres.phase, pres.style);
    if (!paint) return;
    try {
      const provider = await this.cesium.SingleTileImageryProvider.fromUrl(paint.dataUrl, {
        rectangle: this.cesium.Rectangle.fromDegrees(paint.rect[0], paint.rect[1], paint.rect[2], paint.rect[3]),
      });
      if (this.destroyed || token !== this.rasterToken) return;
      if (this.rasterLayer) this.viewer.imageryLayers.remove(this.rasterLayer, true);
      this.rasterLayer = this.viewer.imageryLayers.addImageryProvider(provider);
      this.rasterLayer.alpha = HEAT_RISK_STYLE_ALPHA[pres.style];
      this.rasterLayer.show = this.visible;
      this.callbacks.onRasterAdded?.();
      this.render();
    } catch {
      // 色斑图生成/加载失败时保留上一帧
    }
  }

  /** 极值热点徽标：仅在峰值时相（14 时）显示，构建一次后随数据集缓存 */
  private updateHotspots(dataset: HeatRiskDataset, pres: HeatRiskPresentation) {
    const visible = pres.phase === 14 && dataset.hotspots.length > 0;
    this.hotspotSource.show = visible && this.visible;
    if (!visible || this.hotspotDataset === dataset) return;
    this.hotspotSource.entities.removeAll();
    const cesium = this.cesium;
    for (const hotspot of dataset.hotspots) {
      const position = cesium.Cartesian3.fromDegrees(hotspot.lon, hotspot.lat, 26);
      this.hotspotSource.entities.add({
        name: `热暴露极值热点 #${hotspot.rank} · ${hotspot.name}`,
        position,
        properties: new cesium.PropertyBag({
          layer_id: 'heat_risk_hotspot',
          name: `热暴露极值热点 #${hotspot.rank}`,
          行政区: hotspot.name,
          '主观偏热概率 P(hot)': hotspot.p_enhanced != null ? `${Math.round(hotspot.p_enhanced * 100)}%` : '缺测',
          '客观 UTCI': hotspot.utci_c != null ? `${hotspot.utci_c.toFixed(1)} °C` : '缺测',
          网格编号: hotspot.grid_id,
          _accent_color: '#cd4a4a',
          _summary: `模型反演显示该网格为峰值时相主观偏热概率第 ${hotspot.rank} 位的极值热点${hotspot.p_enhanced != null ? `，P(hot) 达 ${Math.round(hotspot.p_enhanced * 100)}%` : ''}，建议优先纳入防暑保障。`,
        }),
        billboard: {
          image: this.hotspotBadge(hotspot.rank),
          width: 46,
          height: 46,
          verticalOrigin: cesium.VerticalOrigin.CENTER,
          disableDepthTestDistance: Infinity,
          scaleByDistance: new cesium.NearFarScalar(3e4, 1.0, 2.5e5, 0.55),
        },
        label: {
          text: `#${hotspot.rank} ${hotspot.name}${hotspot.p_enhanced != null ? ` · 偏热概率 ${Math.round(hotspot.p_enhanced * 100)}%` : ''}`,
          font: '600 13px "Microsoft YaHei", "PingFang SC", sans-serif',
          fillColor: cesium.Color.fromCssColorString('#7c1f2d'),
          outlineColor: cesium.Color.WHITE,
          outlineWidth: 4,
          style: cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new cesium.Cartesian2(0, 42),
          disableDepthTestDistance: Infinity,
          distanceDisplayCondition: new cesium.DistanceDisplayCondition(0, 90000),
        },
      });
    }
    this.hotspotDataset = dataset;
  }

  private hotspotDataset: HeatRiskDataset | null = null;

  /** Top 徽标：暖红渐变圆牌 + 白色火焰 + 排名，2x 超采样保证高清 */
  private hotspotBadge(rank: number): string {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 64 64">
      <defs>
        <linearGradient id="hrg${rank}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#ef6a50"/>
          <stop offset="100%" stop-color="#b03038"/>
        </linearGradient>
        <filter id="hrs${rank}" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="2" stdDeviation="2.4" flood-color="#000000" flood-opacity="0.35"/>
        </filter>
      </defs>
      <circle cx="32" cy="32" r="30" fill="rgba(255,255,255,0.45)"/>
      <circle cx="32" cy="32" r="25" fill="url(#hrg${rank})" stroke="#ffffff" stroke-width="3" filter="url(#hrs${rank})"/>
      <path d="M32 10 C34.2 15.5 39.5 18.5 39.5 25 A7.5 8 0 1 1 24.5 25 C24.5 21.2 27.3 18.6 28.8 15.2 C29.8 17.2 31.2 18.3 32.2 19.3 C31.6 16.2 31.6 13 32 10 Z" fill="#ffffff"/>
      <text x="32" y="52" text-anchor="middle" fill="#ffffff" font-family="-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif" font-size="21" font-weight="700">${rank}</text>
    </svg>`;
    return `data:image/svg+xml,${encodeURIComponent(svg)}`;
  }
}
