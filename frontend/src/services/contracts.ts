export type Coordinates = [number, number];
export type Bbox = [number, number, number, number];
export type Variable = 'utci' | 'air_temperature' | 'relative_humidity' | 'wind_speed' | 'dew_point' | 'solar_radiation' | 'net_shortwave_background' | 'local_downwelling_shortwave' | 'sun_visibility' | 'sky_factor';
export type Mode = 'current_estimate' | 'forecast' | 'historical';
export type TimeSelection = { kind: 'now' } | { kind: 'at'; time: string };
export type Availability = 'available' | 'missing' | 'unsupported';
export interface Page<T> { items: T[]; next_cursor: string | null }
export interface Asset { type: 'geojson' | 'image' | 'xyz' | '3dtiles' | 'terrain' | 'demo'; format?: 'platform-features' | 'cesium-osm-buildings' | string; url?: string; bbox?: Bbox; attribution?: string; minimum_level?: number; maximum_level?: number }
export interface Scene {
  scene_id: string; name: string; description: string; scene_version: string;
  bbox: Bbox; timezone: string; initial_camera: { longitude: number; latitude: number; heading: number; pitch: number; range: number };
  capabilities: { media_upload: boolean }; attribution: string[]; tianditu_key?: string;
}
export interface Layer { layer_id: string; name: string; layer_version: string; type: string; default_visible: boolean; availability: Availability; reason_code?: string; assets: Asset[]; attribution: string }
export interface Product {
  variable: Variable; name: string; unit: string; product_id: string; availability: Availability;
  reason_code?: string; definition: string; times: string[]; legend: { min: number; max: number; colors: string[] };
}
export interface Catalog { products: Product[] }
export interface ViewItem {
  variable: Variable; product_id: string; release_id: string; unit: string; availability: Availability;
  freshness: 'fresh' | 'stale' | 'unknown'; reason_code: string | null; requested_time: string;
  resolved_time: string | null; interval_start: string | null; interval_end: string | null;
  temporal_support: 'instant' | 'interval_mean' | 'unknown'; assets: Asset[];
  provenance: { source: string; spatial_support: string; receiver_height: string; model_version: string; omissions: string[] };
  legend: Product['legend'];
}
export interface EnvironmentView { view_id: string; requested_time: string; mode: Mode; expires_at: string; items: ViewItem[] }
export interface PointValue extends ViewItem { value: number | null; value_status: 'valid' | 'no_data' | 'outside_coverage' | 'incompatible' }
export interface PointResult { view_id: string; location: { type: 'Point'; coordinates: Coordinates }; items: PointValue[]; elevation_m?: number | null; slope_deg?: number | null; }
export interface SeriesPoint { time: string; value: number | null; interval_start?: string; interval_end?: string }
export interface SeriesResult { view_id: string; variable: Variable; unit: string; points: SeriesPoint[] }
export interface Place { place_id: string; name: string; description: string; location: { type: 'Point'; coordinates: Coordinates } }
export type Sensation = 'cold' | 'cool' | 'neutral' | 'warm' | 'hot';
export interface CheckInBody {
  scene_id: string; location: { type: 'Point'; coordinates: Coordinates };
  location_source: 'manual_map' | 'manual_coordinates' | 'browser_geolocation'; horizontal_accuracy_m: number | null;
  experienced_at: string; time_source: 'user_selected'; time_uncertainty_minutes: number | null;
  thermal_sensation: Sensation; thermal_comfort: 'comfortable' | 'ordinary' | 'uncomfortable' | null;
  setting: 'indoor' | 'outdoor' | 'mixed' | 'unknown'; activity: string | null; sun_exposure: string | null;
  note: string | null; visibility: 'private' | 'public'; public_location_precision: 'exact' | 'grid_200m' | null;
}
export interface CheckIn extends CheckInBody {
  check_in_id: string; revision: string; alias: string; published_at: string | null;
  match_status: 'pending' | 'matched' | 'unmatched' | 'failed'; publication_status: string;
}
export type PublicCheckIn = Pick<CheckIn, 'check_in_id' | 'alias' | 'location' | 'experienced_at' | 'thermal_sensation' | 'thermal_comfort' | 'setting' | 'activity' | 'sun_exposure' | 'note' | 'public_location_precision'>;
export interface Session { authenticated: boolean; user: { user_id: string; alias: string } | null; csrf_token?: string }
export interface Status { release_ids: string[]; freshness: 'fresh' | 'stale' | 'unknown'; update_state: string }
export interface ExportResult { export_id: string; task_id: string; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'; expires_at?: string; download_url?: string }
export interface FeatureDetail { feature_id: string; name: string; type: string; height_m: number | null; elevation_m?: number | null; levels?: number | null; height_source: string | null; properties: Record<string, unknown> }

export interface ForecastQuota {
  budget_limit: number;
  hard_cutoff_limit: number;
  soft_warning_limit: number;
  total_used: number;
  remaining_quota: number;
  remaining_safe_quota: number;
  usage_percentage: number;
  is_blocked: boolean;
  is_warning: boolean;
  last_updated: string;
}

export interface ForecastPoint {
  id: string;
  name: string;
  district: string;
  type: 'control' | 'test';
  lon: number;
  lat: number;
  tag: string;
  hourly?: {
    time: string[];
    temperature_2m: (number | null)[];
    relative_humidity_2m: (number | null)[];
    wind_speed_10m: (number | null)[];
    dew_point: (number | null)[];
  };
}

export interface ForecastGridResult {
  variable: string;
  hour_index: number;
  forecast_time: string;
  created_at: string;
  urban_bounds: { west: number; south: number; east: number; north: number };
  grid_meta: { resolution_m: number; shape: [number, number]; min_val: number; max_val: number; mean_val: number };
  audit_metrics: {
    test_points_count: number;
    test_mae: number;
    test_rmse: number;
    max_abs_error: number;
    mean_error: number;
    test_details: Array<{
      id: string;
      name: string;
      district: string;
      lon: number;
      lat: number;
      tag: string;
      api_observed: number;
      tile_background: number;
      fused_estimate: number;
      residual_error: number;
    }>;
  };
  control_points_summary: {
    total_count: number;
    valid_inliers_count: number;
    rejected_outliers: string[];
    mean_residual: number;
    min_residual: number;
    max_residual: number;
  };
  grid_data: {
    lons: number[];
    lats: number[];
    values: number[][];
  };
}
