import time
from decimal import Decimal, InvalidOperation
from datetime import datetime

import requests
from django.db import transaction

from apps.mutual_funds.models import (
    FundHouse,
    MutualFundScheme,
)


# ============================================================
# MFAPI CONFIGURATION
# ============================================================

MFAPI_BASE_URL = "https://api.mfapi.in"

MFAPI_SCHEMES_URL = (
    f"{MFAPI_BASE_URL}/mf"
)


# ============================================================
# REQUEST CONFIGURATION
# ============================================================

REQUEST_TIMEOUT = 30

# Small delay between requests so that the external API
# is not unnecessarily overloaded.
REQUEST_DELAY = 0.05


# ============================================================
# DECIMAL CLEANER
# ============================================================

def clean_decimal(value):
    """
    Convert an API NAV value into Decimal.

    Invalid or empty values return None.
    """

    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    value = value.replace(",", "")

    try:
        return Decimal(value)

    except (
        InvalidOperation,
        ValueError,
    ):
        return None


# ============================================================
# DATE FORMATTER
# ============================================================

def format_nav_date(date_string):
    """
    Convert MFAPI date format:

        25-06-2013

    into the format used by nav_history:

        25-06-2013

    This function also accepts other common formats.
    """

    if not date_string:
        return None

    date_string = str(date_string).strip()

    formats = (
        "%d-%m-%Y",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%Y-%m-%d",
    )

    for date_format in formats:

        try:

            parsed_date = datetime.strptime(
                date_string,
                date_format,
            )

            return parsed_date.strftime(
                "%d-%m-%Y"
            )

        except ValueError:
            continue

    return None


# ============================================================
# GET ALL MFAPI SCHEMES
# ============================================================

def fetch_all_mfapi_schemes():
    """
    Fetch the complete scheme list from MFAPI.

    Returns a list like:

        [
            {
                "schemeCode": 122612,
                "schemeName": "360 ONE Dynamic Bond Fund..."
            },
            ...
        ]
    """

    response = requests.get(
        MFAPI_SCHEMES_URL,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):

        raise ValueError(
            "MFAPI returned an unexpected scheme-list response."
        )

    return data


# ============================================================
# GET ONE SCHEME'S COMPLETE HISTORY
# ============================================================

def fetch_scheme_history(scheme_code):
    """
    Fetch complete historical data for one scheme.

    Example:

        https://api.mfapi.in/mf/122612
    """

    url = (
        f"{MFAPI_BASE_URL}/mf/"
        f"{scheme_code}"
    )

    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):

        raise ValueError(
            f"Invalid MFAPI response for scheme {scheme_code}."
        )

    return data


# ============================================================
# BUILD NAV HISTORY
# ============================================================

def build_nav_history(api_data):
    """
    Convert MFAPI NAV data into the structure used by
    MutualFundScheme.nav_history.

    Example:

        [
            {
                "nav": "24.2752",
                "date": "11-08-2026"
            },
            {
                "nav": "24.2839",
                "date": "10-08-2026"
            }
        ]

    Duplicate dates are removed.
    """

    raw_history = api_data.get("data") or []

    if not isinstance(raw_history, list):
        return []

    history_by_date = {}

    for entry in raw_history:

        if not isinstance(entry, dict):
            continue

        raw_date = entry.get("date")
        raw_nav = entry.get("nav")

        formatted_date = format_nav_date(
            raw_date
        )

        nav = clean_decimal(
            raw_nav
        )

        if not formatted_date:
            continue

        if nav is None:
            continue

        history_by_date[formatted_date] = {
            "nav": str(nav),
            "date": formatted_date,
        }

    # --------------------------------------------------------
    # Sort oldest → newest
    # --------------------------------------------------------

    history = list(
        history_by_date.values()
    )

    history.sort(
        key=lambda item: datetime.strptime(
            item["date"],
            "%d-%m-%Y",
        )
    )

    return history


# ============================================================
# CREATE / UPDATE FUND HOUSE
# ============================================================

def get_or_create_fund_house(
    fund_house_name,
):
    """
    Create the fund house if it does not already exist.
    """

    if not fund_house_name:

        fund_house_name = (
            "Unknown Fund House"
        )

    fund_house_name = str(
        fund_house_name
    ).strip()

    fund_house, created = (
        FundHouse.objects.get_or_create(
            name=fund_house_name,
            defaults={
                "number_of_schemes": 0,
                "is_active": True,
            },
        )
    )

    if not fund_house.is_active:

        fund_house.is_active = True

        fund_house.save(
            update_fields=[
                "is_active",
            ]
        )

    return fund_house, created


