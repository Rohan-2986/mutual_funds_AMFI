from decimal import Decimal

from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone


from ..models import (
    Portfolio,
    PortfolioImport,
)


# ============================================================
# CONSTANTS
# ============================================================

SOURCE_CAS = "CAS"

STATUS_PROCESSING = "PROCESSING"
STATUS_SUCCESS = "SUCCESS"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAILED = "FAILED"


# ============================================================
# MAIN CAS IMPORT
# ============================================================


@transaction.atomic
def import_cas_portfolio(
    investor,
    portfolio_totals,
    mutual_fund_details,
    file_name=None,
):
    """
    Import the latest CAS portfolio.

    MATCHING RULE
    -------------

    An existing Portfolio is considered the same investor when
    EITHER of these matches:

        PAN
        OR
        Email

    When an existing Portfolio is found:

        username  -> KEEP existing value
        email     -> KEEP existing value
        contact   -> KEEP existing value
        pan       -> KEEP existing value

        portfolio_totals
            -> REPLACE with latest CAS data

        mutual_fund_details
            -> REPLACE with latest CAS data

    When no Portfolio matches by PAN or email:

        A new Portfolio is created using the CAS investor data.

    IMPORTANT
    ---------

    This function does NOT append holdings from the previous CAS.

    The latest CAS represents the current portfolio state.

    This function also does NOT modify:

        MutualFundScheme
        MutualFundNAV
        FundHouse
        NAV history
    """

    if not isinstance(
        investor,
        dict,
    ):
        raise ValueError(
            "investor must be a dictionary."
        )

    if not isinstance(
        portfolio_totals,
        dict,
    ):
        raise ValueError(
            "portfolio_totals must be a dictionary."
        )

    if not isinstance(
        mutual_fund_details,
        list,
    ):
        raise ValueError(
            "mutual_fund_details must be a list."
        )

    # --------------------------------------------------------
    # Extract CAS identity.
    # --------------------------------------------------------

    username = clean_string(
        investor.get("username")
    )

    email = clean_email(
        investor.get("email")
    )

    contact = clean_string(
        investor.get("contact")
    )

    pan = clean_pan(
        investor.get("pan")
    )

    # --------------------------------------------------------
    # Find existing Portfolio by PAN OR email.
    #
    # IMPORTANT:
    #
    # This is not PAN-first then email.
    #
    # Either match is sufficient.
    # --------------------------------------------------------

    portfolio = find_portfolio(
        pan=pan,
        email=email,
    )

    portfolio_created = (
        portfolio is None
    )

    # --------------------------------------------------------
    # Create a new Portfolio only when neither PAN nor email
    # matches an existing Portfolio.
    # --------------------------------------------------------

    if portfolio is None:

        portfolio = Portfolio(
            username=username,
            email=email,
            contact=contact,
            pan=pan,
        )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # If Portfolio already exists:
    #
    # DO NOT update:
    #
    #     username
    #     email
    #     contact
    #     pan
    #
    # The existing Portfolio identity remains unchanged.
    # --------------------------------------------------------

    # --------------------------------------------------------
    # Replace portfolio-level financial totals with the
    # latest CAS values.
    # --------------------------------------------------------

    portfolio.portfolio_totals = (
        make_json_safe(
            portfolio_totals
        )
    )

    # --------------------------------------------------------
    # Replace all current mutual-fund details with the latest
    # CAS holdings.
    #
    # This is deliberately NOT an append operation.
    # --------------------------------------------------------

    portfolio.mutual_fund_details = (
        make_json_safe(
            mutual_fund_details
        )
    )

    # --------------------------------------------------------
    # Save portfolio.
    # --------------------------------------------------------

    portfolio.save()

    # --------------------------------------------------------
    # Create import log.
    # --------------------------------------------------------

    portfolio_import = (
        PortfolioImport.objects.create(
            portfolio=portfolio,
            source=SOURCE_CAS,
            status=STATUS_PROCESSING,
            file_name=file_name,
            records_found=len(
                mutual_fund_details
            ),
            records_created=0,
            records_updated=0,
            started_at=timezone.now(),
        )
    )

    # --------------------------------------------------------
    # Determine import statistics.
    #
    # For a new portfolio:
    #
    #     records_created = number of CAS holdings
    #
    # For an existing portfolio:
    #
    #     records_updated = number of CAS holdings
    #
    # because the current portfolio snapshot is being replaced.
    # --------------------------------------------------------

    if portfolio_created:

        records_created = len(
            mutual_fund_details
        )

        records_updated = 0

    else:

        records_created = 0

        records_updated = len(
            mutual_fund_details
        )

    # --------------------------------------------------------
    # Successful import.
    # --------------------------------------------------------

    portfolio_import.status = (
        STATUS_SUCCESS
    )

    portfolio_import.records_found = (
        len(mutual_fund_details)
    )

    portfolio_import.records_created = (
        records_created
    )

    portfolio_import.records_updated = (
        records_updated
    )

    portfolio_import.completed_at = (
        timezone.now()
    )

    portfolio_import.error_message = None

    portfolio_import.save(
        update_fields=[
            "status",
            "records_found",
            "records_created",
            "records_updated",
            "completed_at",
            "error_message",
        ]
    )

    return {
        "status": STATUS_SUCCESS,

        "portfolio": portfolio,

        "portfolio_import": (
            portfolio_import
        ),

        "records_found": (
            len(mutual_fund_details)
        ),

        "records_created": (
            records_created
        ),

        "records_updated": (
            records_updated
        ),

        "records_failed": 0,

        "errors": [],
    }


