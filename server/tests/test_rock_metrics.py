"""Recovery / RQD derived from individual piece lengths."""
from decimal import Decimal

import pytest

from app.rock_metrics import (
    MAX_PIECES,
    RQD_MIN_PIECE_CM,
    RockValidationError,
    compute_rock_metrics,
    pieces_to_cm,
    to_centimetres,
)


class TestUnits:
    def test_centimetres_pass_through(self):
        assert to_centimetres(Decimal("12.5"), "cm") == Decimal("12.5")

    def test_metres_convert_to_centimetres(self):
        assert to_centimetres(Decimal("0.25"), "m") == Decimal("25.00")

    def test_unknown_unit_is_rejected(self):
        with pytest.raises(RockValidationError, match="Piece unit must be"):
            to_centimetres(Decimal("10"), "inches")

    def test_negative_piece_is_rejected(self):
        with pytest.raises(RockValidationError, match="negative"):
            to_centimetres(Decimal("-1"), "cm")

    def test_non_numeric_is_rejected(self):
        with pytest.raises(RockValidationError, match="not a number"):
            to_centimetres("abc", "cm")

    def test_nan_is_rejected(self):
        with pytest.raises(RockValidationError, match="finite"):
            to_centimetres(Decimal("NaN"), "cm")

    def test_order_is_preserved(self):
        assert pieces_to_cm(["30", "5", "12.5"], "cm") == [
            Decimal("30"),
            Decimal("5"),
            Decimal("12.5"),
        ]

    def test_none_is_an_empty_run(self):
        assert pieces_to_cm(None) == []

    def test_piece_cap_is_enforced(self):
        with pytest.raises(RockValidationError, match="more than"):
            pieces_to_cm(["1"] * (MAX_PIECES + 1), "cm")


class TestRecovery:
    def test_full_recovery(self):
        # 1.5 m run holding 150 cm of pieces is 100%.
        m = compute_rock_metrics([Decimal("150")], Decimal("0"), Decimal("1.5"))
        assert m.recovery == Decimal("100.00")
        assert m.rqd == Decimal("100.00")

    def test_no_pieces_is_zero(self):
        m = compute_rock_metrics([], Decimal("0"), Decimal("1.5"))
        assert m.recovery == Decimal("0.00")
        assert m.rqd == Decimal("0.00")

    def test_partial_recovery(self):
        # 120 cm out of a 150 cm run.
        m = compute_rock_metrics([Decimal("120")], Decimal("0"), Decimal("1.5"))
        assert m.recovery == Decimal("80.00")

    def test_fractional_run_length(self):
        # 0.45 m = 45 cm, holding 30 cm.
        m = compute_rock_metrics([Decimal("30")], Decimal("1.00"), Decimal("1.45"))
        assert m.recovery == Decimal("66.67")

    def test_sum_of_several_pieces(self):
        m = compute_rock_metrics(
            [Decimal("40"), Decimal("35"), Decimal("25")],
            Decimal("0"),
            Decimal("1.0"),
        )
        assert m.recovery == Decimal("100.00")

    def test_more_pieces_than_run_length_is_rejected(self):
        with pytest.raises(RockValidationError, match="cannot be greater"):
            compute_rock_metrics([Decimal("200")], Decimal("0"), Decimal("1.5"))

    def test_recovery_is_rounded_to_two_places(self):
        # 1 cm out of a 3 m (300 cm) run is 0.33%.
        m = compute_rock_metrics([Decimal("1")], Decimal("0"), Decimal("3"))
        assert m.recovery == Decimal("0.33")


class TestRqd:
    def test_only_pieces_at_or_above_ten_count(self):
        # Run 0-100 cm. 10 + 50 + 30 = 90 cm qualifies, so RQD is 90%. The
        # 9.99 cm piece still counts towards recovery, giving 99.99%.
        m = compute_rock_metrics(
            [Decimal("10"), Decimal("50"), Decimal("9.99"), Decimal("30")],
            Decimal("0"),
            Decimal("1.0"),
        )
        assert m.rqd == Decimal("90.00")
        assert m.recovery == Decimal("99.99")

    def test_threshold_is_inclusive(self):
        m = compute_rock_metrics(
            [Decimal(str(RQD_MIN_PIECE_CM))], Decimal("0"), Decimal("1.0")
        )
        assert m.rqd == Decimal("10.00")

    def test_just_under_threshold_is_excluded(self):
        m = compute_rock_metrics(
            [Decimal("9.99")], Decimal("0"), Decimal("1.0")
        )
        assert m.rqd == Decimal("0.00")

    def test_short_pieces_still_count_towards_recovery(self):
        # Recovery sees every piece, RQD only the long ones.
        m = compute_rock_metrics(
            [Decimal("95"), Decimal("5")], Decimal("0"), Decimal("1.0")
        )
        assert m.recovery == Decimal("100.00")
        assert m.rqd == Decimal("95.00")

    def test_rqd_never_exceeds_recovery(self):
        m = compute_rock_metrics(
            [Decimal("80"), Decimal("20")], Decimal("0"), Decimal("1.0")
        )
        assert m.rqd <= m.recovery


class TestDepthValidation:
    def test_depth_to_must_exceed_depth_from(self):
        with pytest.raises(RockValidationError, match="must be greater"):
            compute_rock_metrics([], Decimal("5"), Decimal("5"))

    def test_reversed_interval_is_rejected(self):
        with pytest.raises(RockValidationError, match="must be greater"):
            compute_rock_metrics([], Decimal("5"), Decimal("2"))

    def test_negative_depth_is_rejected(self):
        with pytest.raises(RockValidationError, match="negative"):
            compute_rock_metrics([], Decimal("-1"), Decimal("2"))

    def test_non_numeric_depth_is_rejected(self):
        with pytest.raises(RockValidationError, match="must be numbers"):
            compute_rock_metrics([], "x", Decimal("2"))

    def test_total_exactly_equal_to_run_length_is_allowed(self):
        m = compute_rock_metrics([Decimal("100")], Decimal("0"), Decimal("1.0"))
        assert m.recovery == Decimal("100.00")


class TestEndToEndUnits:
    def test_same_run_entered_in_metres_gives_the_same_answer(self):
        in_cm = compute_rock_metrics(
            pieces_to_cm(["40", "50"], "cm"), Decimal("0"), Decimal("1.0")
        )
        in_m = compute_rock_metrics(
            pieces_to_cm(["0.4", "0.5"], "m"), Decimal("0"), Decimal("1.0")
        )
        assert in_cm.recovery == in_m.recovery == Decimal("90.00")
        # Both pieces clear 10 cm, so both qualify towards RQD.
        assert in_cm.rqd == in_m.rqd == Decimal("90.00")