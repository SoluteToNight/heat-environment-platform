"""Universal Thermal Climate Index (UTCI) & Mean Radiant Temperature (Tmrt) Service.

Implements bioclimatic thermal stress calculations following international standards:
1. Mean Radiant Temperature (Tmrt) via standard isotropic six-direction Stefan-Boltzmann radiant balance:
   - Tmrt = [ (Ta + 273.15)^4 + ( (1 + albedo) * S_down * f_p * alpha_k ) / (eps_p * sigma) ]^0.25 - 273.15
   - Parameters:
     * sigma = 5.670374419e-8 W/(m²·K⁴) (Stefan-Boltzmann constant)
     * alpha_k = 0.70 (Standard clothed human body shortwave absorption coefficient)
     * eps_p = 0.97 (Standard human emissivity in the thermal infrared)
     * f_p = 0.25 (Projected area factor averaged across all human body orientations)
     * albedo = 0.20 (Standard urban ground surface albedo)
2. UTCI operational 6th-order polynomial approximation (Bröde et al., 2012; Błażejczyk et al., 2013)
   via pythermalcomfort library with Numba JIT acceleration.
3. Standard 10-category thermal stress classification (ISO 7730 / VDI 3787 / UTCI Guideline).
"""

import logging
from typing import Union
import numpy as np
from pythermalcomfort.models import utci

logger = logging.getLogger(__name__)

# Physical constants
STEFAN_BOLTZMANN = 5.670374419e-8  # W/(m²·K⁴)
HUMAN_SHORTWAVE_ABSORPTIVITY = 0.70  # alpha_k
HUMAN_LONGWAVE_EMISSIVITY = 0.97     # eps_p
MEAN_PROJECTION_FACTOR = 0.25        # f_p
URBAN_GROUND_ALBEDO = 0.20           # albedo

# UTCI Thermal Stress Thresholds (°C) and Chinese / English descriptions
UTCI_STRESS_LEVELS = [
    (46.0, float("inf"), "极强热应激", "Extreme heat stress", "#d73027"),
    (38.0, 46.0, "很强热应激", "Very strong heat stress", "#f46d43"),
    (32.0, 38.0, "强热应激", "Strong heat stress", "#fdae61"),
    (26.0, 32.0, "中度热应激", "Moderate heat stress", "#fee090"),
    (9.0, 26.0, "无热应激", "No thermal stress", "#abd9e9"),
    (0.0, 9.0, "轻度冷应激", "Slight cold stress", "#74add1"),
    (-13.0, 0.0, "中度冷应激", "Moderate cold stress", "#4575b4"),
    (float("-inf"), -13.0, "强/极强冷应激", "Strong/Extreme cold stress", "#313695"),
]


def calculate_tmrt(
    ta_c: Union[float, np.ndarray],
    solar_rad_w_m2: Union[float, np.ndarray],
    albedo: float = URBAN_GROUND_ALBEDO,
    f_p: float = MEAN_PROJECTION_FACTOR,
    alpha_k: float = HUMAN_SHORTWAVE_ABSORPTIVITY,
    eps_p: float = HUMAN_LONGWAVE_EMISSIVITY,
) -> Union[float, np.ndarray]:
    """Calculate Mean Radiant Temperature (Tmrt, °C) from air temperature and solar irradiance.
    
    Args:
        ta_c: Dry bulb air temperature in degrees Celsius (°C).
        solar_rad_w_m2: Downwelling/net global solar irradiance in W/m² (>= 0).
        albedo: Surrounding ground surface shortwave reflectance (default: 0.20).
        f_p: Projected area factor of a standing/walking human (default: 0.25).
        alpha_k: Shortwave solar absorptivity of a clad person (default: 0.70).
        eps_p: Longwave emissivity of human skin and clothing (default: 0.97).
        
    Returns:
        Mean radiant temperature in °C.
    """
    is_scalar = np.isscalar(ta_c)
    ta_arr = np.asarray(ta_c, dtype=float)
    s_arr = np.asarray(solar_rad_w_m2, dtype=float)
    
    # Clip negative radiation
    s_clean = np.maximum(s_arr, 0.0)
    
    ta_k = ta_arr + 273.15
    
    # Shortwave absorbed flux per unit human surface area (including ground reflection)
    solar_absorbed_flux = (1.0 + albedo) * s_clean * f_p * alpha_k
    
    # Stefan-Boltzmann fourth power sum
    rad_term = np.power(ta_k, 4.0) + (solar_absorbed_flux / (eps_p * STEFAN_BOLTZMANN))
    
    tmrt_k = np.power(rad_term, 0.25)
    tmrt_c = tmrt_k - 273.15
    
    return float(tmrt_c) if is_scalar else tmrt_c


def calculate_utci(
    ta_c: Union[float, np.ndarray],
    rh_percent: Union[float, np.ndarray],
    wind_speed_m_s: Union[float, np.ndarray],
    tmrt_c: Union[float, np.ndarray],
) -> tuple[Union[float, np.ndarray], Union[str, np.ndarray]]:
    """Calculate UTCI and thermal stress categories using pythermalcomfort.
    
    Strictly adheres to UTCI input boundary conditions:
    - Air temperature: [-50°C, +50°C]
    - Tmrt - Ta delta: [-30°C, +70°C]
    - Wind speed at 10m: [0.5 m/s, 17.0 m/s] (clamped to 0.5 minimum for metabolic draft)
    - Relative humidity: [5%, 100%]
    
    Returns:
        (utci_values, stress_categories)
    """
    is_scalar = np.isscalar(ta_c)
    ta = np.asarray(ta_c, dtype=float)
    rh = np.asarray(rh_percent, dtype=float)
    wind = np.asarray(wind_speed_m_s, dtype=float)
    tmrt = np.asarray(tmrt_c, dtype=float)
    
    # Enforce standard UTCI bounds
    ta_clamped = np.clip(ta, -50.0, 50.0)
    # Wind speed must be >= 0.5 m/s according to UTCI definition
    wind_clamped = np.clip(wind, 0.5, 17.0)
    rh_clamped = np.clip(rh, 5.0, 100.0)
    
    # Delta Tmrt - Ta must be in [-30, +70]
    delta_tr = np.clip(tmrt - ta_clamped, -30.0, 70.0)
    tmrt_clamped = ta_clamped + delta_tr
    
    # Execute vectorized polynomial model
    result = utci(
        tdb=ta_clamped,
        tr=tmrt_clamped,
        v=wind_clamped,
        rh=rh_clamped,
        units="SI",
        limit_inputs=False,
        round_output=True,
    )
    
    utci_val = result.utci
    stress_cat = result.stress_category
    
    if is_scalar:
        return float(utci_val), str(stress_cat)
    return utci_val, stress_cat


def classify_utci_chinese(utci_val: float) -> tuple[str, str, str]:
    """Map a numerical UTCI value to (Chinese Category, English Category, Color Hex)."""
    if not np.isfinite(utci_val):
        return "缺测", "No Data", "#cccccc"
    
    for lower, upper, zh, en, color in UTCI_STRESS_LEVELS:
        if lower <= utci_val < upper:
            return zh, en, color
            
    return "无热应激", "No thermal stress", "#abd9e9"
