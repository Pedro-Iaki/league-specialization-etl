# %%
from pathlib import Path
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 8)
plt.rcParams['axes.grid'] = True

# %%
current_dir = Path.cwd().resolve()
cdata_dir = current_dir / "Cleaned_Data"

players_candidates = list(cdata_dir.glob("players_*.parquet"))
if not players_candidates:
    raise ValueError("No players.parquet found in Cleaned_Data Folder!")
latest_players_path = max(players_candidates, key=lambda f: f.stat().st_mtime)

timestamp = latest_players_path.stem.split("_")[-1]

latest_masteries_path = cdata_dir / f"masteries_{timestamp}.parquet"
latest_champions_path = cdata_dir / f"champions_{timestamp}.json"

if not latest_masteries_path.exists():
    raise FileNotFoundError(f"Missing masteries file: {latest_masteries_path}")
if not latest_champions_path.exists():
    raise FileNotFoundError(f"Missing champions file: {latest_champions_path}")

# Load the data
players_temp = pd.read_parquet(latest_players_path)
masteries_temp = pd.read_parquet(latest_masteries_path)

with latest_champions_path.open("r", encoding="utf-8") as f:
    champions_dict = json.load(f)
champions_df = pd.DataFrame(champions_dict.values(), index=champions_dict.keys())
champions_df['name'] = champions_df.index
champions_df['key'] = champions_df['key'].astype(int)
champions_df.set_index('key', inplace=True)
#positions_df = pd.read_csv(current_dir / 'champion_positions.csv')
#positions_df['client_positions'] = positions_df['client_positions'].str.split(', ')
#positions_df['external_positions'] = positions_df['external_positions'].str.split(', ')

# Clean up temporary variables
del current_dir, cdata_dir, players_candidates, latest_players_path, timestamp
del latest_masteries_path, latest_champions_path, f, champions_dict

# %%

masteries_temp['lastPlayTime'] = pd.to_datetime(masteries_temp['lastPlayTime'], unit='ms')

masteries_temp['championName'] = masteries_temp['championId'].map(champions_df['name'])

masteries_df = masteries_temp.set_index(['puuid', 'championId'])[['championPoints', 'lastPlayTime']]

players_df = players_temp.set_index('puuid').drop(
    columns=['queueType', 'inactive', 'hotStreak', 'leaguePoints']
)

del masteries_temp, players_temp
# %%
champions_df['client_positions'] = champions_df['client_positions'].str.split(r",\s*")
champions_df['external_positions'] = champions_df['external_positions'].str.split(r",\s*")
def get_expected_positions(row):
    client = row['client_positions']
    external = row['external_positions']

    if 'Bottom' in client:
        return ['Bottom']

    if client == ['Jungle']:
        return ['Jungle']

    return list(set(client+external))

champions_df['expected_positions'] = champions_df.apply(
    get_expected_positions,
    axis=1
)
# %%
champion_expected_positions = champions_df['expected_positions'].to_dict()

def calculate_mastery_pool_profile(player_masteries):
    """Calculate mastery-pool specialization variables for one player,
    including main role and ordered pool champion list."""
    POOL_GAP_MULTIPLIER = 1.5

    mastery_all = pd.to_numeric(player_masteries, errors='coerce').dropna()
    mastery_all = mastery_all[mastery_all > 0]

    if mastery_all.empty:
        return pd.Series({
            'pool_size': np.nan,
            'pool_exclusivity': np.nan,
            'pool_bias': np.nan,
            'pool_depth': np.nan,
            'main_role': np.nan,
            'pool_champions': [],
        })

    mastery_sorted = mastery_all.sort_values(ascending=False)
    total_mastery = mastery_sorted.sum()

    top10 = mastery_sorted.head(10)
    n_top10 = len(top10)

    pool_size = 10
    pool_exclusivity = np.nan

    if n_top10 == 1:
        pool_size = 1
    else:
        top10_values = top10.to_numpy(dtype=float)
        log_gaps = np.log(top10_values[:-1] / top10_values[1:])

        largest_gap_idx = int(np.argmax(log_gaps))
        largest_log_gap = float(log_gaps[largest_gap_idx])
        median_log_gap = float(np.median(log_gaps))

        if median_log_gap > 0:
            pool_exclusivity = largest_log_gap / median_log_gap

            if largest_log_gap >= POOL_GAP_MULTIPLIER * median_log_gap:
                pool_size = largest_gap_idx + 1

    pool_members = mastery_sorted.head(min(pool_size, n_top10))
    top10_total = top10.sum()

    # ---------------------------------------------------------------
    # POOL CHAMPIONS ORDERED BY MASTERY
    # ---------------------------------------------------------------
    pool_champions = list(pool_members.index.get_level_values('championId'))

    # ---------------------------------------------------------------
    # MAIN ROLE FROM EXPECTED POSITIONS
    # ---------------------------------------------------------------
    role_counts = {}

    for champ_id in pool_champions:
        roles = champion_expected_positions.get(champ_id)
    
        if isinstance(roles, list):
            for role in roles:
                if isinstance(role, str):
                    role_counts[role] = role_counts.get(role, 0) + 1
    
    if role_counts:
        # Get the maximum count
        max_count = max(role_counts.values())
        # Get ALL roles with the maximum count (handles ties)
        main_roles = sorted([role for role, count in role_counts.items() if count == max_count])
        
        # Store as list if multiple roles tie, or as single string if one clear winner
        if len(main_roles) == 1:
            main_role = main_roles[0]
        else:
            main_role = main_roles  # Store as list for ties
    else:
        main_role = np.nan

    # ---------------------------------------------------------------
    # POOL BIAS
    # ---------------------------------------------------------------
    if top10_total > 0 and len(pool_members) > 0:
        pool_normalized = pool_members / top10_total
        pool_bias = 1 - float(pool_normalized.max() - pool_normalized.min())
    else:
        pool_bias = np.nan

    # ---------------------------------------------------------------
    # POOL DEPTH
    # ---------------------------------------------------------------
    if total_mastery > 0:
        pool_depth = float(pool_members.sum() / total_mastery)
    else:
        pool_depth = np.nan

    return pd.Series({
        'pool_size': pool_size,
        'pool_exclusivity': pool_exclusivity,
        'pool_bias': pool_bias,
        'pool_depth': pool_depth,
        'main_roles': main_role,
        'pool_champions': pool_champions,
    })


# ---------------------------------------------------------------
# PIPELINE INTEGRATION
# ---------------------------------------------------------------

# Generate profiles per player
player_mastery_profiles = (
    masteries_df['championPoints']
    .groupby(level='puuid')
    .apply(calculate_mastery_pool_profile)
    .unstack()
)

# Safe Merge / Update logic without re-assigning inplace methods:
profile_cols = [
    'pool_size',
    'pool_exclusivity',
    'pool_bias',
    'pool_depth',
    'main_roles',
    'pool_champions',
]

# Drop existing columns if they exist before joining to avoid duplicate suffix errors (_x, _y)
players_df.drop(
    columns=[c for c in profile_cols if c in players_df.columns],
    inplace=True
)
players_df = players_df.join(player_mastery_profiles)

# Ensure pool_size is nullable integer
players_df['pool_size'] = players_df['pool_size'].astype('Int64')

# Optional diagnostic output.
print("\n=== PLAYER MASTERY POOL PROFILE ===")
print(players_df[profile_cols].describe())

print("\nExample player mastery pool profiles:")
print(players_df[profile_cols].head(10))
del player_mastery_profiles
del profile_cols
# %%
# Diagnose the data
print("=== DATA DIAGNOSTICS ===")
print(f"Number of players: {len(players_df)}")
print(f"Number of mastery entries: {len(masteries_df)}")
print(f"\nPlayers DataFrame columns:")
print(players_df.columns.tolist())
print(f"\nMasteries DataFrame columns:")
print(masteries_df.columns.tolist())
print(f"\nFirst 5 rows of players_df:")
print(players_df.head())
print(f"\nFirst 5 rows of masteries_df:")
print(masteries_df.head())

# Check the tier column
print(f"\nUnique values in 'tier' column:")
print(players_df['tier'].unique())
print(f"\nValue counts:")
print(players_df['tier'].value_counts(dropna=False))

# %%
# Add mastery_sum to players_df
mastery_sum = masteries_df.groupby(level='puuid')['championPoints'].sum()
players_df['mastery_sum'] = mastery_sum

print(f"\nPlayers with mastery_sum:")
print(players_df[['mastery_sum']].head())
print(f"\nMastery sum statistics:")
print(players_df['mastery_sum'].describe())

# %%
# Define rank order (adjust based on your actual data)
rank_order = [
    'IRON', 'BRONZE', 'SILVER', 'GOLD', 'PLATINUM',
    'EMERALD', 'DIAMOND'
]

# Convert tier to categorical with ordering (we'll do this later for plots)
players_df['tier'] = pd.Categorical(players_df['tier'], categories=rank_order, ordered=True)

# %%
# ===================== 1. CORRELATION HEATMAP =====================
# Create a player x champion matrix of championPoints
mastery_pivot = masteries_df.reset_index().pivot(
    index='puuid',
    columns='championId',
    values='championPoints'
).fillna(0)

# Select top 20 champions by total mastery points for readability
top_n = 20
champion_totals = mastery_pivot.sum().sort_values(ascending=False).head(top_n)
print(f"\nTop {top_n} champions by total mastery points:")
print(champion_totals)

subset = mastery_pivot[champion_totals.index]

# Compute correlation matrix
corr_matrix = subset.corr()

# Map championId -> name only for display, right before plotting
corr_matrix_named = corr_matrix.rename(
    index=champions_df['name'],
    columns=champions_df['name']
)

# Plot heatmap
plt.figure(figsize=(16, 14))
sns.heatmap(
    corr_matrix_named,
    annot=False,
    cmap='coolwarm',
    center=0,
    square=True,
    linewidths=0.5,
    cbar_kws={"shrink": 0.8},
    vmin=-1,
    vmax=1
)
plt.title(f'Correlation of Mastery Points Among Top {top_n} Champions', fontsize=16, fontweight='bold')
plt.xticks(rotation=45, ha='right', fontsize=10)
plt.yticks(rotation=0, fontsize=10)
plt.tight_layout()
plt.show()

# %%
# ===================== 2. LINE PLOT FOR SPECIFIC CHAMPIONS =====================
# Build ID -> name mapping once, reuse everywhere for display
id_to_name = champions_df['name']

# List of champions to analyze (adjust names to match your ids exactly)
champions_of_interest = ['Mordekaiser', 'TahmKench', 'Irelia', 'Riven', 'KSante', 'Galio']
ids_evaluated = [int(champions_df[champions_df['id']==c].index[0]) for c in champions_of_interest]

# Check which champions exist in the data
available_champions = masteries_df.index.get_level_values('championId').unique()
print(f"\nChampions of interest availability:")
for champ in ids_evaluated:
    exists = champ in available_champions
    print(f"  {id_to_name.get(champ, champ)}: {'✓ Found' if exists else '✗ Not found'}")

# Filter masteries for these champions
champion_mask = masteries_df.index.get_level_values('championId').isin(ids_evaluated)
filtered_masteries = masteries_df[champion_mask].reset_index()

print(f"\nNumber of mastery entries for selected champions: {len(filtered_masteries)}")

# Merge with player tier
merged_data = filtered_masteries.merge(
    players_df[['tier']],   # using tier column
    left_on='puuid',
    right_index=True,
    how='left'
)

# Drop rows where tier is NaN (unranked players)
merged_data_clean = merged_data.dropna(subset=['tier'])
print(f"Rows after dropping missing ranks: {len(merged_data_clean)}")

# Group by tier and champion, compute average mastery
avg_mastery_by_rank = merged_data_clean.groupby(
    ['tier', 'championId'],
    observed=False
)['championPoints'].mean().unstack()

print("\nAverage mastery points by tier and champion:")
print(avg_mastery_by_rank.rename(columns=id_to_name))

# Plot line chart
plt.figure(figsize=(14, 8))
colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
markers = ['o', 's', '^', 'D', 'v']

for i, champ in enumerate(ids_evaluated):
    if champ in avg_mastery_by_rank.columns:
        plt.plot(
            avg_mastery_by_rank.index,
            avg_mastery_by_rank[champ],
            marker=markers[i % len(markers)],
            linewidth=2,
            markersize=8,
            color=colors[i % len(colors)],
            label=id_to_name.get(champ, champ)
        )

plt.title('Average Mastery Points per Rank for Selected Champions', fontsize=16, fontweight='bold')
plt.xlabel('Tier', fontsize=14)
plt.ylabel('Average Champion Points', fontsize=14)
plt.legend(fontsize=12, loc='best')
plt.xticks(rotation=45, ha='right')
plt.grid(True, linestyle='--', alpha=0.7)
plt.tight_layout()
plt.show()

