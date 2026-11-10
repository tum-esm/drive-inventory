# Tests

`uv run pytest` runs a few known-answer tests on invented data. They need no restricted data, so they can run anywhere, including CI. Each test targets an error that would otherwise pass without a warning, and its docstring says which:

| File | Checks |
|---|---|
| `test_kernel.py` | Hot emissions of one link worked out by hand (factor selection, level-of-service limits, hourly profile); the vehicle split keeps the total |
| `test_activity.py` | Daily scaling relative to normal weekdays of the reference year, per link |
| `test_store.py` | Reads pinned to a store batch, latest batch per key |

Results on real data are checked against the frozen v1 baselines in `data/inventory/baselines/` with `scripts/compare_v1_*.py`. Those need the restricted data and only run locally.
