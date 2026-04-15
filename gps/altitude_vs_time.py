import os
import sys

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from gps.nmea import parse_gpgga_altitude_series_from_log_ms  # noqa: E402


ALT_SPIKE_WINDOW = 1       # points on each side used for local-median altitude filter
ALT_SPIKE_THRESH = 5000.0  # meters — drop from local median to flag as spike


def filter_altitude_spikes(t_s: np.ndarray, alt_m: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """Drop points whose altitude is more than threshold meters below local median."""
    n = int(alt_m.size)
    keep_idx: list[int] = []
    for i in range(n):
        lo = max(0, i - ALT_SPIKE_WINDOW)
        hi = min(n, i + ALT_SPIKE_WINDOW + 1)
        local_med = float(np.median(alt_m[lo:hi]))
        if alt_m[i] < local_med - ALT_SPIKE_THRESH:
            continue
        keep_idx.append(i)
    dropped = n - len(keep_idx)
    return t_s[keep_idx], alt_m[keep_idx], dropped


def _resolve_data_file(name: str, *, required: bool = True) -> str:
    candidates = (
        os.path.join(_SCRIPT_DIR, name),
        os.path.join(_PROJECT_DIR, name),
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    if required:
        raise FileNotFoundError(f"{name!r} not found. Tried:\n  " + "\n  ".join(candidates))
    return candidates[0]


CSV_NAME = sys.argv[1] if len(sys.argv) > 1 else "Flight_Data.CSV"
CSV_PATH = _resolve_data_file(CSV_NAME, required=True)

t_ms, alt_m = parse_gpgga_altitude_series_from_log_ms(CSV_PATH)
if len(t_ms) < 2:
    raise RuntimeError("Not enough $GPGGA altitude samples found.")

t_s = (np.asarray(t_ms, dtype=float) - float(t_ms[0])) / 1000.0
alt_m = np.asarray(alt_m, dtype=float)

t_s, alt_m, dropped = filter_altitude_spikes(t_s, alt_m)

fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
ax.plot(t_s, alt_m, linewidth=0.8)
ax.set_xlabel("Time (s from first GPGGA)")
ax.set_ylabel("Altitude (m MSL)")
ax.set_title("Altitude vs Time ($GPGGA)")
ax.set_xlim(left=0)
ax.xaxis.set_major_formatter(ticker.ScalarFormatter(useOffset=False))
ax.yaxis.set_major_formatter(ticker.ScalarFormatter(useOffset=False))
ax.ticklabel_format(style="plain", axis="both")
ax.grid(True, linewidth=0.4, alpha=0.5)
fig.tight_layout()
fig.savefig("altitude_vs_time.png")
plt.close(fig)

print(f"Loaded: {CSV_PATH}")
print(f"GPGGA altitude samples: {len(t_ms):,}  ({dropped} dropped as spikes)")
print("Saved: altitude_vs_time.png")

