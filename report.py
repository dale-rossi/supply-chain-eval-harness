"""
Report: tally grader scores into a scorecard table.

results.json holds one record per (case, run) -- see RUNS_PER_CASE in runner.py --
so scores are aggregated per case: a mean F1 plus a k/n pass count for each
boolean column. The Stable column is the point of sampling: `NO` means the runs
disagreed, so a single-run report would have called that case a pass or a failure
depending on luck.

Run after runner.py:
  python report.py
"""

import json

from graders import grade_case


def summarize(case_id, runs):
    """Collapse one case's runs into a single row. Parse errors are counted, not
    graded -- a run that produced no JSON can't contribute an F1."""
    graded = [r for r in runs if not r.get("parse_error")]
    parse_errors = len(runs) - len(graded)

    summary = {
        "case_id": case_id,
        "runs": len(runs),
        "parse_errors": parse_errors,
    }
    if not graded:
        summary["stable"] = False
        return summary

    n = len(graded)
    f1s = [r["order_id_scores"]["f1"] for r in graded]
    counts = {
        "revenue_pass": sum(r["revenue_scores"]["pass"] for r in graded),
        "no_hallucination_pass": sum(r["hallucination_scores"]["pass"] for r in graded),
        "severity_pass": sum(r["severity_match"] for r in graded),
    }
    summary.update(
        graded_runs=n,
        f1_mean=round(sum(f1s) / n, 3),
        f1_min=min(f1s),
        f1_max=max(f1s),
        **counts,
        # Stable means every run agreed on every column. A split count, a spread
        # of F1s, or any parse error all make the case's verdict luck-dependent.
        stable=(
            parse_errors == 0
            and min(f1s) == max(f1s)
            and all(c in (0, n) for c in counts.values())
        ),
    )
    return summary


def main():
    with open("results.json") as f:
        results = json.load(f)
    with open("data/supply_chain.json") as f:
        supply_chain = json.load(f)

    valid_order_ids = {o["id"] for o in supply_chain["orders"]}
    per_run = [grade_case(case, valid_order_ids) for case in results]

    by_case = {}
    for scores in per_run:  # dicts preserve insertion order, so case order is kept
        by_case.setdefault(scores["case_id"], []).append(scores)

    header = (
        f"{'Case':<10}{'Runs':<6}{'F1 mean':<9}{'Revenue':<10}"
        f"{'No Halluc.':<12}{'Severity':<11}{'Stable':<7}"
    )
    print(header)
    print("-" * len(header))

    summaries = [summarize(cid, runs) for cid, runs in by_case.items()]
    for s in summaries:
        if not s.get("graded_runs"):
            print(f"{s['case_id']:<10}{s['runs']:<6}ALL RUNS PARSE ERROR (see results.json)")
            continue
        n = s["graded_runs"]
        rev = f"{s['revenue_pass']}/{n}"
        hal = f"{s['no_hallucination_pass']}/{n}"
        sev = f"{s['severity_pass']}/{n}"
        stable = "yes" if s["stable"] else "NO"
        print(
            f"{s['case_id']:<10}{s['runs']:<6}{s['f1_mean']:<9.2f}"
            f"{rev:<10}{hal:<12}{sev:<11}{stable:<7}"
        )

    unstable = [s["case_id"] for s in summaries if not s["stable"]]
    errored = [s["case_id"] for s in summaries if s["parse_errors"]]
    print()
    if unstable:
        print(f"UNSTABLE ({len(unstable)}/{len(summaries)}): {', '.join(unstable)}")
        print("  These cases' runs disagreed -- treat any single-run result on them as noise.")
    else:
        print(f"All {len(summaries)} cases stable across every run.")
    if errored:
        print(f"Parse errors in: {', '.join(errored)}")

    with open("scorecard.json", "w") as f:
        json.dump({"by_case": summaries, "runs": per_run}, f, indent=2)
    print("\nSaved scorecard.json")


if __name__ == "__main__":
    main()
