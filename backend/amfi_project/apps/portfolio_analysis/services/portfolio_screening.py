from decimal import Decimal, InvalidOperation


# ============================================================
# PORTFOLIO SCREENING ENGINE
# ============================================================
#
# Purpose:
#
# Convert Portfolio Analysis results into structured screening
# findings.
#
# Current screening areas:
#
# 1. AMC concentration
# 2. Scheme concentration
# 3. Category concentration
# 4. Asset-type concentration
# 5. Unmatched AMFI holdings
# 6. Missing current-value / NAV data
#
# IMPORTANT:
#
# This module DOES NOT:
#
# - recommend buying
# - recommend selling
# - recommend switching
# - declare a fund good or bad
# - compare funds against benchmarks
# - generate final suggestions
# - modify portfolio data
# - modify CAS data
# - modify AMFI data
#
# Future flow:
#
#     Portfolio Analysis
#             |
#             v
#         Screening
#             |
#             v
#        Benchmarking
#             |
#             v
#         Suggestions
#
# ============================================================


# ============================================================
# SCREENING CONFIGURATION
# ============================================================
#
# These are application-level screening thresholds.
#
# They are NOT regulatory limits.
#
# They can be changed later without changing the screening
# engine logic.
#
# ============================================================

DEFAULT_SCREENING_THRESHOLDS = {

    # If one AMC represents >= 50% of current portfolio value.
    "amc_concentration": Decimal("50"),

    # If one scheme represents >= 50% of current portfolio value.
    "scheme_concentration": Decimal("50"),

    # If one category represents >= 75% of current portfolio value.
    "category_concentration": Decimal("75"),

    # If one asset type represents >= 75% of current portfolio value.
    "asset_type_concentration": Decimal("75"),
}


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================


