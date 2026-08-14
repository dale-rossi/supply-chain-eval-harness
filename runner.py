"""
Runner: loop through test cases -> call Claude -> store raw + parsed responses.

Setup:
  pip install anthropic python-dotenv
  export ANTHROPIC_API_KEY=sk-ant-...   # or put it in a .env beside this script

Run:
  python runner.py
"""

import json
import re
import os
import time
from anthropic import Anthropic

try:
    from dotenv import load_dotenv
    load_dotenv()  # .env is optional; a real environment variable always wins
except ImportError:
    pass

client = Anthropic()  # reads ANTHROPIC_API_KEY from environment (or .env, loaded above)

# Override with: export HARNESS_MODEL=claude-haiku-4-5-20251001 (or set it in .env)
MODEL = os.environ.get("HARNESS_MODEL", "claude-sonnet-4-6")

def extract_json(raw_text):
    """Pull a JSON object out of a response, even if the model wrapped it in
    prose and/or a ```json fence instead of returning bare JSON as asked."""
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```json\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    last_brace = raw_text.rfind("{")
    if last_brace != -1:
        try:
            return json.loads(raw_text[last_brace:])
        except json.JSONDecodeError:
            pass

    return None

SYSTEM_PROMPT = """You are a supply chain risk analyst. You will be given the full supply chain
dataset (suppliers, parts, inventory, orders) and a disruption scenario.

Determine which open orders are affected using this rule: an order is affected if the pooled
demand for its part (summed across ALL open orders needing that part) exceeds the part's
available supply (on_hand + in_transit), given the disruption described. If a part has more than
one supplier and the disruption affects only one of them, treat the other supplier's capacity as
still fully available -- a single-supplier delay on a dual-sourced part is not itself a shortfall.

Then assign severity by counting how many of the disrupted part's suppliers could replenish it
before the earliest due date among the affected orders:

  none   -- available supply (on_hand + in_transit) >= pooled demand; there is no shortfall
  high   -- shortfall, and zero suppliers can deliver in time
  medium -- shortfall, and exactly one supplier can deliver in time
  low    -- shortfall, and two or more suppliers can deliver in time

A supplier counts as able to deliver in time if a purchase order placed on the dataset's
as_of_date, using THAT supplier's own lead_time_days, arrives on or before the earliest affected
due date. Each supplier of a part carries its own lead time, so an alternate supplier may be
slower or faster than the disrupted one -- judge an alternate by its own lead time, never by the
disrupted supplier's.

Assume the following: supplier capacity is unbounded, so any supplier that can deliver in time can
cover the whole shortfall; customer tier and order priority do not affect severity; and a supplier
named as disrupted never counts as able to deliver in time, because a newly placed purchase order
queues behind the shipment that is already delayed. Suppliers that are not disrupted count
normally, at their own lead times.

Work through your reasoning first if you find that helpful, then finish your response with a
JSON object in exactly this shape, on its own line, with no text after it:
{
  "affected_orders": ["SO-XXXX", ...],
  "severity": "none" | "low" | "medium" | "high",
  "revenue_at_risk_usd": <integer, sum of revenue_usd for affected orders, 0 if none>,
  "reasoning": "<1-3 sentences>"
}"""


def load_json(path):
    with open(path) as f:
        return json.load(f)


def run():
    supply_chain = load_json("data/supply_chain.json")
    test_cases = load_json("data/test_cases.json")
    results = []

    for case in test_cases:
        t0 = time.perf_counter()
        user_prompt = (
            f"SUPPLY CHAIN DATA:\n{json.dumps(supply_chain, indent=2)}\n\n"
            f"SCENARIO:\n{case['scenario']}"
        )
        t1 = time.perf_counter()  # end of prompt build / start of API call

        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        t2 = time.perf_counter()  # end of API call / start of parsing

        raw_text = response.content[0].text
        parsed = extract_json(raw_text)
        if parsed is None:
            parsed = {"parse_error": True, "raw": raw_text}
        t3 = time.perf_counter()  # end of parsing

        api_call_s = t2 - t1
        timing = {
            "prompt_build_ms": round((t1 - t0) * 1000, 1),
            "api_call_ms": round(api_call_s * 1000, 1),
            "parse_ms": round((t3 - t2) * 1000, 1),
            "total_ms": round((t3 - t0) * 1000, 1),
            "output_tokens_per_sec": (
                round(response.usage.output_tokens / api_call_s, 1) if api_call_s > 0 else None
            ),
        }

        results.append(
            {
                "case_id": case["id"],
                "scenario": case["scenario"],
                "golden_answer": case["golden_answer"],
                "model_response": parsed,
                "model": MODEL,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                "timing": timing,
            }
        )
        print(
            f"Ran {case['id']} ({MODEL}): {parsed.get('severity', 'PARSE ERROR')} "
            f"[{response.usage.input_tokens} in / {response.usage.output_tokens} out] "
            f"[{timing['total_ms']}ms total, {timing['output_tokens_per_sec']} tok/s]"
        )
    out_path = f"results_{MODEL.replace('.', '_')}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    # Also write results.json so report.py's default path keeps working.
    with open("results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {out_path} (and results.json)")


if __name__ == "__main__":
    run()
