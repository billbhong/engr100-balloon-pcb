import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import os
import sys
import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from gps.nmea import parse_gpgga_altitude_series_from_log_ms  # noqa: E402


def _resolve_data_file(name: str, *, required: bool = True) -> str:
    """Prefer this script's folder, then the project root."""
    candidates = (
        os.path.join(_SCRIPT_DIR, name),
        os.path.join(os.path.dirname(_SCRIPT_DIR), name),
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    if required:
        raise FileNotFoundError(
            f"{name!r} not found. Tried:\n  " + "\n  ".join(candidates)
        )
    return candidates[0]


CSV_NAME = sys.argv[1] if len(sys.argv) > 1 else "Flight_Data.CSV"
CSV_PATH = _resolve_data_file(CSV_NAME, required=True)

# Plot/filter config
ACCEL_UNITS = "m/s^2"      # measured units in Flight_Data.CSV
G0 = 9.80665               # m/s^2
# Set to "none" to plot raw |a| (includes gravity). Use "median"/"1g" for dynamic accel.
GRAVITY_REMOVE = "none"    # "none" | "median" | "1g" (uses G0 when units are m/s^2)
MEDIAN_FILTER_S = 4.0      # seconds; robust spike removal (higher = less noise)
EMA_ALPHA = 0.04           # 0..1; lower = smoother
MEAN_FILTER_S = 1.5        # seconds; final heavy smoothing after EMA
MAX_PLOT_POINTS = 250_000  # decimate for responsiveness

df = pd.read_csv(
    CSV_PATH,
    header=0,
    on_bad_lines="skip",
)

required_cols = ["Time (ms)", "xAccel (g)", "yAccel (g)", "zAccel(g)"]
missing = [c for c in required_cols if c not in df.columns]
if missing:
    raise ValueError(f"Missing columns in {CSV_PATH}: {missing}")

for col in required_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")
df.dropna(subset=["Time (ms)", "xAccel (g)", "yAccel (g)", "zAccel(g)"], inplace=True)

time_ms0 = float(df["Time (ms)"].iloc[0])
time_s = (df["Time (ms)"] - time_ms0) / 1000.0

cutoff_seconds = 4700.0

# Keep data up to the 4700-second mark
mask_cutoff = time_s <= cutoff_seconds

# Keep data outside the excluded millisecond range (since gps didn't have a lock)
mask_gap = (df["Time (ms)"] <= 2045770) | (df["Time (ms)"] >= 2950000)
# 3391810

# Combine masks: both conditions must be true (use & for pandas 'AND')
valid_mask = mask_cutoff & mask_gap
# valid_mask = mask_cutoff


df = df[valid_mask]         # Apply to the main DataFrame
time_s = time_s[valid_mask] # Apply to the time series

ax = df["xAccel (g)"].to_numpy(dtype=float)
ay = df["yAccel (g)"].to_numpy(dtype=float)
az = df["zAccel(g)"].to_numpy(dtype=float)
# amag = np.sqrt(ax * ax + ay * ay + az * az)
amag = np.sqrt(ax * ax + ay * ay )


if GRAVITY_REMOVE == "median":
    amag = np.abs(amag - float(np.nanmedian(amag)))
elif GRAVITY_REMOVE == "1g":
    amag = np.abs(amag - (G0 if ACCEL_UNITS == "m/s^2" else 1.0))
elif GRAVITY_REMOVE != "none":
    raise ValueError(f"Unknown GRAVITY_REMOVE={GRAVITY_REMOVE!r}")

FIGSIZE = (10, 5)
DPI = 150

def style_ax(ax, xlabel, ylabel):
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.xaxis.set_major_formatter(ticker.ScalarFormatter(useOffset=False))
    ax.yaxis.set_major_formatter(ticker.ScalarFormatter(useOffset=False))
    ax.ticklabel_format(style="plain", axis="both")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(nbins=8))
    ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins=6))
    ax.set_xlim(0)
    ax.grid(True, linewidth=0.4, alpha=0.5)

print(f"Loaded: {CSV_PATH}")
print(f"Accel samples: {len(df):,}")

