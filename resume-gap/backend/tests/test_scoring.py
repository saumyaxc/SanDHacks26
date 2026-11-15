from app.domain.enums import Bucket, Priority
from app.domain.scoring import match_score

R, P = Priority.REQUIRED, Priority.PREFERRED
C, U, T, G = Bucket.COVERED, Bucket.UNDEREMPHASIZED, Bucket.TRANSFERABLE, Bucket.GAP


def test_required_weighs_double():
    # required covered (2*1) + preferred gap (1*0) = 2/3
    s = match_score([(R, [C]), (P, [G])])
    assert (s.percent, s.required_met, s.required_total) == (67, 1, 1)


def test_partial_credit_by_bucket():
    s = match_score([(R, [U]), (R, [T]), (R, [G])])
    # (0.8 + 0.4 + 0) / 3
    assert (s.percent, s.required_met) == (40, 1)


def test_group_counts_once_at_best_member():
    s = match_score([(R, [G, G, C])])
    assert (s.percent, s.required_met, s.required_total) == (100, 1, 1)


def test_verdicts():
    assert match_score([(R, [C]), (P, [T])]).verdict == "strong"  # (2 + 0.4) / 3 = 80
    assert match_score([(R, [U]), (R, [G]), (P, [C])]).verdict == "tailor"  # 2.6 / 5 = 52
    assert match_score([(R, [G]), (P, [C])]).verdict == "stretch"  # 1 / 3 = 33
    assert match_score([]).percent == 0


def test_failed_eligibility_overrides_verdict_but_keeps_percent():
    s = match_score([(R, [C])], ineligible=True)
    assert (s.percent, s.verdict) == (100, "not_eligible")