# %%
# ===================== 3. BAR PLOT OF AVERAGE MASTERY_SUM PER RANK =====================
# (No championId involved here — this is per-tier, not per-champion — left unchanged)
players_ranked = players_df.dropna(subset=['tier'])

avg_mastery_sum_by_rank = players_ranked.groupby('tier', observed=False)['mastery_sum'].mean()

print("\nAverage mastery sum by tier:")
print(avg_mastery_sum_by_rank)

plt.figure(figsize=(12, 8))
bars = plt.bar(
    avg_mastery_sum_by_rank.index,
    avg_mastery_sum_by_rank.values,
    color='steelblue',
    edgecolor='black',
    linewidth=1.5
)

for bar, value in zip(bars, avg_mastery_sum_by_rank.values):
    plt.text(
        bar.get_x() + bar.get_width()/2,
        bar.get_height() + (bar.get_height() * 0.01),
        f'{value:,.0f}',
        ha='center',
        va='bottom',
        fontsize=10,
        fontweight='bold'
    )

plt.title('Average Total Mastery Points per Rank', fontsize=16, fontweight='bold')
plt.xlabel('Tier', fontsize=14)
plt.ylabel('Average Sum of Mastery Points', fontsize=14)
plt.xticks(rotation=45, ha='right')
plt.grid(axis='y', linestyle='--', alpha=0.7)
plt.tight_layout()
plt.show()

# %%
# ===================== 4. NORMALIZED LINE PLOT =====================
normalized_mastery = avg_mastery_by_rank.div(avg_mastery_sum_by_rank, axis=0)
normalized_mastery = normalized_mastery * 100

print("\nNormalized average mastery (percentage of overall average mastery sum):")
print(normalized_mastery.rename(columns=id_to_name))

plt.figure(figsize=(14, 8))
for i, champ in enumerate(ids_evaluated):
    if champ in normalized_mastery.columns:
        plt.plot(
            normalized_mastery.index,
            normalized_mastery[champ],
            marker=markers[i % len(markers)],
            linewidth=2,
            markersize=8,
            color=colors[i % len(colors)],
            label=id_to_name.get(champ, champ)
        )

plt.title('Normalized Champion Mastery per Rank (Relative to Overall Average)', fontsize=16, fontweight='bold')
plt.xlabel('Tier', fontsize=14)
plt.ylabel('Normalized Mastery (%)', fontsize=14)
plt.legend(fontsize=12, loc='best')
plt.xticks(rotation=45, ha='right')
plt.grid(True, linestyle='--', alpha=0.7)
plt.tight_layout()
plt.show()
# %%
# Additional summary statistics
print("\n=== SUMMARY STATISTICS ===")
print("\nTop 10 players by total mastery:")
top_players = players_df.nlargest(10, 'mastery_sum')[['mastery_sum']]
print(top_players)

print("\nMastery distribution by champion (top 10):")
champion_stats = masteries_df.groupby(level='championId')['championPoints'].agg(['count', 'mean', 'sum'])
champion_stats = champion_stats.sort_values('sum', ascending=False).head(10)
print(champion_stats)

print("\nRank distribution:")
tier_dist = players_df['tier'].value_counts(dropna=False)
print(tier_dist)

# %%
# ===================== SETUP FOR ADDITIONAL ANALYSES =====================
import numpy as np
from collections import Counter
from scipy import stats

MIN_SAMPLE = 50  # minimum group size before including in a plot
ROLES = ['Top', 'Jungle', 'Middle', 'Bottom', 'Support']

id_to_name = champions_df['name']  # championId -> name, reused throughout

role_colors = {
    'Top': '#1f77b4', 'Jungle': '#2ca02c', 'Middle': '#ff7f0e',
    'Bottom': '#d62728', 'Support': '#9467bd'
}

def as_list(x):
    """Coerce a value to a list; NaN/None -> [], bare scalars get wrapped."""
    if isinstance(x, list):
        return x
    if pd.isna(x):
        return []
    return [x]

# Ensure tier is an ordered categorical (adjust to your actual tier labels)
tier_order = ['IRON', 'BRONZE', 'SILVER', 'GOLD', 'PLATINUM', 'EMERALD',
              'DIAMOND']
if not (isinstance(players_df['tier'].dtype, pd.CategoricalDtype) and players_df['tier'].cat.ordered):
    players_df['tier'] = pd.Categorical(players_df['tier'], categories=tier_order, ordered=True)

# Single canonical filtered df, reused by every tier-based section below
ranked_df = players_df.dropna(subset=['tier']).copy()


# %%
# ===================== 1. SPECIALIZATION VS MAIN ROLE =====================
metrics = ['pool_depth', 'pool_bias', 'pool_exclusivity']

roles_flat = players_df[['main_roles', 'pool_size'] + metrics].copy()
roles_flat['main_roles'] = roles_flat['main_roles'].apply(as_list)
roles_flat = roles_flat.explode('main_roles')
roles_clean = roles_flat.dropna(subset=['main_roles'] + metrics)

role_counts = roles_clean['main_roles'].value_counts()
valid_roles = [r for r in ROLES if role_counts.get(r, 0) > MIN_SAMPLE]
roles_clean = roles_clean[roles_clean['main_roles'].isin(valid_roles)]
roles_clean['pool_exclusivity_log'] = np.log1p(roles_clean['pool_exclusivity'].astype(float))

fig, axes = plt.subplots(2, 2, figsize=(16, 12))

sns.boxplot(data=roles_clean, x='main_roles', y='pool_depth', order=valid_roles,
            hue='main_roles', palette=role_colors, legend=False, ax=axes[0, 0])
axes[0, 0].set_title('Pool Depth by Main Role', fontweight='bold')

sns.boxplot(data=roles_clean, x='main_roles', y='pool_bias', order=valid_roles,
            hue='main_roles', palette=role_colors, legend=False, ax=axes[0, 1])
axes[0, 1].set_title('Pool Bias by Main Role', fontweight='bold')

sns.boxplot(data=roles_clean, x='main_roles', y='pool_exclusivity_log', order=valid_roles,
            hue='main_roles', palette=role_colors, legend=False, ax=axes[1, 0])
axes[1, 0].set_title('Pool Exclusivity (log1p) by Main Role', fontweight='bold')

pool_size_by_role = roles_clean.groupby('main_roles', observed=True)['pool_size'].mean().reindex(valid_roles)
axes[1, 1].bar(pool_size_by_role.index, pool_size_by_role.values,
                color=[role_colors.get(r, 'steelblue') for r in pool_size_by_role.index],
                edgecolor='black')
axes[1, 1].set_title('Average Pool Size by Main Role', fontweight='bold')
for i, (role, n) in enumerate(role_counts[valid_roles].items()):
    axes[1, 1].text(i, pool_size_by_role[role], f'n={n}', ha='center', va='bottom', fontsize=8)

for ax in axes.flat:
    ax.set_xlabel('Main Role')
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True, linestyle='--', alpha=0.5, axis='y')

plt.tight_layout()
plt.show()


# %%
# ===================== 2. TOP-20 CHAMPION HEATMAPS PER ROLE =====================
masteries_reset = masteries_df.reset_index()  # puuid, championId, championPoints, ...

fig, axes = plt.subplots(1, 5, figsize=(35, 7))

for ax, role in zip(axes, ROLES):
    role_players = players_df[players_df['main_roles'].apply(lambda r: role in as_list(r))]

    if len(role_players) < MIN_SAMPLE:
        ax.set_title(f'{role} (n={len(role_players)}, insufficient)')
        ax.axis('off')
        continue

    champion_counter = Counter()
    for pool_list in role_players['pool_champions'].dropna():
        champion_counter.update(pool_list)
    top20_ids = [cid for cid, _ in champion_counter.most_common(20)]

    if len(top20_ids) < 2:
        ax.set_title(f'{role} (not enough champions)')
        ax.axis('off')
        continue

    role_masteries = masteries_reset[
        masteries_reset['puuid'].isin(role_players.index) &
        masteries_reset['championId'].isin(top20_ids)
    ]
    mastery_matrix = role_masteries.pivot_table(
        index='puuid', columns='championId', values='championPoints', aggfunc='max'
    ).fillna(0)

    corr_named = mastery_matrix.corr().rename(index=id_to_name, columns=id_to_name)

    sns.heatmap(corr_named, ax=ax, cmap='coolwarm', center=0, vmin=-1, vmax=1,
                square=True, cbar=(role == ROLES[-1]), linewidths=0.3, annot=False)
    ax.set_title(f'{role} (n={len(role_players)})', fontweight='bold')
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45, ha='right', fontsize=8)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=8)

plt.suptitle('Top-20 Champion Mastery Correlation by Main Role', fontsize=18, fontweight='bold', y=1.05)
plt.tight_layout()
plt.show()


# %%
# ===================== 3. SPECIALIZATION VS TIER =====================
tier_counts = ranked_df['tier'].value_counts()
valid_tiers = [t for t in tier_order if tier_counts.get(t, 0) > MIN_SAMPLE]
tier_plot_df = ranked_df[ranked_df['tier'].isin(valid_tiers)].copy()
tier_plot_df['pool_exclusivity_log'] = np.log1p(tier_plot_df['pool_exclusivity'].astype(float))
tier_plot_df = tier_plot_df.reset_index(drop=True)

fig, axes = plt.subplots(2, 2, figsize=(16, 12))

sns.boxplot(data=tier_plot_df, x='tier', y='pool_depth', order=valid_tiers, ax=axes[0, 0])
axes[0, 0].set_title('Pool Depth by Tier', fontweight='bold')

sns.boxplot(data=tier_plot_df, x='tier', y='pool_bias', order=valid_tiers, ax=axes[0, 1])
axes[0, 1].set_title('Pool Bias by Tier', fontweight='bold')

sns.boxplot(data=tier_plot_df, x='tier', y='pool_exclusivity_log', order=valid_tiers, ax=axes[1, 0])
axes[1, 0].set_title('Pool Exclusivity (log1p) by Tier', fontweight='bold')

pool_size_by_tier = tier_plot_df.groupby('tier', observed=True)['pool_size'].mean().reindex(valid_tiers)
axes[1, 1].bar(pool_size_by_tier.index.astype(str), pool_size_by_tier.values,
                color='steelblue', edgecolor='black')
axes[1, 1].set_title('Average Pool Size by Tier', fontweight='bold')
for i, tier in enumerate(valid_tiers):
    axes[1, 1].text(i, pool_size_by_tier[tier], f'n={tier_counts[tier]}', ha='center', va='bottom', fontsize=8)

for ax in axes.flat:
    ax.set_xlabel('Tier')
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True, linestyle='--', alpha=0.5, axis='y')

plt.tight_layout()
plt.show()


# %%
# ===================== 4. TIER VS MAIN ROLE COMPOSITION =====================
roles_by_tier = ranked_df[['tier', 'main_roles']].copy()
roles_by_tier['main_roles'] = roles_by_tier['main_roles'].apply(as_list)
roles_by_tier = roles_by_tier.explode('main_roles').dropna(subset=['main_roles'])

ct = pd.crosstab(roles_by_tier['tier'], roles_by_tier['main_roles'])
ct = ct.reindex(columns=[r for r in ROLES if r in ct.columns])
ct_norm = ct.div(ct.sum(axis=1), axis=0)

fig, ax = plt.subplots(figsize=(14, 8))
bottom = np.zeros(len(ct_norm))
for role in ct_norm.columns:
    ax.bar(ct_norm.index.astype(str), ct_norm[role], bottom=bottom,
           label=role, color=role_colors.get(role), edgecolor='black', linewidth=0.5)
    bottom += ct_norm[role].values

ax.set_title('Main Role Composition by Tier', fontsize=16, fontweight='bold')
ax.set_xlabel('Tier', fontsize=14)
ax.set_ylabel('Proportion of Players', fontsize=14)
ax.legend(title='Main Role', bbox_to_anchor=(1.02, 1.0), loc='upper left')
plt.xticks(rotation=45, ha='right')
plt.tight_layout()
plt.show()


# %%
# ===================== 5. FRESHBLOOD VS MASTERY TOTAL =====================
print(players_df['freshBlood'].value_counts(dropna=False))

fresh_df = players_df.dropna(subset=['freshBlood', 'mastery_sum']).copy()
fresh_df['freshBlood'] = fresh_df['freshBlood'].astype(bool)

plt.figure(figsize=(10, 7))
sns.boxplot(data=fresh_df, x='freshBlood', y='mastery_sum',
            hue='freshBlood', palette=['steelblue', 'darkorange'], legend=False)
plt.yscale('log')
plt.title('Mastery Sum by Freshblood Status', fontsize=16, fontweight='bold')
plt.xlabel('Freshblood')
plt.ylabel('Mastery Sum (log scale)')
plt.tight_layout()
plt.show()

