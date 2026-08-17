# C:\Users\Rohan Patil\office\AMFI_PROJECT\apps\mutual_funds\services\parser.py
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re


# =============================================================================
# CONSTANTS
# =============================================================================

DATE_FORMATS = (
    "%d-%b-%Y",
    "%d-%b-%y",
)

SCHEME_CODE_RE = re.compile(
    r"^\d+$"
)

NUMBER_RE = re.compile(
    r"^-?\d+(?:\.\d+)?$"
)

ISIN_RE = re.compile(
    r"^IN[A-Z0-9]{10}$",
    re.IGNORECASE,
)


# =============================================================================
# BASIC CLEANERS
# =============================================================================

def clean_text(value):
    """
    Normalize text received from AMFI.

    Handles:
        - BOM
        - non-breaking spaces
        - extra whitespace
        - leading/trailing spaces
    """

    if value is None:
        return ""

    value = str(value)

    value = value.replace("\ufeff", "")
    value = value.replace("\xa0", " ")

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def clean_optional(value):
    """
    Convert empty/placeholder AMFI values to None.
    """

    value = clean_text(value)

    if not value:
        return None

    if value.upper() in {
        "-",
        "--",
        "N/A",
        "NA",
        "N.A.",
        "NULL",
    }:
        return None

    return value


def clean_decimal(value):
    """
    Convert an AMFI numeric value into Decimal.

    Examples:

        "24.2752"    -> Decimal("24.2752")
        "1,234.56"   -> Decimal("1234.56")
        ""           -> None
    """

    value = clean_optional(value)

    if value is None:
        return None

    value = value.replace(",", "")

    if not NUMBER_RE.fullmatch(value):
        return None

    try:
        return Decimal(value)

    except (
        InvalidOperation,
        ValueError,
    ):
        return None


# =============================================================================
# DATE PARSER
# =============================================================================

def parse_nav_date(value):
    """
    Parse AMFI NAV date.

    Supported formats:

        15-Jul-2026
        15-Jul-26
    """

    value = clean_text(value)

    if not value:
        return None

    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(
                value,
                date_format,
            ).date()

        except ValueError:
            continue

    return None


# =============================================================================
# ISIN VALIDATION
# =============================================================================

def is_isin(value):
    """
    Validate an ISIN value.

    Example:

        INF579M01183
    """

    value = clean_text(value)

    if not value:
        return False

    return bool(
        ISIN_RE.fullmatch(value)
    )


# =============================================================================
# SCHEME CODE VALIDATION
# =============================================================================

def is_scheme_code(value):
    """
    Validate AMFI scheme code.

    AMFI scheme codes contain only digits.
    """

    value = clean_text(value)

    if not value:
        return False

    return bool(
        SCHEME_CODE_RE.fullmatch(value)
    )


# =============================================================================
# HEADER DETECTION
# =============================================================================

def is_header_line(line):
    """
    Detect normal AMFI report header lines.

    Examples:

        Scheme Code
        Scheme Name
        ISIN
        Net Asset Value
        NAV Date
        Repurchase Price
        Sale Price
    """

    normalized = clean_text(line).lower()

    if not normalized:
        return True

    header_words = (
        "scheme code",
        "scheme name",
        "isin",
        "net asset value",
        "nav date",
        "repurchase price",
        "sale price",
    )

    matches = sum(
        1
        for word in header_words
        if word in normalized
    )

    return matches >= 2


# =============================================================================
# FUND HOUSE DETECTION
# =============================================================================

def looks_like_fund_house(line):
    """
    Detect AMFI fund-house headings.

    Examples:

        360 ONE Mutual Fund
        Aditya Birla Sun Life Mutual Fund
    """

    line = clean_text(line)

    if not line:
        return False

    if ";" in line:
        return False

    if "|" in line:
        return False

    if "\t" in line:
        return False

    if is_scheme_code(line):
        return False

    if is_header_line(line):
        return False

    lower = line.lower()

    return (
        "mutual fund" in lower
        or "mutual funds" in lower
    )


# =============================================================================
# SCHEME HEADING PARSER
# =============================================================================

