from decimal import Decimal, InvalidOperation
from pathlib import Path


# ============================================================
# CAS PROCESSING ERROR
# ============================================================


class CASProcessingError(Exception):
    """
    Custom exception raised when CAS processing fails.
    """

    pass


# ============================================================
# PARSE CAS PDF
# ============================================================


def parse_cas_pdf(pdf_path, password):
    """
    Parse a password-protected CAMS/KFintech CAS PDF.

    The password is used only during parsing and is never stored.
    """

    if not pdf_path:
        raise CASProcessingError(
            "CAS PDF path is required."
        )

    if not password:
        raise CASProcessingError(
            "CAS PDF password is required."
        )

    path = Path(pdf_path)

    if not path.exists():
        raise CASProcessingError(
            "CAS PDF file does not exist."
        )

    if not path.is_file():
        raise CASProcessingError(
            "CAS PDF path is not a file."
        )

    if path.suffix.lower() != ".pdf":
        raise CASProcessingError(
            "Only PDF files are supported."
        )

    try:
        import casparser
    except ImportError as exc:
        raise CASProcessingError(
            "casparser is not installed. "
            "Run: python -m pip install -U casparser"
        ) from exc

    try:
        parsed_data = casparser.read_cas_pdf(
            str(path),
            password,
        )

    except Exception as exc:
        raise CASProcessingError(
            "Unable to parse the CAS PDF. "
            "Please verify the PDF and password."
        ) from exc

    return normalize_cas_data(parsed_data)


# ============================================================
# NORMALIZE CAS DATA
# ============================================================


def normalize_cas_data(parsed_data):
    """
    Convert casparser response into a normal Python dictionary.
    """

    if parsed_data is None:
        raise CASProcessingError(
            "CAS parser returned no data."
        )

    if hasattr(parsed_data, "model_dump"):

        data = parsed_data.model_dump(
            mode="json"
        )

    elif hasattr(parsed_data, "dict"):

        data = parsed_data.dict()

    elif isinstance(parsed_data, dict):

        data = parsed_data

    else:

        raise CASProcessingError(
            "Unsupported CAS parser response type."
        )

    if not isinstance(data, dict):
        raise CASProcessingError(
            "CAS parser returned invalid data."
        )

    return data


# ============================================================
# COMPLETE CAS DATA
# ============================================================


def extract_cas_portfolio_data(parsed_data):
    """
    Extract the complete application-level CAS structure.
    """

    if not isinstance(parsed_data, dict):
        raise CASProcessingError(
            "Invalid CAS data."
        )

    return {
        "investor": extract_cas_investor(
            parsed_data
        ),

        "portfolio_totals": (
            extract_cas_portfolio_totals(
                parsed_data
            )
        ),

        "mutual_fund_details": (
            extract_cas_holdings(
                parsed_data
            )
        ),
    }


# ============================================================
# INVESTOR INFORMATION
# ============================================================


