from apps.mutual_funds.models import MutualFundScheme

from django.db.models import F, Q, Value
from django.db.models.functions import Lower, Replace


# ============================================================
# MATCH STATUS
# ============================================================


MATCHED_BY_AMFI_CODE = "AMFI_CODE"
MATCHED_BY_ISIN = "ISIN"
MATCHED_BY_SCHEME_NAME = "SCHEME_NAME"
NOT_MATCHED = "NOT_MATCHED"


# ============================================================
# PUBLIC MATCH FUNCTION
# ============================================================


def match_cas_holding(holding):
    """
    Match one CAS mutual-fund holding against the existing
    AMFI MutualFundScheme master.

    Matching priority:

        1. AMFI scheme code
        2. ISIN
        3. Normalized scheme name

    Scheme-name matching ignores harmless formatting differences
    such as:

        "Fund Regular Plan - Growth"

        "Fund-Regular Plan-Growth"

    This function is READ-ONLY.

    It does not:
        - create schemes
        - update schemes
        - change NAV history
        - change fund houses
        - change portfolio data
    """

    if not isinstance(
        holding,
        dict,
    ):
        raise ValueError(
            "holding must be a dictionary."
        )

    amfi_code = clean_string(
        holding.get("amfi_code")
    )

    isin = clean_string(
        holding.get("isin")
    )

    scheme_name = clean_string(
        holding.get("scheme_name")
    )

    # --------------------------------------------------------
    # 1. AMFI CODE
    # --------------------------------------------------------

    if amfi_code:

        scheme = (
            MutualFundScheme.objects
            .select_related("fund_house")
            .filter(
                scheme_code=amfi_code
            )
            .first()
        )

        if scheme:

            return build_match_result(
                scheme=scheme,
                match_type=MATCHED_BY_AMFI_CODE,
            )

    # --------------------------------------------------------
    # 2. ISIN
    # --------------------------------------------------------

    if isin:

        scheme = (
            MutualFundScheme.objects
            .select_related("fund_house")
            .filter(
                _isin_query(
                    isin
                )
            )
            .first()
        )

        if scheme:

            return build_match_result(
                scheme=scheme,
                match_type=MATCHED_BY_ISIN,
            )

    # --------------------------------------------------------
    # 3. NORMALIZED SCHEME NAME
    # --------------------------------------------------------

    if scheme_name:

        scheme = find_scheme_by_normalized_name(
            scheme_name
        )

        if scheme:

            return build_match_result(
                scheme=scheme,
                match_type=MATCHED_BY_SCHEME_NAME,
            )

    # --------------------------------------------------------
    # NO MATCH
    # --------------------------------------------------------

    return {
        "matched": False,
        "match_type": NOT_MATCHED,
        "scheme": None,
        "scheme_id": None,
        "scheme_code": None,
        "scheme_name": scheme_name,
        "fund_house": None,
        "scheme_type": None,
        "scheme_category": None,
        "is_active": None,
    }


# ============================================================
# MATCH ALL PORTFOLIO HOLDINGS
# ============================================================


def match_portfolio_holdings(
    mutual_fund_details,
):
    """
    Match every holding inside a Portfolio.

    The existing Portfolio JSON is NOT modified.
    """

    if not isinstance(
        mutual_fund_details,
        list,
    ):
        raise ValueError(
            "mutual_fund_details must be a list."
        )

    results = []

    for index, holding in enumerate(
        mutual_fund_details,
        start=1,
    ):

        if not isinstance(
            holding,
            dict,
        ):

            results.append(
                {
                    "holding_index": index,
                    "matched": False,
                    "match_type": NOT_MATCHED,
                    "scheme": None,
                    "scheme_id": None,
                    "scheme_code": None,
                    "scheme_name": None,
                    "fund_house": None,
                    "scheme_type": None,
                    "scheme_category": None,
                    "is_active": None,
                    "error": (
                        "Holding must be a dictionary."
                    ),
                }
            )

            continue

        result = match_cas_holding(
            holding
        )

        result["holding_index"] = index

        results.append(
            result
        )

    return results


# ============================================================
# FIND SCHEME BY NORMALIZED NAME
# ============================================================


def find_scheme_by_normalized_name(
    scheme_name,
):
    """
    Match scheme names while ignoring harmless formatting
    differences such as spaces and hyphens.

    Example:

        CAS:
            Tata Business Cycle Fund Regular Plan - Growth

        AMFI:
            Tata Business Cycle Fund-Regular Plan-Growth

    Both normalize to:

        tatabusinesscyclefundregularplangrowth
    """

    normalized_name = normalize_scheme_name(
        scheme_name
    )

    if not normalized_name:
        return None

    # --------------------------------------------------------
    # PostgreSQL expression:
    #
    # lower(scheme_name)
    #      ↓
    # remove "-"
    #      ↓
    # remove spaces
    #
    # Then compare with the normalized CAS value.
    # --------------------------------------------------------

    normalized_expression = Replace(
        Replace(
            Lower(
                F("scheme_name")
            ),
            Value("-"),
            Value(""),
        ),
        Value(" "),
        Value(""),
    )

    return (
        MutualFundScheme.objects
        .select_related("fund_house")
        .annotate(
            normalized_name=normalized_expression
        )
        .filter(
            normalized_name=normalized_name
        )
        .first()
    )


# ============================================================
# BUILD MATCH RESULT
# ============================================================


def build_match_result(
    scheme,
    match_type,
):
    """
    Build a consistent result for a successful AMFI match.
    """

    return {
        "matched": True,

        "match_type": match_type,

        "scheme": scheme,

        "scheme_id": scheme.id,

        "scheme_code": (
            clean_string(
                scheme.scheme_code
            )
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


# ============================================================
# ISIN QUERY
# ============================================================


def _isin_query(
    isin,
):
    """
    Build the AMFI ISIN lookup query.

    AMFI stores ISIN information in:

        isin_growth
        isin_div_payout
        isin_div_reinvestment
    """

    return (
        Q(
            isin_growth__iexact=isin
        )
        | Q(
            isin_div_payout__iexact=isin
        )
        | Q(
            isin_div_reinvestment__iexact=isin
        )
    )


# ============================================================
# SCHEME NAME NORMALIZATION
# ============================================================


def normalize_scheme_name(
    value,
):
    """
    Normalize a scheme name for matching.

    Current normalization removes:

        - spaces
        - hyphens
        - case differences

    It does NOT modify the stored scheme name.
    """

    value = clean_string(
        value
    )

    if not value:
        return None

    return (
        value
        .lower()
        .replace(" ", "")
        .replace("-", "")
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