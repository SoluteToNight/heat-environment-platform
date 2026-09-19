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
export interface ReportReceipt { report_id: string; check_in_id: string; status: 'pending'; created_at: string }
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

/** 后端 /forecast/24h/summary 的 hourly_details 逐时行（字段名与 OpenAPI 一致） */
export interface HourlyPerceptionDetail {
  time: string;
  hour: number;
  temperature_c: number;
  humidity_pct: number;
  wind_speed_ms: number;
  radiation_wm2: number;
  utci_c: number;
  stress_desc: string;
  p_hot_inland: number;
  p_hot_waterfront: number;
  cooling_benefit_pct: number;
  /** extreme | high | moderate | low */
  risk_level: string;
}

export interface Forecast24hSummary {
  status: string;
  generated_at: string;
  real_forecast_source: string;
  real_ugc_sample_size: number;
  ugc_validation_metrics: {
    sample_count: number;
    m0_auc: number;
    m0_brier: number;
    m1_auc: number;
    m1_brier: number;
    optimal_threshold: number;
    accuracy_optimal: number;
    f1_score_optimal: number;
    precision_optimal: number;
    recall_optimal: number;
    nominal_threshold_0_5: { accuracy: number };
  };
  forecast_24h_overview: {
    peak_time_bjt: string;
    peak_temperature_c: number;
    peak_utci_c: number;
    peak_stress_desc: string;
    peak_p_hot_inland: number;
    peak_p_hot_waterfront: number;
    max_cooling_benefit_pct: number;
    mean_cooling_benefit_pct: number;
    continuous_heat_hours?: number[];
  };
  hourly_details: HourlyPerceptionDetail[];
}

export interface ExtremeHotspotItem {
  rank: number;
  grid_id: string;
  district_name: string;
  lon: number;
  lat: number;
  utci_c: number;
  p_enhanced: number;
  p_base: number;
  delta_p: number;
  green_fraction: number;
  water_fraction: number;
  building_fraction: number;
}

export interface ExtremeRegionsResponse {
  lead_hour: number;
  top_extreme_hotspots: ExtremeHotspotItem[];
  total_identified_hotspots?: number;
}

export interface ShelterLocation {
  name: string;
  capacity: number;
  radius_m: number;
}

/** 键为行业标识（后端下发英文 key，演示数据可能直接用中文行业名） */
export interface SectorGuideline {
  action?: string;
  instructions?: string[];
  locations?: ShelterLocation[];
}

export interface DecisionSupportResponse {
  valid_period: string;
  max_utci_c: number;
  overall_risk_level: string;
  active_alerts: Array<{
    level: string;
    title: string;
    trigger_period: string;
    message: string;
  }>;
  sector_guidelines: Record<string, SectorGuideline>;
}

export interface ModelCoefficientRow {
  variable: string;
  coefficient: number;
  odds_ratio: number;
  ci95_lower: number;
  ci95_upper: number;
  unit_change: string;
  interpretation: string;
}

export interface ModelEvaluationResponse {
  model_version: string;
  training_sample_size: number;
  test_sample_size: number;
  sampling_strategy: string;
  pooled_spatial_m1_auc: number;
  test_2024_m1_auc: number;
  test_2024_pure_extrap_m1_auc: number;
  environmental_effects: ModelCoefficientRow[];
  metrics_table: Array<{
    model: string;
    split_type: string;
    auc_roc: number;
    brier_score: number;
    log_loss: number;
  }>;
  coefficients_table: ModelCoefficientRow[];
  calibration_table?: Array<{
    model: string;
    decile_bin: number;
    sample_count: number;
    unit_weight_sum: number;
    predicted_probability: number;
    observed_hot_fraction: number;
  }>;
}

export interface CustomInversionRequest {
  air_temperature_c: number;
  relative_humidity_pct: number;
  wind_speed_10m_ms: number;
  net_solar_radiation_wm2: number;
  green_fraction: number;
  water_fraction: number;
  building_fraction: number;
}

export interface CustomInversionResult {
  calculated_utci_c: number;
  utci_stress_level: string;
  p_hot_base: number;
  p_hot_enhanced: number;
  delta_p: number;
  environmental_mitigation_pct: number;
  risk_level: string;
}

/* ---------- Landing card: real point weather & warnings ---------- */

export interface UtciStressCategory { zh: string; en: string; color: string }

export interface WeatherReading {
  /** 位置当地墙上时间（ISO 字符串，仅用于展示，不含时区偏移） */
  time: string;
  air_temperature_c: number;
  relative_humidity_pct: number;
  wind_speed_ms: number;
  shortwave_radiation_wm2: number;
  tmrt_c: number;
  utci_c: number;
  utci_shade_c: number;
  stress: UtciStressCategory;
}

export interface WeatherPoint {
  location: { longitude: number; latitude: number; grid_rounded: boolean };
  timezone: string | null;
  utc_offset_seconds: number | null;
  source: { provider: string; utci_model: string; fetched_at: string };
  now_index: number;
  current: WeatherReading;
  hourly: WeatherReading[];
  peak: { utci_c: number; time: string } | null;
}

export interface WeatherAlert {
  title: string;
  type_name: string;
  level: string;
  severity_color: string;
  text: string;
  pub_time: string | null;
  start_time: string | null;
  end_time: string | null;
  status: string;
}

export interface WeatherAlerts {
  available: boolean;
  reason_code: 'not_configured' | 'provider_error' | 'quota_exhausted' | null;
  update_time: string | null;
  source: string;
  fetched_at: string;
  alerts: WeatherAlert[];
}


/** UtciCard 加载完成后向兄弟卡片广播的实时读数（风险推导同源，避免二次计算）。 */
export interface UtciReading {
  utciC: number;
  stressZh: string;
  stressColor: string;
}
