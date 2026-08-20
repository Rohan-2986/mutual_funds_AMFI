from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation

from apps.portfolio_analysis.services.amfi_matcher import (
    match_cas_holding,
)


# ============================================================
# PUBLIC API
# ============================================================


def enrich_cas_holding_with_current_nav(
    holding,
):
    """
    Enrich one CAS holding with the latest available NAV
    from the matched AMFI MutualFundScheme.

    IMPORTANT:
        - Original CAS holding is NOT modified.
        - Existing CAS NAV is NOT overwritten.
        - Existing CAS NAV date is NOT overwritten.
        - Existing NAV history is NOT modified.
        - This function is READ-ONLY.

    The latest NAV is read from:

        MutualFundScheme.data

    Expected NAV history format:

        [
            {
                "date": "19-08-2026",
                "nav": "20.14000"
            },
            ...
        ]
    """

    if not isinstance(
        holding,
        dict,
    ):
        raise ValueError(
            "holding must be a dictionary."
        )

    # --------------------------------------------------------
    # Match CAS holding with AMFI scheme
    # --------------------------------------------------------

    match_result = match_cas_holding(
        holding
    )

    # --------------------------------------------------------
    # No AMFI match
    # --------------------------------------------------------

    if not match_result.get(
        "matched"
    ):

        return {
            **deepcopy(holding),

            "nav_enrichment": {
                "available": False,
                "reason": "SCHEME_NOT_MATCHED",
                "latest_nav": None,
                "latest_nav_date": None,
                "latest_value": None,
            },

            "amfi_match": {
                "matched": False,
                "match_type": match_result.get(
                    "match_type"
                ),
            },
        }

    scheme = match_result.get(
        "scheme"
    )

    # --------------------------------------------------------
    # Find latest NAV
    # --------------------------------------------------------

    latest_nav_record = (
        get_latest_nav_record(
            scheme.data
        )
    )

    # --------------------------------------------------------
    # No NAV history
    # --------------------------------------------------------

    if latest_nav_record is None:

        return {
            **deepcopy(holding),

            "nav_enrichment": {
                "available": False,
                "reason": "NAV_HISTORY_NOT_AVAILABLE",
                "latest_nav": None,
                "latest_nav_date": None,
                "latest_value": None,
            },

            "amfi_match": {
                "matched": True,
                "match_type": match_result.get(
                    "match_type"
                ),
                "scheme_id": scheme.id,
                "scheme_code": scheme.scheme_code,
                "scheme_name": scheme.scheme_name,
            },
        }

    latest_nav = latest_nav_record[
        "nav"
    ]

    latest_nav_date = latest_nav_record[
        "date"
    ]

    # --------------------------------------------------------
    # Calculate latest estimated value
    # --------------------------------------------------------

    latest_value = calculate_latest_value(
        holding=holding,
        latest_nav=latest_nav,
    )

    # --------------------------------------------------------
    # Return enriched copy
    # --------------------------------------------------------

    enriched_holding = deepcopy(
        holding
    )

    enriched_holding[
        "nav_enrichment"
    ] = {
        "available": True,

        "latest_nav": (
            latest_nav
        ),

        "latest_nav_date": (
            latest_nav_date
        ),

        "latest_value": (
            latest_value
        ),
    }

    enriched_holding[
        "amfi_match"
    ] = {
        "matched": True,

        "match_type": (
            match_result.get(
                "match_type"
            )
        ),

        "scheme_id": (
            scheme.id
        ),

        "scheme_code": (
            scheme.scheme_code
        ),

        "scheme_name": (
            scheme.scheme_name
        ),

        "fund_house": (
            scheme.fund_house.name
            if scheme.fund_house
            else None
        ),

        "scheme_type": (
            scheme.scheme_type
        ),

        "scheme_category": (
            scheme.scheme_category
        ),

        "is_active": (
            scheme.is_active
        ),
    }

    return enriched_holding


# ============================================================
# ENRICH ALL HOLDINGS
# ============================================================


