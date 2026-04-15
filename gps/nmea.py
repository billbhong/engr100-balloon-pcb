from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GpggaFix:
    t_utc_s: float
    lat_deg: float
    lon_deg: float
    alt_m: float


@dataclass(frozen=True)
class GpggaAltSample:
    t_ms: int
    alt_m: float


@dataclass(frozen=True)
class GpggaLogSample:
    t_ms: int
    sentence: str
    fix_quality: int | None
    lat_deg: float | None
    lon_deg: float | None
    alt_m: float | None


def _parse_hhmmss_to_seconds(raw_time: str) -> float:
    hh = int(raw_time[0:2])
    mm = int(raw_time[2:4])
    ss = float(raw_time[4:])
    return hh * 3600 + mm * 60 + ss


def _parse_nmea_lat(raw_lat: str, ns: str) -> float:
    # ddmm.mmmm
    v = float(raw_lat)
    deg = int(v / 100)
    minutes = v - deg * 100
    out = deg + minutes / 60.0
    return -out if ns == "S" else out


def _parse_nmea_lon(raw_lon: str, ew: str) -> float:
    # dddmm.mmmm
    v = float(raw_lon)
    deg = int(v / 100)
    minutes = v - deg * 100
    out = deg + minutes / 60.0
    return -out if ew == "W" else out


def parse_gpgga_fixes(filename: str) -> list[GpggaFix]:
    """
    Parse $GPGGA sentences from a messy log file.

    Returns a list of fixes with:
    - `t_utc_s`: seconds since midnight UTC (from GPGGA time field)
    - `lat_deg`, `lon_deg`: decimal degrees (W negative)
    - `alt_m`: meters above mean sea level (GPGGA field 9)
    """
    fixes: list[GpggaFix] = []

    with open(filename, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            start = 0
            while True:
                idx = line.find("$GPGGA", start)
                if idx == -1:
                    break
                end = line.find("$", idx + 1)
                sentence = line[idx:end] if end != -1 else line[idx:]
                start = idx + 1

                fields = sentence.split(",")
                # Need at least up through altitude (index 9).
                if len(fields) < 10:
                    continue

                # Fix quality 0 = invalid; also skip empty field.
                if not fields[6] or fields[6] == "0":
                    continue

                # Need time, lat, N/S, lon, E/W, altitude.
                if not all(fields[i] for i in (1, 2, 3, 4, 5, 9)):
                    continue

                try:
                    t_utc_s = _parse_hhmmss_to_seconds(fields[1])
                    lat = _parse_nmea_lat(fields[2], fields[3])
                    lon = _parse_nmea_lon(fields[4], fields[5])
                    alt = float(fields[9])
                except (ValueError, IndexError):
                    continue

                # Keep plausible USA bounding box (avoids junk parses).
                if not (30.0 <= lat <= 55.0) or not (-95.0 <= lon <= -70.0):
                    continue

                fixes.append(GpggaFix(t_utc_s=t_utc_s, lat_deg=lat, lon_deg=lon, alt_m=alt))

    return fixes


def parse_gpgga_altitude_series(filename: str) -> tuple[list[float], list[float]]:
    """Convenience helper returning (t_utc_s[], alt_m[]) from GPGGA."""
    fixes = parse_gpgga_fixes(filename)
    return [f.t_utc_s for f in fixes], [f.alt_m for f in fixes]


def parse_gpgga_altitude_series_from_log_ms(filename: str) -> tuple[list[int], list[float]]:
    """
    Parse altitude samples from $GPGGA lines and attach the nearest log timestamp.

    Many payload logs emit sensor CSV rows interleaved with bare NMEA lines like:
      11554,8.11,...           (sensor row; starts with Time (ms))
      $GPGGA,145709.000,...    (GPS row; no millis)

    For this format we attach each $GPGGA altitude to the most recent sensor-row
    `Time (ms)` seen in the file. This avoids relying on UTC entirely.
    """
    out_t_ms: list[int] = []
    out_alt_m: list[float] = []

    last_ms: int | None = None

    with open(filename, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Try to capture millis from sensor CSV rows.
            # These rows start with an integer millis field before the first comma.
            if line[0].isdigit():
                head = line.split(",", 1)[0]
                try:
                    last_ms = int(head)
                except ValueError:
                    pass

            # Extract any $GPGGA sentence(s) from the line.
            start = 0
            while True:
                idx = line.find("$GPGGA", start)
                if idx == -1:
                    break
                end = line.find("$", idx + 1)
                sentence = line[idx:end] if end != -1 else line[idx:]
                start = idx + 1

                fields = sentence.split(",")
                if len(fields) < 10:
                    continue
                if not fields[6] or fields[6] == "0":
                    continue
                if not fields[9]:
                    continue
                if last_ms is None:
                    continue

                try:
                    alt = float(fields[9])
                except ValueError:
                    continue

                out_t_ms.append(last_ms)
                out_alt_m.append(alt)

    return out_t_ms, out_alt_m


def parse_gpgga_log_samples(filename: str) -> list[GpggaLogSample]:
    """
    Extract every $GPGGA sentence and attach the most recent log `Time (ms)`.

    Unlike `parse_gpgga_altitude_series_from_log_ms`, this keeps samples even if
    fix quality is 0 or lat/lon/alt are missing, so you can export raw GPS lines.
    """
    out: list[GpggaLogSample] = []
    last_ms: int | None = None

    with open(filename, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            if line[0].isdigit():
                head = line.split(",", 1)[0]
                try:
                    last_ms = int(head)
                except ValueError:
                    pass

            start = 0
            while True:
                idx = line.find("$GPGGA", start)
                if idx == -1:
                    break
                end = line.find("$", idx + 1)
                sentence = line[idx:end] if end != -1 else line[idx:]
                start = idx + 1

                fields = sentence.split(",")
                fq: int | None = None
                lat: float | None = None
                lon: float | None = None
                alt: float | None = None

                if len(fields) > 6 and fields[6]:
                    try:
                        fq = int(fields[6])
                    except ValueError:
                        fq = None

                if len(fields) > 5 and all(fields[i] for i in (2, 3, 4, 5)):
                    try:
                        lat = _parse_nmea_lat(fields[2], fields[3])
                        lon = _parse_nmea_lon(fields[4], fields[5])
                    except ValueError:
                        lat = lon = None

                if len(fields) > 9 and fields[9]:
                    try:
                        alt = float(fields[9])
                    except ValueError:
                        alt = None

                if last_ms is None:
                    continue

                out.append(
                    GpggaLogSample(
                        t_ms=last_ms,
                        sentence=sentence,
                        fix_quality=fq,
                        lat_deg=lat,
                        lon_deg=lon,
                        alt_m=alt,
                    )
                )

    return out

