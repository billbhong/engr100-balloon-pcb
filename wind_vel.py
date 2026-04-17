import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# 1. Load the previously processed data
df = pd.read_csv('wind_shear_results.csv')

# Drop rows where essential plotting data is missing
plot_df = df.dropna(subset=['alt_m', 'u', 'v', 'wind_shear']).copy()

# Calculate the overall wind magnitude (speed)
plot_df['wind_mag'] = np.sqrt(plot_df['u']**2 + plot_df['v']**2)

# 2. Separate Ascent and Descent
# Find the index of the maximum altitude. 
peak_idx = plot_df['alt_m'].idxmax()

# Split the dataframe into ascent (before peak) and descent (after peak)
ascent_df = plot_df.loc[:peak_idx]
descent_df = plot_df.loc[peak_idx+1:]

# 3. Set up the plotting area
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 8), sharey=True)

# --- Plot 1: Wind Magnitude vs Altitude ---
# Ascent (steelblue)
ax1.plot(ascent_df['wind_mag'], ascent_df['alt_m'], label='Ascent', color='steelblue', linestyle='-')

# Descent (orangered)
ax1.plot(descent_df['wind_mag'], descent_df['alt_m'], label='Descent', color='orangered', linestyle='-')

ax1.set_xlabel('Wind Magnitude (m/s)', fontsize=12)
ax1.set_ylabel('Altitude (m)', fontsize=12)
ax1.set_title('Wind Velocity Magnitude vs Altitude', fontsize=14)
ax1.grid(True, linestyle=':', alpha=0.7)
ax1.legend()

# --- Plot 2: Wind Shear vs Altitude ---
# Ascent
ax2.plot(ascent_df['wind_shear'], ascent_df['alt_m'], color='steelblue', 
         alpha=0.6, marker='.', linestyle='none', label='Ascent')

# Descent
ax2.plot(descent_df['wind_shear'], descent_df['alt_m'], color='orangered', 
         alpha=0.6, marker='.', linestyle='none', label='Descent')

ax2.set_xlabel('Wind Shear (1/s)', fontsize=12)
ax2.set_title('Wind Shear vs Altitude', fontsize=14)

# Limit x-axis to filter out extreme spikes based on 95th percentile
shear_95 = plot_df['wind_shear'].quantile(0.95)
if pd.notna(shear_95):
    ax2.set_xlim(0, shear_95 * 2)

ax2.grid(True, linestyle=':', alpha=0.7)
ax2.legend()

# 4. Finalize and save
plt.tight_layout()
plt.savefig('wind_shear_profile_mag.png')
# plt.show()