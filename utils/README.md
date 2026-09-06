# utils — dataset acquisition & preparation

Three sub-components, run in order:

1. `download/` — pull `EaminC/AgentBug-Smith` `all_combined_f2p` dataset
   to `data/raw/`. Uses `git sparse-checkout` (no auth needed) — only
   the target subdirectory is fetched, not the whole repo.
2. `classify/` — for each downloaded issue, ask the LLM (default
   `openai/gpt-4o-mini` via `https://api.tu-zi.com`) for a primary
   category from `docs/taxonomy.md` and write a flat index at
   `data/index.jsonl`.
3. `split/` — read `data/index.jsonl` and carve out a stratified,
   repo-disjoint train/test split (e.g., 40 / N-40). Default
   outputs at `data/splits/<split-name>/{train,test}.jsonl`.

No agent harness — just scripts. Steps 2 and 3 do not depend on
mini-swe-agent or openhands, only on the same LLM gateway the
agent components use.

## Why not an agent?

The user explicitly asked for this. The classification task is
mechanical (one call per issue, JSON out) and the split is a pure
algorithm. Using an agent here would add tool-call noise, nondeterminism,
and cost. The LLM call itself goes straight through the OpenAI SDK
against the tu-zi gateway.

## Files

- `download/run.py`     — sparse-checkout the dataset
- `classify/run.py`     — batch LLM classification → index.jsonl
- `split/run.py`        — stratified, repo-disjoint train/test split
- `pipeline.py`         — runs all three end-to-end
- `config.json`         — shared tunables (LLM endpoint, paths, defaults)
- `README.md`           — usage docs

## Pipeline

```bash
source agent/.venv/bin/activate
source utils/.env
python utils/pipeline.py                       # full dataset
python utils/pipeline.py --limit 20            # 20-issue dry run
```

The pipeline runs three steps in order. Each can also be run
individually:

```bash
python utils/download/run.py --out data/raw
python utils/classify/run.py \
    --in data/raw/results/all_combined_f2p \
    --out data/index.jsonl
python utils/split/run.py \
    --index data/index.jsonl \
    --train-size 40 \
    --out data/splits/default
```

## Split algorithm notes

The split has two objectives that can pull in opposite directions on
small datasets:

1. **Stratified coverage**: train must contain every category present
   in the index. Quotas per category are computed by *largest-remainder
   rounding* on the proportional share `train_size * n_c / N` (Hamilton's
   method). This is the "snake / serpentine recall-merge" — the
   rounding leftover is allocated to the categories with the largest
   fractional parts so the total exactly hits `train_size`.
2. **Repo leakage reduction**: once a repo lands in the seed, sibling
   issues from the same repo are preferred for train over test, *up to
   a per-repo cap* `m_r ≈ train_size / |claimed_repos|`. This is the
   "smart" part: with `n=11` repos in the dataset, the cap is
   `40 / 11 ≈ 4` issues per repo, which means most issues from any
   claimed repo still go to test. That's the unavoidable trade-off when
   the dataset is small relative to `train_size`; the summary reports
   `test_repo_leakage_pct` so you can see how much overlap remains.

The split is deterministic given `--seed`.

## Files

- `download/run.py`     — sparse-checkout the dataset
- `classify/run.py`     — batch LLM classification → index.jsonl
- `split/run.py`        — stratified, repo-disjoint train/test split
- `pipeline.py`         — runs all three end-to-end
- `config.json`         — shared tunables (LLM endpoint, paths, defaults)
- `README.md`           — this file