# Legacy implementation retained below for reference.
#
# def extract_cas_investor(parsed_data):
#     """
#     Extract investor information from the actual casparser
#     structure.
#
#     Your installed casparser output contains:
#
#         investor_info
#
#     Therefore investor_info is checked first.
#
#     Returned structure:
#
#         {
#             "username": ...,
#             "email": ...,
#             "contact": ...,
#             "pan": ...
#         }
#     """
#
#     if not isinstance(parsed_data, dict):
#         raise CASProcessingError(
#             "Invalid CAS data."
#         )
#
#     investor_info = parsed_data.get(
#         "investor_info",
#         {},
#     )
#
#     if not isinstance(
#         investor_info,
#         dict,
#     ):
#         investor_info = {}
#
#     username = first_non_empty(
#         investor_info.get("name"),
#         investor_info.get("full_name"),
#         investor_info.get("investor_name"),
#         investor_info.get("holder_name"),
#         investor_info.get("username"),
#         parsed_data.get("name"),
#         parsed_data.get("investor_name"),
#     )
#
#     email = first_non_empty(
#         investor_info.get("email"),
#         investor_info.get("email_id"),
#         investor_info.get("email_address"),
#         parsed_data.get("email"),
#         parsed_data.get("email_id"),
#     )
#
#     contact = first_non_empty(
#         investor_info.get("mobile"),
#         investor_info.get("mobile_number"),
#         investor_info.get("contact"),
#         investor_info.get("phone"),
#         investor_info.get("phone_number"),
#         parsed_data.get("mobile"),
#         parsed_data.get("mobile_number"),
#     )
#
#     pan = first_non_empty(
#         investor_info.get("pan"),
#         investor_info.get("pan_number"),
#         investor_info.get("pan_no"),
#         investor_info.get("primary_holder_pan"),
#         parsed_data.get("pan"),
#         parsed_data.get("pan_number"),
#     )
#
#     nested_sections = (
#         investor_info.get("holder"),
#         investor_info.get("primary_holder"),
#         investor_info.get("personal_details"),
#         investor_info.get("contact_details"),
#     )
#
#     for section in nested_sections:
#
#         if not isinstance(
#             section,
#             dict,
#         ):
#             continue
#
#         if username is None:
#
#             username = first_non_empty(
#                 section.get("name"),
#                 section.get("full_name"),
#                 section.get("holder_name"),
#             )
#
#         if email is None:
#
#             email = first_non_empty(
#                 section.get("email"),
#                 section.get("email_id"),
#                 section.get("email_address"),
#             )
#
#         if contact is None:
#
#             contact = first_non_empty(
#                 section.get("mobile"),
#                 section.get("mobile_number"),
#                 section.get("phone"),
#                 section.get("phone_number"),
#             )
#
#         if pan is None:
#
#             pan = first_non_empty(
#                 section.get("pan"),
#                 section.get("pan_number"),
#                 section.get("pan_no"),
#             )
#
#     return {
#         "username": clean_string(
#             username
#         ),
#
#         "email": clean_string(
#             email
#         ),
#
#         "contact": clean_string(
#             contact
#         ),
#
#         "pan": clean_string(
#             pan
#         ),
#     }


def recursive_find_value(data, keys):
    """
    Recursively search nested dictionaries/lists for one of
    the requested keys.

    Returns the first non-empty value found.
    """

    if isinstance(data, dict):

        for key in data.keys():

            if str(key).lower() in {
                str(item).lower()
                for item in keys
            }:

                value = data.get(key)

                if value not in (
                    None,
                    "",
                    [],
                    {},
                ):

                    return value

        for value in data.values():

            result = recursive_find_value(
                value,
                keys,
            )

            if result not in (
                None,
                "",
            ):

                return result

    elif isinstance(data, list):

        for item in data:

            result = recursive_find_value(
                item,
                keys,
            )

            if result not in (
                None,
                "",
            ):

                return result

    return None


def extract_cas_investor(parsed_data):
    """
    Extract investor information from normalized CAS data.

    In the current casparser output, investor_info contains:

        name
        email
        address
        mobile

    PAN is not present inside investor_info, so PAN is searched
    recursively throughout the complete CAS response.
    """

    if not isinstance(parsed_data, dict):
        raise CASProcessingError(
            "Invalid CAS data."
        )

    investor_info = parsed_data.get(
        "investor_info",
        {},
    )

    if not isinstance(
        investor_info,
        dict,
    ):

        investor_info = {}

    username = first_non_empty(
        investor_info.get("name"),
        investor_info.get("full_name"),
        investor_info.get("investor_name"),
        investor_info.get("holder_name"),
    )

    email = first_non_empty(
        investor_info.get("email"),
        investor_info.get("email_id"),
        investor_info.get("email_address"),
    )

    contact = first_non_empty(
        investor_info.get("mobile"),
        investor_info.get("mobile_number"),
        investor_info.get("contact"),
        investor_info.get("phone"),
        investor_info.get("phone_number"),
    )

    address = first_non_empty(
        investor_info.get("address"),
        investor_info.get("address_line"),
    )

    # --------------------------------------------------------
    # PAN is not present in investor_info.
    #
    # Search the complete parsed CAS recursively.
    # --------------------------------------------------------

    pan = recursive_find_value(
        parsed_data,
        (
            "pan",
            "PAN",
            "pan_number",
            "PAN_number",
            "pan_no",
            "panNumber",
            "primary_holder_pan",
        ),
    )

    return {
        "username": clean_string(
            username
        ),

        "email": clean_string(
            email
        ),

        "contact": clean_string(
            contact
        ),

        "pan": clean_string(
            pan
        ),

        "address": clean_string(
            address
        ),
    }


# ============================================================
# PORTFOLIO TOTALS
# ============================================================


