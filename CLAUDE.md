# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A from-scratch (no eval framework) harness that scores Claude on a supply-chain risk-analysis
prompt against four hand-derived golden answers. `harness-and-evals-onepager.md` is the design
document behind it and tracks the build phases; `README.md` covers the same ground for a reader.

## Commands

There is no test suite, linter, or build step. Everything runs through the local `venv/`
(Python 3.14, `anthropic` + `pandas` installed). It is gitignored and there is no
`requirements.txt`, so a fresh clone needs `pip install anthropic pandas`.

```bash
source venv/bin/activate
export ANTHROPIC_API_KEY=sk-ant-...

python runner.py                              # calls the API for all 4 cases -> results.json
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
- **A supplier delay is not itself a shortfall.** Case 3 is the negative control: a delay at
  Corvair, P-1040's sole supplier, must still yield an empty `affected_orders`, because 5000
  on-hand dwarfs the 900 pooled demand. It exists to catch pattern-matching ("supplier delay" →
  "orders affected") rather than actual reasoning. Don't "fix" a model failure there by loosening
  the grader. The dual-sourcing rule — one supplier's delay never removes the other's capacity —
  is exercised by case 4 instead, where it decides `medium` vs `high` rather than whether a
  shortfall exists at all.
- **Case 3 moved from P-1020 to P-1040 when SO-4009 was added.** It was previously a dual-sourcing
  negative test on the precision housing, and it held only because P-1020 pooled demand (750) sat
  under available supply (1200). SO-4009 adds 500 units, taking pooled demand to 1250 and putting
  P-1020 short by 50 — which would have flipped case 3 to three affected orders at `high` and
  silently destroyed the harness's only negative control. Keep the negative control on a part with
  a large deliberate surplus; P-1040 has 4100 units of headroom.
- **`safety_stock` is never deducted.** Available supply is `on_hand + in_transit`, full stop —
  `SYSTEM_PROMPT` defines it that way and never mentions `safety_stock`, even though the field sits
  in plain view in `supply_chain.json`. Case 6 is the control: P-1060 holds 400 on hand against 150
  pooled demand, so the golden is `none`, but a model that protects the 300-unit safety stock sees
  100 available, invents a 50-unit shortfall and returns `high` / `SO-4010` / `540000`. The failure
  signature is single-valued on purpose — SUP-006's 24-day lead time lands a PO on 2026-08-27,
  after SO-4010's 2026-08-20 due date, so a model that also forgets the disrupted-supplier
  exclusion still reaches `high` rather than `medium`. Don't "fix" a failure here by teaching
  `SYSTEM_PROMPT` about `safety_stock`; that deletes the fixture.
- **Case 6, not case 5, is the isolated safety-stock test.** Case 5 was built for that job, but
  Meridian supplies both P-1010 and P-1050, and Haiku failed it by answering about P-1010 and
  reproducing case-1's answer verbatim — never reaching the safety-stock step. Both traps are still
  live in case 5, so a failure there needs its `reasoning` read to tell which one fired. SUP-006
  supplies only P-1060, which is what makes case 6 unambiguous; keep it that way.
- **Revenue tolerance** is 5%, except a golden of 0 requires exact 0 (no dividing by zero); that
  branch returns `pct_off: None` to mean undefined.
- **Hallucination** means citing an order ID absent from `supply_chain.json` entirely — distinct
  from citing a real-but-wrong ID, which precision/recall already penalizes.
- **Only a both-empty comparison scores 1.0** in `grade_order_ids`. Correctly predicting nothing is
  a perfect score — cases 3 and 5 depend on it — so it is special-cased ahead of the ratios. Past
  that branch every zero denominator means a wrong answer and returns `0.0`, which is what makes
  all three columns independently readable. Two earlier conventions were wrong and both are gone
  as of 2026-08-14: F1 returned `1.0` whenever a prediction was disjoint from a non-empty golden,
  scoring a total miss as perfect and leaving cases 1, 2 and 4 unguarded; and precision/recall each
  returned `1.0` for their own undefined case, so an empty prediction against a non-empty golden
  read `precision: 1.0`, and a non-empty prediction against an empty golden read `recall: 1.0`.
  That last one is not hypothetical — it is what Haiku's failed case-5 run scored before the fix.
  Don't reintroduce a `1.0` fallback for an undefined ratio; vacuous truth reads as success.
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
  `medium`, two for `low`. Case 4 is that `medium` fixture, and it is deliberately tight —
  Aldridge clears the 2026-08-26 deadline by two days, so moving SO-4004's due date earlier, or
  disrupting Aldridge instead of Kessler, flips it to `high`. `low` is still unreachable: it needs
  a third supplier on some part, or a shortfall with no supplier disrupted at all.

`data/supply_chain.json` is small on purpose (6 suppliers, 6 parts, 10 orders) so answers stay
hand-derivable. New test cases need their golden answer worked out by hand against that data.

## Comments

Comments prefixed `# DR:` are the owner's notes. Preserve them when editing;never rewrite or remove them.