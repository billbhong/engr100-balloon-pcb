import csv
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from gps.nmea import parse_gpgga_log_samples  # noqa: E402


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

OUT_NAME = sys.argv[2] if len(sys.argv) > 2 else "gpgga_strings.csv"
OUT_PATH = os.path.join(_PROJECT_DIR, OUT_NAME)

samples = parse_gpgga_log_samples(CSV_PATH)
if not samples:
    raise RuntimeError("No $GPGGA sentences found.")

with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(
        [
            "Time (ms)",
            "Elapsed (s)",
            "fix_quality",
            "lat_deg",
            "lon_deg",
            "alt_m",
            "gpgga_sentence",
        ]
    )
    t0 = samples[0].t_ms
    for s in samples:
        w.writerow(
            [
                s.t_ms,
                (s.t_ms - t0) / 1000.0,
                s.fix_quality,
                s.lat_deg,
                s.lon_deg,
                s.alt_m,
                s.sentence,
            ]
        )

print(f"Loaded: {CSV_PATH}")
print(f"GPGGA sentences exported: {len(samples):,}")
print(f"Saved: {OUT_PATH}")