def extract_cas_portfolio_totals(
    parsed_data,
):
    """
    Extract portfolio-level totals.

    Explicit CAS totals are preferred.

    Missing totals are calculated from holdings.
    """

    if not isinstance(parsed_data, dict):
        raise CASProcessingError(
            "Invalid CAS data."
        )

    summary = {}

    possible_sections = (
        "summary",
        "portfolio_summary",
        "portfolio_totals",
        "totals",
        "valuation_summary",
        "valuation",
    )

    for key in possible_sections:

        section = parsed_data.get(
            key
        )

        if isinstance(
            section,
            dict,
        ):

            summary.update(
                section
            )

    total_cost = find_decimal(
        summary,
        (
            "total_cost_value",
            "total_cost",
            "cost_value",
            "total_invested_value",
            "invested_value",
            "cost",
        ),
    )

    total_market = find_decimal(
        summary,
        (
            "total_market_value",
            "total_current_value",
            "market_value",
            "current_value",
            "total_value",
            "value",
        ),
    )

    total_gain = find_decimal(
        summary,
        (
            "total_gain",
            "gain",
            "total_profit",
            "profit",
        ),
    )

    total_gain_percentage = find_decimal(
        summary,
        (
            "total_gain_percentage",
            "gain_percentage",
            "profit_percentage",
        ),
    )

    holdings = extract_cas_holdings(
        parsed_data
    )

    if total_cost is None:

        total_cost = sum_decimal(
            holdings,
            "invested_value",
        )

    if total_market is None:

        total_market = sum_decimal(
            holdings,
            "current_value",
        )

    if total_gain is None:

        total_gain = (
            total_market
            - total_cost
        )

    if (
        total_gain_percentage is None
        and total_cost > 0
    ):

        total_gain_percentage = (
            total_gain
            / total_cost
            * Decimal("100")
        )

    # --------------------------------------------------------
    # Required output order:
    #
    # total_cost_value
    # total_market_value
    # total_gain
    # total_gain_percentage
    # total_holdings
    #
    # No calculation or value is changed here.
    # --------------------------------------------------------

    return {
        "total_cost_value": (
            decimal_to_string(
                total_cost
            )
        ),

        "total_market_value": (
            decimal_to_string(
                total_market
            )
        ),

        "total_gain": (
            decimal_to_string(
                total_gain
            )
        ),

        "total_gain_percentage": (
            decimal_to_string(
                total_gain_percentage
            )
        ),

        "total_holdings": len(
            holdings
        ),
    }


# ============================================================
# HOLDINGS
# ============================================================


def extract_cas_holdings(parsed_data):
    """
    Extract all mutual-fund holdings.

    Dictionary key order is intentionally set for the API/Admin
    display.

    Required order:

        amc
        amfi_code
        isin
        scheme_name
        asset_type
        folio_number
        nav
        units
        nav_date
        current_value
        invested_value
    """

    if not isinstance(parsed_data, dict):
        raise CASProcessingError(
            "Invalid CAS data."
        )

    folios = parsed_data.get(
        "folios",
        [],
    )

    if not isinstance(
        folios,
        list,
    ):

        raise CASProcessingError(
            "CAS folios data is invalid."
        )

    holdings = []

    for folio in folios:

        if not isinstance(
            folio,
            dict,
        ):
            continue

        folio_number = first_non_empty(
            folio.get("folio"),
            folio.get("folio_number"),
        )

        amc = first_non_empty(
            folio.get("amc"),
            folio.get("amc_name"),
        )

        schemes = folio.get(
            "schemes",
            [],
        )

        if not isinstance(
            schemes,
            list,
        ):
            continue

        for scheme in schemes:

            if not isinstance(
                scheme,
                dict,
            ):
                continue

            valuation = scheme.get(
                "valuation",
                {},
            )

            if not isinstance(
                valuation,
                dict,
            ):

                valuation = {}

            # ------------------------------------------------
            # ONLY key order has been changed.
            #
            # All existing extraction logic is preserved.
            # ------------------------------------------------

            holdings.append(
                {
                    "amc": clean_string(
                        amc
                    ),

                    "amfi_code": clean_string(
                        first_non_empty(
                            scheme.get("amfi"),
                            scheme.get("amfi_code"),
                            scheme.get("scheme_code"),
                        )
                    ),

                    "isin": clean_string(
                        first_non_empty(
                            scheme.get("isin"),
                            scheme.get("isin_growth"),
                            scheme.get("isin_div_payout"),
                            scheme.get(
                                "isin_div_reinvestment"
                            ),
                        )
                    ),

                    "scheme_name": clean_string(
                        first_non_empty(
                            scheme.get("scheme"),
                            scheme.get("scheme_name"),
                        )
                    ),

                    "asset_type": clean_string(
                        first_non_empty(
                            scheme.get("type"),
                            scheme.get("asset_type"),
                        )
                    ),

                    "folio_number": clean_string(
                        folio_number
                    ),

                    "nav": to_decimal(
                        first_non_empty(
                            valuation.get("nav"),
                            scheme.get("nav"),
                        )
                    ),

                    "units": to_decimal(
                        first_non_empty(
                            scheme.get("close"),
                            scheme.get("units"),
                        )
                    ),

                    "nav_date": first_non_empty(
                        valuation.get("date"),
                        scheme.get("nav_date"),
                    ),

                    "current_value": to_decimal(
                        first_non_empty(
                            valuation.get("value"),
                            scheme.get("value"),
                            scheme.get(
                                "current_value"
                            ),
                        )
                    ),

                    "invested_value": to_decimal(
                        first_non_empty(
                            valuation.get("cost"),
                            scheme.get("cost"),
                            scheme.get(
                                "invested_value"
                            ),
                        )
                    ),
                }
            )

    return holdings


