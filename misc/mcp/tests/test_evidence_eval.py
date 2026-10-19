"""Golden claim evals: false confidence and equivalent wording both matter."""
import pytest
from cpu_perf.evidence import audit
from eval_evidence import CASES


@pytest.mark.parametrize("ident,text,verdict,present,absent", CASES, ids=[c[0] for c in CASES])
def test_evidence_cases(ident, text, verdict, present, absent):
    result = audit(text)
    states = {f.number: f.status for f in result.fields}
    assert result.verdict == verdict, result
    assert all(states[n] == "present" for n in present), result
    assert all(states[n] != "present" for n in absent), result