summary = fresh_df.groupby('freshBlood')['mastery_sum'].agg(['mean', 'median', 'count'])
print("\nSummary statistics by freshBlood status:")
print(summary)

g_true = fresh_df.loc[fresh_df['freshBlood'], 'mastery_sum']
g_false = fresh_df.loc[~fresh_df['freshBlood'], 'mastery_sum']
if len(g_true) > 0 and len(g_false) > 0:
    u_stat, p_val = stats.mannwhitneyu(g_true, g_false, alternative='two-sided')
    print(f"\nMann-Whitney U test: U={u_stat:.1f}, p={p_val:.4g}")


# %%
# ===================== 6. MASTERY TOTAL VS TOTAL GAMES =====================
if 'total_games' not in players_df.columns:
    players_df['total_games'] = players_df['wins'] + players_df['losses']

games_df = players_df.dropna(subset=['total_games', 'mastery_sum'])
games_df = games_df[(games_df['total_games'] > 0) & (games_df['mastery_sum'] > 0)]

corr_pearson = games_df['total_games'].corr(games_df['mastery_sum'])
print(f"Pearson correlation (total_games vs mastery_sum): {corr_pearson:.3f}")

plt.figure(figsize=(10, 8))
sns.regplot(data=games_df, x='total_games', y='mastery_sum',
            scatter_kws={'alpha': 0.3, 's': 15}, line_kws={'color': 'red'})
plt.xscale('log')
plt.yscale('log')
plt.title(f'Total Games vs Mastery Sum (r={corr_pearson:.2f})', fontsize=16, fontweight='bold')
plt.xlabel('Total Games (log scale)')
plt.ylabel('Mastery Sum (log scale)')
plt.tight_layout()
plt.show()


# %%
# ===================== 7. MASTERY TOTAL VS SPECIALIZATION =====================
spec_df = players_df.dropna(subset=['pool_depth', 'pool_bias', 'pool_exclusivity', 'pool_size', 'mastery_sum']).copy()
spec_df = spec_df[spec_df['pool_size'] >= 2]  # pool_exclusivity undefined below this, fix later
spec_df[['mastery_sum', 'pool_depth', 'pool_bias','pool_size', 'pool_exclusivity']] = spec_df[['mastery_sum', 'pool_depth', 'pool_bias','pool_size', 'pool_exclusivity']].astype(float)

fig, axes = plt.subplots(2, 2, figsize=(16, 12))

for ax, col in zip([axes[0, 0], axes[0, 1]], ['pool_depth', 'pool_bias']):
    sns.regplot(data=spec_df, x=col, y='mastery_sum', ax=ax,
                scatter_kws={'alpha': 0.3, 's': 15}, line_kws={'color': 'red'})
    r = spec_df[col].corr(spec_df['mastery_sum'])
    ax.set_title(f'Mastery Sum vs {col} (r={r:.2f})', fontweight='bold')

sns.regplot(data=spec_df, x='pool_exclusivity', y='mastery_sum', ax=axes[1, 0],
            scatter_kws={'alpha': 0.3, 's': 15}, line_kws={'color': 'red'})
axes[1, 0].set_yscale('log')
r_excl = spec_df['pool_exclusivity'].corr(spec_df['mastery_sum'])
axes[1, 0].set_title(f'Mastery Sum vs pool_exclusivity (r={r_excl:.2f})', fontweight='bold')

sns.boxplot(data=spec_df, x='pool_size', y='mastery_sum', ax=axes[1, 1])
axes[1, 1].set_yscale('log')
axes[1, 1].set_title('Mastery Sum by Pool Size', fontweight='bold')

plt.tight_layout()
plt.show()


# %%
# ===================== 8. MASTERY TOTAL PER ROLE ACROSS TIERS =====================
roles_by_tier_m = ranked_df[['tier', 'main_roles', 'mastery_sum']].copy()
roles_by_tier_m['main_roles'] = roles_by_tier_m['main_roles'].apply(as_list)
roles_by_tier_m = roles_by_tier_m.explode('main_roles').dropna(subset=['main_roles'])

group_counts = roles_by_tier_m.groupby(['tier', 'main_roles'], observed=True).size()
avg_mastery = roles_by_tier_m.groupby(['tier', 'main_roles'], observed=True)['mastery_sum'].mean()
avg_mastery = avg_mastery.where(group_counts >= MIN_SAMPLE)  # mask thin cells instead of dropping rows

pivot = avg_mastery.unstack()
pivot = pivot.reindex(columns=[r for r in ROLES if r in pivot.columns])

fig, axes = plt.subplots(1, 2, figsize=(20, 8))

for role in pivot.columns:
    axes[0].plot(pivot.index.astype(str), pivot[role], marker='o',
                 color=role_colors.get(role), label=role, linewidth=2)
axes[0].set_title('Average Mastery Sum by Tier and Role', fontweight='bold')
axes[0].set_xlabel('Tier')
axes[0].set_ylabel('Average Mastery Sum')
axes[0].legend(title='Main Role')
axes[0].tick_params(axis='x', rotation=45)
axes[0].grid(True, linestyle='--', alpha=0.5)

sns.heatmap(pivot, annot=True, fmt='.0f', cmap='viridis', ax=axes[1])
axes[1].set_title('Average Mastery Sum (Tier × Role)', fontweight='bold')
axes[1].set_xlabel('Main Role')
axes[1].set_ylabel('Tier')

plt.tight_layout()
plt.show()
# %%
# ===================== 4B. NORMALIZED MASTERY PER RANK - TOP 20 CHAMPIONS PER ROLE =====================
masteries_reset_all = masteries_df.reset_index()  # puuid, championId, championPoints, lastPlayTime

# Merge tier onto every mastery entry once, reused across all 5 role panels
masteries_with_tier = masteries_reset_all.merge(
    players_df[['tier']],
    left_on='puuid',
    right_index=True,
    how='left'
).dropna(subset=['tier'])

fig, axes = plt.subplots(1, 5, figsize=(35, 8), sharey=True)

for ax, role in zip(axes, ROLES):
    # Champions expected to play this role
    role_champ_ids = champions_df.index[
        champions_df['expected_positions'].apply(lambda positions: role in positions)
    ]

    if len(role_champ_ids) == 0:
        ax.set_title(f'{role} (no champions)')
        ax.axis('off')
        continue

    # Top 20 champions for this role by total mastery points across all players
    role_totals = (
        masteries_df.loc[
            masteries_df.index.get_level_values('championId').isin(role_champ_ids),
            'championPoints'
        ]
        .groupby(level='championId')
        .sum()
        .sort_values(ascending=False)
    )
    top20_role_ids = role_totals.head(20).index.tolist()

    # Average mastery per tier for these champions
    role_masteries = masteries_with_tier[masteries_with_tier['championId'].isin(top20_role_ids)]
    avg_by_rank_role = (
        role_masteries.groupby(['tier', 'championId'], observed=False)['championPoints']
        .mean()
        .unstack()
        .reindex(index=rank_order, columns=top20_role_ids)
    )

    # Normalize using the same overall average mastery sum per tier as plot #4
    normalized_role = avg_by_rank_role.div(avg_mastery_sum_by_rank, axis=0) * 100

    cmap = plt.get_cmap('tab20')
    for i, champ_id in enumerate(top20_role_ids):
        ax.plot(
            normalized_role.index,
            normalized_role[champ_id],
            marker='o',
            linewidth=1.5,
            markersize=4,
            color=cmap(i % 20),
            label=id_to_name.get(champ_id, champ_id)
        )

    ax.set_title(f'{role} (top {len(top20_role_ids)})', fontweight='bold')
    ax.set_xlabel('Tier')
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(fontsize=6, loc='upper left', bbox_to_anchor=(1.0, 1.0), ncol=1)

axes[0].set_ylabel('Normalized Mastery (%)')
plt.suptitle(
    'Normalized Champion Mastery per Rank — Top 20 Champions per Role',
    fontsize=18, fontweight='bold', y=1.05
)
plt.tight_layout()
plt.show()
# %%
# ===================== 4B. SELF-NORMALIZED MASTERY TREND PER RANK - TOP 20 PER ROLE =====================
masteries_reset_all = masteries_df.reset_index()  # puuid, championId, championPoints, lastPlayTime

# Merge tier onto every mastery entry once, reused across all 5 role panels
masteries_with_tier = masteries_reset_all.merge(
    players_df[['tier']],
    left_on='puuid',
    right_index=True,
    how='left'
).dropna(subset=['tier'])

fig, axes = plt.subplots(1, 5, figsize=(35, 8), sharey=True)

for ax, role in zip(axes, ROLES):
    # Champions expected to play this role
    role_champ_ids = champions_df.index[
        champions_df['expected_positions'].apply(lambda positions: role in positions)
    ]

    if len(role_champ_ids) == 0:
        ax.set_title(f'{role} (no champions)')
        ax.axis('off')
        continue

    # Top 20 champions for this role by total mastery points across all players
    role_totals = (
        masteries_df.loc[
            masteries_df.index.get_level_values('championId').isin(role_champ_ids),
            'championPoints'
        ]
        .groupby(level='championId')
        .sum()
        .sort_values(ascending=False)
    )
    top20_role_ids = role_totals.head(20).index.tolist()

    # Average mastery per tier for these champions
    role_masteries = masteries_with_tier[masteries_with_tier['championId'].isin(top20_role_ids)]
    avg_by_rank_role = (
        role_masteries.groupby(['tier', 'championId'], observed=False)['championPoints']
        .mean()
        .unstack()
        .reindex(index=rank_order, columns=top20_role_ids)
    )

    # ---- Self-normalize: each champion's own first available tier value = baseline (0%) ----
    self_normalized = pd.DataFrame(index=avg_by_rank_role.index, columns=avg_by_rank_role.columns, dtype=float)
    for champ_id in avg_by_rank_role.columns:
        series = avg_by_rank_role[champ_id]
        valid = series.dropna()
        if valid.empty:
            continue
        baseline = valid.iloc[0]  # first tier with data for this champion
        if baseline == 0:
            continue
        self_normalized[champ_id] = (series / baseline - 1) * 100

    self_normalized = self_normalized.dropna(axis=1, how='all')

    cmap = plt.get_cmap('tab20')
    for i, champ_id in enumerate(self_normalized.columns):
        ax.plot(
            self_normalized.index,
            self_normalized[champ_id],
            marker='o',
            linewidth=1.5,
            markersize=4,
            color=cmap(i % 20),
            label=id_to_name.get(champ_id, champ_id)
        )

    ax.axhline(0, color='black', linewidth=1, linestyle='-', alpha=0.6)
    ax.set_title(f'{role} (top {len(self_normalized.columns)})', fontweight='bold')
    ax.set_xlabel('Tier')
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(fontsize=6, loc='upper left', bbox_to_anchor=(1.0, 1.0), ncol=1)

# Symmetric y-axis around 0 so "halfway = 0%" holds visually across all panels
y_max = max(ax.get_ylim()[1] for ax in axes if ax.has_data())
y_min = min(ax.get_ylim()[0] for ax in axes if ax.has_data())
y_bound = max(abs(y_max), abs(y_min))
for ax in axes:
    if ax.has_data():
        ax.set_ylim(-y_bound, y_bound)

axes[0].set_ylabel('Mastery Trend vs Own Baseline Tier (%)')
plt.suptitle(
    'Self-Normalized Champion Mastery Trend per Rank — Top 20 Champions per Role',
    fontsize=18, fontweight='bold', y=1.05
)
plt.tight_layout()
plt.show()
# %%
# ===================== 4B. DOUBLY-NORMALIZED MASTERY TREND PER RANK - TOP 20 PER ROLE =====================
masteries_reset_all = masteries_df.reset_index()  # puuid, championId, championPoints, lastPlayTime

# Merge tier onto every mastery entry once, reused across all 5 role panels
masteries_with_tier = masteries_reset_all.merge(
    players_df[['tier']],
    left_on='puuid',
    right_index=True,
    how='left'
).dropna(subset=['tier'])

fig, axes = plt.subplots(1, 5, figsize=(35, 8), sharey=True)

