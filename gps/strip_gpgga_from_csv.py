import os
import sys


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)


def _resolve_data_file(name: str) -> str:
    candidates = (
        os.path.join(_SCRIPT_DIR, name),
        os.path.join(_PROJECT_DIR, name),
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(f"{name!r} not found. Tried:\n  " + "\n  ".join(candidates))


IN_NAME = sys.argv[1] if len(sys.argv) > 1 else "Flight_Data.CSV"
IN_PATH = _resolve_data_file(IN_NAME)

OUT_NAME = sys.argv[2] if len(sys.argv) > 2 else "Flight_Data_no_gpgga.csv"
OUT_PATH = os.path.join(_PROJECT_DIR, OUT_NAME)

kept = 0
skipped = 0

with open(IN_PATH, "r", encoding="utf-8", errors="ignore") as fin, open(
    OUT_PATH, "w", encoding="utf-8", newline=""
) as fout:
    first = True
    for raw in fin:
        line = raw.strip("\r\n")
        if not line:
            skipped += 1
            continue

        # Keep header (first non-empty line).
        if first:
            fout.write(line + "\n")
            kept += 1
            first = False
            continue

        # Keep only sensor rows that begin with the millis integer.
        # Drop NMEA lines like "$GPGGA,...".
        if line[0].isdigit():
            fout.write(line + "\n")
            kept += 1
        else:
            skipped += 1

print(f"Loaded: {IN_PATH}")
print(f"Saved:  {OUT_PATH}")
print(f"Kept lines: {kept:,}")
print(f"Skipped lines: {skipped:,}")