# ============================================================
# CREATE / UPDATE SCHEME
# ============================================================

def save_historical_scheme(
    scheme_code,
    api_data,
):
    """
    Create or update one MutualFundScheme using MFAPI data.

    Existing scheme information is preserved whenever MFAPI
    does not provide a value.
    """

    meta = api_data.get("meta") or {}

    if not isinstance(meta, dict):

        raise ValueError(
            f"Invalid metadata for scheme {scheme_code}."
        )

    # ========================================================
    # SCHEME INFORMATION
    # ========================================================

    scheme_code = str(
        meta.get("scheme_code")
        or scheme_code
    ).strip()

    scheme_name = (
        meta.get("scheme_name")
        or ""
    ).strip()

    fund_house_name = (
        meta.get("fund_house")
        or ""
    ).strip()

    scheme_type = (
        meta.get("scheme_type")
        or None
    )

    scheme_category = (
        meta.get("scheme_category")
        or None
    )

    isin_growth = (
        meta.get("isin_growth")
        or None
    )

    isin_div_reinvestment = (
        meta.get(
            "isin_div_reinvestment"
        )
        or None
    )

    # MFAPI may not provide every ISIN field.
    # We therefore do NOT overwrite an existing value
    # with None.

    # ========================================================
    # NAV HISTORY
    # ========================================================

    nav_history = build_nav_history(
        api_data
    )

    # ========================================================
    # FUND HOUSE
    # ========================================================

    (
        fund_house,
        fund_house_created,
    ) = get_or_create_fund_house(
        fund_house_name
    )

    # ========================================================
    # SCHEME
    # ========================================================

    (
        scheme,
        scheme_created,
    ) = MutualFundScheme.objects.get_or_create(
        scheme_code=scheme_code,
        defaults={
            "fund_house": fund_house,
            "scheme_name": scheme_name,
            "scheme_type": scheme_type,
            "scheme_category": scheme_category,
            "isin_growth": isin_growth,
            "isin_div_payout": None,
            "isin_div_reinvestment": (
                isin_div_reinvestment
            ),
            "is_active": True,
            "nav_history": nav_history,
        },
    )

    # ========================================================
    # EXISTING SCHEME
    # ========================================================

    if not scheme_created:

        changed_fields = []

        # ----------------------------------------------------
        # FUND HOUSE
        # ----------------------------------------------------

        if (
            scheme.fund_house_id
            != fund_house.id
        ):

            scheme.fund_house = fund_house

            changed_fields.append(
                "fund_house"
            )

        # ----------------------------------------------------
        # SCHEME NAME
        # ----------------------------------------------------

        if (
            scheme_name
            and scheme.scheme_name
            != scheme_name
        ):

            scheme.scheme_name = scheme_name

            changed_fields.append(
                "scheme_name"
            )

        # ----------------------------------------------------
        # SCHEME TYPE
        # ----------------------------------------------------

        if (
            scheme_type
            and scheme.scheme_type
            != scheme_type
        ):

            scheme.scheme_type = scheme_type

            changed_fields.append(
                "scheme_type"
            )

        # ----------------------------------------------------
        # SCHEME CATEGORY
        # ----------------------------------------------------

        if (
            scheme_category
            and scheme.scheme_category
            != scheme_category
        ):

            scheme.scheme_category = (
                scheme_category
            )

            changed_fields.append(
                "scheme_category"
            )

        # ----------------------------------------------------
        # ISIN GROWTH
        # ----------------------------------------------------

        if (
            isin_growth
            and scheme.isin_growth
            != isin_growth
        ):

            scheme.isin_growth = isin_growth

            changed_fields.append(
                "isin_growth"
            )

        # ----------------------------------------------------
        # ISIN DIV REINVESTMENT
        # ----------------------------------------------------

        if (
            isin_div_reinvestment
            and scheme.isin_div_reinvestment
            != isin_div_reinvestment
        ):

            scheme.isin_div_reinvestment = (
                isin_div_reinvestment
            )

            changed_fields.append(
                "isin_div_reinvestment"
            )

        # ----------------------------------------------------
        # REACTIVATE SCHEME
        # ----------------------------------------------------

        if not scheme.is_active:

            scheme.is_active = True

            changed_fields.append(
                "is_active"
            )

        # ----------------------------------------------------
        # NAV HISTORY
        #
        # IMPORTANT:
        #
        # Historical backfill replaces the scheme's current
        # nav_history with the complete history returned by
        # MFAPI.
        #
        # This happens only inside this NEW backfill process.
        # Your daily AMFI sync remains unchanged.
        # ----------------------------------------------------

        if nav_history:

            scheme.nav_history = (
                nav_history
            )

            changed_fields.append(
                "nav_history"
            )

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        if changed_fields:

            scheme.save(
                update_fields=changed_fields
            )

    return {
        "scheme": scheme,
        "scheme_created": scheme_created,
        "fund_house_created": fund_house_created,
        "nav_count": len(nav_history),
    }