def screen_portfolio(
    analysis_result,
    thresholds=None,
):
    """
    Screen an already-analyzed portfolio.

    Expected input:

        analysis_result = analyze_portfolio(holdings)

    Example:

        screening_result = screen_portfolio(
            analysis_result
        )

    Optional custom thresholds:

        {
            "amc_concentration": Decimal("50"),
            "scheme_concentration": Decimal("50"),
            "category_concentration": Decimal("75"),
            "asset_type_concentration": Decimal("75"),
        }

    Returns:

        {
            "screening_status": "...",

            "summary": {
                "total_rules_checked": ...,
                "rules_triggered": ...,
                "concentration_findings": ...,
                "data_quality_findings": ...,
            },

            "findings": [...]
        }

    This function is READ-ONLY.
    """

    if not isinstance(
        analysis_result,
        dict,
    ):
        raise ValueError(
            "analysis_result must be a dictionary."
        )

    thresholds = build_thresholds(
        thresholds
    )

    findings = []

    # ========================================================
    # ANALYSIS COVERAGE
    # ========================================================

    analysis_coverage = analysis_result.get(
        "analysis_coverage"
    )

    if not isinstance(
        analysis_coverage,
        dict,
    ):

        analysis_coverage = {}

    # ========================================================
    # RULE 1
    # AMC CONCENTRATION
    # ========================================================

    findings.extend(
        screen_concentration_distribution(
            distribution=analysis_result.get(
                "amc_allocation"
            ),
            threshold=thresholds[
                "amc_concentration"
            ],
            rule_code="AMC_CONCENTRATION",
            concentration_type="AMC",
        )
    )

    # ========================================================
    # RULE 2
    # SCHEME CONCENTRATION
    # ========================================================

    concentration = analysis_result.get(
        "concentration"
    )

    if not isinstance(
        concentration,
        dict,
    ):

        concentration = {}

    scheme_concentration = concentration.get(
        "scheme"
    )

    if not isinstance(
        scheme_concentration,
        dict,
    ):

        scheme_concentration = {}

    findings.extend(
        screen_concentration_distribution(
            distribution=scheme_concentration.get(
                "distribution"
            ),
            threshold=thresholds[
                "scheme_concentration"
            ],
            rule_code="SCHEME_CONCENTRATION",
            concentration_type="SCHEME",
        )
    )

    # ========================================================
    # RULE 3
    # CATEGORY CONCENTRATION
    # ========================================================

    category_concentration = concentration.get(
        "category"
    )

    if not isinstance(
        category_concentration,
        dict,
    ):

        category_concentration = {}

    findings.extend(
        screen_concentration_distribution(
            distribution=category_concentration.get(
                "distribution"
            ),
            threshold=thresholds[
                "category_concentration"
            ],
            rule_code="CATEGORY_CONCENTRATION",
            concentration_type="CATEGORY",
        )
    )

    # ========================================================
    # RULE 4
    # ASSET TYPE CONCENTRATION
    # ========================================================

    asset_type_concentration = concentration.get(
        "asset_type"
    )

    if not isinstance(
        asset_type_concentration,
        dict,
    ):

        asset_type_concentration = {}

    findings.extend(
        screen_concentration_distribution(
            distribution=asset_type_concentration.get(
                "distribution"
            ),
            threshold=thresholds[
                "asset_type_concentration"
            ],
            rule_code="ASSET_TYPE_CONCENTRATION",
            concentration_type="ASSET_TYPE",
        )
    )

    # ========================================================
    # RULE 5
    # UNMATCHED AMFI HOLDINGS
    # ========================================================

    findings.extend(
        screen_unmatched_holdings(
            analysis_result=analysis_result,
            analysis_coverage=analysis_coverage,
        )
    )

    # ========================================================
    # RULE 6
    # MISSING CURRENT VALUE
    # ========================================================

    findings.extend(
        screen_missing_current_value(
            analysis_result=analysis_result,
            analysis_coverage=analysis_coverage,
        )
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    total_rules_checked = 6

    concentration_findings = sum(
        1
        for finding in findings
        if finding.get("finding_type")
        == "CONCENTRATION"
    )

    data_quality_findings = sum(
        1
        for finding in findings
        if finding.get("finding_type")
        == "DATA_QUALITY"
    )

    rules_triggered = len(
        findings
    )

    # ========================================================
    # SCREENING STATUS
    # ========================================================

    if not analysis_result.get(
        "holdings"
    ):

        screening_status = (
            "NO_DATA"
        )

    elif not findings:

        screening_status = (
            "NO_FINDINGS"
        )

    elif data_quality_findings > 0:

        screening_status = (
            "FINDINGS_WITH_DATA_QUALITY"
        )

    else:

        screening_status = (
            "FINDINGS_PRESENT"
        )

    # ========================================================
    # FINAL RESULT
    # ========================================================

    return {

        "screening_status": (
            screening_status
        ),

        "summary": {

            "total_rules_checked": (
                total_rules_checked
            ),

            "rules_triggered": (
                rules_triggered
            ),

            "concentration_findings": (
                concentration_findings
            ),

            "data_quality_findings": (
                data_quality_findings
            ),
        },

        "thresholds": {
            key: decimal_to_string(value)
            for key, value in thresholds.items()
        },

        "findings": findings,
    }


# ============================================================
# THRESHOLD BUILDING
# ============================================================


def build_thresholds(
    thresholds=None,
):
    """
    Build the final screening threshold configuration.

    Custom values override defaults.
    """

    result = dict(
        DEFAULT_SCREENING_THRESHOLDS
    )

    if thresholds is None:

        return result

    if not isinstance(
        thresholds,
        dict,
    ):

        raise ValueError(
            "thresholds must be a dictionary."
        )

    for key, value in thresholds.items():

        if key not in result:

            continue

        decimal_value = to_decimal(
            value
        )

        if decimal_value is None:

            raise ValueError(
                f"Invalid threshold for '{key}'."
            )

        if decimal_value < Decimal("0"):

            raise ValueError(
                f"Threshold for '{key}' "
                f"cannot be negative."
            )

        result[key] = decimal_value

    return result


# ============================================================
# CONCENTRATION SCREENING
# ============================================================


def screen_concentration_distribution(
    distribution,
    threshold,
    rule_code,
    concentration_type,
):
    """
    Screen an allocation/concentration distribution.

    Example:

        [
            {
                "name": "ABC Mutual Fund",
                "value": "90000",
                "percentage": "90"
            }
        ]

    If percentage >= threshold, a finding is generated.

    This does NOT say the concentration is bad.

    It only identifies that the configured screening condition
    was triggered.
    """

    if not isinstance(
        distribution,
        list,
    ):

        return []

    findings = []

    for item in distribution:

        if not isinstance(
            item,
            dict,
        ):

            continue

        name = clean_string(
            item.get(
                "name"
            )
        )

        percentage = to_decimal(
            item.get(
                "percentage"
            )
        )

        value = to_decimal(
            item.get(
                "value"
            )
        )

        if not name:

            continue

        if percentage is None:

            continue

        if percentage < threshold:

            continue

        findings.append(
            {

                "rule_code": (
                    rule_code
                ),

                "finding_type": (
                    "CONCENTRATION"
                ),

                "status": (
                    "TRIGGERED"
                ),

                "severity": (
                    get_concentration_severity(
                        percentage
                    )
                ),

                "concentration_type": (
                    concentration_type
                ),

                "name": (
                    name
                ),

                "actual_percentage": (
                    decimal_to_string(
                        percentage
                    )
                ),

                "threshold_percentage": (
                    decimal_to_string(
                        threshold
                    )
                ),

                "current_value": (
                    decimal_to_string(
                        value
                    )
                    if value is not None
                    else None
                ),

                "message": (
                    build_concentration_message(
                        concentration_type=(
                            concentration_type
                        ),
                        name=name,
                        percentage=percentage,
                        threshold=threshold,
                    )
                ),
            }
        )

    return findings


# ============================================================
# CONCENTRATION SEVERITY
# ============================================================


def get_concentration_severity(
    percentage,
):
    """
    Assign a descriptive screening severity.

    This is a screening classification only.

    It is NOT a financial risk rating.
    """

    percentage = to_decimal(
        percentage
    )

    if percentage is None:

        return "INFO"

    if percentage >= Decimal("90"):

        return "HIGH"

    if percentage >= Decimal("75"):

        return "MEDIUM"

    return "LOW"


# ============================================================
# CONCENTRATION MESSAGE
# ============================================================


def build_concentration_message(
    concentration_type,
    name,
    percentage,
    threshold,
):
    """
    Build a neutral screening message.

    No buy/sell recommendation is made.
    """

    labels = {

        "AMC": "AMC",

        "SCHEME": "mutual fund scheme",

        "CATEGORY": "scheme category",

        "ASSET_TYPE": "asset type",
    }

    label = labels.get(
        concentration_type,
        concentration_type,
    )

    return (
        f"{label} '{name}' represents "
        f"{decimal_to_string(percentage)}% "
        f"of the current portfolio value, "
        f"which meets or exceeds the configured "
        f"screening threshold of "
        f"{decimal_to_string(threshold)}%."
    )


# ============================================================
# UNMATCHED HOLDING SCREENING
# ============================================================


def screen_unmatched_holdings(
    analysis_result,
    analysis_coverage,
):
    """
    Identify holdings that were not successfully matched
    against AMFI data.

    This is a DATA QUALITY finding.

    It does not imply that the mutual fund itself is bad.
    """

    holdings = analysis_result.get(
        "holdings"
    )

    if not isinstance(
        holdings,
        list,
    ):

        return []

    findings = []

    for holding in holdings:

        if not isinstance(
            holding,
            dict,
        ):

            continue

        # ----------------------------------------------------
        # Determine whether the holding was matched.
        #
        # The analyzer output does not currently preserve
        # the complete amfi_match object, so use the overall
        # analysis coverage plus the available holding data.
        #
        # We primarily detect unmatched holdings through the
        # absence of a usable scheme category/AMC combination.
        # ----------------------------------------------------

        amfi_code = clean_string(
            holding.get(
                "amfi_code"
            )
        )

        amc = clean_string(
            holding.get(
                "amc"
            )
        )

        scheme_category = clean_string(
            holding.get(
                "scheme_category"
            )
        )

        scheme_name = clean_string(
            holding.get(
                "scheme_name"
            )
        )

        # A holding with no meaningful AMFI-derived information
        # is treated as potentially unmatched.
        #
        # We intentionally do not mark every incomplete holding
        # as unmatched when the analyzer cannot prove it.

        if (
            not amc
            and not scheme_category
            and not amfi_code
        ):

            findings.append(
                build_data_quality_finding(
                    rule_code=(
                        "AMFI_MATCH_MISSING"
                    ),
                    holding=holding,
                    message=(
                        "The holding does not contain "
                        "sufficient AMFI identification "
                        "information for complete screening."
                    ),
                )
            )

    return findings


# ============================================================
# MISSING CURRENT VALUE SCREENING
# ============================================================


def screen_missing_current_value(
    analysis_result,
    analysis_coverage,
):
    """
    Identify holdings where current value could not be
    calculated because current NAV enrichment was unavailable.
    """

    holdings = analysis_result.get(
        "holdings"
    )

    if not isinstance(
        holdings,
        list,
    ):

        return []

    findings = []

    for holding in holdings:

        if not isinstance(
            holding,
            dict,
        ):

            continue

        current_value_available = (
            holding.get(
                "current_value_available"
            )
        )

        if current_value_available is True:

            continue

        findings.append(
            build_data_quality_finding(
                rule_code=(
                    "CURRENT_VALUE_UNAVAILABLE"
                ),
                holding=holding,
                message=(
                    "Current portfolio value is "
                    "not available for this holding, "
                    "so current-value-based screening "
                    "is incomplete for this holding."
                ),
            )
        )

    return findings


# ============================================================
# DATA QUALITY FINDING
# ============================================================


def build_data_quality_finding(
    rule_code,
    holding,
    message,
):
    """
    Build a standard data-quality finding.
    """

    return {

        "rule_code": (
            rule_code
        ),

        "finding_type": (
            "DATA_QUALITY"
        ),

        "status": (
            "TRIGGERED"
        ),

        "severity": (
            "INFO"
        ),

        "holding_index": (
            holding.get(
                "holding_index"
            )
        ),

        "amfi_code": (
            holding.get(
                "amfi_code"
            )
        ),

        "isin": (
            holding.get(
                "isin"
            )
        ),

        "scheme_name": (
            holding.get(
                "scheme_name"
            )
        ),

        "message": (
            message
        ),
    }


# ============================================================
# DECIMAL CONVERSION
# ============================================================


def to_decimal(
    value,
):
    """
    Safely convert a value to Decimal.

    Returns None for invalid values.
    """

    if value in (
        None,
        "",
    ):

        return None

    if isinstance(
        value,
        Decimal,
    ):

        return value

    try:

        return Decimal(
            str(value)
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):

        return None


# ============================================================
# DECIMAL OUTPUT
# ============================================================


def decimal_to_string(
    value,
):
    """
    Convert Decimal to a string while preserving precision.
    """

    if value is None:

        return None

    value = to_decimal(
        value
    )

    if value is None:

        return None

    return format(
        value,
        "f",
    )


# ============================================================
# STRING CLEANING
# ============================================================


def clean_string(
    value,
):
    """
    Convert a value to a trimmed string.

    Empty values become None.
    """

    if value is None:

        return None

    value = str(
        value
    ).strip()

    if not value:

        return None

    return value