def parse_scheme_heading(line):
    """
    Parse AMFI scheme type/category headings.

    Examples:

        Open Ended Schemes ( Debt Scheme - Dynamic Bond )

        Open Ended Schemes ( Equity Scheme - Small Cap Fund )

        Open Ended Schemes ( Hybrid Scheme - Aggressive Hybrid Fund )

        Close Ended Schemes ( Equity Scheme - ... )

        Interval Fund ( Debt Scheme - ... )

    Returns:

        {
            "scheme_type": "...",
            "scheme_category": "..."
        }

    or:

        None
    """

    line = clean_text(line)

    if not line:
        return None

    # A scheme heading must be a standalone line.
    if ";" in line:
        return None

    if "|" in line:
        return None

    if "\t" in line:
        return None

    # -------------------------------------------------------------------------
    # Combined heading
    #
    # Example:
    #
    # Open Ended Schemes ( Debt Scheme - Dynamic Bond )
    # -------------------------------------------------------------------------

    combined_pattern = re.compile(
        r"^(?P<scheme_type>.+?)\s*"
        r"\(\s*(?P<scheme_category>.+?)\s*\)$",
        re.IGNORECASE,
    )

    match = combined_pattern.match(line)

    if match:

        scheme_type = clean_text(
            match.group("scheme_type")
        )

        scheme_category = clean_text(
            match.group("scheme_category")
        )

        if (
            scheme_type
            and scheme_category
        ):

            scheme_type_lower = (
                scheme_type.lower()
            )

            valid_type = (
                "open ended" in scheme_type_lower
                or "close ended" in scheme_type_lower
                or "interval fund" in scheme_type_lower
            )

            if valid_type:

                return {
                    "scheme_type": scheme_type,
                    "scheme_category": scheme_category,
                }

    # -------------------------------------------------------------------------
    # Standalone scheme type
    #
    # Example:
    #
    # Open Ended Schemes
    # -------------------------------------------------------------------------

    lower = line.lower()

    standalone_types = {
        "open ended schemes",
        "open-ended schemes",
        "close ended schemes",
        "close-ended schemes",
        "interval fund",
        "interval funds",
    }

    if lower in standalone_types:

        return {
            "scheme_type": line,
            "scheme_category": None,
        }

    return None


# =============================================================================
# LEGACY SCHEME TYPE DETECTION
# =============================================================================

def looks_like_scheme_type(line):
    """
    Compatibility helper for standalone scheme types.
    """

    parsed = parse_scheme_heading(line)

    if not parsed:
        return False

    return (
        parsed["scheme_type"] is not None
        and parsed["scheme_category"] is None
    )


# =============================================================================
# LEGACY CATEGORY DETECTION
# =============================================================================

def looks_like_category(line):
    """
    Compatibility helper for standalone scheme categories.

    Examples:

        Equity Scheme - Large Cap Fund
        Debt Scheme - Dynamic Bond
        Hybrid Scheme - Balanced Hybrid Fund
    """

    line = clean_text(line)

    if not line:
        return False

    if ";" in line:
        return False

    if "|" in line:
        return False

    lower = line.lower()

    category_patterns = (
        "equity scheme",
        "debt scheme",
        "hybrid scheme",
        "solution oriented scheme",
        "other scheme",
        "index fund",
        "etf",
        "fund of funds",
        "fund of fund",
    )

    return any(
        pattern in lower
        for pattern in category_patterns
    )


# =============================================================================
# FIELD SPLITTER
# =============================================================================

def split_fields(line):
    """
    Split a structured AMFI record.

    AMFI normally uses semicolon-separated fields.

    Example:

        122612;
        360 ONE Dynamic Bond Fund - Regular Plan - Growth Option;
        INF579M01183;
        ;
        24.2752;
        ;
        ;
        11-Aug-2026
    """

    line = line.strip()

    if ";" in line:

        fields = line.split(";")

    elif "|" in line:

        fields = line.split("|")

    elif "\t" in line:

        fields = line.split("\t")

    else:

        return None

    return [
        clean_text(field)
        for field in fields
    ]


# =============================================================================
# STRUCTURED AMFI RECORD PARSER
# =============================================================================

