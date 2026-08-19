from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.mutual_funds.models import MutualFundScheme


# ============================================================
# PERFORMANCE SETTINGS
# ============================================================

# Number of database records loaded at a time.
#
# This command does NOT call MFAPI.
# It only reads and updates the existing JSON data.
#
BATCH_SIZE = 500


# Number of records written to PostgreSQL in one bulk_update.
#
# This reduces the number of individual UPDATE queries.
BULK_UPDATE_SIZE = 200


# ============================================================
# DATE FORMAT
# ============================================================

NAV_DATE_FORMAT = "%d-%m-%Y"


# ============================================================
# SORT NAV HISTORY
# ============================================================

def reorder_nav_history(data):
    """
    Clean and reorder an existing NAV history list.

    Final order:

        NEWEST
        ↓
        12-08-2026
        11-08-2026
        10-08-2026
        ...
        OLDEST

    Rules:

    1. Existing NAV records are preserved.
    2. Existing NAV values are NOT changed.
    3. Invalid records are skipped.
    4. Duplicate dates are removed.
    5. For duplicate dates, the FIRST existing record is kept.
    6. No data is downloaded from MFAPI.
    7. No historical records are intentionally deleted.
    """

    if not isinstance(data, list):
        return [], 0, 0, 0

    cleaned_data = []

    seen_dates = set()

    invalid_records = 0
    duplicate_records = 0

    # ========================================================
    # CLEAN EXISTING DATA
    # ========================================================

    for entry in data:

        # ----------------------------------------------------
        # Must be dictionary
        # ----------------------------------------------------

        if not isinstance(entry, dict):

            invalid_records += 1

            continue

        date_value = entry.get("date")
        nav_value = entry.get("nav")

        # ----------------------------------------------------
        # Required fields
        # ----------------------------------------------------

        if not date_value or nav_value is None:

            invalid_records += 1

            continue

        date_value = str(
            date_value
        ).strip()

        # ----------------------------------------------------
        # Validate date
        # ----------------------------------------------------

        try:

            datetime.strptime(
                date_value,
                NAV_DATE_FORMAT,
            )

        except (
            ValueError,
            TypeError,
        ):

            invalid_records += 1

            continue

        # ----------------------------------------------------
        # Duplicate date
        # ----------------------------------------------------

        if date_value in seen_dates:

            duplicate_records += 1

            # IMPORTANT:
            #
            # Keep the FIRST existing NAV value.
            #
            # We do NOT overwrite it with another value.
            #
            continue

        seen_dates.add(
            date_value
        )

        # ----------------------------------------------------
        # Preserve original NAV value
        # ----------------------------------------------------

        cleaned_data.append(
            {
                "nav": nav_value,
                "date": date_value,
            }
        )

    # ========================================================
    # SORT
    # ========================================================

    cleaned_data.sort(
        key=lambda entry: datetime.strptime(
            entry["date"],
            NAV_DATE_FORMAT,
        ),
        reverse=True,
    )

    return (
        cleaned_data,
        duplicate_records,
        invalid_records,
        len(seen_dates),
    )


# ============================================================
# MANAGEMENT COMMAND
# ============================================================

