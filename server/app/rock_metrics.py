"""Recovery and RQD for a Rock run, derived from the individual piece lengths.

Both are field formulas over the run interval, and both are computed here
rather than typed in, so a stored value can never disagree with the pieces it
came from.

    Recovery (%) = (sum of all piece lengths / run length) * 100
    RQD (%)      = (sum of piece lengths >= 10 cm / run length) * 100

UNITS. Depths are metres (CORE_TOP / CORE_BASE) and piece lengths are
centimetres, so the run length has to be converted before it can share a
denominator with the pieces. This is the part that is easy to get wrong: a
literal sum(cm) / interval(m) is 100x too large, so a 1.5 m run holding
120 cm of pieces would read 8000% instead of 80%.

    run length (cm) = (depth_to - depth_from) * 100
    Recovery (%)    = sum(pieces in cm) / run length in cm * 100

which is exactly sum(cm) / interval(m), and always lands in 0-100.

The 10 cm RQD threshold is the standard minimum sound piece length; it is
measured in centimetres and therefore always applied to the stored
centimetre values, never to whatever unit the user happened to type in.

Pieces are stored canonically in centimetres. The client may submit
centimetres or metres (PEACEY_UNIT_CHOICES), and the conversion happens
here so the browser never gets to decide what a number means.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# The minimum sound piece length that counts towards RQD.
RQD_MIN_PIECE_CM = Decimal("10")

CM_PER_M = Decimal("100")

# What the client is allowed to submit pieces in.
PIECE_UNITS = ("cm", "m")

# Both results are stored in AGS numeric columns that are reported to two
# decimal places, so they are rounded once, here, rather than at every read.
RESULT_SCALE = Decimal("0.01")

# Guards the per-row "+ piece" button against a runaway paste. This must match
# the client's cap in RockModule.tsx: when they disagreed (500 here, 100 there)
# the UI silently refused input the API would have accepted, and a scripted
# client could store runs the form could not render.
MAX_PIECES = 100


class RockValidationError(ValueError):
    """A Rock run that cannot produce meaningful Recovery / RQD."""


@dataclass(frozen=True)
class RockMetrics:
    recovery: Decimal
    rqd: Decimal
    total_piece_cm: Decimal
    qualifying_piece_cm: Decimal
    run_length_cm: Decimal


def to_centimetres(value: Decimal | int | str, unit: str) -> Decimal:
    """Convert one piece length into centimetres."""

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RockValidationError(f"{value!r} is not a number.") from exc

    if not amount.is_finite():
        raise RockValidationError(f"{value!r} is not a finite number.")
    if amount < 0:
        raise RockValidationError("Piece lengths cannot be negative.")

    if unit == "m":
        return amount * CM_PER_M
    if unit == "cm":
        return amount

    raise RockValidationError(
        f"Piece unit must be one of {', '.join(PIECE_UNITS)}; got {unit!r}."
    )


def pieces_to_cm(
    pieces: list[Decimal | int | str] | None, unit: str = "cm"
) -> list[Decimal]:
    """Normalise submitted pieces to centimetres, preserving their order.

    Order matters: it is the Block Number the engineer typed them in, so the
    register can show "Block 1, Block 2, ..." the way it was captured.
    """

    if pieces is None:
        return []
    if len(pieces) > MAX_PIECES:
        raise RockValidationError(
            f"A run cannot have more than {MAX_PIECES} pieces."
        )

    return [to_centimetres(piece, unit) for piece in pieces]


def compute_rock_metrics(
    pieces_cm: list[Decimal],
    depth_from,
    depth_to,
) -> RockMetrics:
    """Recovery and RQD for one run.

    `pieces_cm` must already be in centimetres (see `pieces_to_cm`).
    Raises RockValidationError rather than returning nonsense: a run whose
    pieces are longer than the run itself has no meaningful Recovery.
    """

    try:
        top = Decimal(str(depth_from))
        base = Decimal(str(depth_to))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RockValidationError("Run depths must be numbers.") from exc

    if not top.is_finite() or not base.is_finite():
        raise RockValidationError("Run depths must be finite numbers.")
    if top < 0:
        raise RockValidationError("Run Depth From cannot be negative.")
    if base <= top:
        raise RockValidationError(
            "Run Depth To must be greater than Run Depth From."
        )

    run_length_cm = (base - top) * CM_PER_M

    total = sum(pieces_cm, Decimal("0"))
    qualifying = sum(
        (piece for piece in pieces_cm if piece >= RQD_MIN_PIECE_CM),
        Decimal("0"),
    )

    # More recovered length than there was room for is physically impossible,
    # and it is the one mistake that would silently publish a wrong
    # percentage, so it is rejected instead of clamped.
    if total > run_length_cm:
        raise RockValidationError(
            "Total piece length "
            f"({total.normalize()} cm) cannot be greater than the run length "
            f"({run_length_cm.normalize()} cm)."
        )

    return RockMetrics(
        recovery=_percent(total, run_length_cm),
        rqd=_percent(qualifying, run_length_cm),
        total_piece_cm=total,
        qualifying_piece_cm=qualifying,
        run_length_cm=run_length_cm,
    )


def _percent(part: Decimal, whole: Decimal) -> Decimal:
    if whole <= 0:
        raise RockValidationError("Run length must be greater than zero.")
    return (part / whole * Decimal("100")).quantize(
        RESULT_SCALE, rounding=ROUND_HALF_UP
    )