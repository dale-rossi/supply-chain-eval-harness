"""
Graders: compare model output to golden answers, produce scores.
This is the part with real logic -- everything else is bookkeeping.
"""

# DR: Helper function - Order specialist that looks at affected_orders
def grade_order_ids(golden_ids, predicted_ids):
    """Set comparison precision/recall/F1 on affected_orders."""
    golden_set, pred_set = set(golden_ids), set(predicted_ids)
    tp = len(golden_set & pred_set) # intersection of both sets
    fp = len(pred_set - golden_set) # predicted but shouldn't be
    fn = len(golden_set - pred_set) # should be but wasn't predicted
 
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    # Fallback is 0.0, not 1.0: the sum is only ever 0 when tp == 0 against a
    # non-empty golden, i.e. a total miss. Two empty sets already give 1.0 here.
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "precision": round(precision, 2),
        "recall": round(recall, 2),
        "f1": round(f1, 2),
    }

# DR: Helper function - Revenue risk tolerance check
def grade_revenue(golden_revenue, predicted_revenue, tolerance=0.05):
    """Numeric-tolerance check on revenue_at_risk_usd. Golden of 0 requires exact 0."""
    if golden_revenue == 0:
        passed = predicted_revenue == 0
        pct_off = 0.0 if passed else None  # None = undefined, flag it don't divide by zero
    else:
        pct_off = abs(predicted_revenue - golden_revenue) / golden_revenue
        passed = pct_off <= tolerance

    return {"pass": passed, "pct_off": round(pct_off, 3) if pct_off is not None else None}

# DR: Helper function - Hallucination check against valid ids
def grade_hallucination(predicted_ids, valid_order_ids):
    """Flags any cited order ID that doesn't exist in the source data at all."""
    hallucinated = [oid for oid in predicted_ids if oid not in valid_order_ids]
    return {"hallucinated_ids": hallucinated, "pass": len(hallucinated) == 0}

# DR: Orchestrator function - for each Case, routes each field to the right grader - assembles results into a single dictionary
def grade_case(case, valid_order_ids):
    predicted = case["model_response"]

    if predicted.get("parse_error"):
        return {"case_id": case["case_id"], "parse_error": True}

    golden = case["golden_answer"]
    predicted_ids = predicted.get("affected_orders", [])

    return {
        "case_id": case["case_id"],
        "order_id_scores": grade_order_ids(golden["affected_orders"], predicted_ids),
        "revenue_scores": grade_revenue(
            golden["revenue_at_risk_usd"], predicted.get("revenue_at_risk_usd", 0)
        ),
        "hallucination_scores": grade_hallucination(predicted_ids, valid_order_ids),
        "severity_match": predicted.get("severity") == golden["severity"],
    }