for ax, role in zip(axes, ROLES):
    # Champions expected to play this role
    role_champ_ids = champions_df.index[
        champions_df['expected_positions'].apply(lambda positions: role in positions)
    ]

    if len(role_champ_ids) == 0:
        ax.set_title(f'{role} (no champions)')
        ax.axis('off')
        continue

    # Top 20 champions for this role by total mastery points across all players
    role_totals = (
        masteries_df.loc[
            masteries_df.index.get_level_values('championId').isin(role_champ_ids),
            'championPoints'
        ]
        .groupby(level='championId')
        .sum()
        .sort_values(ascending=False)
    )
    top20_role_ids = role_totals.head(20).index.tolist()

    # Average mastery per tier for these champions
    role_masteries = masteries_with_tier[masteries_with_tier['championId'].isin(top20_role_ids)]
    avg_by_rank_role = (
        role_masteries.groupby(['tier', 'championId'], observed=False)['championPoints']
        .mean()
        .unstack()
        .reindex(index=rank_order, columns=top20_role_ids)
    )

    # ---- NORMALIZATION 1: relative to overall average mastery sum per tier (same as plot #4) ----
    tier_normalized = avg_by_rank_role.div(avg_mastery_sum_by_rank, axis=0) * 100

    # ---- NORMALIZATION 2: re-baseline each champion's own resulting curve to its first tier = 0% ----
    double_normalized = pd.DataFrame(index=tier_normalized.index, columns=tier_normalized.columns, dtype=float)
    for champ_id in tier_normalized.columns:
        series = tier_normalized[champ_id]
        valid = series.dropna()
        if valid.empty:
            continue
        baseline = valid.iloc[0]  # first tier with data for this champion, post tier-normalization
        if baseline == 0:
            continue
        double_normalized[champ_id] = (series / baseline - 1) * 100

    double_normalized = double_normalized.dropna(axis=1, how='all')

    cmap = plt.get_cmap('tab20')
    for i, champ_id in enumerate(double_normalized.columns):
        ax.plot(
            double_normalized.index,
            double_normalized[champ_id],
            marker='o',
            linewidth=1.5,
            markersize=4,
            color=cmap(i % 20),
            label=id_to_name.get(champ_id, champ_id)
        )

    ax.axhline(0, color='black', linewidth=1, linestyle='-', alpha=0.6)
    ax.set_title(f'{role} (top {len(double_normalized.columns)})', fontweight='bold')
    ax.set_xlabel('Tier')
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(fontsize=6, loc='upper left', bbox_to_anchor=(1.0, 1.0), ncol=1)

# Symmetric y-axis around 0 so "halfway = 0%" holds visually across all panels
y_max = max(ax.get_ylim()[1] for ax in axes if ax.has_data())
y_min = min(ax.get_ylim()[0] for ax in axes if ax.has_data())
y_bound = max(abs(y_max), abs(y_min))
for ax in axes:
    if ax.has_data():
        ax.set_ylim(-y_bound, y_bound)

axes[0].set_ylabel('Trend vs Own Baseline, Tier-Adjusted (%)')
plt.suptitle(
    'Doubly-Normalized Champion Mastery Trend per Rank — Top 20 Champions per Role',
    fontsize=18, fontweight='bold', y=1.05
)
plt.tight_layout()
plt.show()
# %%
# ===================== SHARED SETUP: ROBUST POOL-FILTERED MASTERY NORMALIZATION =====================
from scipy import stats as scipy_stats

# ---- Tunable parameters ----
MIN_CELL_SAMPLE = 40
CLIP_PERCENTILE = 0
CELL_AGG = 'mean'
AGG_QUANTILE = 0.98          # <-- NEW: set to None for original behaviour, or a quantile for high-tail focus
TRIM_PROPORTION = 0

assert CELL_AGG in ('median', 'mean'), "CELL_AGG must be 'median' or 'mean'"

masteries_reset_all = masteries_df.reset_index()  # puuid, championId, championPoints, lastPlayTime

masteries_with_tier = masteries_reset_all.merge(
    players_df[['tier']],
    left_on='puuid',
    right_index=True,
    how='left'
).dropna(subset=['tier'])

# ---------------------------------------------------------------
# POOL-ONLY MASTERY ENTRIES
# ---------------------------------------------------------------
pool_pairs = (
    players_df['pool_champions']
    .dropna()
    .explode()
    .dropna()
    .reset_index()
)
pool_pairs.columns = ['puuid', 'championId']
pool_pairs['championId'] = pool_pairs['championId'].astype(int)

masteries_pool_only = masteries_with_tier.merge(
    pool_pairs, on=['puuid', 'championId'], how='inner'
)

print(f"Pool-only mastery entries: {len(masteries_pool_only)}")


def clipped_agg(series, clip_pct=CLIP_PERCENTILE, agg=CELL_AGG, quantile=AGG_QUANTILE):
    if quantile is not None:
        return series.quantile(quantile)
    
    if len(series) < 5:
        return series.median() if agg == 'median' else series.mean()
    lo, hi = series.quantile([clip_pct, 1 - clip_pct])
    clipped = series.clip(lo, hi)
    return clipped.median() if agg == 'median' else clipped.mean()


# ---- Tier-wide baseline: robust average mastery per pool-champion entry, per tier ----
avg_champion_mastery_by_tier = (
    masteries_pool_only.groupby('tier', observed=False)['championPoints']
    .apply(clipped_agg)
    .reindex(rank_order)
)

print(f"\nRobust {CELL_AGG} pool-champion mastery per entry, by tier:")
print(avg_champion_mastery_by_tier)


def compute_role_log_fold_change(role):
    """Returns a DataFrame: rows=tier, cols=championId, values=log2 fold-change
    vs. that champion's own first-available tier, after normalizing against
    the tier-wide baseline. Symmetric, so 'doubled' = +1, 'halved' = -1."""
    role_champ_ids = champions_df.index[
        champions_df['expected_positions'].apply(lambda positions: role in positions)
    ]
    if len(role_champ_ids) == 0:
        return pd.DataFrame()

    role_masteries = masteries_pool_only[masteries_pool_only['championId'].isin(role_champ_ids)]

    grouped = role_masteries.groupby(['tier', 'championId'], observed=False)['championPoints']
    agg_by_rank_role = grouped.apply(clipped_agg).unstack().reindex(index=rank_order)
    count_by_rank_role = grouped.count().unstack().reindex(index=rank_order)

    # Mask thin cells
    agg_by_rank_role = agg_by_rank_role.where(count_by_rank_role >= MIN_CELL_SAMPLE)

    # ---- STEP 3 (log-space): champion value vs tier-wide baseline ----
    log_tier_normalized = np.log2(agg_by_rank_role.div(avg_champion_mastery_by_tier, axis=0))

    # ---- STEP 4 (log-space): re-baseline each champion to its own first tier = 0 ----
    log_double_normalized = pd.DataFrame(
        index=log_tier_normalized.index, columns=log_tier_normalized.columns, dtype=float
    )
    for champ_id in log_tier_normalized.columns:
        series = log_tier_normalized[champ_id]
        valid = series.dropna()
        if valid.empty:
            continue
        baseline = valid.iloc[0]
        log_double_normalized[champ_id] = series - baseline

    return log_double_normalized.dropna(axis=1, how='all')


per_role_log_fc = {role: compute_role_log_fold_change(role) for role in ROLES}


def summarize_role_row(row):
    """Central tendency + spread for one tier's row of per-champion log2 fold-changes,
    respecting CELL_AGG. For 'median': median + IQR (25th/75th). For 'mean': trimmed
    mean + mean ± 1 std, which is the natural mean-family analogue of IQR."""
    valid = row.dropna()
    n = len(valid)
    if n == 0:
        return pd.Series({'center': np.nan, 'lower': np.nan, 'upper': np.nan})

    if CELL_AGG == 'median':
        center = valid.median()
        if n >= 5:
            lower, upper = valid.quantile([0.25, 0.75])
        else:
            lower, upper = np.nan, np.nan
    else:  # mean
        center = scipy_stats.trim_mean(valid.values, TRIM_PROPORTION) if n >= 5 else valid.mean()
        if n >= 5:
            sd = valid.std()
            lower, upper = center - sd, center + sd
        else:
            lower, upper = np.nan, np.nan

    return pd.Series({'center': center, 'lower': lower, 'upper': upper})
# %%
# ===================== 4C (v4): TREND PER ROLE, RESPECTS CELL_AGG (median or mean) =====================
fig, ax = plt.subplots(figsize=(14, 9))

role_summary = {}

for role in ROLES:
    df = per_role_log_fc.get(role)
    if df is None or df.empty:
        continue

    summary = df.apply(summarize_role_row, axis=1)
    role_summary[role] = summary['center']

    color = role_colors.get(role)
    ax.plot(summary.index, summary['center'].values, marker='o', linewidth=2.5,
            markersize=8, color=color, label=role)
    ax.fill_between(summary.index, summary['lower'].values, summary['upper'].values,
                     color=color, alpha=0.15)

ax.axhline(0, color='black', linewidth=1, linestyle='-', alpha=0.6)
if AGG_QUANTILE is not None:
    metric_label = f'{int(AGG_QUANTILE*100)}th percentile'
    spread_label = ''
    title_suffix = f'Top {int((1-AGG_QUANTILE)*100)}% Mastery ( {metric_label} )'
else:
    metric_label = CELL_AGG.capitalize()
    spread_label = 'IQR' if CELL_AGG == 'median' else '±1 SD'
    title_suffix = f'{metric_label} ± {spread_label}, Whale-Clipped Cells'
spread_label = 'IQR' if CELL_AGG == 'median' else '±1 SD'
ax.set_title(
    f'{title_suffix}Mastery Trend per Rank by Role (Log2 Fold-Change vs Own Baseline)\n'
    f'Pool Champions Only, {CELL_AGG.capitalize()} ± {spread_label}, Whale-Clipped Cells',
    fontsize=16, fontweight='bold'
)
ax.set_xlabel('Tier', fontsize=14)
ax.set_ylabel('log2(fold change) vs own baseline tier', fontsize=14)
ax.tick_params(axis='x', rotation=45)
ax.legend(title='Role', fontsize=12, loc='best')
ax.grid(True, linestyle='--', alpha=0.7)
plt.tight_layout()
plt.show()

print(f"\n{CELL_AGG.capitalize()} log2 fold-change by role and tier (0 = no change, +1 = doubled, -1 = halved):")
print(pd.DataFrame(role_summary).reindex(index=rank_order))
# %%
# ===================== 4C-RAW (v2): DISTRIBUTION OF LOG2 FOLD-CHANGE PER ROLE, BY TIER (BOXPLOT) =====================
fig, axes = plt.subplots(1, 5, figsize=(30, 7), sharey=True)

for ax, role in zip(axes, ROLES):
    df = per_role_log_fc.get(role)
    if df is None or df.empty:
        ax.set_title(f'{role} (no data)')
        ax.axis('off')
        continue

    long_df = df.reset_index().melt(id_vars='tier', var_name='championId', value_name='log2fc').dropna()
    long_df['tier'] = pd.Categorical(long_df['tier'], categories=rank_order, ordered=True)

    sns.boxplot(
        data=long_df, x='tier', y='log2fc', order=rank_order,
        color=role_colors.get(role), fliersize=2, linewidth=1, ax=ax
    )
    ax.axhline(0, color='black', linewidth=1, alpha=0.6)
    n_champs = df.shape[1]
    if AGG_QUANTILE is not None:
        metric_label = f'{int(AGG_QUANTILE*100)}th percentile'
        spread_label = ''
        title_suffix = f'Top {int((1-AGG_QUANTILE)*100)}% Mastery ( {metric_label} )'
    else:
        metric_label = CELL_AGG.capitalize()
        spread_label = 'IQR' if CELL_AGG == 'median' else '±1 SD'
        title_suffix = f'{metric_label} ± {spread_label}, Whale-Clipped Cells'
    ax.set_title(f'{role} (n_champs={n_champs})', fontweight='bold')
    ax.set_xlabel('Tier')
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True, linestyle='--', alpha=0.4, axis='y')

axes[0].set_ylabel('log2(fold change) vs own baseline tier')
plt.suptitle(
    'Distribution of Pool-Champion Mastery Trend per Tier, by Role\n(Log2 Fold-Change, Whale-Clipped Cells, {title_suffix})',
    fontsize=18, fontweight='bold', y=1.05
)
plt.tight_layout()
plt.show()

# %%
# ===================== SPECIALIST TIER DISTRIBUTION BY ROLE (WITH NORMALIZATION OPTIONS) =====================

# ---- Parameters ----
SPECIALIST_TOP_FRACTION = 0.002          # fraction of mastery entries that qualify as "extreme"
NORMALIZE_BY_TIER_MASTERY = 'per_tier'      # options: 'none', 'per_tier', 'trend'

# Map championId -> role(s)
champ_roles = champions_df[['expected_positions']].explode('expected_positions')
champ_roles = champ_roles.reset_index().rename(columns={'key': 'championId', 'expected_positions': 'role'})
champ_roles['championId'] = champ_roles['championId'].astype(int)

# Overall tier counts (all players)
overall_tier_counts = players_df['tier'].value_counts().reindex(rank_order, fill_value=0)

