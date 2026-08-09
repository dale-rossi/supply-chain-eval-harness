# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A from-scratch (no eval framework) harness that scores Claude on a supply-chain risk-analysis
prompt against three hand-derived golden answers. `harness-and-evals-onepager.md` is the design
document behind it and tracks the build phases; `README.md` covers the same ground for a reader.

## Commands

There is no test suite, linter, or build step. Everything runs through the local `venv/`
(Python 3.14, `anthropic` + `pandas` installed). It is gitignored and there is no
`requirements.txt`, so a fresh clone needs `pip install anthropic pandas`.

```bash
source venv/bin/activate
export ANTHROPIC_API_KEY=sk-ant-...

python runner.py                              # calls the API for all 3 cases -> results.json
python report.py                              # grades results.json -> scorecard.json + table
python cost_analysis.py                       # -> cost_actual.csv, cost_hypothetical.csv

HARNESS_MODEL=claude-haiku-4-5-20251001 python runner.py   # run a different model
```

Every script uses relative paths (`data/`, `results*.json`) — **run them from the repo root**, not
from a subdirectory.

Every generated artifact is git-tracked (`results.json`, `results_<model>.json`, `scorecard.json`,
`cost_actual.csv`, `cost_hypothetical.csv`), so running any part of the pipeline dirties the
working tree. Check `git diff` before assuming a change you made caused it.

There is no flag to run a single case. To iterate on one case, run it inline (the README has a
Jupyter cell walkthrough) rather than editing `runner.py`'s loop.

## Architecture

Four stages, in dependency order: `data/` → `runner.py` → `graders.py` → `report.py`, with
`cost_analysis.py` hanging off the runner's output as a separate branch.

**The response schema is duplicated in three places and they must move together.** The JSON shape
the model is told to emit (`affected_orders`, `severity`, `revenue_at_risk_usd`, `reasoning`) is
defined in `SYSTEM_PROMPT` in `runner.py`, mirrored by every `golden_answer` in
`data/test_cases.json`, and read key-by-key in `graders.py`. Adding or renaming a field means
touching all three.

**Results file naming is load-bearing.** `runner.py` writes both `results_<model>.json` (a
per-model archive) and `results.json` (a copy of the most recent run). `report.py` reads only
`results.json`. `cost_analysis.py` globs `results_*.json` for real per-model costs and reads
`results.json` separately for the hypothetical cross-model table — so the underscore-prefixed name
is what makes multi-model cost comparison work, and re-running the same model overwrites its
archive.

**Parse failures are data, not exceptions.** `extract_json` in `runner.py` tries bare JSON, then a
fenced `json` block, then the last `{` in the text. If all three fail it stores
`{"parse_error": True, "raw": ...}`, `graders.py` short-circuits on that key, and `report.py`
prints `PARSE ERROR` for the row. Keep that contract when changing any of the three.

**`runner.py` records per-case timing that nothing reads yet** (`prompt_build_ms`, `api_call_ms`,
`parse_ms`, `total_ms`, `output_tokens_per_sec`). It's staged for the Phase 2 latency comparison in
`harness-and-evals-onepager.md` — don't strip it as dead weight.

**`cost_analysis.py` silently skips cases** whose `model` isn't a key in `PRICING_PER_MTOK`. That
table is maintained by hand from published pricing and carries dated caveats in its comments
(intro pricing with an expiry, and a tokenizer note explaining why the hypothetical table is only
an approximation). Add a model there before running it.

## Grading conventions

These are judgment calls baked into the golden answers, not derivable from the data:

- **Affected order** = pooled demand for the part across *all* open orders exceeds
  `on_hand + in_transit`. Any shortfall flags every order sharing that part.
- **Dual sourcing is not a shortfall.** Case 3 is a deliberate negative test: a delay at one of
  P-1020's two suppliers should yield an empty `affected_orders`. It exists to catch
  pattern-matching ("supplier delay" → "orders affected") rather than actual reasoning. Don't
  "fix" a model failure there by loosening the grader.
- **Revenue tolerance** is 5%, except a golden of 0 requires exact 0 (no dividing by zero); that
  branch returns `pct_off: None` to mean undefined.
- **Hallucination** means citing an order ID absent from `supply_chain.json` entirely — distinct
  from citing a real-but-wrong ID, which precision/recall already penalizes.
- **Empty sets score 1.0 by convention** in `grade_order_ids` (the `if (tp + fp)` / `if (tp + fn)`
  guards). That's what lets case 3 earn a perfect score for correctly predicting nothing, but it
  also means an empty prediction against a non-empty golden gets a vacuous `precision: 1.0`. F1 is
  the trustworthy column; don't read precision in isolation.
- **`severity` counts suppliers that can beat the deadline.** `graders.py` scores it as an exact
  string match against these bands, which `SYSTEM_PROMPT` states verbatim: `none` = available
  supply (`on_hand + in_transit`) meets pooled demand, so no shortfall; otherwise count the
  disrupted part's suppliers that could replenish before the *earliest* due date among the
  affected orders — zero → `high`, exactly one → `medium`, two or more → `low`. A supplier
  qualifies if a PO placed on `as_of_date` using **that supplier's own** `lead_time_days` lands on
  or before that date, which is why lead time is per supplier-part in `supply_chain.json`.
  The rubric rests on three stated assumptions, all of which are simplifications: supplier
  capacity is unbounded (one in-time supplier covers the entire shortfall), customer tier and
  order priority are out of scope, and **the disrupted supplier never qualifies** — a new PO
  queues behind the shipment already delayed, so it is excluded from the count no matter how short
  its nominal lead time. Undisrupted suppliers are counted normally, at their own lead times.
- **A shortfall on a sole-sourced part is therefore always `high`.** Excluding the disrupted
  supplier drops the count to zero whenever the only supplier is the one that was disrupted, which
  is what puts cases 1 and 2 on `high` in agreement with their goldens — case 2 lands there
  despite SUP-004's 28-day lead time nominally beating the 2026-09-14 deadline. Reaching `medium`
  or `low` requires a multi-sourced part with a real shortfall: one healthy in-time supplier for
  `medium`, two for `low`. No current fixture reaches either, since P-1020 is the only
  multi-sourced part and carries 450 units of surplus.

`data/supply_chain.json` is small on purpose (5 suppliers, 5 parts, 8 orders) so answers stay
hand-derivable. New test cases need their golden answer worked out by hand against that data.