# ============================================================
# UPDATE FUND HOUSE COUNTS
# ============================================================

def update_fund_house_counts():
    """
    Recalculate scheme counts for all fund houses.
    """

    fund_houses = FundHouse.objects.all()

    for fund_house in fund_houses:

        active_scheme_count = (
            fund_house.schemes
            .filter(is_active=True)
            .count()
        )

        fund_house.number_of_schemes = (
            active_scheme_count
        )

        fund_house.is_active = (
            active_scheme_count > 0
        )

        fund_house.save(
            update_fields=[
                "number_of_schemes",
                "is_active",
            ]
        )


# ============================================================
# BACKFILL ONE SCHEME
# ============================================================

def backfill_scheme(
    scheme_code,
):
    """
    Backfill one scheme.
    """

    api_data = fetch_scheme_history(
        scheme_code
    )

    with transaction.atomic():

        result = save_historical_scheme(
            scheme_code=scheme_code,
            api_data=api_data,
        )

    return result


# ============================================================
# BACKFILL ALL SCHEMES
# ============================================================

def backfill_all_schemes(
    limit=None,
    delay=REQUEST_DELAY,
    specific_scheme_code=None,
):
    """
    Backfill historical data for all MFAPI schemes.

    Parameters
    ----------
    limit:
        Process only first N schemes.
        Useful for testing.

    delay:
        Delay between API requests.

    specific_scheme_code:
        Process only one scheme.
    """

    # ========================================================
    # ONE SPECIFIC SCHEME
    # ========================================================

    if specific_scheme_code:

        result = backfill_scheme(
            specific_scheme_code
        )

        update_fund_house_counts()

        return {
            "total": 1,
            "processed": 1,
            "created": (
                1
                if result["scheme_created"]
                else 0
            ),
            "failed": 0,
            "nav_records": result[
                "nav_count"
            ],
            "errors": [],
        }

    # ========================================================
    # FETCH COMPLETE SCHEME LIST
    # ========================================================

    schemes = fetch_all_mfapi_schemes()

    if limit is not None:

        schemes = schemes[:limit]

    total = len(schemes)

    processed = 0
    created = 0
    failed = 0
    nav_records = 0

    errors = []

    # ========================================================
    # PROCESS EACH SCHEME
    # ========================================================

    for index, item in enumerate(
        schemes,
        start=1,
    ):

        scheme_code = (
            item.get("schemeCode")
            or item.get("scheme_code")
        )

        if not scheme_code:

            failed += 1

            errors.append(
                "Scheme list item has no scheme code."
            )

            continue

        scheme_code = str(
            scheme_code
        ).strip()

        try:

            result = backfill_scheme(
                scheme_code
            )

            processed += 1

            if result["scheme_created"]:

                created += 1

            nav_records += result[
                "nav_count"
            ]

            print(
                f"[{index}/{total}] "
                f"SUCCESS "
                f"Scheme {scheme_code} "
                f"→ "
                f"{result['nav_count']} NAV records"
            )

        except Exception as error:

            failed += 1

            error_message = (
                f"Scheme {scheme_code}: "
                f"{error}"
            )

            errors.append(
                error_message
            )

            print(
                f"[{index}/{total}] "
                f"FAILED "
                f"{error_message}"
            )

        if delay > 0:

            time.sleep(delay)

    # ========================================================
    # UPDATE FUND HOUSE COUNTS
    # ========================================================

    update_fund_house_counts()

    # ========================================================
    # RESULT
    # ========================================================

    return {
        "total": total,
        "processed": processed,
        "created": created,
        "failed": failed,
        "nav_records": nav_records,
        "errors": errors,
    }