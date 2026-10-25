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
    """A valid Treasury observation could not safely be retrieved."""


class RatesNotPublished(RatesUnavailable):
    """The feed has no published observation for the requested date or tenor."""


FEED_BASE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value_month="
)
SOURCE_BASE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView"
    "?type=daily_treasury_yield_curve&field_tdr_date_value_month="
)
EARLIEST_DATE = date(1990, 1, 2)
DESCRIPTION = "U.S. Treasury daily par yields"
MAX_MONTHLY_DOWNLOADS = 3
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
        raise RatesNotPublished("The requested Treasury yield is not published.")
    try:
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", field.text or ""):
            raise InvalidOperation
        value = Decimal(field.text or "")
        if not value.is_finite() or not Decimal("0") <= value <= Decimal("100"):
            raise InvalidOperation
        return format(value.quantize(Decimal("0.01")), ".2f")
    except (InvalidOperation, ValueError) as exc:
        raise RatesUnavailable("Treasury returned an invalid yield.") from exc


def _requested_dates(dates: list[str] | None, today: date) -> list[str]:
    dates = ["latest"] if dates is None else dates
    if (
        not isinstance(dates, list)
        or not 1 <= len(dates) <= 2
        or any(not isinstance(value, str) for value in dates)
        or len(set(dates)) != len(dates)
    ):
        raise RatesUnavailable("Request one or two distinct Treasury dates.")
    for value in dates:
        if value == "latest":
            continue
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise RatesUnavailable("Treasury dates must use YYYY-MM-DD.")
        try:
            requested = date.fromisoformat(value)
        except ValueError as exc:
            raise RatesUnavailable("Invalid Treasury date.") from exc
        if not EARLIEST_DATE <= requested <= today:
            raise RatesUnavailable("Treasury dates must be between 1990-01-02 and today.")
    return dates


def _freshness_days() -> int:
    try:
        max_age = int(os.environ.get("MAX_DATA_AGE_DAYS", "7"))
        if not 0 <= max_age <= 30:
            raise ValueError
        return max_age
    except ValueError as exc:
        raise RatesUnavailable("Invalid data freshness configuration.") from exc


def fetch_yields(
    maturities: list[str], today: date | None = None, dates: list[str] | None = None
) -> dict:
    """Retrieve up to two maturities on up to two explicitly selected dates.

    ``latest`` uses the newest current-month observation (previous month only
    when current month is empty) and the configured freshness limit. Historical
    dates require an exact published observation and are never shifted to a
    nearby day. Each source month is downloaded at most once per request.
    """
    if (
        not isinstance(maturities, list)
        or not 1 <= len(maturities) <= 2
        or any(not isinstance(m, str) or m not in MATURITY_FIELDS for m in maturities)
        or len(set(maturities)) != len(maturities)
    ):
        raise RatesUnavailable("Request one or two distinct supported Treasury maturities.")
    today = today or datetime.now(ZoneInfo("America/New_York")).date()
    requested_dates = _requested_dates(dates, today)
    max_age = _freshness_days() if "latest" in requested_dates else None
    month_cache: dict[str, list[tuple[date, ElementTree.Element]]] = {}

    def load_month(period: date) -> tuple[str, list[tuple[date, ElementTree.Element]]]:
        month_key = period.strftime("%Y%m")
        if month_key not in month_cache:
            if len(month_cache) >= MAX_MONTHLY_DOWNLOADS:
                raise RatesUnavailable("Treasury lookup exceeded its request limit.")
            observations = _observations(_download(f"{FEED_BASE}{month_key}"))
            seen = set()
            for as_of, _ in observations:
                if as_of.strftime("%Y%m") != month_key or as_of in seen:
                    raise RatesUnavailable("Treasury returned inconsistent observation dates.")
                seen.add(as_of)
            month_cache[month_key] = observations
        return month_key, month_cache[month_key]

    results = []
    for requested_date in requested_dates:
        if requested_date == "latest":
            month = today.replace(day=1)
            month_key, observations = load_month(month)
            if not observations:
                month_key, observations = load_month(month - timedelta(days=1))
            if not observations:
                raise RatesUnavailable("Treasury has no recent observations.")
            as_of, properties = max(observations, key=lambda row: row[0])
            age = (today - as_of).days
            if age < 0 or age > max_age:
                raise RatesUnavailable("Treasury observation is stale or future-dated.")
        else:
            requested = date.fromisoformat(requested_date)
            month_key, observations = load_month(requested)
            matching = [(as_of, row) for as_of, row in observations if as_of == requested]
            if not matching:
                raise RatesNotPublished(
                    f"Treasury did not publish a daily par yield observation for {requested_date}."
                )
            as_of, properties = matching[0]

        try:
            values = {maturity: _yield_value(properties, maturity) for maturity in maturities}
        except RatesNotPublished as exc:
            labels = [f"{m[:-1]}-{'month' if m.endswith('m') else 'year'}" for m in maturities]
            raise RatesNotPublished(
                f"Treasury did not publish all requested yields ({', '.join(labels)}) "
                f"for {as_of.isoformat()}."
            ) from exc
        results.append({
            "as_of": as_of.isoformat(),
            "requested_date": requested_date,
            "rates": values,
            "source_url": f"{SOURCE_BASE}{month_key}",
            "data_url": f"{FEED_BASE}{month_key}",
            "description": DESCRIPTION,
        })
    return results[0] if len(results) == 1 else {"observations": results, "description": DESCRIPTION}
