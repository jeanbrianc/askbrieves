"""Bounded, read-only access to the Treasury's official daily par-yield feed."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree
from zoneinfo import ZoneInfo


class RatesUnavailable(Exception):
    """No sufficiently fresh, valid Treasury observation can be returned."""


FEED_BASE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value_month="
)
MAX_RESPONSE_BYTES = 1_048_576
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
}
MATURITY_FIELDS = {
    "1m": "BC_1MONTH",
    "2m": "BC_2MONTH",
    "3m": "BC_3MONTH",
    "4m": "BC_4MONTH",
    "6m": "BC_6MONTH",
    "1y": "BC_1YEAR",
    "2y": "BC_2YEAR",
    "3y": "BC_3YEAR",
    "5y": "BC_5YEAR",
    "7y": "BC_7YEAR",
    "10y": "BC_10YEAR",
    "20y": "BC_20YEAR",
    "30y": "BC_30YEAR",
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Neither a user nor a remote redirect may select another destination.
        return None


def _download(url: str) -> bytes:
    request = Request(
        url,
        headers={"Accept": "application/xml", "User-Agent": "AskBrieves/1.0"},
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=5) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        if isinstance(exc, HTTPError):
            exc.close()
        raise RatesUnavailable("Treasury data could not be retrieved.") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise RatesUnavailable("Treasury response exceeded the size limit.")
    return body


def _observations(body: bytes) -> list[tuple[date, ElementTree.Element]]:
    # ElementTree does not fetch external entities; rejecting declarations also
    # prevents internal entity expansion. The byte cap bounds the remaining XML.
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RatesUnavailable("Treasury returned an unsupported XML encoding.") from exc
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise RatesUnavailable("Treasury returned unsafe XML.")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise RatesUnavailable("Treasury returned invalid XML.") from exc
    if root.tag != f"{{{NS['a']}}}feed":
        raise RatesUnavailable("Treasury returned an unexpected data format.")
    observations = []
    for entry in root.findall("a:entry", NS):
        properties = entry.find("a:content/m:properties", NS)
        if properties is None:
            raise RatesUnavailable("Treasury observation was incomplete.")
        raw_date = properties.findtext("d:NEW_DATE", namespaces=NS)
        try:
            observation_date = datetime.fromisoformat(raw_date or "").date()
        except ValueError as exc:
            raise RatesUnavailable("Treasury observation had an invalid date.") from exc
        observations.append((observation_date, properties))
    return observations


def _yield_value(properties: ElementTree.Element, maturity: str) -> str:
    field = properties.find(f"d:{MATURITY_FIELDS[maturity]}", NS)
    if field is None or field.get(f"{{{NS['m']}}}null") == "true":
        raise RatesUnavailable("The requested Treasury yield is unavailable.")
    try:
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", field.text or ""):
            raise InvalidOperation
        value = Decimal(field.text or "")
        if not value.is_finite() or not Decimal("0") <= value <= Decimal("100"):
            raise InvalidOperation
        return format(value.quantize(Decimal("0.01")), ".2f")
    except (InvalidOperation, ValueError) as exc:
        raise RatesUnavailable("Treasury returned an invalid yield.") from exc


def fetch_yields(maturities: list[str], today: date | None = None) -> dict:
    """Return one latest dated observation, or fail closed.

    Current-month absence alone permits a previous-month lookup. A missing tenor
    on the latest row never causes silent fallback to an older observation.
    MAX_DATA_AGE_DAYS defaults to seven calendar days and accepts 0 through 30.
    """
    if (
        not isinstance(maturities, list)
        or not maturities
        or len(maturities) > len(MATURITY_FIELDS)
        or any(not isinstance(m, str) or m not in MATURITY_FIELDS for m in maturities)
    ):
        raise RatesUnavailable("Unsupported Treasury maturity.")
    try:
        max_age = int(os.environ.get("MAX_DATA_AGE_DAYS", "7"))
        if not 0 <= max_age <= 30:
            raise ValueError
    except ValueError as exc:
        raise RatesUnavailable("Invalid data freshness configuration.") from exc

    today = today or datetime.now(ZoneInfo("America/New_York")).date()
    month = today.replace(day=1)
    previous_month = month - timedelta(days=1)
    for period in (month, previous_month):
        source_url = f"{FEED_BASE}{period:%Y%m}"
        observations = _observations(_download(source_url))
        if not observations:
            continue
        as_of, properties = max(observations, key=lambda row: row[0])
        age = (today - as_of).days
        if age < 0 or age > max_age:
            raise RatesUnavailable("Treasury observation is stale or future-dated.")
        return {
            "as_of": as_of.isoformat(),
            "rates": {maturity: _yield_value(properties, maturity) for maturity in maturities},
            "source_url": source_url,
            "description": "U.S. Treasury daily par yields",
        }
    raise RatesUnavailable("Treasury has no recent observations.")
