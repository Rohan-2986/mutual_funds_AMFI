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

    value = value.replace(
        "\ufeff",
        "",
    )

    value = value.replace(
        "\xa0",
        " ",
    )

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

    value = value.replace(
        ",",
        "",
    )

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

    normalized = clean_text(
        line
    ).lower()

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

    line = clean_text(
        line
    )

    if not line:
        return False

    # A fund-house heading must be a standalone line.
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

    line = clean_text(
        line
    )

    if not line:
        return None

    # Scheme headings must be standalone lines.
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

    match = combined_pattern.match(
        line
    )

    if match:

        scheme_type = clean_text(
            match.group(
                "scheme_type"
            )
        )

        scheme_category = clean_text(
            match.group(
                "scheme_category"
            )
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

    parsed = parse_scheme_heading(
        line
    )

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

    line = clean_text(
        line
    )

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

    Supported separators:

        ;
        |
        tab
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
# STRUCTURED RECORD DETECTION
# =============================================================================

def is_structured_scheme_line(line):
    """
    Determine whether a line looks like an AMFI scheme data row.

    IMPORTANT:

    We intentionally use the first field as the primary identity.

    If the first field is numeric, it is considered a candidate
    scheme record.

    This allows us to compare:

        RAW NUMERIC ROWS

    against:

        PARSED RECORDS

    during diagnostics.
    """

    fields = split_fields(
        line
    )

    if not fields:
        return False

    if not fields:
        return False

    return is_scheme_code(
        fields[0]
    )


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

    IMPORTANT:

    ISIN positions are preserved.

    We do NOT shift the second ISIN into the first ISIN
    field if the first one is missing/invalid.

    This prevents silent field corruption.
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

    if not is_scheme_code(
        fields[0]
    ):

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
    #
    # IMPORTANT:
    #
    # Keep the original positions.
    #
    # field 2 -> first ISIN
    # field 3 -> second ISIN
    #
    # Do not compact the list.
    #
    # Example:
    #
    # field 2 = ""
    # field 3 = "INF..."
    #
    # Result:
    #
    # isin_growth = None
    # isin_div_reinvestment = "INF..."
    #
    # This is safer than shifting values.
    # =========================================================================

    first_isin = None
    second_isin = None

    if len(fields) > 2:

        value = clean_optional(
            fields[2]
        )

        if value and is_isin(value):

            first_isin = value.upper()

    if len(fields) > 3:

        value = clean_optional(
            fields[3]
        )

        if value and is_isin(value):

            second_isin = value.upper()

    # =========================================================================
    # NAV DATE
    # =========================================================================

    actual_date = None

    # Normal AMFI structure places NAV date at the last field.
    if fields:

        actual_date = parse_nav_date(
            fields[-1]
        )

    # Fallback:
    #
    # Search from right to left.
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
    #
    # Only search fields before the NAV date.
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

        "isin_growth": first_isin,

        "isin_div_payout": None,

        "isin_div_reinvestment": second_isin,

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
# RAW REPORT DIAGNOSTICS
# =============================================================================

def analyze_raw_amfi_report(raw_data):
    """
    Analyze the raw AMFI response BEFORE parsing.

    This function does not modify the data.

    It helps us answer:

        How many numeric scheme rows exist?

        How many unique scheme codes exist?

        Are there duplicate scheme-code rows?

        How many lines are present?

    Returns:

        {
            "raw_lines": ...,
            "numeric_scheme_rows": ...,
            "unique_scheme_codes": ...,
            "duplicate_scheme_code_rows": ...,
        }
    """

    if raw_data is None:

        return {
            "raw_lines": 0,
            "numeric_scheme_rows": 0,
            "unique_scheme_codes": 0,
            "duplicate_scheme_code_rows": 0,
        }

    # Decode bytes if necessary.
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

            return {
                "raw_lines": 0,
                "numeric_scheme_rows": 0,
                "unique_scheme_codes": 0,
                "duplicate_scheme_code_rows": 0,
            }

        raw_data = decoded

    raw_data = str(
        raw_data
    )

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

    numeric_codes = []

    for raw_line in lines:

        line = raw_line.strip()

        if not line:
            continue

        fields = split_fields(
            line
        )

        if not fields:
            continue

        first_field = fields[0]

        if is_scheme_code(
            first_field
        ):

            numeric_codes.append(
                int(first_field)
            )

    unique_codes = set(
        numeric_codes
    )

    return {
        "raw_lines": len(lines),

        "numeric_scheme_rows": len(
            numeric_codes
        ),

        "unique_scheme_codes": len(
            unique_codes
        ),

        "duplicate_scheme_code_rows": (
            len(numeric_codes)
            - len(unique_codes)
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

        Raw AMFI
            ↓
        Scheme heading
            ↓
        Fund house heading
            ↓
        Scheme records
            ↓
        Normalized records
            ↓
        Duplicate protection
            ↓
        Final records

    IMPORTANT:

    This function still returns a LIST.

    Existing code therefore remains compatible:

        records = parse_amfi_report(raw)

    No database changes are performed here.
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

    raw_data = str(
        raw_data
    )

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

        if is_header_line(
            line
        ):

            continue

        # =====================================================================
        # SCHEME TYPE / CATEGORY HEADING
        # =====================================================================

        scheme_heading = parse_scheme_heading(
            line
        )

        if scheme_heading:

            current_scheme_type = (
                scheme_heading[
                    "scheme_type"
                ]
            )

            current_category = (
                scheme_heading[
                    "scheme_category"
                ]
            )

            continue

        # =====================================================================
        # FUND HOUSE
        # =====================================================================

        if looks_like_fund_house(
            line
        ):

            current_fund_house = line

            # IMPORTANT:
            #
            # Do not reset scheme_type/category.
            #
            # AMFI commonly uses:
            #
            #   Open Ended Schemes ( Debt Scheme - Dynamic Bond )
            #
            #   360 ONE Mutual Fund
            #
            #   122612;...
            #
            # Therefore the heading applies to the records below it.

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

        if looks_like_scheme_type(
            line
        ):

            current_scheme_type = line

            current_category = None

            continue

        # =====================================================================
        # LEGACY STANDALONE CATEGORY
        # =====================================================================

        if looks_like_category(
            line
        ):

            current_category = line

            continue

    # =========================================================================
    # DEDUPLICATION
    # =========================================================================
    #
    # The identity of a NAV record is:
    #
    #       scheme_code + nav_date
    #
    # Therefore:
    #
    # same scheme + different date
    #       -> KEEP
    #
    # same scheme + same date
    #       -> ONE RECORD
    #
    # We preserve the FIRST occurrence.
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

        if key not in unique_records:

            unique_records[key] = record

    # =========================================================================
    # FINAL RESULT
    # =========================================================================

    result = list(
        unique_records.values()
    )

    # =========================================================================
    # STABLE ORDERING
    # =========================================================================

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

def parser_summary(
    records,
    raw_data=None,
):
    """
    Return detailed diagnostic information about parsed AMFI data.

    This is intentionally separate from parse_amfi_report().

    Existing application code can continue using:

        records = parse_amfi_report(raw)

    Diagnostic code can additionally use:

        summary = parser_summary(
            records,
            raw,
        )

    This allows us to detect parser/source discrepancies without
    changing the existing application interface.
    """

    if records is None:

        records = []

    # =========================================================================
    # PARSED RECORD INFORMATION
    # =========================================================================

    parsed_scheme_codes = [
        record.get(
            "scheme_code"
        )
        for record in records
        if record.get(
            "scheme_code"
        ) is not None
    ]

    parsed_scheme_code_set = set(
        parsed_scheme_codes
    )

    parsed_record_keys = [
        (
            record.get(
                "scheme_code"
            ),
            record.get(
                "nav_date"
            ),
        )
        for record in records
        if (
            record.get(
                "scheme_code"
            ) is not None
            and record.get(
                "nav_date"
            ) is not None
        )
    ]

    parsed_record_key_set = set(
        parsed_record_keys
    )

    # =========================================================================
    # FUND HOUSES
    # =========================================================================

    fund_houses = {
        record.get(
            "fund_house_name"
        )
        for record in records
        if record.get(
            "fund_house_name"
        )
    }

    # =========================================================================
    # DATES
    # =========================================================================

    dates = {
        record.get(
            "nav_date"
        )
        for record in records
        if record.get(
            "nav_date"
        )
    }

    # =========================================================================
    # INVALID / MISSING REQUIRED DATA
    # =========================================================================

    invalid_scheme_code_records = 0

    invalid_scheme_name_records = 0

    invalid_nav_records = 0

    invalid_date_records = 0

    missing_fund_house_records = 0

    for record in records:

        if not is_scheme_code(
            record.get(
                "scheme_code"
            )
        ):

            invalid_scheme_code_records += 1

        if not clean_optional(
            record.get(
                "scheme_name"
            )
        ):

            invalid_scheme_name_records += 1

        if record.get(
            "nav"
        ) is None:

            invalid_nav_records += 1

        if record.get(
            "nav_date"
        ) is None:

            invalid_date_records += 1

        if not clean_optional(
            record.get(
                "fund_house_name"
            )
        ):

            missing_fund_house_records += 1

    # =========================================================================
    # RAW INFORMATION
    # =========================================================================

    raw_summary = {
        "raw_lines": 0,
        "raw_numeric_scheme_rows": 0,
        "raw_unique_scheme_codes": 0,
        "raw_duplicate_scheme_code_rows": 0,
    }

    if raw_data is not None:

        raw_info = analyze_raw_amfi_report(
            raw_data
        )

        raw_summary = {
            "raw_lines": raw_info[
                "raw_lines"
            ],

            "raw_numeric_scheme_rows": raw_info[
                "numeric_scheme_rows"
            ],

            "raw_unique_scheme_codes": raw_info[
                "unique_scheme_codes"
            ],

            "raw_duplicate_scheme_code_rows": raw_info[
                "duplicate_scheme_code_rows"
            ],
        }

    # =========================================================================
    # RAW/PARSER COMPARISON
    # =========================================================================

    raw_code_set = set()

    if raw_data is not None:

        # Decode raw data for comparison.
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

            raw_data_for_comparison = (
                decoded
                if decoded is not None
                else ""
            )

        else:

            raw_data_for_comparison = str(
                raw_data
            )

        raw_data_for_comparison = (
            raw_data_for_comparison
            .replace(
                "\r\n",
                "\n",
            )
            .replace(
                "\r",
                "\n",
            )
        )

        for raw_line in raw_data_for_comparison.split(
            "\n"
        ):

            line = raw_line.strip()

            if not line:

                continue

            fields = split_fields(
                line
            )

            if not fields:

                continue

            if is_scheme_code(
                fields[0]
            ):

                raw_code_set.add(
                    int(fields[0])
                )

    parsed_but_not_raw = (
        parsed_scheme_code_set
        - raw_code_set
    )

    raw_but_not_parsed = (
        raw_code_set
        - parsed_scheme_code_set
    )

    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================

    return {
        # ---------------------------------------------------------------------
        # Raw source
        # ---------------------------------------------------------------------

        "raw_lines": raw_summary[
            "raw_lines"
        ],

        "raw_numeric_scheme_rows": raw_summary[
            "raw_numeric_scheme_rows"
        ],

        "raw_unique_scheme_codes": raw_summary[
            "raw_unique_scheme_codes"
        ],

        "raw_duplicate_scheme_code_rows": raw_summary[
            "raw_duplicate_scheme_code_rows"
        ],

        # ---------------------------------------------------------------------
        # Parsed data
        # ---------------------------------------------------------------------

        "parsed_records": len(
            records
        ),

        "parsed_unique_scheme_codes": len(
            parsed_scheme_code_set
        ),

        "parsed_unique_scheme_date_records": len(
            parsed_record_key_set
        ),

        "fund_houses": len(
            fund_houses
        ),

        "dates": len(
            dates
        ),

        # ---------------------------------------------------------------------
        # Validation
        # ---------------------------------------------------------------------

        "invalid_scheme_code_records": (
            invalid_scheme_code_records
        ),

        "invalid_scheme_name_records": (
            invalid_scheme_name_records
        ),

        "invalid_nav_records": (
            invalid_nav_records
        ),

        "invalid_date_records": (
            invalid_date_records
        ),

        "missing_fund_house_records": (
            missing_fund_house_records
        ),

        # ---------------------------------------------------------------------
        # Raw vs parsed comparison
        # ---------------------------------------------------------------------

        "raw_but_not_parsed": len(
            raw_but_not_parsed
        ),

        "parsed_but_not_raw": len(
            parsed_but_not_raw
        ),

        # ---------------------------------------------------------------------
        # Overall validation flag
        # ---------------------------------------------------------------------

        "source_parser_consistent": (
            raw_summary[
                "raw_unique_scheme_codes"
            ]
            == len(
                parsed_scheme_code_set
            )
            and not raw_but_not_parsed
            and not parsed_but_not_raw
            and raw_summary[
                "raw_duplicate_scheme_code_rows"
            ] == 0
        ),
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
#         "24.2752"    -> Decimal("24.2752")
#         "1,234.56"   -> Decimal("1234.56")
#         ""           -> None
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
#     Validate AMFI scheme code.
#
#     AMFI scheme codes contain only digits.
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
#         NAV Date
#         Repurchase Price
#         Sale Price
#     """
#
#     normalized = clean_text(line).lower()
#
#     if not normalized:
#         return True
#
#     header_words = (
#         "scheme code",
#         "scheme name",
#         "isin",
#         "net asset value",
#         "nav date",
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
#     Examples:
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
#     return (
#         "mutual fund" in lower
#         or "mutual funds" in lower
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
#     Examples:
#
#         Open Ended Schemes ( Debt Scheme - Dynamic Bond )
#
#         Open Ended Schemes ( Equity Scheme - Small Cap Fund )
#
#         Open Ended Schemes ( Hybrid Scheme - Aggressive Hybrid Fund )
#
#         Close Ended Schemes ( Equity Scheme - ... )
#
#         Interval Fund ( Debt Scheme - ... )
#
#     Returns:
#
#         {
#             "scheme_type": "...",
#             "scheme_category": "..."
#         }
#
#     or:
#
#         None
#     """
#
#     line = clean_text(line)
#
#     if not line:
#         return None
#
#     # A scheme heading must be a standalone line.
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
#     # Combined heading
#     #
#     # Example:
#     #
#     # Open Ended Schemes ( Debt Scheme - Dynamic Bond )
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
#             scheme_type_lower = (
#                 scheme_type.lower()
#             )
#
#             valid_type = (
#                 "open ended" in scheme_type_lower
#                 or "close ended" in scheme_type_lower
#                 or "interval fund" in scheme_type_lower
#             )
#
#             if valid_type:
#
#                 return {
#                     "scheme_type": scheme_type,
#                     "scheme_category": scheme_category,
#                 }
#
#     # -------------------------------------------------------------------------
#     # Standalone scheme type
#     #
#     # Example:
#     #
#     # Open Ended Schemes
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
#     Compatibility helper for standalone scheme types.
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
#     Compatibility helper for standalone scheme categories.
#
#     Examples:
#
#         Equity Scheme - Large Cap Fund
#         Debt Scheme - Dynamic Bond
#         Hybrid Scheme - Balanced Hybrid Fund
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
#     lower = line.lower()
#
#     category_patterns = (
#         "equity scheme",
#         "debt scheme",
#         "hybrid scheme",
#         "solution oriented scheme",
#         "other scheme",
#         "index fund",
#         "etf",
#         "fund of funds",
#         "fund of fund",
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
#         3 = Second ISIN
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
#         value = clean_optional(
#             field
#         )
#
#         if value and is_isin(value):
#
#             isin_values.append(
#                 value.upper()
#             )
#
#     # -------------------------------------------------------------------------
#     # AMFI convention used by this project:
#     #
#     # First ISIN  -> isin_growth
#     # Second ISIN -> isin_div_reinvestment
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
#     # Normal AMFI structure places NAV date at the last field.
#     if fields:
#
#         actual_date = parse_nav_date(
#             fields[-1]
#         )
#
#     # Fallback: search from right to left.
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
#     # Use supplied default date if necessary.
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
#     # Normal AMFI NAV position.
#     if len(fields) > 4:
#
#         nav = clean_decimal(
#             fields[4]
#         )
#
#     # Fallback NAV search.
#     if nav is None:
#
#         date_position = len(fields) - 1
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
#     # FINAL NORMALIZED RECORD
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
#         "sale_price": (
#             sale_price
#         ),
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
#     Processing flow:
#
#         Scheme heading
#                 ↓
#         Fund house heading
#                 ↓
#         Scheme records
#                 ↓
#         Normalized records
#
#     Important:
#
#         The scheme type/category is preserved when the
#         fund-house heading appears AFTER the scheme heading.
#
#     Example AMFI data:
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
#         scheme_type:
#             Open Ended Schemes
#
#         scheme_category:
#             Debt Scheme - Dynamic Bond
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
#     current_date = default_nav_date
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
#         # FUND HOUSE
#         # =====================================================================
#
#         if looks_like_fund_house(line):
#
#             current_fund_house = line
#
#             # IMPORTANT:
#             #
#             # DO NOT RESET current_scheme_type
#             # DO NOT RESET current_category
#             #
#             # AMFI commonly gives:
#             #
#             #   Open Ended Schemes ( Debt Scheme - Dynamic Bond )
#             #
#             #   360 ONE Mutual Fund
#             #
#             #   122612;...
#             #
#             # Therefore the scheme heading belongs to the
#             # fund-house section that follows it.
#             #
#             # This was the main reason your values became NULL.
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
#         # LEGACY STANDALONE SCHEME TYPE
#         # =====================================================================
#
#         if looks_like_scheme_type(line):
#
#             current_scheme_type = line
#
#             current_category = None
#
#             continue
#
#         # =====================================================================
#         # LEGACY STANDALONE CATEGORY
#         # =====================================================================
#
#         if looks_like_category(line):
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
#         # Keep the first occurrence.
#         if key not in unique_records:
#
#             unique_records[key] = record
#
#     # =========================================================================
#     # FINAL RESULT
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