def parse_structured_record(
    fields,
    current_fund_house,
    current_scheme_type,
    current_category,
    current_date=None,
):
    """
    Parse one structured AMFI scheme row.

    Expected AMFI structure:

        0 = Scheme Code
        1 = Scheme Name
        2 = ISIN
        3 = Second ISIN
        4 = NAV
        5 = Repurchase Price
        6 = Sale Price
        7 = NAV Date

    Example:

        [
            "122612",
            "360 ONE Dynamic Bond Fund - Regular Plan - Growth Option",
            "INF579M01183",
            "",
            "24.2752",
            "",
            "",
            "11-Aug-2026"
        ]
    """

    if not fields:
        return None

    fields = [
        clean_text(field)
        for field in fields
    ]

    # =========================================================================
    # SCHEME CODE
    # =========================================================================

    if not is_scheme_code(fields[0]):
        return None

    scheme_code = int(
        fields[0]
    )

    # =========================================================================
    # BASIC FIELD COUNT
    # =========================================================================

    if len(fields) < 5:
        return None

    # =========================================================================
    # SCHEME NAME
    # =========================================================================

    scheme_name = clean_optional(
        fields[1]
    )

    if not scheme_name:
        return None

    # =========================================================================
    # ISIN VALUES
    # =========================================================================

    isin_values = []

    for field in fields[2:4]:

        value = clean_optional(
            field
        )

        if value and is_isin(value):

            isin_values.append(
                value.upper()
            )

    # -------------------------------------------------------------------------
    # AMFI convention used by this project:
    #
    # First ISIN  -> isin_growth
    # Second ISIN -> isin_div_reinvestment
    # -------------------------------------------------------------------------

    isin_growth = (
        isin_values[0]
        if len(isin_values) >= 1
        else None
    )

    isin_div_reinvestment = (
        isin_values[1]
        if len(isin_values) >= 2
        else None
    )

    # =========================================================================
    # NAV DATE
    # =========================================================================

    actual_date = None

    # Normal AMFI structure places NAV date at the last field.
    if fields:

        actual_date = parse_nav_date(
            fields[-1]
        )

    # Fallback: search from right to left.
    if actual_date is None:

        for field in reversed(fields):

            parsed_date = parse_nav_date(
                field
            )

            if parsed_date is not None:

                actual_date = parsed_date

                break

    # Use supplied default date if necessary.
    if actual_date is None:

        actual_date = current_date

    if actual_date is None:
        return None

    # =========================================================================
    # NAV
    # =========================================================================

    nav = None

    # Normal AMFI NAV position.
    if len(fields) > 4:

        nav = clean_decimal(
            fields[4]
        )

    # Fallback NAV search.
    if nav is None:

        date_position = len(fields) - 1

        for index in range(
            2,
            date_position,
        ):

            candidate = clean_decimal(
                fields[index]
            )

            if candidate is not None:

                nav = candidate

                break

    if nav is None:
        return None

    # =========================================================================
    # REPURCHASE PRICE
    # =========================================================================

    repurchase_price = None

    if len(fields) > 5:

        repurchase_price = clean_decimal(
            fields[5]
        )

    # =========================================================================
    # SALE PRICE
    # =========================================================================

    sale_price = None

    if len(fields) > 6:

        sale_price = clean_decimal(
            fields[6]
        )

    # =========================================================================
    # FUND HOUSE
    # =========================================================================

    if not current_fund_house:
        return None

    # =========================================================================
    # FINAL NORMALIZED RECORD
    # =========================================================================

    return {
        "fund_house_name": current_fund_house,

        "scheme_type": (
            current_scheme_type
            if current_scheme_type
            else None
        ),

        "scheme_category": (
            current_category
            if current_category
            else None
        ),

        "scheme_code": scheme_code,

        "scheme_name": scheme_name,

        "isin_growth": isin_growth,

        "isin_div_payout": None,

        "isin_div_reinvestment": (
            isin_div_reinvestment
        ),

        "nav": nav,

        "nav_date": actual_date,

        "repurchase_price": (
            repurchase_price
        ),

        "sale_price": (
            sale_price
        ),
    }


# =============================================================================
# MAIN AMFI PARSER
# =============================================================================

def parse_amfi_report(
    raw_data,
    default_nav_date=None,
):
    """
    Parse the complete AMFI NAV report.

    Processing flow:

        Scheme heading
                ↓
        Fund house heading
                ↓
        Scheme records
                ↓
        Normalized records

    Important:

        The scheme type/category is preserved when the
        fund-house heading appears AFTER the scheme heading.

    Example AMFI data:

        Open Ended Schemes ( Debt Scheme - Dynamic Bond )

        360 ONE Mutual Fund

        122612;360 ONE Dynamic Bond Fund - Regular Plan - Growth Option;
        INF579M01183;;24.2752;;;11-Aug-2026

    Result:

        scheme_type:
            Open Ended Schemes

        scheme_category:
            Debt Scheme - Dynamic Bond
    """

    if raw_data is None:
        return []

    # =========================================================================
    # DECODE BYTES
    # =========================================================================

    if isinstance(
        raw_data,
        bytes,
    ):

        decoded = None

        for encoding in (
            "utf-8-sig",
            "utf-8",
            "cp1252",
            "latin-1",
        ):

            try:

                decoded = raw_data.decode(
                    encoding
                )

                break

            except UnicodeDecodeError:

                continue

        if decoded is None:
            return []

        raw_data = decoded

    # =========================================================================
    # NORMALIZE INPUT
    # =========================================================================

    raw_data = str(raw_data)

    raw_data = raw_data.replace(
        "\r\n",
        "\n",
    )

    raw_data = raw_data.replace(
        "\r",
        "\n",
    )

    lines = raw_data.split(
        "\n"
    )

    # =========================================================================
    # PARSER STATE
    # =========================================================================

    records = []

    current_fund_house = None

    current_scheme_type = None

    current_category = None

    current_date = default_nav_date

    # =========================================================================
    # PROCESS EVERY LINE
    # =========================================================================

    for raw_line in lines:

        line = clean_text(
            raw_line
        )

        if not line:
            continue

        # =====================================================================
        # HEADER
        # =====================================================================

        if is_header_line(line):
            continue

        # =====================================================================
        # SCHEME TYPE / CATEGORY HEADING
        # =====================================================================

        scheme_heading = parse_scheme_heading(
            line
        )

        if scheme_heading:

            current_scheme_type = (
                scheme_heading["scheme_type"]
            )

            current_category = (
                scheme_heading["scheme_category"]
            )

            continue

        # =====================================================================
        # FUND HOUSE
        # =====================================================================

        if looks_like_fund_house(line):

            current_fund_house = line

            # IMPORTANT:
            #
            # DO NOT RESET current_scheme_type
            # DO NOT RESET current_category
            #
            # AMFI commonly gives:
            #
            #   Open Ended Schemes ( Debt Scheme - Dynamic Bond )
            #
            #   360 ONE Mutual Fund
            #
            #   122612;...
            #
            # Therefore the scheme heading belongs to the
            # fund-house section that follows it.
            #
            # This was the main reason your values became NULL.

            continue

        # =====================================================================
        # STRUCTURED AMFI RECORD
        # =====================================================================

        fields = split_fields(
            line
        )

        if fields:

            record = parse_structured_record(
                fields=fields,
                current_fund_house=(
                    current_fund_house
                ),
                current_scheme_type=(
                    current_scheme_type
                ),
                current_category=(
                    current_category
                ),
                current_date=current_date,
            )

            if record:

                records.append(
                    record
                )

                continue

        # =====================================================================
        # LEGACY STANDALONE SCHEME TYPE
        # =====================================================================

        if looks_like_scheme_type(line):

            current_scheme_type = line

            current_category = None

            continue

        # =====================================================================
        # LEGACY STANDALONE CATEGORY
        # =====================================================================

        if looks_like_category(line):

            current_category = line

            continue

    # =========================================================================
    # DEDUPLICATION
    # =========================================================================

    unique_records = {}

    for record in records:

        scheme_code = record[
            "scheme_code"
        ]

        nav_date = record[
            "nav_date"
        ]

        key = (
            scheme_code,
            nav_date,
        )

        # Keep the first occurrence.
        if key not in unique_records:

            unique_records[key] = record

    # =========================================================================
    # FINAL RESULT
    # =========================================================================

    result = list(
        unique_records.values()
    )

    # Stable ordering.
    result.sort(
        key=lambda item: (
            item["fund_house_name"],
            item["scheme_code"],
            item["nav_date"],
        )
    )

    return result


