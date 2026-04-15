import math
import os
import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)


def _resolve_data_file(name: str, *, required: bool = True) -> str:
    """Prefer `gps/name`, then `payload/name` (parent folder), for shared project files."""
    candidates = (
        os.path.join(_SCRIPT_DIR, name),
        os.path.join(_PROJECT_DIR, name),
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    if required:
        raise FileNotFoundError(
            f"{name!r} not found. Tried:\n  " + "\n  ".join(candidates)
        )
    return candidates[0]


# ── Configuration ─────────────────────────────────────────────────────────

FLIGHT_DATA_CSV = _resolve_data_file("Flight_Data.CSV", required=True)
DEM_FILE = _resolve_data_file("output_SRTMGL1.tif", required=False)
SAT_CACHE = os.path.join(_SCRIPT_DIR, "satellite_cache.npz")
MPL_FLIGHT_3D_PNG = os.path.join(_SCRIPT_DIR, "flight_3d.png")  # matplotlib: ascent+descent, no terrain
VERTICAL_EXAG = 30.0        # high exaggeration needed — Michigan terrain is very flat
DEM_MARGIN_DEG = 3.0       # padding (degrees) around flight bbox when cropping DEM
GAP_THRESHOLD_S = 15.0      # seconds — split the path when consecutive fixes are farther apart
ALT_SPIKE_WINDOW = 1       # points on each side used for local-median altitude filter
ALT_SPIKE_THRESH = 5000.0  # meters — drop from local median to flag as spike
SATELLITE_OVERLAY = True    # drape satellite imagery on terrain (needs contextily + internet)
DEM_MAX_DIM = 1500          # downsample DEM so neither axis exceeds this many pixels
TUBE_RADIUS_FRAC = 0.004   # tube radius as a fraction of DEM easting span (was ~0.002)
# If the draped photo looks mirrored vs GPS/DEM, toggle these (geometry is unchanged).
SATELLITE_TEX_FLIP_U = True   # E–W flip of texture coordinates
SATELLITE_TEX_FLIP_V = False  # N–S flip of texture coordinates
SATELLITE_IMAGE_FLIPUD = True # image row order vs northing; try False with TEX_FLIP_V True if N–S is still wrong
# Rare: mirror only the track in UTM through DEM center — usually wrong; try texture flips first.
PATH_UTM_MIRROR = "both"     # "none" | "x" | "y" | "both"
ALT_RULER_OFFSET_FRAC = 0.065    # horizontal offset from ascent path, vs map span
ALT_RULER_TICK_FRAC = 0.012     # tick length vs map span


def _nice_altitude_step_m(span_m: float, *, max_ticks: int = 12) -> float:
    """Pick a round step (meters) for ruler ticks."""
    if span_m <= 0:
        return 1.0
    raw = span_m / max(max_ticks, 1)
    exp = math.floor(math.log10(max(raw, 1e-9)))
    m = raw / (10.0 ** exp)
    if m <= 1.0:
        f = 1.0
    elif m <= 2.0:
        f = 2.0
    elif m <= 5.0:
        f = 5.0
    else:
        f = 10.0
    return f * (10.0 ** exp)


def _ascent_altitude_ruler(
    ascent_pts: np.ndarray,
    ascent_alts_msl: np.ndarray,
    vert_exag: float,
    x_dem: np.ndarray,
    y_dem: np.ndarray,
    tube_r: float,
):
    """Vertical ruler beside the ascent: spine + ticks in scene Z; labels in m MSL."""
    import pyvista as pv

    alt_min = float(np.min(ascent_alts_msl))
    alt_max = float(np.max(ascent_alts_msl))
    z_lo = alt_min * vert_exag
    z_hi = alt_max * vert_exag

    span_xy = max(
        float(np.nanmax(x_dem) - np.nanmin(x_dem)),
        float(np.nanmax(y_dem) - np.nanmin(y_dem)),
        1.0,
    )
    offset = ALT_RULER_OFFSET_FRAC * span_xy
    tick_len = max(tube_r * 6.0, ALT_RULER_TICK_FRAC * span_xy)

    # Mirrored UTM: +X on screen is west, so place spine at max easting
    # (visually west) and ticks toward -X (visually east, toward the path).
    asc_x_max = float(np.max(ascent_pts[:, 0]))
    asc_y_mid = float(np.median(ascent_pts[:, 1]))
    spine_x = asc_x_max + offset
    spine_y = asc_y_mid
    spine = pv.Line([spine_x, spine_y, z_lo], [spine_x, spine_y, z_hi])

    step = _nice_altitude_step_m(alt_max - alt_min, max_ticks=12)
    first = math.ceil(alt_min / step) * step
    tick_alts = np.arange(first, alt_max + 0.01 * step, step, dtype=np.float64)
    tick_alts = tick_alts[(tick_alts >= alt_min - 1e-6) & (tick_alts <= alt_max + 1e-6)]
    tick_alts = np.unique(
        np.concatenate([[alt_min], tick_alts, [alt_max]])
    )

    tick_lines = []
    label_xyz = []
    labels = []
    for a in tick_alts:
        z = float(a) * vert_exag
        tick_lines.append(pv.Line([spine_x, spine_y, z],
                                  [spine_x - tick_len, spine_y, z]))
        label_xyz.append([spine_x - tick_len * 1.25, spine_y, z])
        labels.append(f"{a:.0f} m")

    if len(tick_lines) == 1:
        ticks_mesh = tick_lines[0]
    else:
        ticks_mesh = tick_lines[0].merge(tick_lines[1:])

    return {
        "spine": spine,
        "ticks": ticks_mesh,
        "label_points": np.array(label_xyz, dtype=np.float64),
        "labels": labels,
        "spine_tube_radius": max(tube_r * 0.35, span_xy * 1.5e-4),
    }


def _save_mpl_flight_3d(
    asc_x: np.ndarray, asc_y: np.ndarray, asc_z: np.ndarray,
    desc_x: np.ndarray, desc_y: np.ndarray, desc_z: np.ndarray,
    out_path: str,
) -> None:
    """Matplotlib 3D flight track: ascent + gap + descent, no terrain mesh."""
    import matplotlib.pyplot as plt

    ax_arr = np.asarray(asc_x, dtype=np.float64).ravel()
    ay_arr = np.asarray(asc_y, dtype=np.float64).ravel()
    az_arr = np.asarray(asc_z, dtype=np.float64).ravel()
    dx_arr = np.asarray(desc_x, dtype=np.float64).ravel()
    dy_arr = np.asarray(desc_y, dtype=np.float64).ravel()
    dz_arr = np.asarray(desc_z, dtype=np.float64).ravel()
    if ax_arr.size == 0 and dx_arr.size == 0:
        return

    all_x = np.concatenate([ax_arr, dx_arr])
    all_y = np.concatenate([ay_arr, dy_arr])
    x0, y0 = float(all_x[0]), float(all_y[0])

    fig = plt.figure(figsize=(11, 8))
    ax = fig.add_subplot(111, projection="3d")

    ax.plot(ax_arr - x0, ay_arr - y0, az_arr,
            color="steelblue", lw=3.0, alpha=0.9, label="Ascent")
    ax.plot(dx_arr - x0, dy_arr - y0, dz_arr,
            color="orangered", lw=3.0, alpha=0.9, label="Descent")

    if ax_arr.size and dx_arr.size:
        gap_x = np.array([ax_arr[-1], dx_arr[0]]) - x0
        gap_y = np.array([ay_arr[-1], dy_arr[0]]) - y0
        gap_z = np.array([az_arr[-1], dz_arr[0]])
        ax.plot(gap_x, gap_y, gap_z,
                color="gray", ls="--", lw=2, alpha=0.6, label="Gap (no fix)")

    ax.set_xlabel("\u0394 Easting (m)")
    ax.set_ylabel("\u0394 Northing (m)")
    ax.set_zlabel("Altitude (m MSL)")
    ax.set_title("Balloon Flight (3D)", fontsize=15, fontweight=10)
    ax.legend(loc="upper right", fontsize=13)

    all_xr = all_x - x0
    all_yr = all_y - y0
    all_z = np.concatenate([az_arr, dz_arr])
    try:
        px = float(np.ptp(all_xr))
        py = float(np.ptp(all_yr))
        pz = float(np.ptp(all_z))
        m = max(px, py, pz, 1.0)
        
        z_exaggeration = 5.0  # Increase this to stretch the altitude more
        ax.set_box_aspect((px / m, py / m, (pz / m) * z_exaggeration))
    except Exception:
        pass

    fig.tight_layout()
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


# ── 1. Read and parse $GPGGA lines from the GPS data file ──────────────────

def parse_gpgga(filename):
    """Parse $GPGGA sentences and return lists of time, lat, lon, altitude.

    Handles messy logging where GPGGA sentences may be concatenated with
    other NMEA sentences on the same line, appear multiple times per line,
    or be truncated mid-field.
    """
    times = []       # seconds since midnight UTC
    latitudes = []   # decimal degrees (positive = N)
    longitudes = []  # decimal degrees (positive = E, negative = W)
    altitudes = []   # meters above mean sea level

    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            start = 0
            while True:
                idx = line.find('$GPGGA', start)
                if idx == -1:
                    break
                end = line.find('$', idx + 1)
                sentence = line[idx:end] if end != -1 else line[idx:]
                start = idx + 1

                fields = sentence.split(',')
                if len(fields) < 10:
                    continue
                if not fields[6] or fields[6] == '0':
                    continue
                if not all(fields[i] for i in (1, 2, 3, 4, 5, 9)):
                    continue

                try:
                    raw_time = fields[1]
                    hh = int(raw_time[0:2])
                    mm = int(raw_time[2:4])
                    ss = float(raw_time[4:])
                    t = hh * 3600 + mm * 60 + ss

                    raw_lat = float(fields[2])
                    lat_deg = int(raw_lat / 100)
                    lat_min = raw_lat - lat_deg * 100
                    lat = lat_deg + lat_min / 60.0
                    if fields[3] == 'S':
                        lat = -lat

                    raw_lon = float(fields[4])
                    lon_deg = int(raw_lon / 100)
                    lon_min = raw_lon - lon_deg * 100
                    lon = lon_deg + lon_min / 60.0
                    if fields[5] == 'W':
                        lon = -lon

                    alt = float(fields[9])
                except (ValueError, IndexError):
                    continue

                if not (30.0 <= lat <= 55.0) or not (-95.0 <= lon <= -70.0):
                    continue

                times.append(t)
                latitudes.append(lat)
                longitudes.append(lon)
                altitudes.append(alt)

    return times, latitudes, longitudes, altitudes


def filter_altitude_spikes(times, lats, lons, alts,
                           window=ALT_SPIKE_WINDOW,
                           threshold=ALT_SPIKE_THRESH):
    """Drop points whose altitude is more than *threshold* meters below
    the local median of a surrounding window.  Catches GPS glitches that
    cause sudden altitude dips without disturbing legitimate ascent/descent.
    """
    n = len(alts)
    keep = []
    for i in range(n):
        lo = max(0, i - window)
        hi = min(n, i + window + 1)
        neighbourhood = sorted(alts[lo:hi])
        local_median = neighbourhood[len(neighbourhood) // 2]
        if alts[i] < local_median - threshold:
            continue
        keep.append(i)

    dropped = n - len(keep)
    return (
        [times[i] for i in keep],
        [lats[i]  for i in keep],
        [lons[i]  for i in keep],
        [alts[i]  for i in keep],
        dropped,
    )


# ── 2. Load data ───────────────────────────────────────────────────────────

times, lats, lons, alts = parse_gpgga(FLIGHT_DATA_CSV)
times, lats, lons, alts, n_dropped = filter_altitude_spikes(times, lats, lons, alts)

t0 = times[0]

# Keep only data points that occurred within 4200 seconds of t0
cutoff_seconds = 4700.0
valid_indices = [i for i, t in enumerate(times) if (t - t0) <= cutoff_seconds]

times = [times[i] for i in valid_indices]
lats = [lats[i] for i in valid_indices]
lons = [lons[i] for i in valid_indices]
alts = [alts[i] for i in valid_indices]

times_min = [(t - t0) / 60.0 for t in times]

print(f"Flight data: {FLIGHT_DATA_CSV}")
print(f"Parsed {len(lats)} GPS fixes  ({n_dropped} altitude spikes removed)")
print(f"  Lat range:  {min(lats):.4f} to {max(lats):.4f}")
print(f"  Lon range:  {min(lons):.4f} to {max(lons):.4f}")
print(f"  Alt range:  {min(alts):.1f} to {max(alts):.1f} m MSL")

# ── 6. 3D terrain + flight path (PyVista) ─────────────────────────────────

if not os.path.isfile(DEM_FILE):
    print(f"\n[3D] DEM file '{DEM_FILE}' not found — skipping 3D terrain view.")
    print("     Download SRTM tile N42W085 (.hgt or .tif) and place it here,")
    print("     then update DEM_FILE at the top of this script if the name differs.")
else:
    import pyvista as pv
    import rasterio
    from rasterio.windows import from_bounds
    from pyproj import Transformer

    flight_lats = np.array(lats)
    flight_lons = np.array(lons)
    flight_alts = np.array(alts)

    _mlon = float(np.median(flight_lons))
    _zone = int(math.floor((_mlon + 180.0) / 6.0)) + 1
    utm_epsg = 32600 + _zone  # WGS84 UTM north (flight latitudes are N)
    print(f"[3D] UTM zone {_zone}  (EPSG:{utm_epsg}, median lon {_mlon:.3f}°)")

    lat_lo, lat_hi = flight_lats.min(), flight_lats.max()
    lon_lo, lon_hi = flight_lons.min(), flight_lons.max()

    # ── 6a. Read DEM, cropped to flight bounding box ──────────────────────
    print("\n[3D] Loading DEM ...")
    with rasterio.open(DEM_FILE) as dem:
        window = from_bounds(
            lon_lo - DEM_MARGIN_DEG, lat_lo - DEM_MARGIN_DEG,
            lon_hi + DEM_MARGIN_DEG, lat_hi + DEM_MARGIN_DEG,
            dem.transform,
        )
        raw_h = int(window.height)
        raw_w = int(window.width)
        step = max(1, max(raw_h, raw_w) // DEM_MAX_DIM)
        out_h = max(1, raw_h // step)
        out_w = max(1, raw_w // step)
        print(f"     DEM window: {raw_w} x {raw_h} → reading as {out_w} x {out_h}")

        from rasterio.enums import Resampling
        elevation = dem.read(
            1, window=window, boundless=True, fill_value=-32768,
            out_shape=(out_h, out_w),
            resampling=Resampling.bilinear,
        ).astype(np.float32)
        nodata = dem.nodata
        win_transform = dem.window_transform(window)

    elevation[elevation <= -1000] = np.nan
    if nodata is not None and nodata > -1000:
        elevation[elevation == nodata] = np.nan
    fill_elev = float(np.nanmedian(elevation))
    elevation[np.isnan(elevation)] = fill_elev

    nrows, ncols = elevation.shape
    if elevation.size == 0:
        raise SystemExit("[3D] DEM does not cover the flight area — check DEM_FILE.")

    elev_min = np.nanmin(elevation)
    elev_max = np.nanmax(elevation)
    print(f"     Elevation range: {elev_min:.1f} – {elev_max:.1f} m  "
          f"(relief: {elev_max - elev_min:.1f} m)")

    col_scale = raw_w / ncols
    row_scale = raw_h / nrows
    dem_lons = win_transform.c + (np.arange(ncols) * col_scale + 0.5) * win_transform.a
    dem_lats = win_transform.f + (np.arange(nrows) * row_scale + 0.5) * win_transform.e

    # Flip so rows go south→north (ascending Y) — gives correct upward face normals
    dem_lats = dem_lats[::-1]
    elevation = elevation[::-1, :]

    # ── 6b. Project to UTM 16N (EPSG:32616) for metric X / Y / Z ─────────
    transformer = Transformer.from_crs(
        "EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True,
    )

    lon_grid, lat_grid = np.meshgrid(dem_lons, dem_lats)
    x_dem, y_dem = transformer.transform(lon_grid, lat_grid)
    x_flight, y_flight = transformer.transform(flight_lons, flight_lats)

    if PATH_UTM_MIRROR in ("x", "y", "both"):
        xc = 0.5 * (float(np.nanmin(x_dem)) + float(np.nanmax(x_dem)))
        yc = 0.5 * (float(np.nanmin(y_dem)) + float(np.nanmax(y_dem)))
        if PATH_UTM_MIRROR in ("x", "both"):
            x_flight = 2.0 * xc - x_flight
        if PATH_UTM_MIRROR in ("y", "both"):
            y_flight = 2.0 * yc - y_flight
        print(f"[3D] Flight path UTM mirror: {PATH_UTM_MIRROR!r} (center {xc:.0f} E, {yc:.0f} N)")

    # ── 6c. Build terrain mesh ────────────────────────────────────────────
    print("[3D] Building terrain mesh ...")
    terrain = pv.StructuredGrid(
        x_dem, y_dem, elevation * VERTICAL_EXAG,
    )
    terrain["Elevation (m)"] = elevation.ravel(order="F")

    # ── 6c-2. Optional satellite imagery overlay ──────────────────────────
    sat_texture = None
    if SATELLITE_OVERLAY:
        try:
            margin = DEM_MARGIN_DEG
            merc_to_utm = Transformer.from_crs(
                "EPSG:3857", f"EPSG:{utm_epsg}", always_xy=True,
            )

            if os.path.isfile(SAT_CACHE):
                print(f"[3D] Loading cached satellite image ({SAT_CACHE}) ...")
                cached = np.load(SAT_CACHE)
                img = cached["img"]
                ext = cached["ext"]
            else:
                import contextily as cx
                print("[3D] Downloading satellite tiles (first run only) ...")
                img, ext = cx.bounds2img(
                    lon_lo - margin, lat_lo - margin,
                    lon_hi + margin, lat_hi + margin,
                    ll=True,
                    source=cx.providers.Esri.WorldImagery,
                    zoom=10,
                )
                np.savez_compressed(SAT_CACHE, img=img, ext=np.array(ext))
                print(f"     Saved to {SAT_CACHE} for future runs.")

            # ext = (left, right, bottom, top) in Web Mercator (EPSG:3857)
            img_left, img_bottom = merc_to_utm.transform(ext[0], ext[2])
            img_right, img_top = merc_to_utm.transform(ext[1], ext[3])

            pts = terrain.points
            u = (pts[:, 0] - img_left) / (img_right - img_left)
            v = (pts[:, 1] - img_bottom) / (img_top - img_bottom)
            if SATELLITE_TEX_FLIP_U:
                u = 1.0 - u
            if SATELLITE_TEX_FLIP_V:
                v = 1.0 - v
            terrain.active_texture_coordinates = np.column_stack([u, v])
            if SATELLITE_TEX_FLIP_U or SATELLITE_TEX_FLIP_V:
                print(f"     Texture UV flips: U={SATELLITE_TEX_FLIP_U}  V={SATELLITE_TEX_FLIP_V}")

            tex_img = img[:, :, :3]
            if SATELLITE_IMAGE_FLIPUD:
                tex_img = np.flipud(tex_img)
            sat_texture = pv.Texture(tex_img)
            print(f"     Satellite image: {img.shape[1]} x {img.shape[0]} px")
        except ImportError:
            print("[3D] contextily not installed — falling back to elevation colormap.")
            print("     Install with:  pip install contextily")
        except Exception as e:
            print(f"[3D] Satellite download failed ({e}) — using elevation colormap.")

    # ── 6d. Build two splines: ascent + descent ─────────────────────────
    #   Split at the longest time gap (where GPS lost fix near burst).
    path_pts = np.column_stack([
        x_flight, y_flight, flight_alts * VERTICAL_EXAG,
    ])

    time_arr = np.array(times)
    dt = np.diff(time_arr)
    split_idx = int(np.argmax(dt)) + 1
    gap_secs = dt[split_idx - 1]
    print(f"[3D] Splitting at index {split_idx}  "
          f"(gap of {gap_secs:.0f}s between last ascent fix and first descent fix)")

    ascent_pts   = path_pts[:split_idx]
    descent_pts  = path_pts[split_idx:]
    ascent_alts  = flight_alts[:split_idx]
    descent_alts = flight_alts[split_idx:]

    n_asc  = min(len(ascent_pts)  * 5, 5000)
    n_desc = min(len(descent_pts) * 5, 5000)

    ascent_spline  = pv.Spline(ascent_pts,  n_points=n_asc)
    descent_spline = pv.Spline(descent_pts, n_points=n_desc)

    tube_r = (float(np.nanmax(x_dem)) - float(np.nanmin(x_dem))) * TUBE_RADIUS_FRAC
    ascent_tube  = ascent_spline.tube(radius=tube_r)
    descent_tube = descent_spline.tube(radius=tube_r)

    _save_mpl_flight_3d(
        ascent_pts[:, 0],  ascent_pts[:, 1],
        np.asarray(ascent_alts, dtype=np.float64),
        descent_pts[:, 0], descent_pts[:, 1],
        np.asarray(descent_alts, dtype=np.float64),
        MPL_FLIGHT_3D_PNG,
    )
    print(f"[3D] Matplotlib flight figure saved: {MPL_FLIGHT_3D_PNG}")

    # ── 6e. Launch interactive viewer ─────────────────────────────────────
    print("[3D] Launching viewer ...")
    pl = pv.Plotter(window_size=[1400, 900],
                    title="Balloon Flight — 3D Terrain View")

    if sat_texture is not None:
        pl.add_mesh(terrain, texture=sat_texture, lighting=True)
    else:
        pl.add_mesh(terrain, scalars="Elevation (m)", cmap="gist_earth",
                    show_scalar_bar=False, lighting=True)
    # Flat shading — pale Phong-lit tubes look washed out / semi-transparent.
    pl.add_mesh(ascent_tube, color="lightskyblue", lighting=True, opacity=1.0)
    pl.add_mesh(descent_tube, color="orangered", lighting=True, opacity=1.0)

    ruler = _ascent_altitude_ruler(
        ascent_pts,
        ascent_alts,
        VERTICAL_EXAG,
        x_dem,
        y_dem,
        tube_r,
    )
    rr = ruler["spine_tube_radius"]
    pl.add_mesh(ruler["spine"].tube(radius=rr), color="#252525", lighting=False)  # type: ignore
    pl.add_mesh(
        ruler["ticks"],
        color="#252525",
        lighting=False,
        line_width=5,
        render_lines_as_tubes=True,
    )  # type: ignore
    pl.add_point_labels(
        ruler["label_points"],
        ruler["labels"],
        text_color="#FFFFFF",
        point_size=0,
        shape=None,
        always_visible=True,
        font_size=11,
    )  # type: ignore

    pl.show()
