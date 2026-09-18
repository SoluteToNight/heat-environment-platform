import { describe, expect, it } from 'vitest';
import { normalizeBackendResponse, normalizeCatalog, normalizeLayers, normalizeScene, normalizeView } from '../services/backend-adapter';

const wireScene = { id: 'scene_shanghai', name: '上海', center: [121.4737, 31.2304] as [number, number], bbox: [120.85, 30.65, 122.25, 31.88] as [number, number, number, number] };

describe('live backend contracts', () => {
  it('adapts the actual scene array envelope and camera', () => {
    const response = normalizeBackendResponse('/scenes', [wireScene], '/api/v1');
    expect(response).toMatchObject({ items: [{ scene_id: 'scene_shanghai', initial_camera: { longitude: 121.4737, latitude: 31.2304 } }], next_cursor: null });
  });

  it('maps vector feature URLs without inventing a 3D tiles resource', () => {
    normalizeScene(wireScene);
    const layers = normalizeLayers([{ layer_id: 'layer_buildings', name: '建筑', is_visible_default: true, attribution: 'OSM 2026' }], wireScene.id, '/api/v1');
    expect(layers[0]).toMatchObject({ type: 'buildings', layer_version: 'unversioned', assets: [{ type: 'geojson', format: 'platform-features' }] });
    const url = new URL(layers[0]!.assets[0]!.url!, 'http://local');
    expect(url.searchParams.get('limit')).toBe('200');
    expect(url.searchParams.get('bbox')).toBeTruthy();
  });

  it('maps 3dtiles layers to cesium-osm-buildings format asset', () => {
    normalizeScene(wireScene);
    const layers = normalizeLayers([{ layer_id: 'layer_buildings', name: '建筑要素与高度', type: '3dtiles', is_visible_default: true, attribution: 'OSM 2026' }], wireScene.id, '/api/v1');
    expect(layers[0]).toMatchObject({ type: 'buildings', layer_version: 'unversioned', assets: [{ type: '3dtiles', format: 'cesium-osm-buildings' }] });
  });

  it('flattens provider catalogs without fabricating forecast times', () => {
    const catalog = normalizeCatalog([{ product_id: 'qweather', variables: [
      { code: 'air_temperature', name: '气温', unit: '°C', description: '单点预报', availability: 'available' },
      { code: 'net_shortwave_background', name: '净短波', unit: 'W/m²', description: '未提供', availability: 'unsupported' },
      { code: 'unknown', name: '未接入变量', unit: '', description: '', availability: 'available' },
    ] }]);
    expect(catalog.products).toHaveLength(2);
    expect(catalog.products[0]?.times).toEqual([]);
    expect(catalog.products[1]?.availability).toBe('unsupported');
  });

  it('retains forecast provenance and zero or missing point values without synthesizing rasters', () => {
    const view = normalizeView({ view_id: 'test-view', requested_time: '2026-09-17T00:00:00Z', resolved_time: '2026-09-17T01:00:00Z', expires_at: '2026-09-18T00:00:00Z', variables: [
      { variable: 'air_temperature', product_id: 'qweather', release_id: 'release', unit: '°C', availability: 'available', freshness: 'fresh', provenance: { model: 'QWeather', temporal_support: 'hourly_forecast', attributions: ['source'] } },
    ] });
    expect(view.mode).toBe('forecast');
    expect(view.items[0]?.assets).toEqual([]);
    expect(view.items[0]?.provenance.source).toContain('source');
    for (const value of [0, null]) {
      expect(normalizeBackendResponse('/environment/views/test-view/point', { view_id: 'test-view', lon: 121.47, lat: 31.23, readings: [{ variable: 'air_temperature', value, value_status: value === null ? 'no_data' : 'valid', reason_code: null }] }, '/api/v1')).toMatchObject({ items: [{ release_id: 'release', value }] });
    }
  });

  it('adapts release status and preserves already compatible responses', () => {
    expect(normalizeBackendResponse('/scenes/scene_shanghai/status', { active_releases: ['release'], freshness: 'fresh', update_state: 'idle' }, '/api/v1')).toMatchObject({ release_ids: ['release'] });
    const compatible = { items: [], next_cursor: null };
    expect(normalizeBackendResponse('/scenes', compatible, '/api/v1')).toBe(compatible);
  });
});