# ============================================================
# CAS SUMMARY
# ============================================================


def get_cas_summary(parsed_data):
    """
    Return a small processing summary.
    """

    if not isinstance(parsed_data, dict):
        raise CASProcessingError(
            "Invalid normalized CAS data."
        )

    folios = parsed_data.get(
        "folios",
        [],
    )

    if not isinstance(
        folios,
        list,
    ):

        folios = []

    scheme_count = 0

    for folio in folios:

        if not isinstance(
            folio,
            dict,
        ):

            continue

        schemes = folio.get(
            "schemes",
            [],
        )

        if isinstance(
            schemes,
            list,
        ):

            scheme_count += len(
                schemes
            )

    warnings = parsed_data.get(
        "parse_warnings",
        [],
    )

    if not isinstance(
        warnings,
        list,
    ):

        warnings = []

    return {
        "file_type": parsed_data.get(
            "file_type"
        ),

        "cas_type": parsed_data.get(
            "cas_type"
        ),

        "folio_count": len(
            folios
        ),

        "scheme_count": scheme_count,

        "parse_warning_count": len(
            warnings
        ),
    }


# ============================================================
# HELPERS
# ============================================================


def first_non_empty(*values):
    """
    Return the first non-empty value.
    """

    for value in values:

        if value is None:
            continue

        if isinstance(
            value,
            str,
        ):

            if value.strip():
                return value

        else:

            return value

    return None


def clean_string(value):
    """
    Convert value to trimmed string.
    """

    if value is None:
        return None

    value = str(
        value
    ).strip()

    return value or None


def to_decimal(value):
    """
    Convert financial value to Decimal.

    No float is used for financial calculations.
    """

    if value is None:
        return None

    if isinstance(
        value,
        Decimal,
    ):

        return value

    try:

        cleaned = (
            str(value)
            .strip()
            .replace(",", "")
            .replace("₹", "")
        )

        if not cleaned:
            return None

        return Decimal(
            cleaned
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):

        return None


def find_decimal(
    data,
    keys,
):
    """
    Find the first valid Decimal in a dictionary.
    """

    if not isinstance(
        data,
        dict,
    ):

        return None

    for key in keys:

        if key not in data:
            continue

        value = to_decimal(
            data.get(key)
        )

        if value is not None:
            return value

    return None


def sum_decimal(
    records,
    field_name,
):
    """
    Sum a numeric field using Decimal.
    """

    total = Decimal(
        "0.00"
    )

    for record in records:

        if not isinstance(
            record,
            dict,
        ):

            continue

        value = to_decimal(
            record.get(
                field_name
            )
        )

        if value is not None:

            total += value

    return total


def decimal_to_string(value):
    """
    Convert Decimal to a JSON-safe string.
    """

    value = to_decimal(
        value
    )

    if value is None:
        return "0.00"

    return format(
        value,
        "f",
    )