from collections import defaultdict
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
    Convert Python date into the format stored inside `data`.

    Example:

        2026-08-11

    becomes:

        11-08-2026
    """

    return nav_date.strftime("%d-%m-%Y")


# =============================================================================
# NAV HISTORY SORTER
# =============================================================================

def sort_nav_history(history):
    """
    Sort NAV history newest -> oldest.

    Expected structure:

        [
            {
                "nav": "24.2921",
                "date": "12-08-2026"
            },
            {
                "nav": "24.2752",
                "date": "11-08-2026"
            }
        ]

    Invalid entries are retained at the end instead of being deleted.
    """

    if not isinstance(history, list):
        return []

    valid_entries = []
    invalid_entries = []

    for entry in history:

        if not isinstance(entry, dict):

            invalid_entries.append(entry)
            continue

        date_string = entry.get("date")

        if not date_string:

            invalid_entries.append(entry)
            continue

        try:

            from datetime import datetime

            parsed_date = datetime.strptime(
                date_string,
                "%d-%m-%Y",
            )

            valid_entries.append(
                (
                    parsed_date,
                    entry,
                )
            )

        except (
            ValueError,
            TypeError,
        ):

            invalid_entries.append(entry)

    valid_entries.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return (
        [entry for _, entry in valid_entries]
        + invalid_entries
    )


# =============================================================================
# NAV HISTORY MERGER
# =============================================================================

def merge_nav_history(
    existing_history,
    nav_date,
    nav,
):
    """
    Add one NAV record to existing history.

    IMPORTANT:

    - Uses `data`, not `nav_history`.
    - Existing history is preserved.
    - Same scheme + same date is never duplicated.
    - Existing NAV value is never overwritten.
    - New records are added.
    - Final history remains newest -> oldest.

    Returns:

        (history, added)

    Example:

        existing:
            [
                {
                    "nav": "24.2752",
                    "date": "11-08-2026"
                }
            ]

        new:
            12-08-2026 / 24.2921

        result:
            [
                {
                    "nav": "24.2921",
                    "date": "12-08-2026"
                },
                {
                    "nav": "24.2752",
                    "date": "11-08-2026"
                }
            ]
    """

    if not isinstance(existing_history, list):
        existing_history = []

    formatted_date = format_nav_date(nav_date)

    # -------------------------------------------------------------------------
    # FAST DUPLICATE CHECK
    #
    # Instead of scanning the list repeatedly for the same date, create
    # a set once.
    # -------------------------------------------------------------------------

    existing_dates = {
        entry.get("date")
        for entry in existing_history
        if (
            isinstance(entry, dict)
            and entry.get("date")
        )
    }

    # -------------------------------------------------------------------------
    # DUPLICATE
    #
    # Existing record is preserved exactly as requested.
    # -------------------------------------------------------------------------

    if formatted_date in existing_dates:

        return existing_history, False

    # -------------------------------------------------------------------------
    # APPEND NEW NAV
    # -------------------------------------------------------------------------

    existing_history.append(
        {
            "nav": str(nav),
            "date": formatted_date,
        }
    )

    # -------------------------------------------------------------------------
    # KEEP NEWEST -> OLDEST ORDER
    # -------------------------------------------------------------------------

    existing_history = sort_nav_history(
        existing_history
    )

    return existing_history, True


# =============================================================================
# UPDATE FUND HOUSE COUNTS
# =============================================================================

def update_fund_house_counts():
    """
    Recalculate active scheme count for every fund house.

    This functionality is unchanged.

    FundHouse.number_of_schemes
        =
    number of active MutualFundScheme records.
    """

    fund_houses = FundHouse.objects.all()

    for fund_house in fund_houses:

        active_scheme_count = (
            MutualFundScheme.objects
            .filter(
                fund_house_id=fund_house.id,
                is_active=True,
            )
            .count()
        )

        new_is_active = active_scheme_count > 0

        if (
            fund_house.number_of_schemes
            != active_scheme_count
            or fund_house.is_active
            != new_is_active
        ):

            fund_house.number_of_schemes = (
                active_scheme_count
            )

            fund_house.is_active = (
                new_is_active
            )

            fund_house.save(
                update_fields=[
                    "number_of_schemes",
                    "is_active",
                ]
            )


# =============================================================================
# MAIN NAV SYNCHRONIZATION
# =============================================================================

def sync_nav_data(sync_date=None):
    """
    Download AMFI NAV data and synchronize it with PostgreSQL.

    DATABASE STRUCTURE:

        FundHouse
            |
            +---- MutualFundScheme
                        |
                        +---- data JSON
                                  |
                                  +---- NAV history

    IMPORTANT:

    The current model uses:

        MutualFundScheme.data

    NOT:

        MutualFundScheme.nav_history

    NAV history format:

        [
            {
                "nav": "24.2921",
                "date": "12-08-2026"
            },
            {
                "nav": "24.2752",
                "date": "11-08-2026"
            }
        ]

    PERFORMANCE:

    The old implementation performed database operations for every
    individual AMFI record.

    This implementation:

        1. Downloads AMFI once.
        2. Groups records in memory.
        3. Caches fund houses.
        4. Loads existing schemes in one query.
        5. Creates missing schemes in bulk.
        6. Updates existing schemes in bulk.
        7. Writes each scheme's complete JSON only once.
        8. Updates fund-house counts.

    Existing functionality is preserved.
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
    deactivated_count = 0

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
        # 2. PREPARE UNIQUE SCHEME CODES
        # =====================================================================

        scheme_codes = {
            str(record["scheme_code"])
            for record in records
            if record.get("scheme_code") is not None
        }

        # =====================================================================
        # 3. CACHE FUND HOUSES
        # =====================================================================
        #
        # Instead of calling get_or_create() repeatedly for every AMFI row,
        # load existing fund houses once and create missing ones only when
        # required.
        #
        # =====================================================================

        fund_house_cache = {
            fund_house.name: fund_house
            for fund_house in FundHouse.objects.all()
        }

        # =====================================================================
        # 4. LOAD EXISTING SCHEMES ONCE
        # =====================================================================
        #
        # Only schemes present in this AMFI report are loaded.
        #
        # `data` is intentionally loaded here because we need to merge the
        # historical JSON.
        #
        # =====================================================================

        existing_schemes = {
            str(scheme.scheme_code): scheme
            for scheme in (
                MutualFundScheme.objects
                .filter(
                    scheme_code__in=scheme_codes
                )
                .select_related("fund_house")
            )
        }

        # =====================================================================
        # 5. PREPARE NEW FUND HOUSES
        # =====================================================================

        new_fund_house_names = set()

        for record in records:

            fund_house_name = (
                record.get("fund_house_name")
            )

            if not fund_house_name:
                continue

            if fund_house_name not in fund_house_cache:

                new_fund_house_names.add(
                    fund_house_name
                )

        # ---------------------------------------------------------------------
        # BULK CREATE MISSING FUND HOUSES
        # ---------------------------------------------------------------------

        if new_fund_house_names:

            new_fund_houses = [
                FundHouse(
                    name=name,
                    number_of_schemes=0,
                    is_active=True,
                )
                for name in new_fund_house_names
            ]

            FundHouse.objects.bulk_create(
                new_fund_houses,
                ignore_conflicts=True,
            )

            # -----------------------------------------------------------------
            # Refresh cache.
            # -----------------------------------------------------------------

            for fund_house in (
                FundHouse.objects
                .filter(
                    name__in=new_fund_house_names
                )
            ):

                fund_house_cache[
                    fund_house.name
                ] = fund_house

        # =====================================================================
        # 6. PREPARE NEW SCHEMES
        # =====================================================================

        new_scheme_objects = []

        # ---------------------------------------------------------------------
        # First pass:
        #
        # Create all missing scheme objects in memory.
        # ---------------------------------------------------------------------

        for record in records:

            try:

                scheme_code = str(
                    record["scheme_code"]
                )

                if scheme_code in existing_schemes:

                    continue

                fund_house_name = (
                    record["fund_house_name"]
                )

                fund_house = fund_house_cache.get(
                    fund_house_name
                )

                if fund_house is None:

                    raise ValueError(
                        f"Fund House '{fund_house_name}' "
                        f"could not be loaded."
                    )

                nav = clean_decimal(
                    record["nav"]
                )

                if nav is None:

                    raise ValueError(
                        "Invalid NAV value."
                    )

                scheme = MutualFundScheme(
                    scheme_code=scheme_code,

                    fund_house=fund_house,

                    scheme_name=(
                        record["scheme_name"]
                    ),

                    scheme_type=(
                        record.get("scheme_type")
                        or None
                    ),

                    scheme_category=(
                        record.get("scheme_category")
                        or None
                    ),

                    isin_growth=(
                        record.get("isin_growth")
                        or None
                    ),

                    isin_div_payout=(
                        record.get("isin_div_payout")
                        or None
                    ),

                    isin_div_reinvestment=(
                        record.get(
                            "isin_div_reinvestment"
                        )
                        or None
                    ),

                    is_active=True,

                    # IMPORTANT:
                    #
                    # Current model field is `data`.
                    #
                    data=[],
                )

                new_scheme_objects.append(
                    scheme
                )

                # Put temporarily into cache so duplicate records
                # in the same AMFI response are handled correctly.
                existing_schemes[scheme_code] = scheme

                new_schemes += 1

            except Exception as record_error:

                error_count += 1

                errors.append(
                    f"Scheme "
                    f"{record.get('scheme_code')}: "
                    f"{record_error}"
                )

        # ---------------------------------------------------------------------
        # BULK CREATE NEW SCHEMES
        # ---------------------------------------------------------------------

        if new_scheme_objects:

            MutualFundScheme.objects.bulk_create(
                new_scheme_objects,
                batch_size=500,
            )

            # -----------------------------------------------------------------
            # IMPORTANT:
            #
            # bulk_create returns primary keys on PostgreSQL.
            # The objects remain usable in our cache.
            # -----------------------------------------------------------------

        # =====================================================================
        # 7. PROCESS NAV DATA IN MEMORY
        # =====================================================================
        #
        # Each scheme's JSON history is read and modified once.
        #
        # =====================================================================

        schemes_to_update = {}

        for record in records:

            try:

                scheme_code = str(
                    record["scheme_code"]
                )

                scheme = existing_schemes.get(
                    scheme_code
                )

                if scheme is None:

                    raise ValueError(
                        "Scheme could not be loaded."
                    )

                # -------------------------------------------------------------
                # BASIC DATA
                # -------------------------------------------------------------

                fund_house_name = (
                    record["fund_house_name"]
                )

                fund_house = fund_house_cache.get(
                    fund_house_name
                )

                if fund_house is None:

                    raise ValueError(
                        f"Fund House '{fund_house_name}' "
                        f"could not be loaded."
                    )

                scheme_name = (
                    record["scheme_name"]
                )

                scheme_type = (
                    record.get("scheme_type")
                    or None
                )

                scheme_category = (
                    record.get("scheme_category")
                    or None
                )

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

                # -------------------------------------------------------------
                # NAV
                # -------------------------------------------------------------

                nav_date = record["nav_date"]

                nav = clean_decimal(
                    record["nav"]
                )

                if nav is None:

                    raise ValueError(
                        "Invalid NAV value."
                    )

                # -------------------------------------------------------------
                # UPDATE SCHEME METADATA IN MEMORY
                # -------------------------------------------------------------

                scheme.fund_house = fund_house
                scheme.scheme_name = scheme_name
                scheme.scheme_type = scheme_type
                scheme.scheme_category = scheme_category
                scheme.isin_growth = isin_growth
                scheme.isin_div_payout = isin_div_payout
                scheme.isin_div_reinvestment = (
                    isin_div_reinvestment
                )

                # -------------------------------------------------------------
                # REACTIVATE SCHEME
                # -------------------------------------------------------------

                scheme.is_active = True

                # -------------------------------------------------------------
                # GET EXISTING JSON HISTORY
                # -------------------------------------------------------------

                history = scheme.data

                if not isinstance(history, list):

                    history = []

                # -------------------------------------------------------------
                # MERGE NAV
                # -------------------------------------------------------------

                new_history, nav_added = merge_nav_history(
                    existing_history=history,
                    nav_date=nav_date,
                    nav=nav,
                )

                # -------------------------------------------------------------
                # STORE UPDATED HISTORY IN MEMORY
                # -------------------------------------------------------------

                scheme.data = new_history

                schemes_to_update[scheme_code] = scheme

                # -------------------------------------------------------------
                # COUNTERS
                # -------------------------------------------------------------

                if nav_added:

                    records_created += 1

                else:

                    duplicate_records += 1

            except Exception as record_error:

                error_count += 1

                errors.append(
                    f"Scheme "
                    f"{record.get('scheme_code')}: "
                    f"{record_error}"
                )

        # =====================================================================
        # 8. DATABASE WRITE
        # =====================================================================
        #
        # Instead of saving each scheme individually, update all existing
        # schemes in batches.
        #
        # =====================================================================

        if schemes_to_update:

            schemes_list = list(
                schemes_to_update.values()
            )

            with transaction.atomic():

                MutualFundScheme.objects.bulk_update(
                    schemes_list,
                    [
                        "fund_house",
                        "scheme_name",
                        "scheme_type",
                        "scheme_category",
                        "isin_growth",
                        "isin_div_payout",
                        "isin_div_reinvestment",
                        "is_active",
                        "data",
                    ],
                    batch_size=250,
                )

        # =====================================================================
        # 9. DEACTIVATION
        #
        # Disabled because the current model does not use last_seen_date.
        # =====================================================================

        deactivated_count = 0

        # =====================================================================
        # 10. UPDATE FUND HOUSE COUNTS
        # =====================================================================

        update_fund_house_counts()

        # =====================================================================
        # 11. FINAL STATUS
        # =====================================================================

        if error_count == 0:

            sync_status = "SUCCESS"

        elif records_created > 0:

            sync_status = "PARTIAL"

        else:

            sync_status = "FAILED"

        # =====================================================================
        # 12. UPDATE SYNC LOG
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