# Split sweep — train_size sweep × 3 repeats × mode

Usable issues (with valid A–F category): **200**

## Strategies

### Strategy A — `default` (bounded per-repo cap)
1. Compute per-category seed quotas via **largest-remainder rounding** (snake / serpentine recall-merge), one issue per quota slot.
2. For each category, prefer an issue from a repo we have not yet claimed; fall back to an already-claimed repo only if the unclaimed pool is exhausted.
3. After the seed phase, for every claimed repo R, pull in additional issues up to a per-repo cap `m_R = round(train_size / |claimed_repos|)` (largest-remainder rounding so the total stays near `train_size`).

**Goal**: train size ≈ requested, broad repo coverage, low-but-not-zero leakage. On this 200-issue / 11-repo dataset leakage is essentially 100% because the cap is a few issues per repo, not the whole repo.

### Strategy B — `repo_disjoint` (strict, whole-repo isolation)
1. Decide how many repos `N` to claim: choose the smallest `N` such that `Σ issue_counts[claimed_repos] ≥ train_size`.
2. Move **every** issue from each of those `N` repos to train; everything else goes to test.
3. By construction, `test_repo_leakage_pct == 0`.

**Goal**: zero contamination between train and test. Trade-off: actual train size is coarse (whole repos), so it jumps in steps and is rarely equal to the requested size.

## Strategy `default` — full table (per repeat)

| req | rep | train | test | train % | unique repos | leakage % | cats covered |
|---:|---:|---:|---:|---:|---:|---:|---|
| 20 | 0 | 28 | 172 | 14.0 | 11 | 100.0 | 6/6 |
| 20 | 1 | 29 | 171 | 14.5 | 10 | 98.8 | 6/6 |
| 20 | 2 | 29 | 171 | 14.5 | 10 | 98.8 | 6/6 |
| 40 | 0 | 54 | 146 | 27.0 | 11 | 100.0 | 6/6 |
| 40 | 1 | 53 | 147 | 26.5 | 11 | 100.0 | 6/6 |
| 40 | 2 | 53 | 147 | 26.5 | 11 | 100.0 | 6/6 |
| 60 | 0 | 76 | 124 | 38.0 | 11 | 100.0 | 6/6 |
| 60 | 1 | 78 | 122 | 39.0 | 11 | 100.0 | 6/6 |
| 60 | 2 | 76 | 124 | 38.0 | 11 | 100.0 | 6/6 |
| 80 | 0 | 96 | 104 | 48.0 | 11 | 100.0 | 6/6 |
| 80 | 1 | 101 | 99 | 50.5 | 11 | 100.0 | 6/6 |
| 80 | 2 | 96 | 104 | 48.0 | 11 | 100.0 | 6/6 |
| 100 | 0 | 124 | 76 | 62.0 | 11 | 100.0 | 6/6 |
| 100 | 1 | 118 | 82 | 59.0 | 11 | 100.0 | 6/6 |
| 100 | 2 | 119 | 81 | 59.5 | 11 | 100.0 | 6/6 |
| 120 | 0 | 139 | 61 | 69.5 | 11 | 100.0 | 6/6 |
| 120 | 1 | 139 | 61 | 69.5 | 11 | 100.0 | 6/6 |
| 120 | 2 | 137 | 63 | 68.5 | 11 | 100.0 | 6/6 |
| 140 | 0 | 154 | 46 | 77.0 | 11 | 100.0 | 6/6 |
| 140 | 1 | 157 | 43 | 78.5 | 11 | 100.0 | 6/6 |
| 140 | 2 | 148 | 52 | 74.0 | 11 | 100.0 | 6/6 |
| 160 | 0 | 167 | 33 | 83.5 | 11 | 100.0 | 6/6 |
| 160 | 1 | 168 | 32 | 84.0 | 11 | 100.0 | 6/6 |
| 160 | 2 | 168 | 32 | 84.0 | 11 | 100.0 | 6/6 |
| 180 | 0 | 185 | 15 | 92.5 | 11 | 100.0 | 6/6 |
| 180 | 1 | 183 | 17 | 91.5 | 11 | 100.0 | 6/6 |
| 180 | 2 | 185 | 15 | 92.5 | 11 | 100.0 | 6/6 |

### Strategy `default` — averages over 3 repeats

| req | train (mean) | test (mean) | leakage % (mean) | repos (mean) | cats covered |
|---:|---:|---:|---:|---:|---|
| 20 | 28.7 | 171.3 | 99.2 | 10.3 | 6/6 |
| 40 | 53.3 | 146.7 | 100.0 | 11.0 | 6/6 |
| 60 | 76.7 | 123.3 | 100.0 | 11.0 | 6/6 |
| 80 | 97.7 | 102.3 | 100.0 | 11.0 | 6/6 |
| 100 | 120.3 | 79.7 | 100.0 | 11.0 | 6/6 |
| 120 | 138.3 | 61.7 | 100.0 | 11.0 | 6/6 |
| 140 | 153.0 | 47.0 | 100.0 | 11.0 | 6/6 |
| 160 | 167.7 | 32.3 | 100.0 | 11.0 | 6/6 |
| 180 | 184.3 | 15.7 | 100.0 | 11.0 | 6/6 |