class Command(BaseCommand):

    help = (
        "Reorder existing MutualFundScheme JSON NAV history "
        "from newest date to oldest date without calling MFAPI."
    )

    # ========================================================
    # ARGUMENTS
    # ========================================================

    def add_arguments(
        self,
        parser,
    ):

        parser.add_argument(
            "--batch-size",
            type=int,
            default=BATCH_SIZE,
            help=(
                "Number of schemes processed from the database "
                "at a time."
            ),
        )

        parser.add_argument(
            "--bulk-size",
            type=int,
            default=BULK_UPDATE_SIZE,
            help=(
                "Number of modified schemes written to PostgreSQL "
                "in one bulk update."
            ),
        )

    # ========================================================
    # HANDLE
    # ========================================================

    def handle(
        self,
        *args,
        **options,
    ):

        batch_size = options[
            "batch_size"
        ]

        bulk_size = options[
            "bulk_size"
        ]

        # ====================================================
        # VALIDATION
        # ====================================================

        if batch_size < 1:

            raise ValueError(
                "--batch-size must be >= 1."
            )

        if bulk_size < 1:

            raise ValueError(
                "--bulk-size must be >= 1."
            )

        # ====================================================
        # HEADER
        # ====================================================

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                "=" * 80
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "FAST NAV HISTORY REORDER"
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "=" * 80
            )
        )

        self.stdout.write("")

        self.stdout.write(
            "Purpose:"
        )

        self.stdout.write(
            "Reorder existing JSON NAV history "
            "from newest -> oldest."
        )

        self.stdout.write("")

        self.stdout.write(
            "MFAPI requests              : 0"
        )

        self.stdout.write(
            "Historical data downloaded  : 0"
        )

        self.stdout.write(
            "NAV values changed          : NO"
        )

        self.stdout.write(
            "Daily AMFI synchronization  : NOT MODIFIED"
        )

        self.stdout.write(
            "Duplicate dates             : REMOVED"
        )

        self.stdout.write(
            "Final order                 : NEWEST -> OLDEST"
        )

        self.stdout.write("")

        # ====================================================
        # QUERYSET
        # ====================================================

        schemes_queryset = (
            MutualFundScheme.objects
            .only(
                "id",
                "scheme_code",
                "data",
            )
            .order_by(
                "id"
            )
        )

        total_schemes = (
            schemes_queryset.count()
        )

        if total_schemes == 0:

            self.stdout.write(
                self.style.WARNING(
                    "No mutual fund schemes found."
                )
            )

            return

        self.stdout.write(
            f"Total schemes              : "
            f"{total_schemes}"
        )

        self.stdout.write(
            f"Database batch size        : "
            f"{batch_size}"
        )

        self.stdout.write(
            f"PostgreSQL bulk update     : "
            f"{bulk_size}"
        )

        self.stdout.write("")

        # ====================================================
        # COUNTERS
        # ====================================================

        processed_schemes = 0
        updated_schemes = 0
        unchanged_schemes = 0

        total_nav_records = 0
        total_duplicate_dates = 0
        total_invalid_records = 0

        # ====================================================
        # PROCESS DATABASE IN BATCHES
        # ====================================================

        pending_updates = []

        for scheme in schemes_queryset.iterator(
            chunk_size=batch_size
        ):

            processed_schemes += 1

            original_data = (
                scheme.data
                or []
            )

            if not isinstance(
                original_data,
                list,
            ):

                original_data = []

            # ------------------------------------------------
            # REORDER
            # ------------------------------------------------

            (
                reordered_data,
                duplicate_records,
                invalid_records,
                valid_record_count,
            ) = reorder_nav_history(
                original_data
            )

            total_nav_records += (
                valid_record_count
            )

            total_duplicate_dates += (
                duplicate_records
            )

            total_invalid_records += (
                invalid_records
            )

            # ------------------------------------------------
            # Check whether anything actually changed
            # ------------------------------------------------

            if reordered_data == original_data:

                unchanged_schemes += 1

            else:

                scheme.data = (
                    reordered_data
                )

                pending_updates.append(
                    scheme
                )

                updated_schemes += 1

            # ------------------------------------------------
            # Bulk UPDATE
            # ------------------------------------------------

            if len(
                pending_updates
            ) >= bulk_size:

                with transaction.atomic():

                    MutualFundScheme.objects.bulk_update(
                        pending_updates,
                        [
                            "data",
                        ],
                        batch_size=bulk_size,
                    )

                pending_updates.clear()

            # ------------------------------------------------
            # Progress
            # ------------------------------------------------

            if (
                processed_schemes % 500 == 0
                or processed_schemes == total_schemes
            ):

                self.stdout.write(
                    f"Processed "
                    f"{processed_schemes}/"
                    f"{total_schemes} "
                    f"| Updated: "
                    f"{updated_schemes} "
                    f"| Unchanged: "
                    f"{unchanged_schemes}"
                )

        # ====================================================
        # SAVE REMAINING RECORDS
        # ====================================================

        if pending_updates:

            with transaction.atomic():

                MutualFundScheme.objects.bulk_update(
                    pending_updates,
                    [
                        "data",
                    ],
                    batch_size=bulk_size,
                )

            pending_updates.clear()

        # ====================================================
        # FINAL SUMMARY
        # ====================================================

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                "=" * 80
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "NAV HISTORY REORDER COMPLETED"
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "=" * 80
            )
        )

        self.stdout.write("")

        self.stdout.write(
            f"Total schemes              : "
            f"{total_schemes}"
        )

        self.stdout.write(
            f"Schemes processed          : "
            f"{processed_schemes}"
        )

        self.stdout.write(
            f"Schemes updated            : "
            f"{updated_schemes}"
        )

        self.stdout.write(
            f"Schemes already correct    : "
            f"{unchanged_schemes}"
        )

        self.stdout.write("")

        self.stdout.write(
            f"Valid NAV records checked  : "
            f"{total_nav_records}"
        )

        self.stdout.write(
            f"Duplicate dates removed    : "
            f"{total_duplicate_dates}"
        )

        self.stdout.write(
            f"Invalid records skipped    : "
            f"{total_invalid_records}"
        )

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                "MFAPI was NOT called."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Existing NAV values were preserved."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Existing historical NAV data was preserved."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Duplicate dates were removed."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "NAV history is now stored newest -> oldest."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Daily AMFI synchronization was NOT modified."
            )
        )

        self.stdout.write("")