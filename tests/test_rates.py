"""Public-data boundary tests; no network or AWS access is required."""

import io
import os
import unittest
from datetime import date
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from xml.sax.saxutils import escape

from askbrieves import rates


def xml_feed(*rows):
    entries = []
    for observation_date, values in rows:
        fields = f"<d:NEW_DATE>{observation_date}T00:00:00</d:NEW_DATE>"
        for field, value in values.items():
            if value is None:
                fields += f'<d:{field} m:null="true" />'
            else:
                fields += f"<d:{field}>{escape(str(value))}</d:{field}>"
        entries.append(f"<entry><content><m:properties>{fields}</m:properties></content></entry>")
    return (
        f'<feed xmlns="{rates.NS["a"]}" xmlns:m="{rates.NS["m"]}" '
        f'xmlns:d="{rates.NS["d"]}">{"".join(entries)}</feed>'
    ).encode()


class TreasuryRatesTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"MAX_DATA_AGE_DAYS": "7"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_latest_observation_is_selected_independently_of_order(self):
        feed = xml_feed(
            ("2026-10-23", {"BC_10YEAR": "5.00"}),
            ("2026-10-22", {"BC_10YEAR": "4.96"}),
        )
        with patch.object(rates, "_download", return_value=feed):
            result = rates.fetch_yields(["10y"], today=date(2026, 10, 25))
        self.assertEqual(result["as_of"], "2026-10-23")
        self.assertEqual(result["rates"], {"10y": "5.00"})
        self.assertEqual(result["source_url"], f"{rates.FEED_BASE}202610")
        self.assertEqual(result["description"], "U.S. Treasury daily par yields")

    def test_all_supported_maturities_map_to_verified_treasury_fields(self):
        fields = {field: "4.1" for field in rates.MATURITY_FIELDS.values()}
        with patch.object(rates, "_download", return_value=xml_feed(("2026-10-23", fields))):
            result = rates.fetch_yields(list(rates.MATURITY_FIELDS), date(2026, 10, 23))
        self.assertEqual(result["rates"], {m: "4.10" for m in rates.MATURITY_FIELDS})

    def test_year_rollover_uses_previous_december_when_january_is_empty(self):
        with patch.object(
            rates, "_download", side_effect=[xml_feed(), xml_feed(("2025-12-31", {"BC_10YEAR": "4.2"}))]
        ) as download:
            result = rates.fetch_yields(["10y"], date(2026, 1, 1))
        self.assertEqual(result["as_of"], "2025-12-31")
        self.assertEqual(result["source_url"], f"{rates.FEED_BASE}202512")
        self.assertEqual([c.args[0] for c in download.call_args_list], [f"{rates.FEED_BASE}202601", f"{rates.FEED_BASE}202512"])

    def test_missing_latest_tenor_never_backfills_older_row(self):
        feed = xml_feed(
            ("2026-10-22", {"BC_10YEAR": "4.96"}),
            ("2026-10-23", {"BC_2YEAR": "4.69"}),
        )
        with patch.object(rates, "_download", return_value=feed) as download:
            with self.assertRaises(rates.RatesUnavailable):
                rates.fetch_yields(["10y"], date(2026, 10, 25))
        self.assertEqual(download.call_count, 1)

    def test_comparison_requires_both_yields_on_the_same_row(self):
        feed = xml_feed(("2026-10-23", {"BC_2YEAR": "4.69", "BC_10YEAR": "5"}))
        with patch.object(rates, "_download", return_value=feed):
            result = rates.fetch_yields(["2y", "10y"], date(2026, 10, 25))
        self.assertEqual(result["rates"], {"2y": "4.69", "10y": "5.00"})

    def test_null_nonfinite_negative_and_invalid_values_fail_closed(self):
        for value in (None, "", "not-a-yield", "NaN", "Infinity", "-0.1", "101", "1_0", "-0.0"):
            with self.subTest(value=value), patch.object(
                rates, "_download", return_value=xml_feed(("2026-10-23", {"BC_10YEAR": value}))
            ):
                with self.assertRaises(rates.RatesUnavailable):
                    rates.fetch_yields(["10y"], date(2026, 10, 25))

    def test_zero_is_a_valid_nominal_yield(self):
        with patch.object(rates, "_download", return_value=xml_feed(("2026-10-23", {"BC_10YEAR": "0"}))):
            result = rates.fetch_yields(["10y"], date(2026, 10, 25))
        self.assertEqual(result["rates"], {"10y": "0.00"})

    def test_stale_future_and_invalid_dates_are_unavailable(self):
        for observed in ("2026-10-17", "2026-10-26", "invalid-date"):
            with self.subTest(observed=observed), patch.object(
                rates, "_download", return_value=xml_feed((observed, {"BC_10YEAR": "5"}))
            ):
                with self.assertRaises(rates.RatesUnavailable):
                    rates.fetch_yields(["10y"], date(2026, 10, 25))

    def test_seven_day_boundary_is_inclusive(self):
        with patch.object(rates, "_download", return_value=xml_feed(("2026-10-18", {"BC_10YEAR": "5"}))):
            self.assertEqual(rates.fetch_yields(["10y"], date(2026, 10, 25))["as_of"], "2026-10-18")

    def test_freshness_configuration_is_enforced(self):
        with patch.dict(os.environ, {"MAX_DATA_AGE_DAYS": "0"}), patch.object(
            rates, "_download", return_value=xml_feed(("2026-10-23", {"BC_10YEAR": "5"}))
        ):
            with self.assertRaises(rates.RatesUnavailable):
                rates.fetch_yields(["10y"], date(2026, 10, 25))
        for value in ("bad", "-1", "31"):
            with self.subTest(value=value), patch.dict(os.environ, {"MAX_DATA_AGE_DAYS": value}), patch.object(rates, "_download") as download:
                with self.assertRaises(rates.RatesUnavailable):
                    rates.fetch_yields(["10y"], date(2026, 10, 25))
                download.assert_not_called()

    def test_unsupported_maturities_never_trigger_network(self):
        with patch.object(rates, "_download") as download:
            for maturities in ([], ["15y"], ["https://evil.invalid"], "10y", [None], ["10y"] * 14):
                with self.subTest(maturities=maturities), self.assertRaises(rates.RatesUnavailable):
                    rates.fetch_yields(maturities, date(2026, 10, 25))
            download.assert_not_called()

    def test_empty_current_and_previous_month_are_unavailable(self):
        with patch.object(rates, "_download", return_value=xml_feed()) as download:
            with self.assertRaises(rates.RatesUnavailable):
                rates.fetch_yields(["10y"], date(2026, 10, 25))
        self.assertEqual(download.call_count, 2)

    def test_unexpected_malformed_and_unsafe_xml_are_unavailable(self):
        payloads = (b"<html>bad gateway</html>", b"<feed", b'<!DOCTYPE feed [<!ENTITY x "bomb">]><feed/>', b"<!ENTITY x 'value'>")
        for body in payloads:
            with self.subTest(body=body), patch.object(rates, "_download", return_value=body):
                with self.assertRaises(rates.RatesUnavailable):
                    rates.fetch_yields(["10y"], date(2026, 10, 25))

    def test_missing_properties_or_date_are_unavailable(self):
        for entry in ("<entry/>", "<entry><content><m:properties/></content></entry>"):
            body = f'<feed xmlns="{rates.NS["a"]}" xmlns:m="{rates.NS["m"]}">{entry}</feed>'.encode()
            with self.subTest(entry=entry), patch.object(rates, "_download", return_value=body):
                with self.assertRaises(rates.RatesUnavailable):
                    rates.fetch_yields(["10y"], date(2026, 10, 25))

    def test_utf16_cannot_bypass_xml_declaration_rejection(self):
        payload = '<!DOCTYPE feed [<!ENTITY x "bomb">]><feed/>'.encode("utf-16")
        with patch.object(rates, "_download", return_value=payload):
            with self.assertRaises(rates.RatesUnavailable):
                rates.fetch_yields(["10y"], date(2026, 10, 25))

    def test_download_is_bounded_and_uses_fixed_destination(self):
        with patch.object(rates, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(xml_feed(("2026-10-23", {"BC_10YEAR": "5"})))
            rates.fetch_yields(["10y"], date(2026, 10, 25))
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, f"{rates.FEED_BASE}202610")
        self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 5)
        self.assertIsInstance(opener.call_args.args[0], rates._NoRedirect)

    def test_oversized_response_is_unavailable(self):
        with patch.object(rates, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b"x" * (rates.MAX_RESPONSE_BYTES + 1))
            with self.assertRaises(rates.RatesUnavailable):
                rates.fetch_yields(["10y"], date(2026, 10, 25))

    def test_network_timeout_and_redirect_fail_without_fallback(self):
        errors = (
            TimeoutError("timeout"),
            URLError("unavailable"),
            HTTPError(f"{rates.FEED_BASE}202610", 302, "redirect", {}, None),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__), patch.object(rates, "build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(rates.RatesUnavailable):
                    rates.fetch_yields(["10y"], date(2026, 10, 25))
                self.assertEqual(opener.return_value.open.call_count, 1)

    def test_redirect_handler_does_not_follow_external_or_internal_urls(self):
        for url in ("https://evil.invalid", "https://home.treasury.gov/another"):
            self.assertIsNone(rates._NoRedirect().redirect_request(None, None, 302, "Found", {}, url))


if __name__ == "__main__":
    unittest.main()
