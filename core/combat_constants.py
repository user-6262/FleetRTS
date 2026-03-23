"""Combat tuning values shared by the client and headless sim (no pygame)."""

# World size (authoritative geometry for sim + camera clamp). Window / UI pixels stay in demo_game.
WORLD_W = 5600
WORLD_H = 3400

# Fog-of-war grid (world XY).
FOG_CW = 48
FOG_CH = 29
SENSOR_RANGE_CAPITAL = 400.0
SENSOR_RANGE_STRIKE = 260.0

# Player capital soft collision while moving.
CAPITAL_SEPARATION = 52.0
SEPARATION_PUSH = 72.0

REINF_INTERVAL_BASE = 36.0
SALVAGE_PICKUP_R = 105.0
SALVAGE_POD_VALUE = 16

# Impassable asteroid XY resolution (capital vs craft hit radii).
SHIP_BLOCK_RADIUS_CAPITAL = 26.0
SHIP_BLOCK_RADIUS_CRAFT = 11.0
WORLD_EDGE_MARGIN = 22.0

# Altitude band for hit detection (ships / ordnance).
Z_HIT_BAND = 24.0

# PD HUD stress + overload (RoF taper when saturated).
PD_STRESS_WINDOW_SEC = 0.5
PD_OVERLOAD_LEVEL_THRESHOLD = 0.78
PD_OVERLOAD_GRACE_SEC = 1.0
PD_OVERLOAD_RAMP_SEC = 2.75
PD_OVERLOAD_MIN_ROF_MULT = 0.38
PD_OVERLOAD_RECOVERY_RATE = 0.72

# Ballistics / missiles / VFX (authoritative tuning for sim + client).
BALLISTIC_ACQUISITION_MULT = 4.85
BALLISTIC_SPEED_MULT = 0.52
MAX_BALLISTICS = 1400
BALLISTIC_DESPAWN_PAD = 280
MISSILE_SPEED_MULT = 0.38
MISSILE_ACCEL_TIME = 0.88
MISSILE_CRUISE_SHIP_MULT = 2.85
MISSILE_CRUISE_NOMINAL_MULT = 1.18
MISSILE_LAUNCH_MAX_START_FRAC = 0.68
MISSILE_LAUNCH_SPEED_FLOOR_FRAC = 0.1
MISSILE_PD_INTERCEPT_HP_DEFAULT = 1.05
MISSILE_TURN_MULT = 0.82
SPARK_SPEED_SCALE = 0.48
FIGHTER_MISSILE_RETARGET_R = 128.0

# Return-fire window after hull damage (UI + sim).
ENGAGEMENT_RETURN_FIRE_SEC = 4.0