# If trend normalization is requested, use the tier-wide baseline mastery curve
if NORMALIZE_BY_TIER_MASTERY == 'trend':
    # avg_champion_mastery_by_tier already exists from earlier analysis
    tier_mastery_baseline = avg_champion_mastery_by_tier.reindex(rank_order)
    overall_mean_mastery = tier_mastery_baseline.mean()
    # We'll divide specialist percentages by (tier_mastery_baseline / overall_mean_mastery)
    # so that tiers with average mastery equal to the overall mean get factor 1.
    normalization_factor = tier_mastery_baseline / overall_mean_mastery
elif NORMALIZE_BY_TIER_MASTERY == 'per_tier':
    # Per‑tier thresholds will be computed inside the loop
    pass
else:  # 'none'
    # Global threshold (same for all tiers)
    global_threshold = masteries_pool_only['championPoints'].quantile(1 - SPECIALIST_TOP_FRACTION)
    print(f"Global specialist threshold: {global_threshold:.0f} mastery points")

# ---- Compute specialist percentages per role ----
specialist_pct_by_role = {}
specialist_counts_by_role = {}

for role in ROLES:
    role_champ_ids = champ_roles[champ_roles['role'] == role]['championId'].unique()
    if len(role_champ_ids) == 0:
        continue

    role_masteries = masteries_pool_only[masteries_pool_only['championId'].isin(role_champ_ids)]

    if NORMALIZE_BY_TIER_MASTERY == 'per_tier':
        # Define top X% within each tier separately
        thresholds = role_masteries.groupby('tier')['championPoints'].quantile(1 - SPECIALIST_TOP_FRACTION)
        # Filter entries above their tier's threshold
        extreme_entries = role_masteries[
            role_masteries.apply(
                lambda row: row['championPoints'] >= thresholds[row['tier']], axis=1
            )
        ]
    else:
        # Use global threshold (or none, i.e., no threshold but we need to filter somehow)
        # For 'none' and 'trend', we still use a global threshold to define specialists
        global_threshold = masteries_pool_only['championPoints'].quantile(1 - SPECIALIST_TOP_FRACTION)
        extreme_entries = role_masteries[role_masteries['championPoints'] >= global_threshold]

    specialist_puuids = extreme_entries['puuid'].unique()
    if len(specialist_puuids) == 0:
        specialist_pct_by_role[role] = pd.Series(0, index=rank_order)
        specialist_counts_by_role[role] = 0
        continue

    specialist_tier_counts = players_df.loc[specialist_puuids, 'tier'].value_counts().reindex(rank_order, fill_value=0)
    specialist_pct = (specialist_tier_counts / overall_tier_counts * 100).fillna(0)

    if NORMALIZE_BY_TIER_MASTERY == 'trend':
        # Divide by the normalization factor (tier average mastery relative to overall mean)
        specialist_pct = specialist_pct / normalization_factor
        # Replace any remaining NaN (from missing factor) with 0
        specialist_pct = specialist_pct.fillna(0)

    specialist_pct_by_role[role] = specialist_pct
    specialist_counts_by_role[role] = len(specialist_puuids)

# ---- Plot ----
fig, axes = plt.subplots(1, 5, figsize=(25, 6), sharey=True)

for ax, role in zip(axes, ROLES):
    if role not in specialist_pct_by_role:
        ax.set_title(f'{role} (no data)')
        ax.axis('off')
        continue

    specialist_pct = specialist_pct_by_role[role]
    n_specialists = specialist_counts_by_role[role]

    x = np.arange(len(rank_order))
    bars = ax.bar(x, specialist_pct.values, color=role_colors[role], alpha=0.8,
                  label=f'Specialists (n={n_specialists})')

    # Add value labels if bars are not too small
    for bar, val in zip(bars, specialist_pct.values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                    f'{val:.1f}', ha='center', va='bottom', fontsize=8)

    ax.set_title(f'{role}\n(n={n_specialists})', fontweight='bold')
    ax.set_xlabel('Tier')
    ax.set_xticks(x)
    ax.set_xticklabels(rank_order, rotation=45, ha='right')
    ax.grid(True, axis='y', linestyle='--', alpha=0.5)
    if ax == axes[0]:
        ylabel = 'Specialists as % of tier population'
        if NORMALIZE_BY_TIER_MASTERY == 'trend':
            ylabel += '\n(normalized by tier mastery)'
        elif NORMALIZE_BY_TIER_MASTERY == 'per_tier':
            ylabel += '\n(per‑tier threshold)'
        ax.set_ylabel(ylabel)

    ax.legend(fontsize=9)

plt.suptitle(
    f'Specialists (Top {SPECIALIST_TOP_FRACTION*100:.2f}% Mastery) by Tier and Role\n'
    f'Normalization: {NORMALIZE_BY_TIER_MASTERY}',
    fontsize=18, fontweight='bold', y=1.05
)
plt.tight_layout()
plt.show()
# %%


# ===================== PLAYER ARCHETYPE CLUSTERING (FIXED) =====================

from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
import matplotlib.pyplot as plt
import seaborn as sns

# ---- 1. Create a boolean mask for rows with no missing feature values ----
feature_cols = ['pool_depth', 'pool_bias', 'pool_exclusivity', 'pool_size']
mask = players_df[feature_cols].notna().all(axis=1)

# Subset the data using the mask (keeps original order)
clustering_data = players_df.loc[mask, feature_cols].copy()
print(f"Players used for clustering: {len(clustering_data)} (out of {len(players_df)})")

# ---- 2. Standardize features ----
scaler = StandardScaler()
scaled_features = scaler.fit_transform(clustering_data)

# ---- 3. Determine optimal number of clusters (elbow + silhouette) ----
K_range = range(2, 10)   # adjust if needed
inertias = []
silhouettes = []

for k in K_range:
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
    kmeans.fit(scaled_features)
    inertias.append(kmeans.inertia_)
    silhouettes.append(silhouette_score(scaled_features, kmeans.labels_))

# Plot elbow and silhouette
fig, axes = plt.subplots(1, 2, figsize=(12, 4))
axes[0].plot(list(K_range), inertias, marker='o')
axes[0].set_title('Elbow Method')
axes[0].set_xlabel('Number of clusters')
axes[0].set_ylabel('Inertia')
axes[1].plot(list(K_range), silhouettes, marker='o', color='orange')
axes[1].set_title('Silhouette Score')
axes[1].set_xlabel('Number of clusters')
axes[1].set_ylabel('Silhouette score')
plt.tight_layout()
plt.show()

# ---- 4. Choose number of clusters ----
N_CLUSTERS = 4   # <-- Change this based on the plots above

# ---- 5. Fit KMeans ----
kmeans_final = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10)
cluster_labels = kmeans_final.fit_predict(scaled_features)

# ---- 6. Assign labels back to the original DataFrame using the same mask ----
# Initialize the column with NaN
players_df['archetype'] = np.nan
players_df['pool_exclusivity'] = players_df['pool_exclusivity'].astype(float)

# Assign cluster labels only to rows that were clustered (mask == True)
players_df.loc[mask, 'archetype'] = cluster_labels

# Map to letters (A, B, C, ...) and set NaN for unclustered rows
players_df['archetype_letter'] = players_df['archetype'].map(
    lambda x: chr(65 + int(x)) if pd.notna(x) else np.nan
)

# ---- 7. Cluster summaries (in original units) ----
cluster_centers_original = pd.DataFrame(
    scaler.inverse_transform(kmeans_final.cluster_centers_),
    columns=feature_cols,
    index=[chr(65 + i) for i in range(N_CLUSTERS)]
)
cluster_counts = players_df['archetype_letter'].value_counts().sort_index()

print("\nCluster centroids (original units):")
print(cluster_centers_original)
print("\nNumber of players per archetype:")
print(cluster_counts)

import webbrowser
import plotly.express as px

# Interactive 3D scatter with 4 dimensions (x, y, z, color)
fig = px.scatter_3d(
    players_df.loc[mask],
    x='pool_depth',
    y='pool_bias',
    z='pool_size',
    color='archetype_letter',
    size='pool_exclusivity',
    hover_name=players_df.loc[mask].index,  # player ID
    hover_data=['pool_depth', 'pool_bias', 'pool_exclusivity', 'pool_size'],
    title='Interactive 3D Cluster Visualization (4 features shown)'
)
fig.write_html("Plots/cluster_visualization.html")
webbrowser.open("Plots/cluster_visualization.html")

archetype_map = pd.Series(["Multi Specialist","Focused Generalist", "True Generalist", "Specialist"])
players_df['archetype'] = players_df['archetype'].map(archetype_map)
players_df = players_df.drop('archetype_letter', axis=1)
# %%

# ===================== PLOT 1 (LINE): ARCHETYPE PROPORTION BY TIER =====================
import matplotlib.pyplot as plt

# Prepare data: exclude players without archetype or tier
archetype_tier = players_df.dropna(subset=['tier', 'archetype']).copy()

# Crosstab with normalization per tier (proportion)
ct = pd.crosstab(archetype_tier['tier'], archetype_tier['archetype'], normalize='index')
# Ensure order of tiers follows rank_order
ct = ct.reindex(index=rank_order)
# Ensure columns are sorted for consistent colors (optional)
ct = ct.reindex(columns=sorted(archetype_tier['archetype'].unique()))

# Plot lines
fig, ax = plt.subplots(figsize=(12, 7))

# Use a colormap for consistent coloring (or define manual palette)
colors = plt.cm.tab10.colors[:len(ct.columns)]
markers = ['o', 's', '^', 'D', 'v', '<', '>', 'p', '*', 'X']

for i, archetype in enumerate(ct.columns):
    ax.plot(
        ct.index.astype(str),
        ct[archetype].values,
        marker=markers[i % len(markers)],
        linewidth=2.5,
        markersize=8,
        color=colors[i % len(colors)],
        label=archetype
    )

ax.set_title('Proportion of Each Archetype by Tier', fontsize=16, fontweight='bold')
ax.set_xlabel('Tier', fontsize=14)
ax.set_ylabel('Proportion of Players in Tier', fontsize=14)
ax.tick_params(axis='x', rotation=45)
ax.legend(title='Archetype', fontsize=12, loc='best')
ax.grid(True, linestyle='--', alpha=0.7)
ax.set_ylim(0, None)  # ensure y starts at 0
plt.tight_layout()
plt.show()
# %%
# ===================== PLOT 2 (NORMALIZED BY CHAMPION): ARCHETYPE COMPOSITION PER CHAMPION =====================

# Explode pool_champions to get one row per player-champion
player_pool_long = players_df[['tier', 'archetype', 'pool_champions']].copy()
player_pool_long = player_pool_long.dropna(subset=['pool_champions', 'archetype'])  # keep only valid archetype
player_pool_long = player_pool_long.explode('pool_champions')
player_pool_long.rename(columns={'pool_champions': 'championId'}, inplace=True)
player_pool_long['championId'] = player_pool_long['championId'].astype(int)

# Select top 20 most popular champions overall (by number of players who include them)
champion_popularity = player_pool_long['championId'].value_counts().head(20)
top_champ_ids = champion_popularity.index.tolist()

# Filter to top champions
usage_df = player_pool_long[player_pool_long['championId'].isin(top_champ_ids)]

# Count players per archetype and champion (rows = archetype, columns = champion)
champ_usage_by_arch = usage_df.groupby(['archetype', 'championId']).size().unstack(fill_value=0)

# Normalize by champion (each column sums to 100%)
champ_usage_by_arch_norm = champ_usage_by_arch.div(champ_usage_by_arch.sum(axis=0), axis=1) * 100

# Reindex columns to top champions order and sort rows by archetype name
champ_usage_by_arch_norm = champ_usage_by_arch_norm.reindex(columns=top_champ_ids)
champ_usage_by_arch_norm = champ_usage_by_arch_norm.reindex(index=sorted(champ_usage_by_arch_norm.index))

# Replace championId with names for readability
champ_names = champions_df['name'].to_dict()
champ_usage_named = champ_usage_by_arch_norm.rename(columns=champ_names)

# Heatmap
plt.figure(figsize=(16, 8))
sns.heatmap(champ_usage_named, annot=True, fmt='.1f', cmap='YlGnBu', linewidths=0.5,
            cbar_kws={'label': '% of champion\'s player base'})
plt.title('Archetype Composition per Champion (Top 20 Champions)', fontsize=16, fontweight='bold')
plt.xlabel('Champion', fontsize=12)
plt.ylabel('Archetype', fontsize=12)
plt.xticks(rotation=45, ha='right')
plt.yticks(rotation=0)
plt.tight_layout()
plt.show()
# %%
# ===================== PLOT 3 (LINE, PER CHAMPION): ARCHETYPE PROPORTION BY TIER FOR A GIVEN CHAMPION =====================

