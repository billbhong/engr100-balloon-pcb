import matplotlib.pyplot as plt

# ── 1. Read and parse $GPGGA lines from the GPS data file ──────────────────

def parse_gpgga(filename):
    """Parse $GPGGA sentences and return lists of time, lat, lon.

    Handles messy logging where GPGGA sentences may be concatenated with
    other NMEA sentences on the same line, appear multiple times per line,
    or be truncated mid-field.
    """
    times = []       # seconds since midnight UTC
    latitudes = []   # decimal degrees (positive = N)
    longitudes = []  # decimal degrees (positive = E, negative = W)

    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            # Find every $GPGGA occurrence in the line (may not be at start)
            start = 0
            while True:
                idx = line.find('$GPGGA', start)
                if idx == -1:
                    break
                # Extract from this $GPGGA to the next '$' or end-of-line
                end = line.find('$', idx + 1)
                sentence = line[idx:end] if end != -1 else line[idx:]
                start = idx + 1

                fields = sentence.split(',')
                if len(fields) < 7:
                    continue
                # Fix quality 0 = no fix; also skip if field is empty
                if not fields[6] or fields[6] == '0':
                    continue
                # Need non-empty lat, N/S, lon, E/W, and time
                if not all(fields[i] for i in (1, 2, 3, 4, 5)):
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
                except (ValueError, IndexError):
                    continue

                # if not (42.0 <= lat <= 43.0) or not (-84.5 <= lon <= -83.0):
                if not (30.0 <= lat <= 55.0) or not (-95.0 <= lon <= -70.0):
                    continue

                times.append(t)
                latitudes.append(lat)
                longitudes.append(lon)

    return times, latitudes, longitudes


# ── 2. Load data ───────────────────────────────────────────────────────────

times, lats, lons = parse_gpgga('Flight_Data.CSV')

# Convert time to minutes from start for easier reading
t0 = times[0]

# Keep only data points that occurred within 4200 seconds of t0
cutoff_seconds = 4700.0
valid_indices = [i for i, t in enumerate(times) if (t - t0) <= cutoff_seconds]

times = [times[i] for i in valid_indices]
lats = [lats[i] for i in valid_indices]
lons = [lons[i] for i in valid_indices]

times_min = [(t - t0) / 60.0 for t in times]

# ── 3. Create three separate plots ─────────────────────────────────────────

# Plot 1: Latitude vs Time
fig1, ax1 = plt.subplots(figsize=(8, 5))
ax1.plot(times_min, lats, 'b.-')
ax1.set_xlabel('Time (minutes from start)')
ax1.set_ylabel('Latitude (°N)')
ax1.set_title('Latitude vs Time')
ax1.ticklabel_format(useOffset=False, style='plain')
ax1.grid(True)
fig1.tight_layout()
fig1.savefig('lat_vs_time.png', dpi=150)

# Plot 2: Longitude vs Time
fig2, ax2 = plt.subplots(figsize=(8, 5))
ax2.plot(times_min, lons, 'r.-')
ax2.set_xlabel('Time (minutes from start)')
ax2.set_ylabel('Longitude (°W)')
ax2.set_title('Longitude vs Time')
ax2.ticklabel_format(useOffset=False, style='plain')
ax2.grid(True)
fig2.tight_layout()
fig2.savefig('lon_vs_time.png', dpi=150)

# Plot 3: Latitude vs Longitude (map-like view)
fig3, ax3 = plt.subplots(figsize=(8, 6))
ax3.plot(lons, lats, 'g.-')
ax3.plot(lons[0], lats[0], 'ko', markersize=8, label='Start')
ax3.plot(lons[-1], lats[-1], 'rs', markersize=8, label='End')
ax3.set_xlabel('Longitude (°)')
ax3.set_ylabel('Latitude (°)')
ax3.set_title('Latitude vs Longitude')
ax3.legend(loc='upper left', bbox_to_anchor=(1.02, 1), borderaxespad=0)
ax3.set_aspect('equal')
ax3.ticklabel_format(useOffset=False, style='plain')
ax3.grid(True)
fig3.tight_layout()
fig3.savefig('lat_vs_lon.png', dpi=150)

plt.show()

# ── 4. Print sample points for Google Maps ─────────────────────────────────

print('\n=== Sample points for Google Maps (paste into Google Maps) ===')
# Pick ~4 evenly-spaced indices
n = len(lats)
indices = [0, n // 3, 2 * n // 3, n - 1]
for i in indices:
    # Google Maps format: lat, lon  (decimal degrees)
    print(f'  Point {i+1}: {lats[i]:.6f}, {lons[i]:.6f}')

print('\nTo use: go to google.com/maps, paste each "lat, lon" pair into')
print('the search bar, or use Google My Maps to create pins/lines.')

# ── 5. Dump all lat/lon pairs to a text file ─────────────────────────────

with open('latlon.txt', 'w') as f:
    for lat, lon in zip(lats, lons):
        f.write(f'  new google.maps.LatLng({lat:.6f}, {lon:.6f}),\n')
print(f'\nWrote {len(lats)} lat/lon pairs to latlon.txt')
