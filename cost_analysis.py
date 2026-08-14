"""
Cost analysis: turns the token usage runner.py now records into dollar costs,
and lets you compare models.

Two different comparisons live in here -- they answer different questions,
so don't mix them up:

1. ACTUAL cost of the run(s) you've done. If you've run runner.py more than
   once with different HARNESS_MODEL values, each run is saved to its own
   results_<model>.json and this script sums real cost per model, using each
   model's own real token counts (tokenizers differ between model families,
   so token counts for the "same" prompt aren't identical across models --
   this is the only way to get a truly accurate comparison).

2. HYPOTHETICAL cost if the LAST run's token counts were billed at other
   models' rates. This is a fast estimate you can get without spending any
   more API calls, but it's an approximation: it reuses one model's actual
   token count and pretends another model would produce the same count,
   which isn't quite true (see the tokenizer note in PRICING_PER_MTOK below).

Setup:
  pip install pandas

Run (after at least one `python runner.py`):
  python cost_analysis.py
"""

import glob
import json

import pandas as pd

# Source: https://platform.claude.com/docs/en/about-claude/pricing
# Checked August 2026. Sonnet 5 is on introductory pricing through Aug 31, 2026;
# it reverts to $3/$15 on Sep 1, 2026 -- update the number below after that date.
# NOTE: Claude 4.7+ and Sonnet 5 use a newer tokenizer that produces ~30% MORE
# tokens for the same text than Sonnet 4.6 and earlier. That means a straight
# token-count comparison across model families (see build_hypothetical_table)
# is only a rough estimate, not a precise one.
PRICING_PER_MTOK = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},  # intro price thru Aug 31 2026
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-fable-5": {"input": 10.00, "output": 50.00},
}


def cost_for(model, input_tokens, output_tokens):
    rates = PRICING_PER_MTOK[model]
    input_cost = input_tokens / 1_000_000 * rates["input"]
    output_cost = output_tokens / 1_000_000 * rates["output"]
    return input_cost, output_cost


def build_actual_table():
    """Real cost per case, using each results_<model>.json file's own
    recorded model + token usage."""
    rows = []
    for path in sorted(glob.glob("results_*.json")):
        with open(path) as f:
            cases = json.load(f)
        for case in cases:
            usage = case.get("usage")
            model = case.get("model")
            if not usage or not model or model not in PRICING_PER_MTOK:
                continue
            input_cost, output_cost = cost_for(
                model, usage["input_tokens"], usage["output_tokens"]
            )
            rows.append(
                {
                    "source_file": path,
                    "case_id": case["case_id"],
                    "model": model,
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "input_cost_usd": round(input_cost, 5),
                    "output_cost_usd": round(output_cost, 5),
                    "total_cost_usd": round(input_cost + output_cost, 5),
                }
            )
    return pd.DataFrame(rows)


def build_hypothetical_table(results_path="results.json"):
    """Price ONE pass over the suite at every model's rate, for a fast
    (approximate) cross-model estimate.

    results.json holds RUNS_PER_CASE records per case, so token counts are
    averaged across a case's runs first. Without that the totals would silently
    be the cost of the whole sampled sweep while still reading as per-case."""
    with open(results_path) as f:
        cases = json.load(f)

    # case_id -> summed tokens + run count, so we can take the mean per case.
    totals = {}
    for case in cases:
        usage = case.get("usage")
        if not usage:
            continue
        acc = totals.setdefault(case["case_id"], {"input": 0, "output": 0, "runs": 0})
        acc["input"] += usage["input_tokens"]
        acc["output"] += usage["output_tokens"]
        acc["runs"] += 1

    rows = []
    for case_id, acc in totals.items():
        usage = {
            "input_tokens": round(acc["input"] / acc["runs"]),
            "output_tokens": round(acc["output"] / acc["runs"]),
        }
        for model, rates in PRICING_PER_MTOK.items():
            input_cost, output_cost = cost_for(
                model, usage["input_tokens"], usage["output_tokens"]
            )
            rows.append(
                {
                    "case_id": case_id,
                    "model": model,
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "input_cost_usd": round(input_cost, 5),
                    "output_cost_usd": round(output_cost, 5),
                    "total_cost_usd": round(input_cost + output_cost, 5),
                }
            )
    return pd.DataFrame(rows)


def main():
    actual = build_actual_table()
    if not actual.empty:
        print("=" * 70)
        print("ACTUAL cost per run (from results_<model>.json files present)")
        print("=" * 70)
        print(actual.to_string(index=False))
        print("\nTotal cost per model:")
        print(actual.groupby("model")["total_cost_usd"].sum().to_string())
        actual.to_csv("cost_actual.csv", index=False)
        print("\nSaved cost_actual.csv")
    else:
        print("No results_<model>.json files found yet -- run runner.py first.")

    print()
    print("=" * 70)
    print("HYPOTHETICAL cost of ONE pass over the suite at each model's rate,")
    print("from results.json's token counts averaged per case across its runs")
    print("(approximation -- see docstring)")
    print("=" * 70)
    hypothetical = build_hypothetical_table()
    if not hypothetical.empty:
        print(hypothetical.to_string(index=False))
        n_cases = hypothetical["case_id"].nunique()
        print(f"\nTotal hypothetical cost per model, all {n_cases} cases:")
        print(hypothetical.groupby("model")["total_cost_usd"].sum().sort_values().to_string())
        hypothetical.to_csv("cost_hypothetical.csv", index=False)
        print("\nSaved cost_hypothetical.csv")
    else:
        print("No results.json found -- run runner.py first.")


if __name__ == "__main__":
    main()
