"""
Report: tally grader scores into a scorecard table.

Run after runner.py:
  python report.py
"""

import json
from graders import grade_case


def main():
    with open("results.json") as f:
        results = json.load(f)
    with open("data/supply_chain.json") as f:
        supply_chain = json.load(f)

    valid_order_ids = {o["id"] for o in supply_chain["orders"]}

    header = f"{'Case':<10}{'F1':<6}{'Revenue OK':<12}{'No Halluc.':<12}{'Severity OK':<12}"
    print(header)
    print("-" * len(header))

    all_scores = []
    for case in results:
        scores = grade_case(case, valid_order_ids)
        all_scores.append(scores)

        if scores.get("parse_error"):
            print(f"{scores['case_id']:<10}PARSE ERROR (see results.json)")
            continue

        print(
            f"{scores['case_id']:<10}"
            f"{scores['order_id_scores']['f1']:<6}"
            f"{str(scores['revenue_scores']['pass']):<12}"
            f"{str(scores['hallucination_scores']['pass']):<12}"
            f"{str(scores['severity_match']):<12}"
        )

    with open("scorecard.json", "w") as f:
        json.dump(all_scores, f, indent=2)
    print("\nSaved scorecard.json")


if __name__ == "__main__":
    main()