# =============================================================================
# PARSER SUMMARY
# =============================================================================

def parser_summary(records):
    """
    Return diagnostic information about parsed records.
    """

    if not records:

        return {
            "records": 0,
            "fund_houses": 0,
            "schemes": 0,
            "dates": 0,
        }

    fund_houses = {
        record["fund_house_name"]
        for record in records
    }

    schemes = {
        record["scheme_code"]
        for record in records
    }

    dates = {
        record["nav_date"]
        for record in records
    }

    return {
        "records": len(records),
        "fund_houses": len(fund_houses),
        "schemes": len(schemes),
        "dates": len(dates),
    }
# from datetime import datetime
# from decimal import Decimal, InvalidOperation
# import re
#
#
# # =============================================================================
# # CONSTANTS
# # =============================================================================
#
# DATE_FORMATS = (
#     "%d-%b-%Y",
#     "%d-%b-%y",
# )
#
# SCHEME_CODE_RE = re.compile(
#     r"^\d+$"
# )
#
# NUMBER_RE = re.compile(
#     r"^-?\d+(?:\.\d+)?$"
# )
#
# ISIN_RE = re.compile(
#     r"^IN[A-Z0-9]{10}$",
#     re.IGNORECASE,
# )
#
#
# # =============================================================================
# # BASIC CLEANERS
# # =============================================================================
#
# def clean_text(value):
#     """
#     Normalize text received from AMFI.
#
#     Handles:
#         - BOM
#         - non-breaking spaces
#         - extra whitespace
#         - leading/trailing spaces
#     """
#
#     if value is None:
#         return ""
#
#     value = str(value)
#
#     value = value.replace("\ufeff", "")
#     value = value.replace("\xa0", " ")
#
#     value = re.sub(
#         r"\s+",
#         " ",
#         value,
#     )
#
#     return value.strip()
#
#
# def clean_optional(value):
#     """
#     Convert empty/placeholder AMFI values to None.
#     """
#
#     value = clean_text(value)
#
#     if not value:
#         return None
#
#     if value.upper() in {
#         "-",
#         "--",
#         "N/A",
#         "NA",
#         "N.A.",
#         "NULL",
#     }:
#         return None
#
#     return value
#
#
# def clean_decimal(value):
#     """
#     Convert an AMFI numeric value into Decimal.
#
#     Examples:
#
#         "24.2752" -> Decimal("24.2752")
#         "1,234.56" -> Decimal("1234.56")
#         "" -> None
#     """
#
#     value = clean_optional(value)
#
#     if value is None:
#         return None
#
#     value = value.replace(",", "")
#
#     if not NUMBER_RE.fullmatch(value):
#         return None
#
#     try:
#         return Decimal(value)
#
#     except (
#         InvalidOperation,
#         ValueError,
#     ):
#         return None
#
#
# # =============================================================================
# # DATE PARSER
# # =============================================================================
#
# def parse_nav_date(value):
#     """
#     Parse AMFI NAV date.
#
#     Supported formats:
#
#         15-Jul-2026
#         15-Jul-26
#     """
#
#     value = clean_text(value)
#
#     if not value:
#         return None
#
#     for date_format in DATE_FORMATS:
#
#         try:
#             return datetime.strptime(
#                 value,
#                 date_format,
#             ).date()
#
#         except ValueError:
#             continue
#
#     return None
#
#
# # =============================================================================
# # ISIN VALIDATION
# # =============================================================================
#
# def is_isin(value):
#     """
#     Validate an ISIN value.
#
#     Example:
#
#         INF579M01183
#     """
#
#     value = clean_text(value)
#
#     if not value:
#         return False
#
#     return bool(
#         ISIN_RE.fullmatch(value)
#     )
#
#
# # =============================================================================
# # SCHEME CODE VALIDATION
# # =============================================================================
#
# def is_scheme_code(value):
#     """
#     AMFI scheme code must contain only digits.
#     """
#
#     value = clean_text(value)
#
#     if not value:
#         return False
#
#     return bool(
#         SCHEME_CODE_RE.fullmatch(value)
#     )
#
#
# # =============================================================================
# # HEADER DETECTION
# # =============================================================================
#
# def is_header_line(line):
#     """
#     Detect normal AMFI report header lines.
#
#     Examples:
#
#         Scheme Code
#         Scheme Name
#         ISIN
#         Net Asset Value
#         Date
#     """
#
#     normalized = clean_text(line).lower()
#
#     if not normalized:
#         return True
#
#     header_words = (
#         "scheme code",
#         "isin",
#         "scheme name",
#         "net asset value",
#         "nav",
#         "nav date",
#         "date",
#         "repurchase price",
#         "sale price",
#     )
#
#     matches = sum(
#         1
#         for word in header_words
#         if word in normalized
#     )
#
#     return matches >= 2
#
#
# # =============================================================================
# # FUND HOUSE DETECTION
# # =============================================================================
#
# def looks_like_fund_house(line):
#     """
#     Detect AMFI fund-house headings.
#
#     Example:
#
#         360 ONE Mutual Fund
#         Aditya Birla Sun Life Mutual Fund
#     """
#
#     line = clean_text(line)
#
#     if not line:
#         return False
#
#     if ";" in line:
#         return False
#
#     if "|" in line:
#         return False
#
#     if "\t" in line:
#         return False
#
#     if is_scheme_code(line):
#         return False
#
#     if is_header_line(line):
#         return False
#
#     lower = line.lower()
#
#     fund_house_keywords = (
#         "mutual fund",
#         "mutual funds",
#     )
#
#     return any(
#         keyword in lower
#         for keyword in fund_house_keywords
#     )
#
#
# # =============================================================================
# # SCHEME HEADING PARSER
# # =============================================================================
#
# def parse_scheme_heading(line):
#     """
#     Parse AMFI scheme type/category headings.
#
#     AMFI commonly provides headings such as:
#
#         Open Ended Schemes ( Debt Scheme - Dynamic Bond )
#
#         Open Ended Schemes ( Equity Scheme - Large Cap Fund )
#
#         Open Ended Schemes ( Hybrid Scheme - Balanced Hybrid Fund )
#
#         Close Ended Schemes ( Equity Scheme - ... )
#
#         Interval Fund ( Debt Scheme - ... )
#
#     The important point is that scheme_type and scheme_category
#     are sometimes present in ONE line.
#
#     Returns:
#
#         {
#             "scheme_type": "...",
#             "scheme_category": "..."
#         }
#
#     or None if the line is not a scheme heading.
#     """
#
#     line = clean_text(line)
#
#     if not line:
#         return None
#
#     # AMFI scheme heading must normally be a standalone line.
#     if ";" in line:
#         return None
#
#     if "|" in line:
#         return None
#
#     if "\t" in line:
#         return None
#
#     # -------------------------------------------------------------------------
#     # Pattern:
#     #
#     # Open Ended Schemes ( Debt Scheme - Dynamic Bond )
#     #
#     # Close Ended Schemes ( Equity Scheme - Small Cap )
#     #
#     # -------------------------------------------------------------------------
#
#     combined_pattern = re.compile(
#         r"^(?P<scheme_type>.+?)\s*"
#         r"\(\s*(?P<scheme_category>.+?)\s*\)$",
#         re.IGNORECASE,
#     )
#
#     match = combined_pattern.match(line)
#
#     if match:
#
#         scheme_type = clean_text(
#             match.group("scheme_type")
#         )
#
#         scheme_category = clean_text(
#             match.group("scheme_category")
#         )
#
#         if (
#             scheme_type
#             and scheme_category
#         ):
#
#             # Make sure this is actually an AMFI scheme heading.
#             scheme_type_lower = scheme_type.lower()
#
#             if (
#                 "open ended" in scheme_type_lower
#                 or "close ended" in scheme_type_lower
#                 or "interval fund" in scheme_type_lower
#             ):
#
#                 return {
#                     "scheme_type": scheme_type,
#                     "scheme_category": scheme_category,
#                 }
#
#     # -------------------------------------------------------------------------
#     # Standalone scheme type.
#     #
#     # Example:
#     #
#     # Open Ended Schemes
#     #
#     # -------------------------------------------------------------------------
#
#     lower = line.lower()
#
#     standalone_types = {
#         "open ended schemes",
#         "open-ended schemes",
#         "close ended schemes",
#         "close-ended schemes",
#         "interval fund",
#         "interval funds",
#     }
#
#     if lower in standalone_types:
#
#         return {
#             "scheme_type": line,
#             "scheme_category": None,
#         }
#
#     return None
#
#
# # =============================================================================
# # LEGACY SCHEME TYPE DETECTION
# # =============================================================================
#
# def looks_like_scheme_type(line):
#     """
#     Detect standalone AMFI scheme types.
#
#     This function is kept for compatibility with existing code.
#     """
#
#     parsed = parse_scheme_heading(line)
#
#     if not parsed:
#         return False
#
#     return (
#         parsed["scheme_type"] is not None
#         and parsed["scheme_category"] is None
#     )
#
#
# # =============================================================================
# # LEGACY CATEGORY DETECTION
# # =============================================================================
#
# def looks_like_category(line):
#     """
#     Detect standalone AMFI categories.
#
#     This is mainly a compatibility fallback.
#
#     Examples:
#
#         Equity Scheme - Large Cap Fund
#         Debt Scheme - Dynamic Bond
#         Hybrid Scheme
#     """
#
#     line = clean_text(line)
#
#     if not line:
#         return False
#
#     if ";" in line:
#         return False
#
#     lower = line.lower()
#
#     category_patterns = (
#         "scheme -",
#         "scheme–",
#         "scheme –",
#         "fund)",
#         "fund",
#         "etf",
#         "fof",
#         "fund of funds",
#     )
#
#     return any(
#         pattern in lower
#         for pattern in category_patterns
#     )
#
#
# # =============================================================================
# # FIELD SPLITTER
# # =============================================================================
#
# def split_fields(line):
#     """
#     Split a structured AMFI record.
#
#     AMFI normally uses semicolon-separated fields.
#
#     Example:
#
#         122612;
#         360 ONE Dynamic Bond Fund - Regular Plan - Growth Option;
#         INF579M01183;
#         ;
#         24.2752;
#         ;
#         ;
#         11-Aug-2026
#     """
#
#     line = line.strip()
#
#     if ";" in line:
#
#         fields = line.split(";")
#
#     elif "|" in line:
#
#         fields = line.split("|")
#
#     elif "\t" in line:
#
#         fields = line.split("\t")
#
#     else:
#
#         return None
#
#     return [
#         clean_text(field)
#         for field in fields
#     ]
#
#
# # =============================================================================
# # STRUCTURED AMFI RECORD PARSER
# # =============================================================================
#
# def parse_structured_record(
#     fields,
#     current_fund_house,
#     current_scheme_type,
#     current_category,
#     current_date=None,
# ):
#     """
#     Parse one structured AMFI scheme row.
#
#     Expected AMFI structure:
#
#         0 = Scheme Code
#         1 = Scheme Name
#         2 = ISIN
#         3 = second ISIN
#         4 = NAV
#         5 = Repurchase Price
#         6 = Sale Price
#         7 = NAV Date
#
#     Example:
#
#         [
#             "122612",
#             "360 ONE Dynamic Bond Fund - Regular Plan - Growth Option",
#             "INF579M01183",
#             "",
#             "24.2752",
#             "",
#             "",
#             "11-Aug-2026"
#         ]
#
#     Returns one normalized dictionary.
#     """
#
#     if not fields:
#         return None
#
#     fields = [
#         clean_text(field)
#         for field in fields
#     ]
#
#     # =========================================================================
#     # SCHEME CODE
#     # =========================================================================
#
#     if not is_scheme_code(fields[0]):
#         return None
#
#     scheme_code = int(
#         fields[0]
#     )
#
#     # =========================================================================
#     # BASIC FIELD COUNT
#     # =========================================================================
#
#     if len(fields) < 5:
#         return None
#
#     # =========================================================================
#     # SCHEME NAME
#     # =========================================================================
#
#     scheme_name = clean_optional(
#         fields[1]
#     )
#
#     if not scheme_name:
#         return None
#
#     # =========================================================================
#     # ISIN VALUES
#     # =========================================================================
#
#     isin_values = []
#
#     for field in fields[2:4]:
#
#         value = clean_optional(field)
#
#         if value and is_isin(value):
#
#             isin_values.append(
#                 value.upper()
#             )
#
#     # -------------------------------------------------------------------------
#     # AMFI convention used here:
#     #
#     # First ISIN  -> isin_growth
#     # Second ISIN -> isin_div_reinvestment
#     #
#     # This preserves the existing project structure.
#     # -------------------------------------------------------------------------
#
#     isin_growth = (
#         isin_values[0]
#         if len(isin_values) >= 1
#         else None
#     )
#
#     isin_div_reinvestment = (
#         isin_values[1]
#         if len(isin_values) >= 2
#         else None
#     )
#
#     # =========================================================================
#     # NAV DATE
#     # =========================================================================
#
#     actual_date = None
#
#     # The normal AMFI date is the last field.
#     if fields:
#
#         actual_date = parse_nav_date(
#             fields[-1]
#         )
#
#     # -------------------------------------------------------------------------
#     # Fallback: search from right to left.
#     # -------------------------------------------------------------------------
#
#     if actual_date is None:
#
#         for field in reversed(fields):
#
#             parsed_date = parse_nav_date(
#                 field
#             )
#
#             if parsed_date is not None:
#
#                 actual_date = parsed_date
#
#                 break
#
#     # -------------------------------------------------------------------------
#     # If AMFI did not provide a valid date,
#     # use supplied default date.
#     # -------------------------------------------------------------------------
#
#     if actual_date is None:
#
#         actual_date = current_date
#
#     if actual_date is None:
#         return None
#
#     # =========================================================================
#     # NAV
#     # =========================================================================
#
#     nav = None
#
#     # -------------------------------------------------------------------------
#     # In normal AMFI structure NAV is field 4.
#     # -------------------------------------------------------------------------
#
#     if len(fields) > 4:
#
#         nav = clean_decimal(
#             fields[4]
#         )
#
#     # -------------------------------------------------------------------------
#     # Fallback NAV search.
#     #
#     # Search numeric values before the date.
#     # Do NOT search scheme code or scheme name.
#     # -------------------------------------------------------------------------
#
#     if nav is None:
#
#         date_position = (
#             len(fields) - 1
#         )
#
#         for index in range(
#             2,
#             date_position,
#         ):
#
#             candidate = clean_decimal(
#                 fields[index]
#             )
#
#             if candidate is not None:
#
#                 nav = candidate
#
#                 break
#
#     if nav is None:
#         return None
#
#     # =========================================================================
#     # REPURCHASE PRICE
#     # =========================================================================
#
#     repurchase_price = None
#
#     if len(fields) > 5:
#
#         repurchase_price = clean_decimal(
#             fields[5]
#         )
#
#     # =========================================================================
#     # SALE PRICE
#     # =========================================================================
#
#     sale_price = None
#
#     if len(fields) > 6:
#
#         sale_price = clean_decimal(
#             fields[6]
#         )
#
#     # =========================================================================
#     # FUND HOUSE
#     # =========================================================================
#
#     if not current_fund_house:
#         return None
#
#     # =========================================================================
#     # FINAL RECORD
#     # =========================================================================
#
#     return {
#         "fund_house_name": current_fund_house,
#
#         "scheme_type": (
#             current_scheme_type
#             if current_scheme_type
#             else None
#         ),
#
#         "scheme_category": (
#             current_category
#             if current_category
#             else None
#         ),
#
#         "scheme_code": scheme_code,
#
#         "scheme_name": scheme_name,
#
#         "isin_growth": isin_growth,
#
#         "isin_div_payout": None,
#
#         "isin_div_reinvestment": (
#             isin_div_reinvestment
#         ),
#
#         "nav": nav,
#
#         "nav_date": actual_date,
#
#         "repurchase_price": (
#             repurchase_price
#         ),
#
#         "sale_price": sale_price,
#     }
#
#
# # =============================================================================
# # MAIN AMFI PARSER
# # =============================================================================
#
# def parse_amfi_report(
#     raw_data,
#     default_nav_date=None,
# ):
#     """
#     Parse the complete AMFI NAV report.
#
#     Important behavior:
#
#     1. Reads fund-house headings.
#     2. Reads combined scheme headings.
#     3. Extracts scheme_type.
#     4. Extracts scheme_category.
#     5. Reads scheme records.
#     6. Extracts ISIN.
#     7. Extracts NAV.
#     8. Extracts NAV date.
#     9. Preserves historical dates.
#     10. Deduplicates by scheme_code + nav_date.
#
#     Example input:
#
#         Open Ended Schemes ( Debt Scheme - Dynamic Bond )
#
#         360 ONE Mutual Fund
#
#         122612;360 ONE Dynamic Bond Fund - Regular Plan - Growth Option;
#         INF579M01183;;24.2752;;;11-Aug-2026
#
#     Result:
#
#         {
#             "fund_house_name": "360 ONE Mutual Fund",
#             "scheme_type": "Open Ended Schemes",
#             "scheme_category": "Debt Scheme - Dynamic Bond",
#             "scheme_code": 122612,
#             "scheme_name": "...",
#             "isin_growth": "INF579M01183",
#             "nav": Decimal("24.2752"),
#             "nav_date": date(2026, 8, 11)
#         }
#     """
#
#     if raw_data is None:
#         return []
#
#     # =========================================================================
#     # DECODE BYTES
#     # =========================================================================
#
#     if isinstance(
#         raw_data,
#         bytes,
#     ):
#
#         decoded = None
#
#         for encoding in (
#             "utf-8-sig",
#             "utf-8",
#             "cp1252",
#             "latin-1",
#         ):
#
#             try:
#
#                 decoded = raw_data.decode(
#                     encoding
#                 )
#
#                 break
#
#             except UnicodeDecodeError:
#
#                 continue
#
#         if decoded is None:
#             return []
#
#         raw_data = decoded
#
#     # =========================================================================
#     # NORMALIZE INPUT
#     # =========================================================================
#
#     raw_data = str(raw_data)
#
#     raw_data = raw_data.replace(
#         "\r\n",
#         "\n",
#     )
#
#     raw_data = raw_data.replace(
#         "\r",
#         "\n",
#     )
#
#     lines = raw_data.split(
#         "\n"
#     )
#
#     # =========================================================================
#     # PARSER STATE
#     # =========================================================================
#
#     records = []
#
#     current_fund_house = None
#
#     current_scheme_type = None
#
#     current_category = None
#
#     current_date = (
#         default_nav_date
#     )
#
#     # =========================================================================
#     # PROCESS EVERY LINE
#     # =========================================================================
#
#     for raw_line in lines:
#
#         line = clean_text(
#             raw_line
#         )
#
#         if not line:
#             continue
#
#         # =====================================================================
#         # HEADER
#         # =====================================================================
#
#         if is_header_line(line):
#             continue
#
#         # =====================================================================
#         # SCHEME TYPE / CATEGORY HEADING
#         #
#         # THIS IS THE IMPORTANT FIX.
#         #
#         # Example:
#         #
#         # Open Ended Schemes ( Debt Scheme - Dynamic Bond )
#         #
#         # becomes:
#         #
#         # current_scheme_type = "Open Ended Schemes"
#         # current_category    = "Debt Scheme - Dynamic Bond"
#         # =====================================================================
#
#         scheme_heading = parse_scheme_heading(
#             line
#         )
#
#         if scheme_heading:
#
#             current_scheme_type = (
#                 scheme_heading["scheme_type"]
#             )
#
#             current_category = (
#                 scheme_heading["scheme_category"]
#             )
#
#             continue
#
#         # =====================================================================
#         # STRUCTURED AMFI RECORD
#         # =====================================================================
#
#         fields = split_fields(
#             line
#         )
#
#         if fields:
#
#             record = parse_structured_record(
#                 fields=fields,
#                 current_fund_house=(
#                     current_fund_house
#                 ),
#                 current_scheme_type=(
#                     current_scheme_type
#                 ),
#                 current_category=(
#                     current_category
#                 ),
#                 current_date=current_date,
#             )
#
#             if record:
#
#                 records.append(
#                     record
#                 )
#
#                 continue
#
#         # =====================================================================
#         # FUND HOUSE
#         # =====================================================================
#
#         if looks_like_fund_house(
#             line
#         ):
#
#             current_fund_house = line
#
#             # When a new fund house starts,
#             # category information will be updated
#             # when the next scheme heading appears.
#             #
#             # Do not incorrectly carry previous category
#             # information into another fund house.
#
#             current_scheme_type = None
#
#             current_category = None
#
#             continue
#
#         # =====================================================================
#         # LEGACY STANDALONE SCHEME TYPE/CATEGORY FALLBACK
#         # =====================================================================
#
#         if looks_like_scheme_type(
#             line
#         ):
#
#             current_scheme_type = line
#
#             current_category = None
#
#             continue
#
#         if looks_like_category(
#             line
#         ):
#
#             current_category = line
#
#             continue
#
#     # =========================================================================
#     # DEDUPLICATION
#     # =========================================================================
#
#     unique_records = {}
#
#     for record in records:
#
#         scheme_code = record[
#             "scheme_code"
#         ]
#
#         nav_date = record[
#             "nav_date"
#         ]
#
#         key = (
#             scheme_code,
#             nav_date,
#         )
#
#         # Keep first occurrence.
#         if key not in unique_records:
#
#             unique_records[key] = record
#
#     # =========================================================================
#     # RESULT
#     # =========================================================================
#
#     result = list(
#         unique_records.values()
#     )
#
#     # Stable ordering.
#     result.sort(
#         key=lambda item: (
#             item["fund_house_name"],
#             item["scheme_code"],
#             item["nav_date"],
#         )
#     )
#
#     return result
#
#
# # =============================================================================
# # PARSER SUMMARY
# # =============================================================================
#
# def parser_summary(records):
#     """
#     Return diagnostic information about parsed records.
#     """
#
#     if not records:
#
#         return {
#             "records": 0,
#             "fund_houses": 0,
#             "schemes": 0,
#             "dates": 0,
#         }
#
#     fund_houses = {
#         record["fund_house_name"]
#         for record in records
#     }
#
#     schemes = {
#         record["scheme_code"]
#         for record in records
#     }
#
#     dates = {
#         record["nav_date"]
#         for record in records
#     }
#
#     return {
#         "records": len(records),
#         "fund_houses": len(fund_houses),
#         "schemes": len(schemes),
#         "dates": len(dates),
#     }