from collections import defaultdict
from decimal import Decimal, InvalidOperation


# ============================================================
# PORTFOLIO ANALYSIS ENGINE
# ============================================================
#
# Current phases:
#
# Part 1:
#     Portfolio totals
#     Gain / loss
#
# Part 2:
#     Asset allocation
#     AMC allocation
#     Category allocation
#
# Part 3:
#     AMC concentration
#     Scheme concentration
#     Category concentration
#     Asset-type concentration
#
# Part 4:
#     Portfolio quality
#     AMFI match coverage
#     Current-value coverage
#     Invested-value coverage
#
# IMPORTANT:
#
# This file performs ANALYSIS only.
#
# It does NOT:
#     - make buy/sell recommendations
#     - decide whether a portfolio is good/bad
#     - apply screening thresholds
#     - compare against benchmarks
#     - generate suggestions
#     - modify Portfolio
#     - modify CAS data
#     - modify AMFI data
#     - modify NAV history
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
# MAIN PORTFOLIO ANALYSIS
# ============================================================


def analyze_portfolio(holdings):
    """
    Analyze an enriched mutual-fund portfolio.

    Expected input:

        [
            {
                "amfi_code": "149068",
                "isin": "INF277KA1190",
                "scheme_name": "Tata Business Cycle Fund",
                "amc": "Tata Mutual Fund",
                "asset_type": "Equity",
                "folio_number": "TEST001",
                "units": "500",
                "invested_value": "9000.00",

                "amfi_match": {
                    "matched": True,
                    "scheme_code": "149068",
                    "fund_house": "Tata Mutual Fund",
                    "scheme_name": "...",
                    "scheme_category": "...",
                },

                "nav_enrichment": {
                    "available": True,
                    "latest_nav": "19.2089",
                    "latest_nav_date": "18-08-2026",
                    "latest_value": "9604.4500",
                },
            }
        ]

    Returns:

        {
            "totals": {...},

            "asset_allocation": [...],

            "amc_allocation": [...],

            "category_allocation": [...],

            "concentration": {...},

            "analysis_coverage": {...},

            "holdings": [...]
        }

    This function is READ-ONLY.
    """

    if not isinstance(
        holdings,
        list,
    ):
        raise ValueError(
            "holdings must be a list."
        )

    total_holdings = len(
        holdings
    )

    total_invested_value = Decimal(
        "0"
    )

    total_current_value = Decimal(
        "0"
    )

    holdings_with_current_value = 0

    holdings_without_current_value = 0

    analyzed_holdings = []

    # ========================================================
    # ALLOCATION DATA
    # ========================================================

    asset_allocation = defaultdict(
        lambda: Decimal("0")
    )

    amc_allocation = defaultdict(
        lambda: Decimal("0")
    )

    category_allocation = defaultdict(
        lambda: Decimal("0")
    )

    # ========================================================
    # CONCENTRATION DATA
    # ========================================================

    scheme_concentration = defaultdict(
        lambda: Decimal("0")
    )

    # ========================================================
    # PROCESS EACH HOLDING
    # ========================================================

    for index, holding in enumerate(
        holdings,
        start=1,
    ):

        # ----------------------------------------------------
        # INVALID HOLDING
        # ----------------------------------------------------

        if not isinstance(
            holding,
            dict,
        ):

            analyzed_holdings.append(
                {
                    "holding_index": index,
                    "valid": False,
                    "reason": "INVALID_HOLDING",
                }
            )

            holdings_without_current_value += 1

            continue

        # ----------------------------------------------------
        # INVESTED VALUE
        # ----------------------------------------------------

        invested_value = to_decimal(
            holding.get(
                "invested_value"
            )
        )

        if invested_value is None:

            invested_value = Decimal(
                "0"
            )

        total_invested_value += (
            invested_value
        )

        # ----------------------------------------------------
        # CURRENT / LATEST VALUE
        # ----------------------------------------------------

        nav_enrichment = holding.get(
            "nav_enrichment"
        )

        if not isinstance(
            nav_enrichment,
            dict,
        ):

            nav_enrichment = {}

        latest_value = None

        if nav_enrichment.get(
            "available"
        ):

            latest_value = to_decimal(
                nav_enrichment.get(
                    "latest_value"
                )
            )

        current_value_available = (
            latest_value is not None
        )

        # ====================================================
        # CURRENT VALUE AVAILABLE
        # ====================================================

        if current_value_available:

            total_current_value += (
                latest_value
            )

            holdings_with_current_value += 1

            # ------------------------------------------------
            # PART 2
            # ASSET ALLOCATION
            # ------------------------------------------------

            asset_type = get_asset_type(
                holding
            )

            if asset_type:

                asset_allocation[
                    asset_type
                ] += latest_value

            # ------------------------------------------------
            # PART 2
            # AMC ALLOCATION
            # ------------------------------------------------

            amc = get_amc(
                holding
            )

            if amc:

                amc_allocation[
                    amc
                ] += latest_value

            # ------------------------------------------------
            # PART 2
            # CATEGORY ALLOCATION
            # ------------------------------------------------

            category = get_scheme_category(
                holding
            )

            if category:

                category_allocation[
                    category
                ] += latest_value

            # ------------------------------------------------
            # PART 3
            # SCHEME CONCENTRATION
            # ------------------------------------------------

            scheme_name = get_scheme_identifier(
                holding
            )

            if scheme_name:

                scheme_concentration[
                    scheme_name
                ] += latest_value

        # ====================================================
        # CURRENT VALUE NOT AVAILABLE
        # ====================================================

        else:

            holdings_without_current_value += 1

        # ====================================================
        # INDIVIDUAL HOLDING ANALYSIS
        # ====================================================

        analyzed_holdings.append(
            build_holding_analysis(
                holding=holding,
                holding_index=index,
                invested_value=invested_value,
                latest_value=latest_value,
            )
        )

    # ========================================================
    # PART 1
    # PORTFOLIO TOTALS
    # ========================================================

    total_gain = (
        total_current_value
        - total_invested_value
    )

    total_gain_percentage = (
        calculate_percentage(
            numerator=total_gain,
            denominator=total_invested_value,
        )
    )

    # ========================================================
    # PART 2
    # ALLOCATION RESULTS
    # ========================================================

    asset_allocation_result = (
        build_allocation_result(
            allocation=asset_allocation,
            total_current_value=(
                total_current_value
            ),
        )
    )

    amc_allocation_result = (
        build_allocation_result(
            allocation=amc_allocation,
            total_current_value=(
                total_current_value
            ),
        )
    )

    category_allocation_result = (
        build_allocation_result(
            allocation=category_allocation,
            total_current_value=(
                total_current_value
            ),
        )
    )

    # ========================================================
    # PART 3
    # CONCENTRATION ANALYSIS
    # ========================================================

    concentration_analysis = (
        build_concentration_analysis(
            total_current_value=(
                total_current_value
            ),
            amc_allocation=(
                amc_allocation
            ),
            scheme_concentration=(
                scheme_concentration
            ),
            category_allocation=(
                category_allocation
            ),
            asset_allocation=(
                asset_allocation
            ),
        )
    )

    # ========================================================
    # PART 4
    # ANALYSIS COVERAGE
    # ========================================================

    analysis_coverage = (
        build_analysis_coverage(
            holdings=holdings,
            total_holdings=total_holdings,
            total_invested_value=(
                total_invested_value
            ),
            total_current_value=(
                total_current_value
            ),
        )
    )

    # ========================================================
    # FINAL RESULT
    # ========================================================

    return {

        # ----------------------------------------------------
        # PART 1
        # ----------------------------------------------------

        "totals": {

            "total_holdings": (
                total_holdings
            ),

            "total_invested_value": (
                decimal_to_string(
                    total_invested_value
                )
            ),

            "total_current_value": (
                decimal_to_string(
                    total_current_value
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

            "holdings_with_current_value": (
                holdings_with_current_value
            ),

            "holdings_without_current_value": (
                holdings_without_current_value
            ),
        },

        # ----------------------------------------------------
        # PART 2
        # ----------------------------------------------------

        "asset_allocation": (
            asset_allocation_result
        ),

        "amc_allocation": (
            amc_allocation_result
        ),

        "category_allocation": (
            category_allocation_result
        ),

        # ----------------------------------------------------
        # PART 3
        # ----------------------------------------------------

        "concentration": (
            concentration_analysis
        ),

        # ----------------------------------------------------
        # PART 4
        # ----------------------------------------------------

        "analysis_coverage": (
            analysis_coverage
        ),

        # ----------------------------------------------------
        # INDIVIDUAL HOLDINGS
        # ----------------------------------------------------

        "holdings": (
            analyzed_holdings
        ),
    }


# ============================================================
# PART 3
# CONCENTRATION ANALYSIS
# ============================================================


def build_concentration_analysis(
    total_current_value,
    amc_allocation,
    scheme_concentration,
    category_allocation,
    asset_allocation,
):
    """
    Build raw portfolio concentration information.

    This function does NOT decide whether concentration is:

        - good
        - bad
        - risky
        - excessive
        - acceptable

    It only reports the actual portfolio distribution.

    Screening thresholds will be implemented later.
    """

    return {

        # ====================================================
        # AMC CONCENTRATION
        # ====================================================

        "amc": {

            "largest": (
                get_largest_concentration(
                    allocation=(
                        amc_allocation
                    ),
                    total_current_value=(
                        total_current_value
                    ),
                )
            ),

            "distribution": (
                build_allocation_result(
                    allocation=(
                        amc_allocation
                    ),
                    total_current_value=(
                        total_current_value
                    ),
                )
            ),
        },

        # ====================================================
        # SCHEME CONCENTRATION
        # ====================================================

        "scheme": {

            "largest": (
                get_largest_concentration(
                    allocation=(
                        scheme_concentration
                    ),
                    total_current_value=(
                        total_current_value
                    ),
                )
            ),

            "distribution": (
                build_allocation_result(
                    allocation=(
                        scheme_concentration
                    ),
                    total_current_value=(
                        total_current_value
                    ),
                )
            ),
        },

        # ====================================================
        # CATEGORY CONCENTRATION
        # ====================================================

        "category": {

            "largest": (
                get_largest_concentration(
                    allocation=(
                        category_allocation
                    ),
                    total_current_value=(
                        total_current_value
                    ),
                )
            ),

            "distribution": (
                build_allocation_result(
                    allocation=(
                        category_allocation
                    ),
                    total_current_value=(
                        total_current_value
                    ),
                )
            ),
        },

        # ====================================================
        # ASSET TYPE CONCENTRATION
        # ====================================================

        "asset_type": {

            "largest": (
                get_largest_concentration(
                    allocation=(
                        asset_allocation
                    ),
                    total_current_value=(
                        total_current_value
                    ),
                )
            ),

            "distribution": (
                build_allocation_result(
                    allocation=(
                        asset_allocation
                    ),
                    total_current_value=(
                        total_current_value
                    ),
                )
            ),
        },
    }


# ============================================================
# LARGEST CONCENTRATION
# ============================================================


def get_largest_concentration(
    allocation,
    total_current_value,
):
    """
    Return the largest concentration bucket.

    Example:

        {
            "name": "Aditya Birla Sun Life Mutual Fund",
            "value": "97158.00",
            "percentage": "91.0039..."
        }

    Returns None when no valid current-value data exists.
    """

    if not allocation:

        return None

    largest_name = None

    largest_value = Decimal(
        "0"
    )

    for name, value in allocation.items():

        if value > largest_value:

            largest_name = name

            largest_value = value

    if largest_name is None:

        return None

    percentage = calculate_percentage(
        numerator=largest_value,
        denominator=total_current_value,
    )

    return {

        "name": (
            largest_name
        ),

        "value": (
            decimal_to_string(
                largest_value
            )
        ),

        "percentage": (
            decimal_to_string(
                percentage
            )
        ),
    }


# ============================================================
# PART 4
# PORTFOLIO QUALITY & ANALYSIS COVERAGE
# ============================================================


def build_analysis_coverage(
    holdings,
    total_holdings,
    total_invested_value,
    total_current_value,
):
    """
    Calculate data-quality and analysis coverage metrics.

    This function tells us how much of the portfolio was
    successfully understood and valued.

    It does NOT decide whether the portfolio is good or bad.

    Coverage types:

        1. Holding-count coverage
        2. AMFI matching coverage
        3. Current-value coverage
        4. Invested-value coverage

    This information will later be consumed by:

        Screening
        Benchmarking
        Suggestions
    """

    matched_holdings = 0

    unmatched_holdings = 0

    current_value_holdings = 0

    missing_current_value_holdings = 0

    matched_invested_value = Decimal(
        "0"
    )

    current_value_available_invested_value = Decimal(
        "0"
    )

    unmatched_invested_value = Decimal(
        "0"
    )

    missing_current_value_invested_value = Decimal(
        "0"
    )

    # ========================================================
    # PROCESS EACH HOLDING
    # ========================================================

    for holding in holdings:

        if not isinstance(
            holding,
            dict,
        ):
            continue

        # ----------------------------------------------------
        # INVESTED VALUE
        # ----------------------------------------------------

        invested_value = to_decimal(
            holding.get(
                "invested_value"
            )
        )

        if invested_value is None:

            invested_value = Decimal(
                "0"
            )

        # ----------------------------------------------------
        # AMFI MATCH
        # ----------------------------------------------------

        amfi_match = holding.get(
            "amfi_match"
        )

        is_matched = (
            isinstance(
                amfi_match,
                dict,
            )
            and amfi_match.get(
                "matched"
            ) is True
        )

        if is_matched:

            matched_holdings += 1

            matched_invested_value += (
                invested_value
            )

        else:

            unmatched_holdings += 1

            unmatched_invested_value += (
                invested_value
            )

        # ----------------------------------------------------
        # CURRENT VALUE
        # ----------------------------------------------------

        nav_enrichment = holding.get(
            "nav_enrichment"
        )

        current_value_available = (
            isinstance(
                nav_enrichment,
                dict,
            )
            and nav_enrichment.get(
                "available"
            ) is True
            and to_decimal(
                nav_enrichment.get(
                    "latest_value"
                )
            ) is not None
        )

        if current_value_available:

            current_value_holdings += 1

            current_value_available_invested_value += (
                invested_value
            )

        else:

            missing_current_value_holdings += 1

            missing_current_value_invested_value += (
                invested_value
            )

    # ========================================================
    # HOLDING COUNT COVERAGE
    # ========================================================

    matched_holding_percentage = (
        calculate_percentage(
            numerator=matched_holdings,
            denominator=total_holdings,
        )
    )

    unmatched_holding_percentage = (
        calculate_percentage(
            numerator=unmatched_holdings,
            denominator=total_holdings,
        )
    )

    current_value_holding_percentage = (
        calculate_percentage(
            numerator=current_value_holdings,
            denominator=total_holdings,
        )
    )

    missing_current_value_holding_percentage = (
        calculate_percentage(
            numerator=(
                missing_current_value_holdings
            ),
            denominator=total_holdings,
        )
    )

    # ========================================================
    # INVESTED VALUE MATCH COVERAGE
    # ========================================================

    matched_invested_value_percentage = (
        calculate_percentage(
            numerator=matched_invested_value,
            denominator=total_invested_value,
        )
    )

    unmatched_invested_value_percentage = (
        calculate_percentage(
            numerator=unmatched_invested_value,
            denominator=total_invested_value,
        )
    )

    # ========================================================
    # CURRENT VALUE INVESTED COVERAGE
    # ========================================================

    current_value_invested_value_percentage = (
        calculate_percentage(
            numerator=(
                current_value_available_invested_value
            ),
            denominator=total_invested_value,
        )
    )

    missing_current_value_invested_value_percentage = (
        calculate_percentage(
            numerator=(
                missing_current_value_invested_value
            ),
            denominator=total_invested_value,
        )
    )

    # ========================================================
    # CURRENT VALUE VS INVESTED VALUE
    #
    # Informational only.
    #
    # Example:
    #
    # Current value = 106762.45
    # Invested value = 109000
    #
    # Current / Invested * 100
    #
    # = 97.947...
    #
    # This is NOT a coverage percentage.
    # ========================================================

    current_value_vs_invested_percentage = (
        calculate_percentage(
            numerator=total_current_value,
            denominator=total_invested_value,
        )
    )

    # ========================================================
    # ANALYSIS STATUS
    # ========================================================

    if total_holdings == 0:

        analysis_status = (
            "NO_HOLDINGS"
        )

    elif matched_holdings == 0:

        analysis_status = (
            "INSUFFICIENT_MATCHED_DATA"
        )

    elif current_value_holdings == 0:

        analysis_status = (
            "NO_CURRENT_VALUE_DATA"
        )

    elif (
        matched_holdings == total_holdings
        and current_value_holdings == total_holdings
    ):

        analysis_status = (
            "COMPLETE"
        )

    else:

        analysis_status = (
            "PARTIAL"
        )

    # ========================================================
    # FINAL COVERAGE RESULT
    # ========================================================

    return {

        "analysis_status": (
            analysis_status
        ),

        "total_holdings": (
            total_holdings
        ),

        # ====================================================
        # AMFI MATCH COVERAGE
        # ====================================================

        "matched_holdings": (
            matched_holdings
        ),

        "unmatched_holdings": (
            unmatched_holdings
        ),

        "matched_holding_percentage": (
            decimal_to_string(
                matched_holding_percentage
            )
        ),

        "unmatched_holding_percentage": (
            decimal_to_string(
                unmatched_holding_percentage
            )
        ),

        # ====================================================
        # CURRENT VALUE HOLDING COVERAGE
        # ====================================================

        "current_value_holdings": (
            current_value_holdings
        ),

        "missing_current_value_holdings": (
            missing_current_value_holdings
        ),

        "current_value_holding_percentage": (
            decimal_to_string(
                current_value_holding_percentage
            )
        ),

        "missing_current_value_holding_percentage": (
            decimal_to_string(
                missing_current_value_holding_percentage
            )
        ),

        # ====================================================
        # MATCHED INVESTED VALUE
        # ====================================================

        "matched_invested_value": (
            decimal_to_string(
                matched_invested_value
            )
        ),

        "matched_invested_value_percentage": (
            decimal_to_string(
                matched_invested_value_percentage
            )
        ),

        # ====================================================
        # UNMATCHED INVESTED VALUE
        # ====================================================

        "unmatched_invested_value": (
            decimal_to_string(
                unmatched_invested_value
            )
        ),

        "unmatched_invested_value_percentage": (
            decimal_to_string(
                unmatched_invested_value_percentage
            )
        ),

        # ====================================================
        # CURRENT-VALUE AVAILABLE INVESTED VALUE
        # ====================================================

        "current_value_available_invested_value": (
            decimal_to_string(
                current_value_available_invested_value
            )
        ),

        "current_value_invested_value_percentage": (
            decimal_to_string(
                current_value_invested_value_percentage
            )
        ),

        # ====================================================
        # MISSING CURRENT-VALUE INVESTED VALUE
        # ====================================================

        "missing_current_value_invested_value": (
            decimal_to_string(
                missing_current_value_invested_value
            )
        ),

        "missing_current_value_invested_value_percentage": (
            decimal_to_string(
                missing_current_value_invested_value_percentage
            )
        ),

        # ====================================================
        # INFORMATIONAL METRIC
        # ====================================================

        "current_value_vs_invested_percentage": (
            decimal_to_string(
                current_value_vs_invested_percentage
            )
        ),
    }


# ============================================================
# INDIVIDUAL HOLDING ANALYSIS
# ============================================================


def build_holding_analysis(
    holding,
    holding_index,
    invested_value,
    latest_value,
):
    """
    Build calculated information for one holding.

    Original portfolio/CAS values are not modified.

    Calculated values are added to the analysis output.
    """

    result = {

        "holding_index": (
            holding_index
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

        "amc": (
            get_amc(
                holding
            )
        ),

        "asset_type": (
            get_asset_type(
                holding
            )
        ),

        "scheme_category": (
            get_scheme_category(
                holding
            )
        ),

        "folio_number": (
            holding.get(
                "folio_number"
            )
        ),

        "units": (
            holding.get(
                "units"
            )
        ),

        "invested_value": (
            decimal_to_string(
                invested_value
            )
        ),

        "latest_value": (
            decimal_to_string(
                latest_value
            )
            if latest_value is not None
            else None
        ),

        "current_value_available": (
            latest_value is not None
        ),
    }

    # ========================================================
    # GAIN / LOSS
    # ========================================================

    if latest_value is not None:

        gain = (
            latest_value
            - invested_value
        )

        gain_percentage = (
            calculate_percentage(
                numerator=gain,
                denominator=invested_value,
            )
        )

        result["gain"] = (
            decimal_to_string(
                gain
            )
        )

        result["gain_percentage"] = (
            decimal_to_string(
                gain_percentage
            )
        )

    else:

        result["gain"] = None

        result["gain_percentage"] = None

    return result


# ============================================================
# SCHEME IDENTIFIER
# ============================================================


def get_scheme_identifier(
    holding,
):
    """
    Determine the scheme identity used for concentration.

    Priority:

        1. AMFI matched scheme_code + scheme_name
        2. CAS AMFI code + scheme name
        3. CAS AMFI code
        4. CAS scheme name

    Example:

        149068 - Tata Business Cycle Fund-Regular Plan-Growth
    """

    amfi_match = holding.get(
        "amfi_match"
    )

    if isinstance(
        amfi_match,
        dict,
    ):

        if amfi_match.get(
            "matched"
        ):

            scheme_code = clean_string(
                amfi_match.get(
                    "scheme_code"
                )
            )

            scheme_name = clean_string(
                amfi_match.get(
                    "scheme_name"
                )
            )

            if (
                scheme_code
                and scheme_name
            ):

                return (
                    f"{scheme_code} - "
                    f"{scheme_name}"
                )

            if scheme_code:

                return scheme_code

            if scheme_name:

                return scheme_name

    # ========================================================
    # FALLBACK TO CAS AMFI CODE
    # ========================================================

    amfi_code = clean_string(
        holding.get(
            "amfi_code"
        )
    )

    scheme_name = clean_string(
        holding.get(
            "scheme_name"
        )
    )

    if (
        amfi_code
        and scheme_name
    ):

        return (
            f"{amfi_code} - "
            f"{scheme_name}"
        )

    if amfi_code:

        return amfi_code

    if scheme_name:

        return scheme_name

    return None


# ============================================================
# ASSET TYPE
# ============================================================


def get_asset_type(
    holding,
):
    """
    Determine the broad asset type.

    Priority:

        1. CAS asset_type
        2. AMFI scheme category
        3. Other

    Examples:

        Equity
        Debt
        Hybrid
        Solution Oriented
        Other
    """

    asset_type = clean_string(
        holding.get(
            "asset_type"
        )
    )

    if asset_type:

        return asset_type

    category = get_scheme_category(
        holding
    )

    if not category:

        return "Other"

    category_lower = (
        category.lower()
    )

    if "equity" in category_lower:

        return "Equity"

    if "debt" in category_lower:

        return "Debt"

    if "hybrid" in category_lower:

        return "Hybrid"

    if (
        "solution oriented"
        in category_lower
    ):

        return "Solution Oriented"

    if "other" in category_lower:

        return "Other"

    return "Other"


# ============================================================
# AMC
# ============================================================


def get_amc(
    holding,
):
    """
    Determine AMC / fund house.

    Priority:

        1. AMFI matched fund_house
        2. CAS amc
    """

    amfi_match = holding.get(
        "amfi_match"
    )

    if isinstance(
        amfi_match,
        dict,
    ):

        fund_house = clean_string(
            amfi_match.get(
                "fund_house"
            )
        )

        if fund_house:

            return fund_house

    return clean_string(
        holding.get(
            "amc"
        )
    )


# ============================================================
# SCHEME CATEGORY
# ============================================================


def get_scheme_category(
    holding,
):
    """
    Determine the scheme category.

    Priority:

        1. AMFI matched scheme_category
        2. CAS scheme_category
        3. None
    """

    amfi_match = holding.get(
        "amfi_match"
    )

    if isinstance(
        amfi_match,
        dict,
    ):

        category = clean_string(
            amfi_match.get(
                "scheme_category"
            )
        )

        if category:

            return category

    return clean_string(
        holding.get(
            "scheme_category"
        )
    )


# ============================================================
# ALLOCATION RESULT
# ============================================================


def build_allocation_result(
    allocation,
    total_current_value,
):
    """
    Convert allocation totals into API-friendly output.

    Percentages are calculated against total current value
    available for analysis.

    Results are sorted from largest to smallest value.
    """

    if not allocation:

        return []

    result = []

    for name, value in allocation.items():

        percentage = (
            calculate_percentage(
                numerator=value,
                denominator=total_current_value,
            )
        )

        result.append(
            {
                "name": name,

                "value": (
                    decimal_to_string(
                        value
                    )
                ),

                "percentage": (
                    decimal_to_string(
                        percentage
                    )
                ),
            }
        )

    # ========================================================
    # LARGEST FIRST
    # ========================================================

    result.sort(
        key=lambda item: (
            to_decimal(
                item["value"]
            )
            or Decimal("0")
        ),
        reverse=True,
    )

    return result


# ============================================================
# PERCENTAGE CALCULATION
# ============================================================


def calculate_percentage(
    numerator,
    denominator,
):
    """
    Calculate:

        numerator / denominator * 100

    Example:

        1 / 3 * 100
        =
        33.333333...

    Returns Decimal("0") if denominator is zero.
    """

    numerator = to_decimal(
        numerator
    )

    denominator = to_decimal(
        denominator
    )

    if numerator is None:

        numerator = Decimal(
            "0"
        )

    if (
        denominator is None
        or denominator == 0
    ):

        return Decimal(
            "0"
        )

    return (
        numerator
        / denominator
        * Decimal("100")
    )


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
    Convert Decimal to string.

    Full calculation precision is preserved.

    Formatting such as 91.00% should be handled later by
    the presentation/report/API layer.
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