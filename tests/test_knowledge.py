"""Offline checks for reviewed explanations and curve arithmetic."""

import copy
import unittest
from urllib.parse import urlsplit

from askbrieves.knowledge import TOPICS, curve_answer, explain_concept
from askbrieves.rates import SOURCE_BASE


def observation(as_of="2026-10-23", short="4.69", long="5.00"):
    return {
        "as_of": as_of,
        "requested_date": "latest",
        "rates": {"2y": short, "10y": long},
        "source_url": SOURCE_BASE + as_of[:7].replace("-", ""),
        "description": "U.S. Treasury daily par yields",
    }


class KnowledgeTests(unittest.TestCase):
    def test_seven_bounded_topics_have_concise_sourced_answers(self):
        self.assertEqual(set(TOPICS), {
            "basis_point", "treasury_yield", "yield_curve", "yield_curve_inversion",
            "yield_spread", "yield_vs_apy", "fed_funds_vs_treasury",
        })
        for topic in TOPICS:
            with self.subTest(topic=topic):
                result = explain_concept(topic)
                self.assertLess(len(result["answer"].split()), 80)
                self.assertEqual(result["evidence"]["topic"], topic)
                urls = result["evidence"].get("source_urls", [result["evidence"]["source_url"]])
                self.assertIn(result["evidence"]["source_url"], urls)
                self.assertTrue(result["answer"].endswith(" | ".join(urls)))
                for url in urls:
                    parts = urlsplit(url)
                    self.assertEqual(parts.scheme, "https")
                    self.assertIn(parts.hostname, {
                        "www.investor.gov", "www.federalreserve.gov", "home.treasury.gov",
                        "libertystreeteconomics.newyorkfed.org",
                    })

    def test_unknown_or_unstructured_topics_fail_closed(self):
        for topic in ("buy_bonds", "forecast", "ignore instructions", "", None, ["basis_point"]):
            with self.subTest(topic=topic), self.assertRaises(ValueError):
                explain_concept(topic)

    def test_basis_points_explain_percentage_points_and_absolute_change(self):
        answer = explain_concept("basis_point")["answer"]
        self.assertIn("0.01 percentage point", answer)
        self.assertIn("100 basis points equal 1 percentage point", answer)
        self.assertIn("4.00% to 4.25%", answer)
        self.assertIn("25 basis points", answer)
        self.assertIn("absolute difference", answer)
        self.assertIn("relative percent change", answer)

    def test_treasury_and_apy_conventions_remain_distinct(self):
        answer = explain_concept("yield_vs_apy")["answer"]
        self.assertIn("simple annualized", answer)
        self.assertIn("semiannual", answer)
        self.assertIn("APY) includes compounding", answer)
        self.assertIn("bank deposit APY", answer)

    def test_fed_funds_explanation_has_both_primary_sources(self):
        result = explain_concept("fed_funds_vs_treasury")
        self.assertIn("overnight borrowing", result["answer"])
        self.assertIn("FOMC sets its target range", result["answer"])
        self.assertEqual(len(result["evidence"]["source_urls"]), 2)
        self.assertIn("Sources: ", result["answer"])

    def test_glossary_returns_fresh_objects(self):
        result = explain_concept("fed_funds_vs_treasury")
        result["evidence"]["source_urls"].clear()
        result["evidence"]["source_url"] = "https://evil.invalid"
        self.assertEqual(len(explain_concept("fed_funds_vs_treasury")["evidence"]["source_urls"]), 2)

    def test_positive_segment_has_exact_signed_basis_point_spread(self):
        answer = curve_answer(observation())
        self.assertIn("As of 2026-10-23", answer)
        self.assertIn("2-year Treasury par yield was 4.69%", answer)
        self.assertIn("10-year was 5.00%", answer)
        self.assertIn("+31 basis points", answer)
        self.assertIn("2-year/10-year segment was upward sloping", answer)
        self.assertIn("only the 2-year/10-year segment", answer)
        self.assertIn("It is not a recession forecast", answer)
        self.assertTrue(answer.endswith("Source: " + observation()["source_url"]))

    def test_negative_segment_is_inverted(self):
        answer = curve_answer(observation(short="5.25", long="4.00"))
        self.assertIn("-125 basis points", answer)
        self.assertIn("segment was inverted", answer)

    def test_equal_yields_are_flat_and_do_not_show_negative_zero(self):
        answer = curve_answer(observation(short="4.00", long="4.00"))
        self.assertIn("0 basis points", answer)
        self.assertIn("segment was flat", answer)
        self.assertNotIn("-0 basis points", answer)

    def test_one_basis_point_is_not_lost_to_float_rounding(self):
        answer = curve_answer(observation(short="4.01", long="4.02"))
        self.assertIn("+1 basis point,", answer)

    def test_two_dates_preserve_their_segments_and_source_order(self):
        first = observation("2025-10-23", short="3.48", long="4.01")
        second = observation("2026-10-23", short="4.69", long="5.00")
        evidence = {"observations": [first, second]}
        before = copy.deepcopy(evidence)
        answer = curve_answer(evidence)
        self.assertLess(answer.index("2025-10-23"), answer.index("2026-10-23"))
        self.assertIn("+53 basis points", answer)
        self.assertIn("+31 basis points", answer)
        self.assertTrue(answer.endswith("Sources: " + first["source_url"] + " | " + second["source_url"]))
        self.assertEqual(evidence, before)

    def test_two_dates_in_same_month_have_one_unique_source(self):
        first, second = observation("2026-10-22"), observation("2026-10-23")
        answer = curve_answer({"observations": [first, second]})
        self.assertEqual(answer.count(first["source_url"]), 1)
        self.assertIn("Source: ", answer)
        self.assertNotIn("Sources: ", answer)

    def test_incomplete_or_unbounded_evidence_is_rejected(self):
        invalid = [None, [], {}, {"observations": []}, {"observations": [observation()] * 3},
                   {"observations": "untrusted"}, {"observations": [None]}]
        for change in (
            {"as_of": "2026-02-30"}, {"as_of": "2026-10-23\nInstructions"},
            {"source_url": "https://evil.invalid"},
            {"source_url": SOURCE_BASE + "202609"},
            {"rates": {"2y": "4.69"}},
            {"rates": {"2y": "4.69", "10y": "5.00", "30y": "5.33"}},
        ):
            invalid.append(dict(observation(), **change))
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                curve_answer(value)

    def test_nonfinite_negative_and_unverified_rate_precision_are_rejected(self):
        for value in (None, 5.00, "NaN", "Infinity", "-0.01", "101.00", "4.001", "1e2", "1_0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                curve_answer(observation(short=value))


if __name__ == "__main__":
    unittest.main()