def enrich_portfolio_holdings_with_current_nav(
    mutual_fund_details,
):
    """
    Enrich every CAS mutual-fund holding with the latest
    available AMFI NAV.

    The original mutual_fund_details list is NOT modified.

    Returns a new list.
    """

    if not isinstance(
        mutual_fund_details,
        list,
    ):
        raise ValueError(
            "mutual_fund_details must be a list."
        )

    enriched_holdings = []

    for index, holding in enumerate(
        mutual_fund_details,
        start=1,
    ):

        if not isinstance(
            holding,
            dict,
        ):

            enriched_holdings.append(
                {
                    "holding_index": index,

                    "nav_enrichment": {
                        "available": False,
                        "reason": (
                            "INVALID_HOLDING"
                        ),
                        "latest_nav": None,
                        "latest_nav_date": None,
                        "latest_value": None,
                    },
                }
            )

            continue

        enriched_holding = (
            enrich_cas_holding_with_current_nav(
                holding
            )
        )

        enriched_holding[
            "holding_index"
        ] = index

        enriched_holdings.append(
            enriched_holding
        )

    return enriched_holdings


# ============================================================
# FIND LATEST NAV RECORD
# ============================================================


def get_latest_nav_record(
    nav_history,
):
    """
    Return the latest valid NAV record from a scheme's
    complete NAV history.

    Expected format:

        [
            {
                "date": "19-08-2026",
                "nav": "20.14000"
            }
        ]

    The function does NOT modify nav_history.

    Invalid records are ignored.
    Duplicate dates are not modified here because this function
    is only responsible for finding the latest available NAV.
    """

    if not isinstance(
        nav_history,
        list,
    ):
        return None

    valid_records = []

    for record in nav_history:

        if not isinstance(
            record,
            dict,
        ):
            continue

        date_value = record.get(
            "date"
        )

        nav_value = record.get(
            "nav"
        )

        parsed_date = parse_nav_date(
            date_value
        )

        parsed_nav = parse_decimal(
            nav_value
        )

        if (
            parsed_date is None
            or parsed_nav is None
        ):
            continue

        valid_records.append(
            {
                "date": str(
                    date_value
                ),

                "nav": format_decimal(
                    parsed_nav
                ),

                "_parsed_date": (
                    parsed_date
                ),
            }
        )

    if not valid_records:
        return None

    latest_record = max(
        valid_records,
        key=lambda item: item[
            "_parsed_date"
        ],
    )

    return {
        "date": latest_record[
            "date"
        ],

        "nav": latest_record[
            "nav"
        ],
    }


# ============================================================
# CALCULATE LATEST VALUE
# ============================================================


def calculate_latest_value(
    holding,
    latest_nav,
):
    """
    Calculate estimated latest value:

        units × latest NAV

    The original holding is NOT modified.
    """

    units = parse_decimal(
        holding.get(
            "units"
        )
    )

    nav = parse_decimal(
        latest_nav
    )

    if (
        units is None
        or nav is None
    ):
        return None

    value = units * nav

    return format_decimal(
        value
    )


# ============================================================
# DATE PARSING
# ============================================================


def parse_nav_date(
    value,
):
    """
    Parse supported NAV date formats.

    Supported formats include:

        DD-MM-YYYY
        DD/MM/YYYY
        YYYY-MM-DD
        YYYY/MM/DD

    Returns:
        datetime.date
        or None
    """

    if value is None:
        return None

    value = str(
        value
    ).strip()

    if not value:
        return None

    formats = (
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
    )

    for date_format in formats:

        try:

            return datetime.strptime(
                value,
                date_format,
            ).date()

        except ValueError:
            continue

    return None


# ============================================================
# DECIMAL PARSING
# ============================================================


def parse_decimal(
    value,
):
    """
    Convert a value into Decimal safely.

    Invalid values return None.
    """

    if value in (
        None,
        "",
    ):
        return None

    try:

        return Decimal(
            str(value).strip()
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):

        return None


# ============================================================
# DECIMAL FORMATTING
# ============================================================


def format_decimal(
    value,
):
    """
    Convert Decimal to a plain string representation.

    This avoids floating-point precision problems.
    """

    decimal_value = parse_decimal(
        value
    )

    if decimal_value is None:
        return None

    return format(
        decimal_value,
        "f",
    )