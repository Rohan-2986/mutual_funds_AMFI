from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.mutual_funds.models import (
    FundHouse,
    MutualFundScheme,
    NAVSyncLog,
)

from apps.mutual_funds.services.amfi_client import (
    download_latest_available_nav_report,
)


# =============================================================================
# AMFI SOURCE
# =============================================================================

AMFI_NAV_URL = (
    "https://portal.amfiindia.com/"
    "DownloadNAVHistoryReport_Po.aspx"
)


# =============================================================================
# DECIMAL CLEANER
# =============================================================================

def clean_decimal(value):
    """
    Convert an AMFI numeric value into Decimal.

    Examples:
        "24.2752" -> Decimal("24.2752")
        ""        -> None
        None      -> None
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


# =============================================================================
# NAV HISTORY DATE FORMATTER
# =============================================================================

def format_nav_date(nav_date):
    """
    Convert Python date into the format stored in nav_history.

    Example:

        2026-08-11

    becomes:

        11-08-2026
    """

    return nav_date.strftime("%d-%m-%Y")


# =============================================================================
# UPDATE FUND HOUSE COUNTS
# =============================================================================

def update_fund_house_counts():
    """
    Recalculate the number of active schemes
    belonging to every fund house.
    """

    fund_houses = FundHouse.objects.all()

    for fund_house in fund_houses:

        active_scheme_count = (
            fund_house.schemes
            .filter(is_active=True)
            .count()
        )

        fund_house.number_of_schemes = active_scheme_count
        fund_house.is_active = active_scheme_count > 0

        fund_house.save(
            update_fields=[
                "number_of_schemes",
                "is_active",
            ]
        )


# =============================================================================
# APPEND NAV HISTORY
# =============================================================================

def append_nav_history(
    scheme,
    nav_date,
    nav,
):
    """
    Append one NAV entry to nav_history.

    Example:

        [
            {
                "date": "10-08-2026",
                "nav": "24.2839"
            },
            {
                "date": "11-08-2026",
                "nav": "24.2752"
            }
        ]

    Same scheme + same date = duplicate.
    """

    history = scheme.nav_history or []

    formatted_date = format_nav_date(nav_date)

    # -------------------------------------------------------------------------
    # CHECK DUPLICATE DATE
    # -------------------------------------------------------------------------

    for entry in history:

        if (
            isinstance(entry, dict)
            and entry.get("date") == formatted_date
        ):
            return False

    # -------------------------------------------------------------------------
    # APPEND NEW NAV
    # -------------------------------------------------------------------------

    history.append(
        {
            "date": formatted_date,
            "nav": str(nav),
        }
    )

    scheme.nav_history = history

    scheme.save(
        update_fields=[
            "nav_history",
        ]
    )

    return True


# =============================================================================
# MAIN NAV SYNCHRONIZATION
# =============================================================================

def sync_nav_data(sync_date=None):
    """
    Download AMFI NAV data and synchronize it with the database.

    Database structure:

        FundHouse
            |
            +---- MutualFundScheme
                        |
                        +---- nav_history JSON

    Scheme metadata:

        scheme_type
        scheme_category
        isin_growth
        isin_div_payout
        isin_div_reinvestment

    NAV history:

        nav_history = [
            {
                "date": "11-08-2026",
                "nav": "24.2752"
            }
        ]
    """

    # =========================================================================
    # DEFAULT DATE
    # =========================================================================

    if sync_date is None:
        sync_date = timezone.localdate()

    requested_date = sync_date

    started_at = timezone.now()

    # =========================================================================
    # CREATE SYNC LOG
    # =========================================================================

    sync_log = NAVSyncLog.objects.create(
        started_at=started_at,
        status="FAILED",
        source_url=(
            f"{AMFI_NAV_URL}?frmdt="
            f"{requested_date.strftime('%d-%b-%Y')}"
        ),
    )

    # =========================================================================
    # COUNTERS
    # =========================================================================

    records_received = 0
    records_created = 0
    new_schemes = 0
    duplicate_records = 0
    error_count = 0

    errors = []

    actual_nav_date = None

    try:

        # =====================================================================
        # 1. DOWNLOAD AMFI DATA
        # =====================================================================

        (
            raw_data,
            actual_nav_date,
            records,
        ) = download_latest_available_nav_report(
            requested_date
        )

        records_received = len(records)

        # ---------------------------------------------------------------------
        # SAFETY CHECK
        # ---------------------------------------------------------------------

        if not records:

            raise ValueError(
                "AMFI returned no valid NAV records."
            )

        # ---------------------------------------------------------------------
        # ACTUAL SOURCE URL
        # ---------------------------------------------------------------------

        sync_log.source_url = (
            f"{AMFI_NAV_URL}?frmdt="
            f"{actual_nav_date.strftime('%d-%b-%Y')}"
        )

        # =====================================================================
        # 2. PROCESS EVERY PARSED RECORD
        # =====================================================================

        for record in records:

            try:

                with transaction.atomic():

                    # =========================================================
                    # BASIC DATA
                    # =========================================================

                    fund_house_name = (
                        record["fund_house_name"]
                    )

                    scheme_code = str(
                        record["scheme_code"]
                    )

                    scheme_name = (
                        record["scheme_name"]
                    )

                    # =========================================================
                    # SCHEME TYPE
                    #
                    # Example:
                    #
                    # Open Ended Schemes
                    # =========================================================

                    scheme_type = (
                        record.get("scheme_type")
                        or None
                    )

                    # =========================================================
                    # SCHEME CATEGORY
                    #
                    # Example:
                    #
                    # Debt Scheme - Dynamic Bond
                    # =========================================================

                    scheme_category = (
                        record.get("scheme_category")
                        or None
                    )

                    # =========================================================
                    # ISIN INFORMATION
                    # =========================================================

                    isin_growth = (
                        record.get("isin_growth")
                        or None
                    )

                    isin_div_payout = (
                        record.get("isin_div_payout")
                        or None
                    )

                    isin_div_reinvestment = (
                        record.get(
                            "isin_div_reinvestment"
                        )
                        or None
                    )

                    # =========================================================
                    # NAV
                    # =========================================================

                    nav_date = record["nav_date"]

                    nav = clean_decimal(
                        record["nav"]
                    )

                    if nav is None:

                        raise ValueError(
                            "Invalid NAV value."
                        )

                    # =========================================================
                    # FUND HOUSE
                    # =========================================================

                    (
                        fund_house,
                        fund_house_created,
                    ) = FundHouse.objects.get_or_create(
                        name=fund_house_name,
                        defaults={
                            "number_of_schemes": 0,
                            "is_active": True,
                        },
                    )

                    # -----------------------------------------------------------------
                    # REACTIVATE FUND HOUSE
                    # -----------------------------------------------------------------

                    if not fund_house.is_active:

                        fund_house.is_active = True

                        fund_house.save(
                            update_fields=[
                                "is_active",
                            ]
                        )

                    # =========================================================
                    # GET OR CREATE SCHEME
                    # =========================================================

                    (
                        scheme,
                        scheme_created,
                    ) = MutualFundScheme.objects.get_or_create(
                        scheme_code=scheme_code,
                        defaults={
                            "fund_house": fund_house,
                            "scheme_name": scheme_name,

                            # -------------------------------------------------
                            # IMPORTANT:
                            # Values now come directly from parser.
                            # -------------------------------------------------

                            "scheme_type": scheme_type,

                            "scheme_category": scheme_category,

                            "isin_growth": isin_growth,

                            "isin_div_payout": isin_div_payout,

                            "isin_div_reinvestment": (
                                isin_div_reinvestment
                            ),

                            "is_active": True,

                            "nav_history": [],
                        },
                    )

                    # =========================================================
                    # NEW SCHEME
                    # =========================================================

                    if scheme_created:

                        new_schemes += 1

                    # =========================================================
                    # EXISTING SCHEME
                    # =========================================================

                    else:

                        scheme_changed = False

                        # -----------------------------------------------------
                        # FUND HOUSE
                        # -----------------------------------------------------

                        if (
                            scheme.fund_house_id
                            != fund_house.id
                        ):

                            scheme.fund_house = fund_house

                            scheme_changed = True

                        # -----------------------------------------------------
                        # SCHEME NAME
                        # -----------------------------------------------------

                        if (
                            scheme.scheme_name
                            != scheme_name
                        ):

                            scheme.scheme_name = scheme_name

                            scheme_changed = True

                        # -----------------------------------------------------
                        # SCHEME TYPE
                        # -----------------------------------------------------

                        if (
                            scheme.scheme_type
                            != scheme_type
                        ):

                            scheme.scheme_type = scheme_type

                            scheme_changed = True

                        # -----------------------------------------------------
                        # SCHEME CATEGORY
                        # -----------------------------------------------------

                        if (
                            scheme.scheme_category
                            != scheme_category
                        ):

                            scheme.scheme_category = (
                                scheme_category
                            )

                            scheme_changed = True

                        # -----------------------------------------------------
                        # ISIN GROWTH
                        # -----------------------------------------------------

                        if (
                            scheme.isin_growth
                            != isin_growth
                        ):

                            scheme.isin_growth = isin_growth

                            scheme_changed = True

                        # -----------------------------------------------------
                        # ISIN DIV PAYOUT
                        # -----------------------------------------------------

                        if (
                            scheme.isin_div_payout
                            != isin_div_payout
                        ):

                            scheme.isin_div_payout = (
                                isin_div_payout
                            )

                            scheme_changed = True

                        # -----------------------------------------------------
                        # ISIN DIV REINVESTMENT
                        # -----------------------------------------------------

                        if (
                            scheme.isin_div_reinvestment
                            != isin_div_reinvestment
                        ):

                            scheme.isin_div_reinvestment = (
                                isin_div_reinvestment
                            )

                            scheme_changed = True

                        # -----------------------------------------------------
                        # REACTIVATE SCHEME
                        # -----------------------------------------------------

                        if not scheme.is_active:

                            scheme.is_active = True

                            scheme_changed = True

                        # -----------------------------------------------------
                        # SAVE METADATA CHANGES
                        # -----------------------------------------------------

                        if scheme_changed:

                            scheme.save(
                                update_fields=[
                                    "fund_house",
                                    "scheme_name",
                                    "scheme_type",
                                    "scheme_category",
                                    "isin_growth",
                                    "isin_div_payout",
                                    "isin_div_reinvestment",
                                    "is_active",
                                ]
                            )

                    # =========================================================
                    # APPEND NAV HISTORY
                    # =========================================================

                    nav_added = append_nav_history(
                        scheme=scheme,
                        nav_date=nav_date,
                        nav=nav,
                    )

                    # =========================================================
                    # COUNT RESULT
                    # =========================================================

                    if nav_added:

                        records_created += 1

                    else:

                        duplicate_records += 1

            # =================================================================
            # RECORD ERROR FOR INDIVIDUAL SCHEME
            # =================================================================

            except Exception as record_error:

                error_count += 1

                errors.append(
                    f"Scheme "
                    f"{record.get('scheme_code')}: "
                    f"{record_error}"
                )

        # =====================================================================
        # 3. DEACTIVATION
        #
        # Disabled because current model does not use last_seen_date.
        # =====================================================================

        deactivated_count = 0

        # =====================================================================
        # 4. UPDATE FUND HOUSE COUNTS
        # =====================================================================

        update_fund_house_counts()

        # =====================================================================
        # 5. FINAL STATUS
        # =====================================================================

        if error_count == 0:

            sync_status = "SUCCESS"

        elif records_created > 0:

            sync_status = "PARTIAL"

        else:

            sync_status = "FAILED"

        # =====================================================================
        # 6. UPDATE SYNC LOG
        # =====================================================================

        sync_log.completed_at = timezone.now()

        sync_log.status = sync_status

        sync_log.records_received = (
            records_received
        )

        sync_log.records_created = (
            records_created
        )

        sync_log.new_schemes = (
            new_schemes
        )

        sync_log.deactivated_schemes = (
            deactivated_count
        )

        sync_log.duplicate_records = (
            duplicate_records
        )

        sync_log.error_count = (
            error_count
        )

        if errors:

            sync_log.error_message = (
                "\n".join(errors)
            )

        sync_log.save()

        return sync_log

    # =========================================================================
    # COMPLETE SYNCHRONIZATION FAILURE
    # =========================================================================

    except Exception as error:

        sync_log.completed_at = timezone.now()

        sync_log.status = "FAILED"

        sync_log.records_received = (
            records_received
        )

        sync_log.records_created = (
            records_created
        )

        sync_log.new_schemes = (
            new_schemes
        )

        sync_log.deactivated_schemes = (
            deactivated_count
            if "deactivated_count" in locals()
            else 0
        )

        sync_log.duplicate_records = (
            duplicate_records
        )

        sync_log.error_count = (
            error_count + 1
        )

        sync_log.error_message = str(error)

        sync_log.save()

        raise