# ── Altitude alignment (GPGGA) ────────────────────────────────────────────
# Use the log millis timebase (not UTC). Each $GPGGA sample is attached to the
# most recent sensor-row Time(ms) in the file.
gpgga_t_ms, gpgga_alt_m = parse_gpgga_altitude_series_from_log_ms(CSV_PATH)
if len(gpgga_t_ms) < 2:
    raise RuntimeError("Not enough $GPGGA fixes found to build altitude series.")

t_gps_s = (np.asarray(gpgga_t_ms, dtype=float) - float(gpgga_t_ms[0])) / 1000.0
alt_m = np.asarray(gpgga_alt_m, dtype=float)

t_accel_s = time_s.to_numpy(dtype=float)
alt_at_accel_m = np.interp(t_accel_s, t_gps_s, alt_m, left=np.nan, right=np.nan)

# ── Filter acceleration magnitude ─────────────────────────────────────────
dt = np.diff(t_accel_s)
dt_med = float(np.nanmedian(dt[dt > 0])) if dt.size else 0.0
if not (dt_med > 0):
    dt_med = 0.02  # fallback
win = max(3, int(round(MEDIAN_FILTER_S / dt_med)))
if win % 2 == 0:
    win += 1

amag_s = pd.Series(amag)
amag_med = amag_s.rolling(window=win, center=True, min_periods=1).median().to_numpy()
amag_filt = pd.Series(amag_med).ewm(alpha=EMA_ALPHA, adjust=False).mean().to_numpy()

win_mean = max(3, int(round(MEAN_FILTER_S / dt_med)))
if win_mean % 2 == 0:
    win_mean += 1
amag_mean_s = pd.Series(amag_filt).rolling(
    window=win_mean, center=True, min_periods=1
).mean()
amag_filt = np.asarray(amag_mean_s, dtype=float)

mask = np.isfinite(alt_at_accel_m) & np.isfinite(amag_filt)
t_accel_s = t_accel_s[mask]
alt_at_accel_m = alt_at_accel_m[mask]
amag_filt = amag_filt[mask]

print(f"GPGGA fixes: {len(t_gps_s):,}")
print(f"Aligned samples (inside GPS time range): {len(t_accel_s):,}")
print(
    f"Filter: median win={win} (~{win * dt_med:.2f}s) + "
    f"EMA alpha={EMA_ALPHA} + mean win={win_mean} (~{win_mean * dt_med:.2f}s)"
)

# ── Plot: altitude vs filtered acceleration magnitude ─────────────────────
if len(t_accel_s) == 0:
    raise RuntimeError("No overlapping accel/GPS samples to plot.")

stride = max(1, int(np.ceil(len(t_accel_s) / MAX_PLOT_POINTS)))
xs = amag_filt[::stride]
ys = alt_at_accel_m[::stride]

# 1. Reconstruct original Time (ms) to evaluate against your absolute thresholds
t_ms_plotted = (t_accel_s[::stride] * 1000.0) + time_ms0

# 2. Assign solid colors based on the time thresholds
# (Since the gap between 2045770 and 2950000 is already filtered out, a simple if/else via np.where works perfectly)
point_colors = np.where(t_ms_plotted <= 2045770, "steelblue", "orangered")

fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)

# 3. Update scatter plot to use the color array and remove 'cmap'
sc = ax.scatter(xs, ys, c=point_colors, s=2, alpha=0.35, linewidths=0)

mag_label = f"|a| ({ACCEL_UNITS})" if GRAVITY_REMOVE == "none" else f"dynamic |a| ({ACCEL_UNITS})"
style_ax(ax, f"{mag_label} (filtered)", "Altitude (m MSL)")
ax.set_title("Altitude vs Acceleration Magnitude (Outside Forces) ")

# Create empty scatter plots just to generate the legend handles
ax.scatter([], [], color="steelblue", label="Ascent")
ax.scatter([], [], color="orangered", label="Descent")

# Display the legend
ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), borderaxespad=0.)

fig.tight_layout()
fig.savefig("altitude_vs_accel_outside_forces.png")
plt.close(fig)

print("Saved: altitude_vs_accel_magnitude.png")