# Choose champion (by ID or name)
champion_to_plot = top_champ_ids[0]   # most popular champion overall, can replace with any ID
# If you prefer by name, use:
# champion_to_plot = champions_df[champions_df['name'] == 'Yasuo'].index[0]

champ_name = champions_df.loc[champion_to_plot, 'name']
print(f"Plotting archetype proportions per tier for champion: {champ_name} (ID {champion_to_plot})")

# Filter long data for this champion
champ_data = player_pool_long[player_pool_long['championId'] == champion_to_plot].copy()
champ_data = champ_data.dropna(subset=['tier', 'archetype'])

# Optional: mask tiers with too few players (adjust MIN_PLAYERS as needed)
MIN_PLAYERS = 20
tier_counts = champ_data['tier'].value_counts()
valid_tiers = tier_counts[tier_counts >= MIN_PLAYERS].index
champ_data = champ_data[champ_data['tier'].isin(valid_tiers)]
print(f"Tiers retained (≥{MIN_PLAYERS} players): {list(valid_tiers)}")

# Crosstab: rows = tier, cols = archetype, values = counts
ct = pd.crosstab(champ_data['tier'], champ_data['archetype'])
# Normalize per tier (each tier sums to 1)
ct_norm = ct.div(ct.sum(axis=1), axis=0)
# Reindex tiers to rank_order (only those present with enough data)
ct_norm = ct_norm.reindex(index=[t for t in rank_order if t in ct_norm.index])
# Ensure archetype columns are sorted for consistent coloring
ct_norm = ct_norm.reindex(columns=sorted(ct_norm.columns))

# Plot
fig, ax = plt.subplots(figsize=(12, 7))
colors = plt.cm.tab10.colors[:len(ct_norm.columns)]
markers = ['o', 's', '^', 'D', 'v', '<', '>', 'p', '*', 'X']

for i, archetype in enumerate(ct_norm.columns):
    ax.plot(
        ct_norm.index.astype(str),
        ct_norm[archetype].values,
        marker=markers[i % len(markers)],
        linewidth=2.5,
        markersize=8,
        color=colors[i % len(colors)],
        label=archetype
    )

ax.set_title(f'Archetype Proportion by Tier for {champ_name}', fontsize=16, fontweight='bold')
ax.set_xlabel('Tier', fontsize=14)
ax.set_ylabel('Proportion of {champ_name} Players in Tier', fontsize=14)
ax.tick_params(axis='x', rotation=45)
ax.legend(title='Archetype', fontsize=12, loc='best')
ax.grid(True, linestyle='--', alpha=0.7)
ax.set_ylim(0, None)
plt.tight_layout()
plt.show()
# %%

# ===================== PLOT 4: ARCHETYPE OVER/UNDER-REPRESENTATION FOR A CHAMPION =====================

# Choose champion (same as before, or change)
target = "Skarner"
champion_to_plot = champions_df[champions_df['name'] == target].index[0]  # most popular champion overall
champ_name = champions_df.loc[champion_to_plot, 'name']

# ---- 1. Overall archetype proportions by tier (from Plot 1) ----
# Use the same filtering as before: players with valid archetype and tier
archetype_tier = players_df.dropna(subset=['tier', 'archetype']).copy()
overall_ct = pd.crosstab(archetype_tier['tier'], archetype_tier['archetype'], normalize='index')
overall_ct = overall_ct.reindex(index=rank_order, columns=sorted(archetype_tier['archetype'].unique()))

# ---- 2. Champion-specific proportions by tier (from Plot 3) ----
champ_data = player_pool_long[player_pool_long['championId'] == champion_to_plot].copy()
champ_data = champ_data.dropna(subset=['tier', 'archetype'])

# Mask tiers with too few champion players (use same MIN_PLAYERS as before)
MIN_PLAYERS = 20
tier_counts = champ_data['tier'].value_counts()
valid_tiers = tier_counts[tier_counts >= MIN_PLAYERS].index
champ_data = champ_data[champ_data['tier'].isin(valid_tiers)]

champ_ct = pd.crosstab(champ_data['tier'], champ_data['archetype'])
champ_ct = champ_ct.div(champ_ct.sum(axis=1), axis=0)  # normalize per tier
champ_ct = champ_ct.reindex(index=rank_order, columns=sorted(archetype_tier['archetype'].unique()))

# ---- 3. Compute difference (champion - overall) ----
# Ensure both have same index and columns
champ_ct = champ_ct.reindex(index=overall_ct.index, columns=overall_ct.columns)
overall_ct = overall_ct.reindex(index=champ_ct.index, columns=champ_ct.columns)

delta = (champ_ct - overall_ct) * 100   # convert to percentage points

# Drop tiers where champion has no data (NaN due to missing) – keep only valid_tiers
delta = delta.loc[delta.index.isin(valid_tiers)]

# ---- 4. Plot delta lines ----
fig, ax = plt.subplots(figsize=(12, 7))
colors = plt.cm.tab10.colors[:len(delta.columns)]
markers = ['o', 's', '^', 'D', 'v', '<', '>', 'p', '*', 'X']

for i, archetype in enumerate(delta.columns):
    ax.plot(
        delta.index.astype(str),
        delta[archetype].values,
        marker=markers[i % len(markers)],
        linewidth=2.5,
        markersize=8,
        color=colors[i % len(colors)],
        label=archetype
    )

# Reference line at 0
ax.axhline(0, color='black', linewidth=1, linestyle='--', alpha=0.6)

ax.set_title(
    f'Archetype Over/Under-Representation for {champ_name} by Tier\n'
    f'Difference vs Overall Tier Population (percentage points)',
    fontsize=16, fontweight='bold'
)
ax.set_xlabel('Tier', fontsize=14)
ax.set_ylim(-40, 40)
ax.set_ylabel('Difference (Champion - Overall) [% points]', fontsize=14)
ax.tick_params(axis='x', rotation=45)
ax.legend(title='Archetype', fontsize=12, loc='best')
ax.grid(True, linestyle='--', alpha=0.7)
plt.tight_layout()
plt.show()
# %%
import numpy as np
import pandas as pd
import statsmodels.api as sm
import matplotlib.pyplot as plt
import seaborn as sns
import warnings

warnings.filterwarnings("ignore")


# ------------------------------------------------------------
# 1. Prepare the player-level modeling data
# ------------------------------------------------------------

# Work on a copy so the original DataFrame is not modified
model_df = players_df.copy()

# Keep only players with the required variables
model_df = model_df[
    model_df["archetype"].notna()
    & model_df["pool_size"].notna()
    & model_df["tier"].notna()
].copy()

# Explicitly convert pool_size to ordinary float64
model_df["pool_size"] = pd.to_numeric(
    model_df["pool_size"],
    errors="coerce"
).astype("float64")

# Make tier an ordinary string categorical variable.
# We will one-hot encode it rather than using the ordinal .cat.codes.
model_df["tier_str"] = model_df["tier"].astype(str)

# Remove anything that became invalid
model_df = model_df.dropna(
    subset=["pool_size", "tier_str", "archetype"]
).copy()

# Fixed lists used throughout the analysis
all_archetypes = sorted(
    model_df["archetype"].unique().tolist()
)

all_tiers = [
    "IRON",
    "BRONZE",
    "SILVER",
    "GOLD",
    "PLATINUM",
    "EMERALD",
    "DIAMOND"
]

# Only keep tiers that actually occur in the data
all_tiers = [
    t for t in all_tiers
    if t in model_df["tier_str"].unique()
]

print("Players used:", len(model_df))
print("Archetypes:", all_archetypes)
print("Tiers:", all_tiers)
# ------------------------------------------------------------
# 2. Adjusted archetype representation for one champion
# ------------------------------------------------------------

def archetype_effects_for_champion(
    champion_id,
    min_players=30,
    ridge_alpha=0.0
):
    """
    Estimate adjusted archetype over/under-representation
    for one champion.

    Controls for:
        - pool_size
        - tier

    Returns:
        Series indexed by archetype containing percentage-point
        over/under-representation among this champion's players.

    Positive = over-represented
    Negative = under-represented
    """

    df = model_df.copy()

    # --------------------------------------------------------
    # Binary outcome: does player have this champion?
    # --------------------------------------------------------

    y = df["pool_champions"].apply(
        lambda x: champion_id in x
        if isinstance(x, (list, tuple, set))
        else False
    ).astype("int64")

    n_champion_players = int(y.sum())

    if n_champion_players < min_players:
        return None

    # --------------------------------------------------------
    # Build a completely numeric design matrix
    # --------------------------------------------------------

    # pool_size
    X_numeric = pd.DataFrame(
        {
            "pool_size": df["pool_size"].to_numpy(dtype=np.float64)
        },
        index=df.index
    )

    # Tier dummy variables
    tier_dummies = pd.get_dummies(
        df["tier_str"],
        prefix="tier",
        dtype=np.float64
    )

    # Make sure all expected tier columns exist
    expected_tier_cols = [
        f"tier_{t}" for t in all_tiers
    ]

    tier_dummies = tier_dummies.reindex(
        columns=expected_tier_cols,
        fill_value=0.0
    )

    # Drop one tier as reference
    tier_dummies = tier_dummies.drop(
        columns=["tier_IRON"],
        errors="ignore"
    )

    # Archetype dummies
    arch_dummies = pd.get_dummies(
        df["archetype"],
        prefix="arch",
        dtype=np.float64
    )

    expected_arch_cols = [
        f"arch_{a}" for a in all_archetypes
    ]

    arch_dummies = arch_dummies.reindex(
        columns=expected_arch_cols,
        fill_value=0.0
    )

    # Drop first archetype as reference
    reference_archetype = all_archetypes[0]

    arch_model_cols = [
        f"arch_{a}"
        for a in all_archetypes
        if a != reference_archetype
    ]

    arch_dummies_model = arch_dummies[
        arch_model_cols
    ]

    # Combine everything
    X = pd.concat(
        [
            X_numeric,
            tier_dummies,
            arch_dummies_model
        ],
        axis=1
    )

    # Add intercept
    X = sm.add_constant(
        X,
        has_constant="add"
    )

    # --------------------------------------------------------
    # HARD dtype check
    # --------------------------------------------------------

    X = X.astype("float64")
    y = y.astype("float64")

    # Sanity check
    if X.dtypes.astype(str).str.contains(
        "object|bool"
    ).any():
        raise TypeError(
            "X still contains non-numeric columns:\n"
            + str(X.dtypes)
        )

    # --------------------------------------------------------
    # Fit logistic regression
    # --------------------------------------------------------

    try:
        if ridge_alpha == 0:
            model = sm.Logit(y, X).fit(
                disp=False,
                maxiter=200
            )
        else:
            # statsmodels' regularized Logit can help with
            # quasi-separation for rare champions
            model = sm.Logit(y, X).fit_regularized(
                alpha=ridge_alpha,
                L1_wt=0.0,
                disp=False,
                maxiter=500
            )

    except Exception as e:
        print(
            f"Could not fit champion {champion_id}: {e}"
        )
        return None

    # --------------------------------------------------------
    # 3. Standardize predictions over the actual population
    # --------------------------------------------------------
    #
    # For every player:
    #
    #   keep their pool_size
    #   keep their tier
    #   change archetype to A
    #
    # Then predict champion inclusion.
    #
    # This gives P(champion | archetype=A, adjusted for
    # the observed pool_size/tier distribution).
    # --------------------------------------------------------

    adjusted_probability = {}

    for archetype in all_archetypes:

        X_counterfactual = X.copy()

        # Set every archetype dummy to zero
        for col in arch_model_cols:
            X_counterfactual[col] = 0.0

        # Set target archetype to 1 if it isn't the reference
        if archetype != reference_archetype:
            target_col = f"arch_{archetype}"
            X_counterfactual[target_col] = 1.0

        X_counterfactual = X_counterfactual.astype(
            "float64"
        )

        predictions = model.predict(
            X_counterfactual
        )

        adjusted_probability[archetype] = (
            float(predictions.mean())
        )

    adjusted_probability = pd.Series(
        adjusted_probability,
        dtype="float64"
    )

    # --------------------------------------------------------
    # 4. Convert P(champion | archetype) into
    #    adjusted archetype composition among champion players
    #
    # Bayes:
    #
    # P(archetype | champion)
    #   proportional to
    # P(champion | archetype) * P(archetype)
    # --------------------------------------------------------

    archetype_prevalence = (
        df["archetype"]
        .value_counts(normalize=True)
        .reindex(all_archetypes)
        .fillna(0.0)
    )

    expected_mass = (
        adjusted_probability
        * archetype_prevalence
    )

    adjusted_champion_composition = (
        expected_mass / expected_mass.sum()
    )

    # --------------------------------------------------------
    # 5. Compare adjusted champion composition with
    #    overall archetype composition
    #
    # Positive = over-represented
    # Negative = under-represented
    # --------------------------------------------------------

    effects = (
        adjusted_champion_composition
        - archetype_prevalence
    ) * 100.0

    effects.name = champion_id

    return effects
