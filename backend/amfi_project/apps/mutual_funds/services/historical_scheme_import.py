import time
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

REQUEST_TIMEOUT = 30

# Number of schemes fetched from the scheme-list endpoint
# in one request.
PAGE_SIZE = 100

# Small delay between API requests.
REQUEST_DELAY = 0.25


# ============================================================
# FETCH SCHEME LIST
# ============================================================

def fetch_scheme_list(
    offset=0,
    limit=PAGE_SIZE,
):
    """
    Fetch one page of schemes from MFAPI.

    Example:

        /mf?limit=100&offset=0
        /mf?limit=100&offset=100
        /mf?limit=100&offset=200

    Returns a list containing:

        schemeCode
        schemeName

    """

    response = requests.get(
        MFAPI_SCHEMES_URL,
        params={
            "limit": limit,
            "offset": offset,
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):
        raise ValueError(
            "MFAPI returned an unexpected "
            "scheme-list response."
        )

    return data


# ============================================================
# FETCH COMPLETE SCHEME DATA
# ============================================================

def fetch_scheme_details(
    scheme_code,
):
    """
    Fetch complete information for one scheme.

    MFAPI response contains:

        meta
        data
        status

    meta contains information such as:

        fund_house
        scheme_type
        scheme_category
        scheme_code
        scheme_name
        isin_growth
        isin_div_reinvestment

    data contains the complete available
    historical NAV records.
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
            "MFAPI returned an unexpected "
            "scheme-detail response."
        )

    if data.get("status") != "SUCCESS":
        raise ValueError(
            f"MFAPI returned unsuccessful "
            f"status for scheme {scheme_code}."
        )

    return data


# ============================================================
# DATE CONVERTER
# ============================================================

def format_nav_date(value):
    """
    Convert MFAPI date:

        25-06-2013

    into the exact date format used by
    our nav_history JSON:

        25-06-2013
    """

    if not value:
        return None

    value = str(value).strip()

    try:

        parsed_date = datetime.strptime(
            value,
            "%d-%m-%Y",
        )

        return parsed_date.strftime(
            "%d-%m-%Y"
        )

    except ValueError:

        return None


# ============================================================
# NORMALIZE NAV HISTORY
# ============================================================

def normalize_nav_history(
    nav_records,
):
    """
    Convert MFAPI NAV records into our
    nav_history structure.

    Final structure:

        [
            {
                "nav": "24.2752",
                "date": "11-08-2026"
            }
        ]

    Duplicate dates are removed.
    """

    history = []

    seen_dates = set()

    if not isinstance(
        nav_records,
        list,
    ):
        return history

    for record in nav_records:

        if not isinstance(
            record,
            dict,
        ):
            continue

        nav = record.get(
            "nav"
        )

        raw_date = record.get(
            "date"
        )

        if nav is None:
            continue

        if not raw_date:
            continue

        formatted_date = (
            format_nav_date(
                raw_date
            )
        )

        if formatted_date is None:
            continue

        if formatted_date in seen_dates:
            continue

        seen_dates.add(
            formatted_date
        )

        history.append(
            {
                "nav": str(nav),
                "date": formatted_date,
            }
        )

    return history


# ============================================================
# CREATE / GET FUND HOUSE
# ============================================================

def get_or_create_fund_house(
    fund_house_name,
):
    """
    Get an existing FundHouse or create
    a new one.

    Existing FundHouse records are preserved.
    """

    if not fund_house_name:
        return None, False

    fund_house_name = (
        str(fund_house_name)
        .strip()
    )

    if not fund_house_name:
        return None, False

    fund_house, created = (
        FundHouse.objects.get_or_create(
            name=fund_house_name,
            defaults={
                "number_of_schemes": 0,
                "is_active": True,
            },
        )
    )

    return (
        fund_house,
        created,
    )


# ============================================================
# IMPORT ONE SCHEME
# ============================================================

def import_scheme(
    scheme_code,
):
    """
    Import one complete scheme.

    This function:

        1. Gets MFAPI metadata.
        2. Gets historical NAV.
        3. Creates FundHouse if required.
        4. Creates MutualFundScheme if required.
        5. Updates missing metadata on existing schemes.
        6. Merges NAV history without duplicates.

    Existing data is never deleted.
    """

    # ========================================================
    # FETCH MFAPI DATA
    # ========================================================

    response_data = (
        fetch_scheme_details(
            scheme_code
        )
    )

    meta = (
        response_data.get(
            "meta"
        )
        or {}
    )

    nav_records = (
        response_data.get(
            "data"
        )
        or []
    )

    # ========================================================
    # METADATA
    # ========================================================

    scheme_code = str(
        meta.get(
            "scheme_code"
        )
        or scheme_code
    ).strip()

    scheme_name = (
        meta.get(
            "scheme_name"
        )
        or ""
    ).strip()

    fund_house_name = (
        meta.get(
            "fund_house"
        )
        or ""
    ).strip()

    scheme_type = (
        meta.get(
            "scheme_type"
        )
        or None
    )

    scheme_category = (
        meta.get(
            "scheme_category"
        )
        or None
    )

    isin_growth = (
        meta.get(
            "isin_growth"
        )
        or None
    )

    isin_div_reinvestment = (
        meta.get(
            "isin_div_reinvestment"
        )
        or None
    )

    # ========================================================
    # BASIC VALIDATION
    # ========================================================

    if not scheme_code:
        raise ValueError(
            "MFAPI returned an empty scheme code."
        )

    if not scheme_name:
        raise ValueError(
            f"MFAPI returned no scheme name "
            f"for {scheme_code}."
        )

    if not fund_house_name:
        raise ValueError(
            f"MFAPI returned no fund house "
            f"for {scheme_code}."
        )

    # ========================================================
    # NAV HISTORY
    # ========================================================

    nav_history = (
        normalize_nav_history(
            nav_records
        )
    )

    # ========================================================
    # DATABASE TRANSACTION
    # ========================================================

    with transaction.atomic():

        # ====================================================
        # FUND HOUSE
        # ====================================================

        (
            fund_house,
            fund_house_created,
        ) = get_or_create_fund_house(
            fund_house_name
        )

        if fund_house is None:
            raise ValueError(
                f"Could not resolve fund house "
                f"for scheme {scheme_code}."
            )

        # ====================================================
        # SCHEME
        # ====================================================

        scheme = (
            MutualFundScheme.objects
            .select_for_update()
            .filter(
                scheme_code=scheme_code
            )
            .first()
        )

        # ====================================================
        # CREATE NEW SCHEME
        # ====================================================

        if scheme is None:

            scheme = (
                MutualFundScheme.objects.create(
                    fund_house=fund_house,

                    scheme_code=scheme_code,

                    scheme_name=scheme_name,

                    scheme_type=scheme_type,

                    scheme_category=(
                        scheme_category
                    ),

                    isin_growth=isin_growth,

                    isin_div_payout=None,

                    isin_div_reinvestment=(
                        isin_div_reinvestment
                    ),

                    is_active=True,

                    nav_history=nav_history,
                )
            )

            return {
                "status": "created",
                "scheme": scheme,
                "fund_house_created": (
                    fund_house_created
                ),
                "nav_count": len(
                    nav_history
                ),
                "new_nav_count": len(
                    nav_history
                ),
            }

        # ====================================================
        # EXISTING SCHEME
        # ====================================================

        changed_fields = []

        # ----------------------------------------------------
        # FUND HOUSE
        # ----------------------------------------------------

        if (
            scheme.fund_house_id
            != fund_house.id
        ):

            scheme.fund_house = (
                fund_house
            )

            changed_fields.append(
                "fund_house"
            )

        # ----------------------------------------------------
        # SCHEME NAME
        # ----------------------------------------------------

        if (
            scheme.scheme_name
            != scheme_name
        ):

            scheme.scheme_name = (
                scheme_name
            )

            changed_fields.append(
                "scheme_name"
            )

        # ----------------------------------------------------
        # SCHEME TYPE
        # ----------------------------------------------------

        if (
            scheme.scheme_type
            != scheme_type
        ):

            scheme.scheme_type = (
                scheme_type
            )

            changed_fields.append(
                "scheme_type"
            )

        # ----------------------------------------------------
        # SCHEME CATEGORY
        # ----------------------------------------------------

        if (
            scheme.scheme_category
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
            scheme.isin_growth
            != isin_growth
        ):

            scheme.isin_growth = (
                isin_growth
            )

            changed_fields.append(
                "isin_growth"
            )

        # ----------------------------------------------------
        # ISIN DIV REINVESTMENT
        # ----------------------------------------------------

        if (
            scheme.isin_div_reinvestment
            != isin_div_reinvestment
        ):

            scheme.isin_div_reinvestment = (
                isin_div_reinvestment
            )

            changed_fields.append(
                "isin_div_reinvestment"
            )

        # ----------------------------------------------------
        # NAV HISTORY
        # ----------------------------------------------------

        existing_history = (
            scheme.nav_history
            or []
        )

        # Build a date lookup so we don't
        # duplicate existing NAV dates.

        existing_dates = set()

        for entry in existing_history:

            if not isinstance(
                entry,
                dict,
            ):
                continue

            entry_date = entry.get(
                "date"
            )

            if entry_date:
                existing_dates.add(
                    entry_date
                )

        new_nav_count = 0

        for entry in nav_history:

            entry_date = entry.get(
                "date"
            )

            if not entry_date:
                continue

            if (
                entry_date
                in existing_dates
            ):
                continue

            existing_history.append(
                entry
            )

            existing_dates.add(
                entry_date
            )

            new_nav_count += 1

        # ----------------------------------------------------
        # SAVE NAV HISTORY
        # ----------------------------------------------------

        if new_nav_count > 0:

            scheme.nav_history = (
                existing_history
            )

            changed_fields.append(
                "nav_history"
            )

        # ----------------------------------------------------
        # EXISTING SCHEME SHOULD BE ACTIVE
        #
        # MFAPI's current scheme list represents
        # schemes currently known by MFAPI.
        # ----------------------------------------------------

        if not scheme.is_active:

            scheme.is_active = True

            changed_fields.append(
                "is_active"
            )

        # ----------------------------------------------------
        # SAVE CHANGES
        # ----------------------------------------------------

        if changed_fields:

            # Remove duplicate field names
            # while preserving order.

            changed_fields = list(
                dict.fromkeys(
                    changed_fields
                )
            )

            scheme.save(
                update_fields=(
                    changed_fields
                )
            )

        return {
            "status": "existing",
            "scheme": scheme,
            "fund_house_created": (
                fund_house_created
            ),
            "nav_count": len(
                nav_history
            ),
            "new_nav_count": (
                new_nav_count
            ),
        }


# ============================================================
# UPDATE FUND HOUSE COUNTS
# ============================================================

def update_fund_house_counts():
    """
    Recalculate number_of_schemes for
    every FundHouse.
    """

    fund_houses = (
        FundHouse.objects.all()
    )

    for fund_house in fund_houses:

        active_scheme_count = (
            fund_house.schemes
            .filter(
                is_active=True
            )
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
# DISCOVER SCHEMES
# ============================================================

def discover_schemes(
    start_offset=0,
    max_pages=None,
):
    """
    Discover all schemes available from
    MFAPI's paginated scheme list.

    Parameters:

        start_offset:
            Allows the process to resume.

        max_pages:
            Useful for testing.

            Example:

                max_pages=1

            processes only the first 100 schemes.
    """

    offset = start_offset

    page_number = 0

    total_received = 0
    total_created = 0
    total_existing = 0
    total_failed = 0

    total_new_nav = 0
    total_nav_records = 0

    total_new_fund_houses = 0

    while True:

        page_number += 1

        if (
            max_pages is not None
            and page_number > max_pages
        ):
            break

        print()
        print(
            "=" * 70
        )

        print(
            f"MFAPI PAGE : {page_number}"
        )

        print(
            f"OFFSET     : {offset}"
        )

        print(
            f"LIMIT      : {PAGE_SIZE}"
        )

        print(
            "=" * 70
        )

        # ====================================================
        # FETCH SCHEME LIST
        # ====================================================

        try:

            scheme_records = (
                fetch_scheme_list(
                    offset=offset,
                    limit=PAGE_SIZE,
                )
            )

        except Exception as error:

            print()
            print(
                "ERROR fetching scheme list."
            )

            print(
                f"Offset : {offset}"
            )

            print(
                f"Error  : {error}"
            )

            raise

        received = len(
            scheme_records
        )

        total_received += received

        # ====================================================
        # END
        # ====================================================

        if received == 0:

            print()
            print(
                "MFAPI returned no more schemes."
            )

            break

        # ====================================================
        # PROCESS EACH SCHEME
        # ====================================================

        for index, record in enumerate(
            scheme_records,
            start=1,
        ):

            scheme_code = (
                record.get(
                    "schemeCode"
                )
            )

            scheme_name = (
                record.get(
                    "schemeName"
                )
                or ""
            )

            if not scheme_code:

                total_failed += 1

                print(
                    f"[{index}/{received}] "
                    f"Invalid scheme record"
                )

                continue

            print()
            print(
                f"[{index}/{received}] "
                f"Processing scheme: "
                f"{scheme_code}"
            )

            print(
                f"Scheme Name: "
                f"{scheme_name}"
            )

            try:

                result = import_scheme(
                    scheme_code
                )

                if (
                    result["status"]
                    == "created"
                ):

                    total_created += 1

                    print(
                        "Result      : CREATED"
                    )

                else:

                    total_existing += 1

                    print(
                        "Result      : EXISTING"
                    )

                total_nav_records += (
                    result[
                        "nav_count"
                    ]
                )

                total_new_nav += (
                    result[
                        "new_nav_count"
                    ]
                )

                if result[
                    "fund_house_created"
                ]:

                    total_new_fund_houses += 1

                print(
                    f"NAV records : "
                    f"{result['nav_count']}"
                )

                print(
                    f"New NAV     : "
                    f"{result['new_nav_count']}"
                )

            except Exception as error:

                total_failed += 1

                print(
                    f"ERROR       : {error}"
                )

            # ------------------------------------------------
            # API DELAY
            # ------------------------------------------------

            time.sleep(
                REQUEST_DELAY
            )

        # ====================================================
        # NEXT PAGE
        # ====================================================

        offset += received

        # ----------------------------------------------------
        # If MFAPI returned less than PAGE_SIZE,
        # we have reached the end.
        # ----------------------------------------------------

        if received < PAGE_SIZE:

            print()
            print(
                "Last MFAPI page reached."
            )

            break

    # ========================================================
    # UPDATE COUNTS
    # ========================================================

    update_fund_house_counts()

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print(
        "=" * 70
    )

    print(
        "HISTORICAL SCHEME IMPORT COMPLETED"
    )

    print(
        "=" * 70
    )

    print(
        f"MFAPI schemes received : "
        f"{total_received}"
    )

    print(
        f"New schemes created    : "
        f"{total_created}"
    )

    print(
        f"Existing schemes       : "
        f"{total_existing}"
    )

    print(
        f"Failed schemes         : "
        f"{total_failed}"
    )

    print(
        f"New fund houses        : "
        f"{total_new_fund_houses}"
    )

    print(
        f"NAV records processed  : "
        f"{total_nav_records}"
    )

    print(
        f"New NAV records        : "
        f"{total_new_nav}"
    )

    print(
        "=" * 70
    )

    return {
        "total_received": total_received,
        "total_created": total_created,
        "total_existing": total_existing,
        "total_failed": total_failed,
        "total_new_fund_houses": (
            total_new_fund_houses
        ),
        "total_nav_records": (
            total_nav_records
        ),
        "total_new_nav": total_new_nav,
        "last_offset": offset,
    }