## Strategy `repo_disjoint` — full table (per repeat)

| req | rep | train | test | train % | unique repos | leakage % | cats covered |
|---:|---:|---:|---:|---:|---:|---:|---|
| 20 | 0 | 15 | 185 | 7.5 | 3 | 0.0 | 5/6 |
| 20 | 1 | 16 | 183 | 8.0 | 3 | 0.0 | 5/6 |
| 20 | 2 | 98 | 97 | 49.0 | 3 | 0.0 | 6/6 |
| 40 | 0 | 115 | 80 | 57.5 | 5 | 0.0 | 6/6 |
| 40 | 1 | 89 | 106 | 44.5 | 5 | 0.0 | 6/6 |
| 40 | 2 | 73 | 119 | 36.5 | 5 | 0.0 | 6/6 |
| 60 | 0 | 98 | 95 | 49.0 | 5 | 0.0 | 6/6 |
| 60 | 1 | 65 | 128 | 32.5 | 5 | 0.0 | 6/6 |
| 60 | 2 | 74 | 119 | 37.0 | 5 | 0.0 | 6/6 |
| 80 | 0 | 54 | 143 | 27.0 | 5 | 0.0 | 6/6 |
| 80 | 1 | 90 | 104 | 45.0 | 5 | 0.0 | 6/6 |
| 80 | 2 | 43 | 153 | 21.5 | 5 | 0.0 | 6/6 |
| 100 | 0 | 141 | 55 | 70.5 | 6 | 0.0 | 6/6 |
| 100 | 1 | 168 | 32 | 84.0 | 6 | 0.0 | 6/6 |
| 100 | 2 | 154 | 42 | 77.0 | 6 | 0.0 | 6/6 |
| 120 | 0 | 196 | 4 | 98.0 | 9 | 0.0 | 6/6 |
| 120 | 1 | 184 | 14 | 92.0 | 9 | 0.0 | 6/6 |
| 120 | 2 | 191 | 8 | 95.5 | 9 | 0.0 | 6/6 |
| 140 | 0 | 198 | 2 | 99.0 | 10 | 0.0 | 6/6 |
| 140 | 1 | 176 | 23 | 88.0 | 10 | 0.0 | 6/6 |
| 140 | 2 | 197 | 2 | 98.5 | 10 | 0.0 | 6/6 |
| 160 | 0 | 199 | 0 | 99.5 | 10 | 0.0 | 6/6 |
| 160 | 1 | 199 | 0 | 99.5 | 10 | 0.0 | 6/6 |
| 160 | 2 | 185 | 15 | 92.5 | 10 | 0.0 | 6/6 |
| 180 | 0 | 197 | 2 | 98.5 | 10 | 0.0 | 6/6 |
| 180 | 1 | 121 | 74 | 60.5 | 10 | 0.0 | 6/6 |
| 180 | 2 | 199 | 0 | 99.5 | 10 | 0.0 | 6/6 |

### Strategy `repo_disjoint` — averages over 3 repeats

| req | train (mean) | test (mean) | leakage % (mean) | repos (mean) | cats covered |
|---:|---:|---:|---:|---:|---|
| 20 | 43.0 | 155.0 | 0.0 | 3.0 | 4/6 |
| 40 | 92.3 | 101.7 | 0.0 | 5.0 | 6/6 |
| 60 | 79.0 | 114.0 | 0.0 | 5.0 | 6/6 |
| 80 | 62.3 | 133.3 | 0.0 | 5.0 | 6/6 |
| 100 | 154.3 | 43.0 | 0.0 | 6.0 | 6/6 |
| 120 | 190.3 | 8.7 | 0.0 | 9.0 | 6/6 |
| 140 | 190.3 | 9.0 | 0.0 | 10.0 | 6/6 |
| 160 | 194.3 | 5.0 | 0.0 | 10.0 | 6/6 |
| 180 | 172.3 | 25.3 | 0.0 | 10.0 | 6/6 |

## Side-by-side comparison — averages over 3 repeats

| req | A train | A leakage | A cats | B train | B leakage | B cats |
|---:|---:|---:|---:|---:|---:|---|
| 20 | 28.7 | 99.2 | 6/6 | 43.0 | 0.0 | 4/6 |
| 40 | 53.3 | 100.0 | 6/6 | 92.3 | 0.0 | 6/6 |
| 60 | 76.7 | 100.0 | 6/6 | 79.0 | 0.0 | 6/6 |
| 80 | 97.7 | 100.0 | 6/6 | 62.3 | 0.0 | 6/6 |
| 100 | 120.3 | 100.0 | 6/6 | 154.3 | 0.0 | 6/6 |
| 120 | 138.3 | 100.0 | 6/6 | 190.3 | 0.0 | 6/6 |
| 140 | 153.0 | 100.0 | 6/6 | 190.3 | 0.0 | 6/6 |
| 160 | 167.7 | 100.0 | 6/6 | 194.3 | 0.0 | 6/6 |
| 180 | 184.3 | 100.0 | 6/6 | 172.3 | 0.0 | 6/6 |