# ============================================================
# FIND PORTFOLIO
# ============================================================


def find_portfolio(
    pan=None,
    email=None,
):
    """
    Find an existing Portfolio when either PAN OR email matches.

    Matching rule:

        PAN matches
            OR
        Email matches

    Either one is sufficient to identify the existing Portfolio.

    Returns:
        Portfolio instance or None.
    """

    pan = clean_pan(
        pan
    )

    email = clean_email(
        email
    )

    conditions = Q()

    has_condition = False

    # --------------------------------------------------------
    # PAN condition
    # --------------------------------------------------------

    if pan:

        conditions |= Q(
            pan__iexact=pan
        )

        has_condition = True

    # --------------------------------------------------------
    # Email condition
    # --------------------------------------------------------

    if email:

        conditions |= Q(
            email__iexact=email
        )

        has_condition = True

    # --------------------------------------------------------
    # Nothing usable for identity matching.
    # --------------------------------------------------------

    if not has_condition:

        return None

    # --------------------------------------------------------
    # PAN OR email.
    # --------------------------------------------------------

    return (
        Portfolio.objects
        .filter(
            conditions
        )
        .order_by(
            "id"
        )
        .first()
    )


# ============================================================
# UPDATE EXISTING PORTFOLIO FINANCIAL DATA
# ============================================================


@transaction.atomic
def update_portfolio_financial_data(
    portfolio,
    portfolio_totals,
    mutual_fund_details,
):
    """
    Replace only the financial portion of an existing
    Portfolio.

    Investor identity remains untouched.

    Updated:

        portfolio_totals
        mutual_fund_details

    Not updated:

        username
        email
        contact
        pan
    """

    if not isinstance(
        portfolio,
        Portfolio,
    ):
        raise ValueError(
            "portfolio must be a Portfolio instance."
        )

    if not isinstance(
        portfolio_totals,
        dict,
    ):
        raise ValueError(
            "portfolio_totals must be a dictionary."
        )

    if not isinstance(
        mutual_fund_details,
        list,
    ):
        raise ValueError(
            "mutual_fund_details must be a list."
        )

    portfolio.portfolio_totals = (
        make_json_safe(
            portfolio_totals
        )
    )

    portfolio.mutual_fund_details = (
        make_json_safe(
            mutual_fund_details
        )
    )

    portfolio.save(
        update_fields=[
            "portfolio_totals",
            "mutual_fund_details",
            "updated_at",
        ]
    )

    return portfolio


# ============================================================
# DATA CLEANING
# ============================================================


def clean_string(
    value,
):
    """
    Convert value to a trimmed string.

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


def clean_email(
    value,
):
    """
    Normalize email.
    """

    value = clean_string(
        value
    )

    if value is None:

        return None

    return value.lower()


def clean_pan(
    value,
):
    """
    Normalize PAN.
    """

    value = clean_string(
        value
    )

    if value is None:

        return None

    return value.upper()


# ============================================================
# JSON SAFETY
# ============================================================


def make_json_safe(
    value,
):
    """
    Recursively convert Decimal/date-like values into values
    safe for PostgreSQL JSONField/JSONB.

    Decimal values are stored as strings to avoid floating-point
    precision loss.
    """

    if isinstance(
        value,
        Decimal,
    ):

        return format(
            value,
            "f",
        )

    if hasattr(
        value,
        "isoformat",
    ):

        return value.isoformat()

    if isinstance(
        value,
        dict,
    ):

        return {
            str(key): make_json_safe(
                item
            )
            for key, item in value.items()
        }

    if isinstance(
        value,
        list,
    ):

        return [
            make_json_safe(
                item
            )
            for item in value
        ]

    if isinstance(
        value,
        tuple,
    ):

        return [
            make_json_safe(
                item
            )
            for item in value
        ]

    return value