# ------------------------------------------------------------
# 3. Top 20 champions
# ------------------------------------------------------------

top_champions = (
    player_pool_long["championId"]
    .value_counts()
    .head(20)
    .index
    .tolist()
)


# ------------------------------------------------------------
# 4. Calculate effects
# ------------------------------------------------------------

effects_dict = {}

for i, champ_id in enumerate(top_champions, 1):

    print(
        f"[{i:2d}/{len(top_champions)}] "
        f"Champion {champ_id}"
    )

    effects = archetype_effects_for_champion(
        champ_id,
        min_players=30
    )

    if effects is not None:
        effects_dict[champ_id] = effects


# ------------------------------------------------------------
# 5. Convert to DataFrame
# ------------------------------------------------------------

effects_df = pd.DataFrame.from_dict(
    effects_dict,
    orient="index"
)

effects_df = effects_df.reindex(
    columns=all_archetypes
)

print(effects_df)
# ------------------------------------------------------------
# 6. Add champion names
# ------------------------------------------------------------

def get_champion_name(champ_id):
    try:
        return champions_df.loc[champ_id, "name"]
    except KeyError:
        return str(champ_id)


effects_df.index = [
    get_champion_name(cid)
    for cid in effects_df.index
]

effects_df.index.name = "Champion"

print(effects_df.round(2))
# ------------------------------------------------------------
# 7. Heatmap
# ------------------------------------------------------------

plt.figure(figsize=(12, 10))

sns.heatmap(
    effects_df,
    annot=True,
    fmt=".1f",
    cmap="RdBu_r",
    center=0,
    linewidths=0.5,
    cbar_kws={
        "label": "Adjusted over/under-representation (percentage points)"
    }
)

plt.title(
    "Adjusted Archetype Representation by Champion",
    fontsize=16,
    fontweight="bold"
)

plt.xlabel("Archetype")
plt.ylabel("Champion")

plt.xticks(
    rotation=45,
    ha="right"
)

plt.yticks(rotation=0)

plt.tight_layout()
plt.show()
#
#
#
champ_id = top_champions[0]

eff = archetype_effects_for_champion(
    champ_id,
    min_players=30
)

if eff is not None:

    champ_name = get_champion_name(champ_id)

    plt.figure(figsize=(8, 5))

    eff.sort_values().plot(
        kind="barh"
    )

    plt.axvline(
        0,
        linewidth=1
    )

    plt.title(
        f"Adjusted Archetype Representation: {champ_name}"
    )

    plt.xlabel(
        "Percentage-point over/under-representation"
    )

    plt.tight_layout()
    plt.show()
# %%

# ============================================================
# CONFIGURATION
# ============================================================

# Change ONLY this variable when you want to inspect a
# different champion individually.
target = ["Tahm Kench", "Galio", "Vladimir", "Darius", "Illaoi", "K'Sante", "Garen", "Riven", "Gnar", "Shen", "Sion", "Singed", "Teemo", "Irelia", "Sett"]
INDIVIDUAL_CHAMPION_IDS = champions_df[champions_df['name'].isin(target)].index

# Minimum number of actual players containing the champion.
MIN_PLAYERS = 30

# Optional regularization.
# 0.0 = ordinary logistic regression.
RIDGE_ALPHA = 0.0


# ============================================================
# IMPORTS
# ============================================================

import os
import re
import webbrowser
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
import plotly.graph_objects as go
import plotly.express as px

warnings.filterwarnings("ignore")


# ============================================================
# 1. PREPARE PLAYER DATA
# ============================================================

model_df = players_df.copy()

required_cols = [
    "pool_champions",
    "pool_size",
    "archetype",
    "tier"
]

missing_cols = [
    c for c in required_cols
    if c not in model_df.columns
]

if missing_cols:
    raise ValueError(
        f"Missing required columns: {missing_cols}"
    )


# Valid players only
model_df = model_df[
    model_df["pool_champions"].notna()
    & model_df["archetype"].notna()
    & model_df["pool_size"].notna()
    & model_df["tier"].notna()
].copy()


# Ordinary numeric dtype
model_df["pool_size"] = pd.to_numeric(
    model_df["pool_size"],
    errors="coerce"
).astype("float64")


# Tier as string
model_df["tier_str"] = (
    model_df["tier"]
    .astype(str)
)


# Remove invalid rows
model_df = model_df.dropna(
    subset=[
        "pool_size",
        "tier_str",
        "archetype"
    ]
).copy()


# Make absolutely sure pool_size is valid
model_df = model_df[
    model_df["pool_size"] > 0
].copy()


# ============================================================
# 2. INVERSE POOL-SIZE WEIGHT
# ============================================================

# THIS is the important change.
#
# Every player contributes total weight = 1 across
# their entire champion pool.
#
# Example:
#
# pool_size = 10 -> weight = .10 per champion
# pool_size =  5 -> weight = .20 per champion
# pool_size =  1 -> weight = 1.00 per champion

model_df["analysis_weight"] = (
    1.0 / model_df["pool_size"]
)


# ============================================================
# 3. ARCHETYPE / TIER DEFINITIONS
# ============================================================

all_archetypes = sorted(
    model_df["archetype"].unique()
)


tier_order = [
    "IRON",
    "BRONZE",
    "SILVER",
    "GOLD",
    "PLATINUM",
    "EMERALD",
    "DIAMOND"
]

all_tiers = [
    t
    for t in tier_order
    if t in model_df["tier_str"].unique()
]


reference_archetype = all_archetypes[0]
reference_tier = all_tiers[0]


print(
    f"Players: {len(model_df):,}"
)

print(
    f"Champions: "
    f"{player_pool_long['championId'].nunique():,}"
)

print(
    f"Archetypes: {all_archetypes}"
)

print(
    f"Tiers: {all_tiers}"
)

print(
    f"Reference archetype: "
    f"{reference_archetype}"
)


# ============================================================
# 4. BUILD DESIGN MATRIX
# ============================================================

def build_design_matrix(df):
    """
    Numeric design matrix:

        pool_size
        tier
        archetype

    Everything is forced to float64.
    """

    X = pd.DataFrame(
        index=df.index
    )


    # --------------------------------------------------------
    # Pool size
    # --------------------------------------------------------

    X["pool_size"] = (
        df["pool_size"]
        .to_numpy(dtype=np.float64)
    )


    # --------------------------------------------------------
    # Tier
    # --------------------------------------------------------

    tier_dummies = pd.get_dummies(
        df["tier_str"],
        prefix="tier",
        dtype=np.float64
    )

    tier_cols = [
        f"tier_{t}"
        for t in all_tiers
        if t != reference_tier
    ]

    tier_dummies = tier_dummies.reindex(
        columns=tier_cols,
        fill_value=0.0
    )

    X = pd.concat(
        [
            X,
            tier_dummies
        ],
        axis=1
    )


    # --------------------------------------------------------
    # Archetype
    # --------------------------------------------------------

    arch_dummies = pd.get_dummies(
        df["archetype"],
        prefix="arch",
        dtype=np.float64
    )

    arch_cols = [
        f"arch_{a}"
        for a in all_archetypes
        if a != reference_archetype
    ]

    arch_dummies = arch_dummies.reindex(
        columns=arch_cols,
        fill_value=0.0
    )

    X = pd.concat(
        [
            X,
            arch_dummies
        ],
        axis=1
    )


    # Intercept
    X = sm.add_constant(
        X,
        has_constant="add"
    )


    # Critical:
    # eliminate pandas extension/object dtypes
    X = X.astype(np.float64)

    return X


X_base = build_design_matrix(
    model_df
)


# ============================================================
# 5. CHAMPION MEMBERSHIP
# ============================================================

def champion_membership(champion_id):

    return model_df[
        "pool_champions"
    ].apply(
        lambda x:
            champion_id in x
            if isinstance(
                x,
                (list, tuple, set)
            )
            else False
    ).astype(np.float64)


# ============================================================
# 6. FIT WEIGHTED LOGISTIC REGRESSION
# ============================================================

def fit_champion_model(
    champion_id,
    min_players=MIN_PLAYERS
):

    y_series = champion_membership(
        champion_id
    )

    n_players = int(
        y_series.sum()
    )

    if n_players < min_players:
        return None


    y = y_series.to_numpy(
        dtype=np.float64
    )

    X = X_base.to_numpy(
        dtype=np.float64
    )

    weights = model_df[
        "analysis_weight"
    ].to_numpy(
        dtype=np.float64
    )


    try:

        if RIDGE_ALPHA == 0.0:

            model = sm.GLM(
                y,
                X,
                family=sm.families.Binomial(),
                freq_weights=weights
            ).fit()

        else:

            model = sm.GLM(
                y,
                X,
                family=sm.families.Binomial(),
                freq_weights=weights
            ).fit_regularized(
                alpha=RIDGE_ALPHA,
                L1_wt=0.0
            )


        return (
            model,
            y,
            n_players
        )

    except Exception as e:

        print(
            f"Failed champion "
            f"{champion_id}: {e}"
        )

        return None


# ============================================================
# 7. COUNTERFACTUAL PREDICTIONS
# ============================================================

def counterfactual_predictions(
    model,
    archetype,
    rows=None
):
    """
    Predict champion membership if every player were
    assigned the specified archetype.

    Pool size and tier remain unchanged.
    """

    if rows is None:
        X_cf = X_base.copy()

    else:
        X_cf = X_base.loc[
            rows
        ].copy()


    arch_cols = [
        f"arch_{a}"
        for a in all_archetypes
        if a != reference_archetype
    ]


    # Set every archetype to zero
    for col in arch_cols:
        X_cf[col] = 0.0


    # Set target archetype
    if archetype != reference_archetype:

        X_cf[
            f"arch_{archetype}"
        ] = 1.0


    X_cf = X_cf.astype(
        np.float64
    )


    predictions = model.predict(
        X_cf.to_numpy(
            dtype=np.float64
        )
    )


    return np.asarray(
        predictions,
        dtype=np.float64
    )

# ============================================================
# 8. OVERALL EFFECT FOR ONE CHAMPION
# ============================================================

def overall_champion_effect(
    champion_id,
    min_players=MIN_PLAYERS
):

    result = fit_champion_model(
        champion_id,
        min_players=min_players
    )

    if result is None:
        return None


    model, y, n_players = result


    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Archetype prevalence should also be calculated using
    # inverse-pool-size weights.
    #
    # Otherwise we would fix the regression weighting but
    # compare against an unweighted baseline.
    # --------------------------------------------------------

    weighted_arch_counts = (
        model_df
        .groupby("archetype")[
            "analysis_weight"
        ]
        .sum()
        .reindex(all_archetypes)
        .fillna(0.0)
    )


    archetype_prevalence = (
        weighted_arch_counts
        / weighted_arch_counts.sum()
    )


    # --------------------------------------------------------
    # Counterfactual P(champion | archetype)
    # --------------------------------------------------------

    probabilities = {}


    for archetype in all_archetypes:

        pred = counterfactual_predictions(
            model,
            archetype
        )

        # Weighted standardization
        weights = model_df[
            "analysis_weight"
        ].to_numpy(
            dtype=np.float64
        )

        probabilities[
            archetype
        ] = np.average(
            pred,
            weights=weights
        )


    probabilities = pd.Series(
        probabilities,
        index=all_archetypes,
        dtype=np.float64
    )


    # --------------------------------------------------------
    # Bayes
    # --------------------------------------------------------

    expected_mass = (
        probabilities
        * archetype_prevalence
    )


    adjusted_composition = (
        expected_mass
        / expected_mass.sum()
    )


    # --------------------------------------------------------
    # Percentage-point effect
    # --------------------------------------------------------

    effects = (
        adjusted_composition
        - archetype_prevalence
    ) * 100.0


    effects.name = champion_id

    return effects


# ============================================================
# 9. RUN ALL CHAMPIONS
# ============================================================

all_champions = (
    player_pool_long[
        "championId"
    ]
    .dropna()
    .unique()
    .tolist()
)


print(
    f"\nRunning weighted regression "
    f"for {len(all_champions):,} champions..."
)


effects_dict = {}

failed_champions = []


for i, champion_id in enumerate(
    all_champions,
    start=1
):

    result = overall_champion_effect(
        champion_id
    )

    if result is not None:

        effects_dict[
            champion_id
        ] = result

    else:

        failed_champions.append(
            champion_id
        )


    if (
        i % 25 == 0
        or i == len(all_champions)
    ):

        print(
            f"{i:,}/{len(all_champions):,}"
        )


# ============================================================
# 10. RESULTS DATAFRAME
# ============================================================

effects_df = pd.DataFrame.from_dict(
    effects_dict,
    orient="index"
)


