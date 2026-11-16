# Tests

`uv run pytest` runs a few known-answer tests on invented data. They need no restricted data, so they can run anywhere, including CI. Each test targets an error that would otherwise pass without a warning, and its docstring says which:

| File | Checks |
|---|---|
| `test_kernel.py` | Hot emissions of one link worked out by hand (factor selection, level-of-service limits, hourly profile); the vehicle split keeps the total; the HGV cap (no negative volumes); the hourly ambient pattern selects each hour's factors |
| `test_activity.py` | Daily scaling relative to normal weekdays of the reference year, per link; pooled BUS and MOT shares |
| `test_counts_qa.py` | Implausible LCV shares removed per link and year only; incomplete link-days dropped, not summed as 0; a counter used only for years complete together with the reference year |
| `test_counter_links.py` | Counter link overrides: moved, excluded, per traffic model, unknown links refused |
| `test_readers_and_calendar.py` | BASt raw reader (lanes per direction, Lzg = LmA + Sat, worst flag, inserted records skipped); UTC to local time around the DST change; day type rules; ambient pattern bins |
| `test_gridding.py` | A line split between grid cells by its length inside each |
| `test_outputs.py` | g/km x km -> t in the summary; output contracts reject a wrong CRS and negative hot values |
| `test_store.py` | Reads pinned to a store batch, latest batch per key |

The outputs are also checked against contracts in `drive/schemas.py` whenever `drive run` writes them (spec R7).

Results on real data are checked against the frozen v1 baselines in `data/inventory/baselines/` with `scripts/compare_v1_*.py`. Those need the restricted data and only run locally.
