import { describe, expect, it } from 'vitest';
import { datetimeLocal, effectiveTime, localTime, modeNames, publicGrid, publicLocation, reasonText, sensationNames } from '../services/format';
import type { CheckInBody, Coordinates } from '../services/contracts';

describe('format and projection utilities', () => {
  it('should map mode and sensation names correctly', () => {
    expect(modeNames.current_estimate).toBe('当前估计');
    expect(modeNames.forecast).toBe('未来预报');
    expect(modeNames.historical).toBe('历史回看');

    expect(sensationNames.hot).toBe('很热');
    expect(sensationNames.neutral).toBe('中性');
    expect(sensationNames.cold).toBe('冷');
  });

  it('should format local time in Asia/Shanghai timezone', () => {
    // 2026-09-16T00:00:00Z -> Shanghai 08:00
    const formatted = localTime('2026-09-16T00:00:00Z');
    expect(formatted).toContain('08:00');

    const withDate = localTime('2026-09-16T00:00:00Z', true);
    expect(withDate).toContain('08:00');
    expect(withDate).toContain('09');
  });

  it('should compute 200m public grid center in Shanghai', () => {
    const coords: Coordinates = [121.4737, 31.2304];
    const grid = publicGrid(coords);

    expect(grid.center).toBeDefined();
    expect(grid.center.length).toBe(2);
    // Grid center should be close to point (within ~200m)
    expect(Math.abs(grid.center[0] - coords[0])).toBeLessThan(0.005);
    expect(Math.abs(grid.center[1] - coords[1])).toBeLessThan(0.005);
    expect(grid.corners.length).toBe(4);
  });

  it('should coarsen public location when precision is grid_200m', () => {
    const exactCoords: Coordinates = [121.4737, 31.2304];
    const body: CheckInBody = {
      scene_id: 'scene_shanghai',
      location: { type: 'Point', coordinates: exactCoords },
      location_source: 'manual_map',
      horizontal_accuracy_m: null,
      experienced_at: '2026-09-16T10:00:00Z',
      time_source: 'user_selected',
      time_uncertainty_minutes: null,
      thermal_sensation: 'hot',
      thermal_comfort: 'uncomfortable',
      setting: 'outdoor',
      activity: 'walking',
      sun_exposure: 'sun',
      note: '阳光强烈',
      visibility: 'public',
      public_location_precision: 'grid_200m',
    };

    const pubLoc = publicLocation(body);
    expect(pubLoc).not.toEqual(exactCoords);
    expect(Math.abs(pubLoc[0] - exactCoords[0])).toBeLessThan(0.005);

    // Exact precision keeps exact coordinates
    const bodyExact: CheckInBody = { ...body, public_location_precision: 'exact' };
    expect(publicLocation(bodyExact)).toEqual(exactCoords);
  });

  it('should return human-readable reason text', () => {
    expect(reasonText('outside_coverage')).toBe('该位置无覆盖');
    expect(reasonText('unsupported')).toBe('当前产品暂不支持');
    expect(reasonText(null)).toBe('暂时无法提供此数据');
  });
});
