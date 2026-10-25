"""Reviewed rate definitions and arithmetic, without model-authored prose."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from askbrieves.rates import SOURCE_BASE

TREASURY_FAQ = (
    "https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/"
    "interest-rates-frequently-asked-questions"
)
TREASURY_OVERVIEW = (
    "https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics"
)
BASIS_POINT_SOURCE = "https://www.investor.gov/introduction-investing/investing-basics/glossary/basis-point"
TERM_SPREAD_SOURCE = (
    "https://libertystreeteconomics.newyorkfed.org/2021/11/"
    "the-term-spread-as-a-predictor-of-financial-instability/"
)
FED_FUNDS_SOURCE = "https://www.federalreserve.gov/economy-at-a-glance-policy-rate.htm"

# These are paraphrased, fixed educational explanations, checked against the
# linked primary sources. Topic selection never permits generated answer text.
_CONCEPTS = {
    "basis_point": (
        "One basis point is 0.01 percentage point; 100 basis points equal 1 percentage point. "
        "For example, a rate rising from 4.00% to 4.25% increases by 25 basis points. "
        "Basis points express the absolute difference between rates, rather than their relative percent change.",
        (BASIS_POINT_SOURCE,),
    ),
    "treasury_yield": (
        "A Treasury yield expresses an annualized rate associated with U.S. government debt. "
        "AskBrieves reports Treasury's daily par yields at fixed maturities, such as 2 or 10 years. "
        "These are points on Treasury's estimated curve and may differ from the yield on a particular security.",
        (TREASURY_FAQ,),
    ),
    "yield_curve": (
        "A yield curve relates yields to time until maturity. Treasury's par yield curve shows "
        "maturity-specific yields derived from indicative market prices. Comparing a short maturity "
        "with a longer one describes a segment of that curve; two observations do not describe every maturity.",
        (TREASURY_OVERVIEW,),
    ),
    "yield_curve_inversion": (
        "A yield-curve segment is inverted when its longer-term yield is below its shorter-term yield. "
        "For the 2-year/10-year segment, that means the 10-year minus 2-year spread is negative. "
        "This comparison describes that segment; it neither establishes the shape of the entire curve "
        "nor guarantees a recession.",
        (TERM_SPREAD_SOURCE,),
    ),
    "yield_spread": (
        "A yield spread is the difference between two yields. For the 10-year minus 2-year Treasury spread, "
        "subtract the 2-year yield from the 10-year yield. A difference of 0.50 percentage point equals "
        "50 basis points. The subtraction order matters: reversing it reverses the sign.",
        (TERM_SPREAD_SOURCE, BASIS_POINT_SOURCE),
    ),
    "yield_vs_apy": (
        "Treasury par yields are simple annualized, bond-equivalent rates based on semiannual interest payments. "
        "An annual percentage yield (APY) includes compounding. A displayed Treasury par yield therefore "
        "uses a different convention from a bank deposit APY; the two percentages are not directly interchangeable.",
        (TREASURY_FAQ,),
    ),
    "fed_funds_vs_treasury": (
        "The federal funds rate concerns overnight borrowing between banks, and the FOMC sets its target range. "
        "Treasury yields concern U.S. government debt across different maturities and are derived from market prices. "
        "AskBrieves's Treasury observations are separate from the federal funds rate and its policy target range.",
        (FED_FUNDS_SOURCE, TREASURY_OVERVIEW),
    ),
}
TOPICS = tuple(_CONCEPTS)


def _citation(sources: list[str] | tuple[str, ...]) -> str:
    unique_sources = list(dict.fromkeys(sources))
    return ("Source: " if len(unique_sources) == 1 else "Sources: ") + " | ".join(unique_sources)


def explain_concept(topic: str) -> dict:
    """Return one of seven reviewed definitions; unknown topics fail closed."""
    if not isinstance(topic, str) or topic not in _CONCEPTS:
        raise ValueError("Unsupported interest-rate concept.")
    explanation, sources = _CONCEPTS[topic]
    evidence = {
        "topic": topic,
        "description": "Reviewed interest-rate glossary",
        "source_url": sources[0],
    }
    if len(sources) > 1:
        evidence["source_urls"] = list(sources)
    return {"answer": explanation + " " + _citation(sources), "evidence": evidence}


def _rate(value: str) -> Decimal:
    if (
        not isinstance(value, str)
        or len(value) > 8
        or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value)
    ):
        raise ValueError("Invalid Treasury curve evidence.")
    result = Decimal(value)
    if result > Decimal("100"):
        raise ValueError("Invalid Treasury curve evidence.")
    return result


def curve_answer(evidence: dict) -> str:
    """Describe the 2-year/10-year segment for one or two verified observations."""
    if not isinstance(evidence, dict):
        raise ValueError("Invalid Treasury curve evidence.")
    observations = evidence.get("observations", [evidence])
    if not isinstance(observations, list) or not 1 <= len(observations) <= 2:
        raise ValueError("Invalid Treasury curve evidence.")

    paragraphs = []
    sources = []
    for observation in observations:
        if not isinstance(observation, dict):
            raise ValueError("Invalid Treasury curve evidence.")
        as_of = observation.get("as_of")
        if not isinstance(as_of, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", as_of):
            raise ValueError("Invalid Treasury curve evidence.")
        try:
            date.fromisoformat(as_of)
        except ValueError as exc:
            raise ValueError("Invalid Treasury curve evidence.") from exc
        expected_source = SOURCE_BASE + as_of[:7].replace("-", "")
        if observation.get("source_url") != expected_source:
            raise ValueError("Invalid Treasury curve evidence.")
        yields = observation.get("rates")
        if not isinstance(yields, dict) or set(yields) != {"2y", "10y"}:
            raise ValueError("Invalid Treasury curve evidence.")
        short_yield, long_yield = _rate(yields["2y"]), _rate(yields["10y"])
        spread = (long_yield - short_yield) * 100
        shape = "inverted" if spread < 0 else "upward sloping" if spread > 0 else "flat"
        displayed_spread = f"{spread:+.0f}" if spread else "0"
        unit = "basis point" if abs(spread) == 1 else "basis points"
        paragraphs.append(
            f"As of {as_of}, the 2-year Treasury par yield was {short_yield:.2f}% "
            f"and the 10-year was {long_yield:.2f}%. The 10-year minus 2-year spread "
            f"was {displayed_spread} {unit}, so the 2-year/10-year segment was {shape}."
        )
        sources.append(expected_source)
    return (
        " ".join(paragraphs)
        + " This describes only the 2-year/10-year segment. It is not a recession forecast. "
        + "These are daily par yields, not live quotes or deposit APYs. "
        + _citation(sources)
    )
