from scout.pipeline import hard_gate_reasons, is_duplicate, normalize_candidate, similarity


def good(name="Example"):
    return normalize_candidate({
        "name": name, "type":"public_markets", "vertical":"public_markets", "geography":"Canada",
        "signal":"verified filing changed financing", "what_changed":"new committed financing", "why_now":"valuation not updated",
        "thesis":"The financing may reduce dilution risk and change risked per-share value.",
        "value_capture_mechanism":"Potential public-market repricing if risk falls faster than valuation rises.",
        "evidence":[
            {"title":"Filing","url":"https://example.com/a","source_type":"primary","claim":"financing"},
            {"title":"Independent","url":"https://example.com/b","source_type":"independent","claim":"market context"}
        ],
        "evidence_confidence":0.8,"real":True,"actionable":True,
        "participation_path":"Research the listed security through a supported brokerage before any decision."
    })


def test_good_candidate_passes_hard_gates():
    assert hard_gate_reasons(good()) == []


def test_fake_candidate_fails():
    op = normalize_candidate({"name":"fake","value_capture_mechanism":"","real":False,"actionable":False,"evidence":[]})
    assert len(hard_gate_reasons(op)) >= 4


def test_duplicate_detection():
    a = good("Aclara financing thesis")
    b = good("Aclara financing thesis")
    assert similarity(a, b) == 1.0
    assert is_duplicate(b, [a], 0.72)
