# Supply Chain Eval Harness — Phase 1

A minimal eval harness against the Claude API, testing a supply-chain risk-analysis prompt
against five hand-derived golden answers.

## Structure

```
harness/
  data/
    supply_chain.json   # mock dataset: 5 suppliers, 5 parts, 9 orders
    test_cases.json      # 5 scenarios with golden answers
  runner.py               # loop: build prompt -> call API -> store response
  graders.py              # order-ID precision/recall, revenue tolerance, severity band,
                          #   hallucination check
  report.py                # tallies grader scores into a scorecard
```

Running `runner.py` produces `results.json`. Running `report.py` reads that and produces
`scorecard.json` plus a printed table.

## Setup (works the same in Cursor or Jupyter)

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...   # or set it in a .env and load with python-dotenv
```

## Running in Cursor

```bash
cd harness
python runner.py
python report.py
```

## Running in Jupyter

Same code, cell-by-cell, which is the better environment while you're still iterating on the
prompt or grading rule:

```python
# Cell 1
import json
from anthropic import Anthropic
client = Anthropic()
MODEL = "claude-sonnet-4-6"

# Cell 2 -- paste SYSTEM_PROMPT from runner.py

# Cell 3 -- run a single case and inspect the raw response before parsing
supply_chain = json.load(open("data/supply_chain.json"))
test_cases = json.load(open("data/test_cases.json"))
case = test_cases[0]

response = client.messages.create(
    model=MODEL,
    max_tokens=500,
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": f"SUPPLY CHAIN DATA:\n{json.dumps(supply_chain)}\n\nSCENARIO:\n{case['scenario']}"}]
)
print(response.content[0].text)

# Cell 4 -- once the prompt is stable, loop all cases and json.loads() each response
```

Once the prompt/grading logic stabilizes in Jupyter, the `.py` files here are the "porting to a
real repo" version -- same API calls, same dict comparisons, just structured for `python
runner.py && python report.py` instead of a notebook run-all.

## Design notes (the part that isn't code)

- **Affected-order rule**: an order is affected if pooled demand for its part exceeds
  `on_hand + in_transit`, given the disruption. A single-supplier delay on a dual-sourced part
  does *not* zero out supply — case 3 exists specifically to test that the model doesn't
  over-flag on pattern-match alone ("supplier delay" -> "orders affected") without checking
  whether an alternate supplier exists.
- **Revenue tolerance**: 5% by default in `grade_revenue`. Case 3's golden revenue is exactly 0,
  so that grader requires an exact-zero match rather than a percentage band (dividing by zero
  golden revenue is undefined).
- **Hallucination check**: flags any order ID the model cites that doesn't exist anywhere in
  `supply_chain.json` at all — a distinct failure mode from citing a real-but-wrong order ID,
  which the precision/recall grader already catches.

## Next steps (Phase 1 remainder)

- [ ] Run `runner.py` against all 5 cases, eyeball `results.json` for parse failures or
      reasoning that gets the right answer for the wrong reason
- [ ] Add a model-based grader (Claude scoring the `reasoning` field against a rubric) for the
      cases where "correct" isn't just a set match
- [ ] Expand to ~20 cases once the 5-case loop is solid