effects_df = effects_df.reindex(
    columns=all_archetypes
)


effects_df.index.name = "championId"


# Champion names
def get_champion_name(
    champion_id
):

    try:

        return champions_df.loc[
            champion_id,
            "name"
        ]

    except KeyError:

        return str(champion_id)


effects_df[
    "championName"
] = [
    get_champion_name(cid)
    for cid in effects_df.index
]


effects_df = effects_df[
    [
        "championName"
    ]
    + all_archetypes
]


print(
    "\nResults:"
)

print(
    effects_df.head()
)


# ============================================================
# 11. PLOTLY HEATMAP
# ============================================================

heatmap_df = effects_df[
    all_archetypes
].copy()


heatmap_df.index = effects_df[
    "championName"
]


fig_heatmap = go.Figure(
    data=go.Heatmap(
        z=heatmap_df.to_numpy(),
        x=heatmap_df.columns.tolist(),
        y=heatmap_df.index.tolist(),

        colorscale="RdBu_r",

        zmid=0,

        text=np.round(
            heatmap_df.to_numpy(),
            1
        ),

        texttemplate="%{text:.1f}",

        colorbar=dict(
            title="Adjusted<br>percentage points"
        ),

        hovertemplate=(
            "<b>%{y}</b><br>"
            "Archetype: %{x}<br>"
            "Effect: %{z:.2f} pp"
            "<extra></extra>"
        )
    )
)


fig_heatmap.update_layout(
    title=(
        "Pool-Size-Weighted Adjusted "
        "Archetype Representation"
    ),

    xaxis_title="Archetype",

    yaxis_title="Champion",

    width=1200,

    height=max(
        800,
        len(heatmap_df) * 22
    ),

    xaxis=dict(
        tickangle=-35
    )
)


# ============================================================
# 12. SAVE + OPEN HEATMAP
# ============================================================

OUTPUT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


heatmap_path = os.path.join(
    OUTPUT_DIR,
    "Plots/adjusted_archetype_heatmap.html"
)


fig_heatmap.write_html(
    heatmap_path,
    include_plotlyjs=True,
    full_html=True,
    auto_open=False
)


print(
    f"\nHeatmap:"
    f"\n{heatmap_path}"
)


webbrowser.open(
    "file://" +
    os.path.abspath(
        heatmap_path
    )
)


# ============================================================
# 13. INDIVIDUAL CHAMPION EFFECT BY TIER
# ============================================================

def champion_effect_by_tier(
    champion_id,
    min_players=MIN_PLAYERS
):

    result = fit_champion_model(
        champion_id,
        min_players=min_players
    )

    if result is None:
        return None


    model, y, n_players = result


    rows = []


    for tier in all_tiers:

        tier_indices = (
            model_df.index[
                model_df["tier_str"]
                == tier
            ]
        )


        if len(tier_indices) == 0:
            continue


        tier_df = model_df.loc[
            tier_indices
        ]


        # Weighted archetype prevalence
        weighted_arch = (
            tier_df
            .groupby("archetype")[
                "analysis_weight"
            ]
            .sum()
            .reindex(all_archetypes)
            .fillna(0.0)
        )


        tier_prevalence = (
            weighted_arch
            / weighted_arch.sum()
        )


        # ----------------------------------------------------
        # P(champion | archetype, tier)
        # ----------------------------------------------------

        probabilities = {}


        for archetype in all_archetypes:

            pred = counterfactual_predictions(
                model,
                archetype,
                rows=tier_indices
            )


            weights = tier_df[
                "analysis_weight"
            ].to_numpy(
                dtype=np.float64
            )


            probabilities[
                archetype
            ] = np.average(
                pred,
                weights=weights
            )


        probabilities = pd.Series(
            probabilities,
            index=all_archetypes,
            dtype=np.float64
        )


        # Bayes within tier
        expected_mass = (
            probabilities
            * tier_prevalence
        )


        if expected_mass.sum() == 0:
            continue


        adjusted_composition = (
            expected_mass
            / expected_mass.sum()
        )


        effects = (
            adjusted_composition
            - tier_prevalence
        ) * 100.0


        for archetype in all_archetypes:

            rows.append(
                {
                    "tier": tier,
                    "archetype": archetype,
                    "effect": effects[
                        archetype
                    ]
                }
            )


    result_df = pd.DataFrame(
        rows
    )


    result_df["tier"] = pd.Categorical(
        result_df["tier"],
        categories=all_tiers,
        ordered=True
    )


    return result_df


# ============================================================
# 14. INDIVIDUAL CHAMPION ANALYSES
#     Matplotlib version for Spyder Plots pane
# ============================================================

import matplotlib.pyplot as plt


# Make sure a single integer also works
if isinstance(
    INDIVIDUAL_CHAMPION_IDS,
    (int, np.integer)
):
    INDIVIDUAL_CHAMPION_IDS = [
        int(INDIVIDUAL_CHAMPION_IDS)
    ]


for champion_id in INDIVIDUAL_CHAMPION_IDS:

    print(
        "\n" + "=" * 70
    )

    print(
        f"INDIVIDUAL CHAMPION: "
        f"{get_champion_name(champion_id)} "
        f"({champion_id})"
    )

    print(
        "=" * 70
    )


    # --------------------------------------------------------
    # Calculate effects
    # --------------------------------------------------------

    individual_effects = (
        champion_effect_by_tier(
            champion_id,
            min_players=MIN_PLAYERS
        )
    )


    if individual_effects is None:

        print(
            f"Champion {champion_id} "
            f"does not meet "
            f"MIN_PLAYERS={MIN_PLAYERS}"
        )

        continue


    champion_name = (
        get_champion_name(
            champion_id
        )
    )


    # --------------------------------------------------------
    # Print numerical results
    # --------------------------------------------------------

    result_table = (
        individual_effects
        .pivot(
            index="tier",
            columns="archetype",
            values="effect"
        )
        .reindex(
            index=all_tiers,
            columns=all_archetypes
        )
    )


    print(
        result_table.round(2)
    )


    # --------------------------------------------------------
    # Create standard Matplotlib plot
    # --------------------------------------------------------

    fig, ax = plt.subplots(
        figsize=(10, 6)
    )


    x = np.arange(
        len(all_tiers)
    )


    for archetype in all_archetypes:

        y = result_table[
            archetype
        ].to_numpy(
            dtype=float
        )


        ax.plot(
            x,
            y,
            marker="o",
            linewidth=2,
            label=archetype
        )


    # --------------------------------------------------------
    # Zero reference line
    # --------------------------------------------------------

    ax.axhline(
        y=0,
        linestyle="--",
        linewidth=1
    )


    # --------------------------------------------------------
    # Axes
    # --------------------------------------------------------

    ax.set_xticks(x)

    ax.set_xticklabels(
        all_tiers
    )


    # FIXED Y AXIS
    ax.set_ylim(
        -15,
        15
    )


    ax.set_ylabel(
        "Adjusted over/under-representation "
        "(percentage points)"
    )


    ax.set_xlabel(
        "Tier"
    )


    ax.set_title(
        f"{champion_name}: "
        f"Adjusted Archetype Representation by Tier"
    )


    ax.legend(
        title="Archetype"
    )


    ax.grid(
        axis="y",
        linestyle="--",
        alpha=0.4
    )


    fig.tight_layout()


    # --------------------------------------------------------
    # Show in Spyder's Plots pane
    # --------------------------------------------------------

    plt.show()
# %%
# ===================== DIVERGING BAR: ROLE VS OVERALL =====================
overall_prop = players_df['archetype'].value_counts(normalize=True)
divergence = ct.sub(overall_prop, axis=1)  # difference from overall average

fig, axes = plt.subplots(1, len(divergence.columns), figsize=(15, 4), sharey=True)
for ax, arch in zip(axes, divergence.columns):
    divergence[arch].plot(kind='barh', ax=ax, color='steelblue', edgecolor='black')
    ax.axvline(0, color='black', linewidth=1)
    ax.set_title(arch, fontweight='bold')
    ax.set_xlabel('Difference')
    if ax != axes[0]:
        ax.set_ylabel('')
plt.suptitle('Archetype Over/Under-Representation by Role (vs Overall)', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.show()
# %%

# ===================== DIVERGING BAR: ROLE VS OVERALL (FIXED COMMON SCALE) =====================

# ---- 1. Data preparation (self-contained) ----
def as_list(x):
    if isinstance(x, list):
        return x
    if pd.isna(x):
        return []
    return [x]

role_arch = players_df[['main_roles', 'archetype']].dropna(subset=['archetype']).copy()
role_arch['main_roles'] = role_arch['main_roles'].apply(as_list)
role_arch = role_arch.explode('main_roles')
role_arch = role_arch.dropna(subset=['main_roles'])

valid_roles = ['Top', 'Jungle', 'Middle', 'Bottom', 'Support']
role_arch = role_arch[role_arch['main_roles'].isin(valid_roles)]

# Crosstab normalized per role (proportions)
ct = pd.crosstab(role_arch['main_roles'], role_arch['archetype'], normalize='index')
ct = ct.reindex(index=valid_roles, columns=sorted(players_df['archetype'].dropna().unique()))

# Overall archetype proportions
overall_prop = players_df['archetype'].value_counts(normalize=True)
overall_prop = overall_prop.reindex(ct.columns)

# Difference (role - overall)
divergence = ct.sub(overall_prop, axis=1)

# ---- 2. Set a fixed, common x-axis limit for all subplots ----
# Adjust this value to your preferred range (e.g., 0.3 means -0.3 to +0.3)
FIXED_XLIM = 0.04

# ---- 3. Plot ----
fig, axes = plt.subplots(1, len(divergence.columns), figsize=(15, 4), sharey=True)

for ax, arch in zip(axes, divergence.columns):
    divergence[arch].plot(kind='barh', ax=ax, color='steelblue', edgecolor='black')
    ax.axvline(0, color='black', linewidth=1)
    ax.set_title(arch, fontweight='bold')
    ax.set_xlabel('Difference')
    if ax != axes[0]:
        ax.set_ylabel('')
    # Apply the same fixed x‑axis limits to every subplot
    ax.set_xlim(-FIXED_XLIM, FIXED_XLIM)

plt.suptitle('Archetype Over/Under-Representation by Role (vs Overall)\n'
             f'Common x-axis range: ±{FIXED_XLIM}', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.show()
# %%

# ===================== DIVERGING BAR: PER ROLE – ARCHETYPE DIFFERENCES (FLIPPED) =====================

# ---- 1. Data preparation (self-contained) ----
def as_list(x):
    if isinstance(x, list):
        return x
    if pd.isna(x):
        return []
    return [x]

role_arch = players_df[['main_roles', 'archetype']].dropna(subset=['archetype']).copy()
role_arch['main_roles'] = role_arch['main_roles'].apply(as_list)
role_arch = role_arch.explode('main_roles')
role_arch = role_arch.dropna(subset=['main_roles'])

valid_roles = ['Top', 'Jungle', 'Middle', 'Bottom', 'Support']
role_arch = role_arch[role_arch['main_roles'].isin(valid_roles)]

# Crosstab normalized per role (rows=roles, cols=archetypes)
ct = pd.crosstab(role_arch['main_roles'], role_arch['archetype'], normalize='index')
ct = ct.reindex(index=valid_roles, columns=sorted(players_df['archetype'].dropna().unique()))

# Overall archetype proportions (same for all roles)
overall_prop = players_df['archetype'].value_counts(normalize=True)
overall_prop = overall_prop.reindex(ct.columns)

# Difference = role proportion - overall proportion (rows=roles, cols=archetypes)
divergence = ct.sub(overall_prop, axis=1)

# ---- 2. Set a common x‑axis limit for all subplots ----
max_abs = divergence.abs().max().max()
x_limit = max(max_abs * 1.2, 0.05)   # at least ±0.05 for visibility

# ---- 3. Plot: one subplot per role ----
fig, axes = plt.subplots(1, len(valid_roles), figsize=(18, 5), sharex=True)

for ax, role in zip(axes, valid_roles):
    # Differences for this role across archetypes
    diff = divergence.loc[role]
    
    # Horizontal bar plot: y = archetype, x = difference
    diff.plot(kind='barh', ax=ax, color='steelblue', edgecolor='black')
    ax.axvline(0, color='black', linewidth=1)
    ax.set_title(role, fontweight='bold')
    ax.set_xlabel('Difference')
    if ax != axes[0]:
        ax.set_ylabel('')   # hide y-label for non-first subplot
    else:
        ax.set_ylabel('Archetype')
    # Set common x-axis limit
    ax.set_xlim(-x_limit, x_limit)

plt.suptitle('Archetype Over/Under-Representation by Role (vs Overall)',
             fontsize=14, fontweight='bold')
plt.tight_layout()
plt.show()