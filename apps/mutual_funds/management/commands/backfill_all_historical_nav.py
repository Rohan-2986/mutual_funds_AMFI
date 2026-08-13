from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal, InvalidOperation
import time

import requests

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.mutual_funds.models import MutualFundScheme


# ============================================================
# MFAPI
# ============================================================

MFAPI_URL = "https://api.mfapi.in/mf/{scheme_code}"


# ============================================================
# PERFORMANCE SETTINGS
# ============================================================

MAX_WORKERS = 10

BATCH_SIZE = 50

REQUEST_TIMEOUT = 60

MAX_RETRIES = 3

RETRY_DELAY = 2


# ============================================================
# NAV CLEANER
# ============================================================

def clean_nav(value):
    """
    Validate NAV and return it as a string.

    NAV is stored inside JSON as a string so that
    decimal precision is preserved.

    Example:

        24.2752

    becomes:

        "24.2752"
    """

    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    value = value.replace(",", "")

    try:
        Decimal(value)

    except (
        InvalidOperation,
        ValueError,
    ):
        return None

    return value


# ============================================================
# DATE PARSER
# ============================================================

def parse_mfapi_date(value):
    """
    Convert MFAPI date:

        25-06-2013

    into datetime object.
    """

    return datetime.strptime(
        str(value).strip(),
        "%d-%m-%Y",
    )


# ============================================================
# DATE FORMATTER
# ============================================================

def format_nav_date(value):
    """
    Convert datetime/date into:

        DD-MM-YYYY
    """

    return value.strftime("%d-%m-%Y")


# ============================================================
# FETCH ONE SCHEME FROM MFAPI
# ============================================================

def fetch_scheme_history(scheme_code):
    """
    Fetch complete historical NAV data for one scheme.

    Example:

        https://api.mfapi.in/mf/122612

    Returns:

        {
            "scheme_code": "122612",
            "records": [...],
            "error": None
        }
    """

    url = MFAPI_URL.format(
        scheme_code=scheme_code
    )

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:

            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            data = response.json()

            if data.get("status") != "SUCCESS":

                raise ValueError(
                    "MFAPI returned status: "
                    f"{data.get('status')}"
                )

            records = data.get("data") or []

            if not records:

                raise ValueError(
                    "MFAPI returned no NAV records."
                )

            return {
                "scheme_code": str(
                    scheme_code
                ),
                "records": records,
                "error": None,
            }

        except Exception as error:

            last_error = error

            if attempt < MAX_RETRIES:

                time.sleep(
                    RETRY_DELAY * attempt
                )

    return {
        "scheme_code": str(
            scheme_code
        ),
        "records": [],
        "error": str(last_error),
    }


# ============================================================
# NAV DATE SORT KEY
# ============================================================

def nav_date_sort_key(entry):
    """
    Convert:

        DD-MM-YYYY

    into a datetime object for sorting.

    Invalid dates are placed at the end.
    """

    try:

        return datetime.strptime(
            entry["date"],
            "%d-%m-%Y",
        )

    except (
        ValueError,
        TypeError,
        KeyError,
    ):

        return datetime.min


# ============================================================
# MERGE HISTORY
# ============================================================

def merge_nav_history(
    existing_data,
    api_records,
):
    """
    Merge MFAPI historical NAV records into
    the existing JSON `data` field.

    IMPORTANT:

    Existing records are never deleted.

    Existing date:
        -> duplicate
        -> keep existing value

    New date:
        -> add

    Final order:

        NEWEST
        ↓
        12-08-2026
        11-08-2026
        10-08-2026
        ...
        OLDEST

    Duplicate dates are never added.
    """

    if not isinstance(
        existing_data,
        list,
    ):
        existing_data = []

    # --------------------------------------------------------
    # Existing dates
    # --------------------------------------------------------

    existing_dates = set()

    cleaned_data = []

    for entry in existing_data:

        if not isinstance(
            entry,
            dict,
        ):
            continue

        date_value = entry.get(
            "date"
        )

        nav_value = entry.get(
            "nav"
        )

        if not date_value:
            continue

        if nav_value is None:
            continue

        date_value = str(
            date_value
        ).strip()

        nav_value = clean_nav(
            nav_value
        )

        if nav_value is None:
            continue

        # ----------------------------------------------------
        # Validate date
        # ----------------------------------------------------

        try:

            datetime.strptime(
                date_value,
                "%d-%m-%Y",
            )

        except (
            ValueError,
            TypeError,
        ):

            continue

        # ----------------------------------------------------
        # Avoid duplicate dates
        # ----------------------------------------------------

        if date_value in existing_dates:
            continue

        existing_dates.add(
            date_value
        )

        cleaned_data.append(
            {
                "nav": nav_value,
                "date": date_value,
            }
        )

    # --------------------------------------------------------
    # Counters
    # --------------------------------------------------------

    new_records = 0
    duplicate_records = 0
    invalid_records = 0

    # --------------------------------------------------------
    # Add MFAPI records
    # --------------------------------------------------------

    for record in api_records:

        if not isinstance(
            record,
            dict,
        ):

            invalid_records += 1

            continue

        raw_date = record.get(
            "date"
        )

        raw_nav = record.get(
            "nav"
        )

        if not raw_date or raw_nav is None:

            invalid_records += 1

            continue

        # ----------------------------------------------------
        # Parse date
        # ----------------------------------------------------

        try:

            nav_date = parse_mfapi_date(
                raw_date
            )

        except (
            ValueError,
            TypeError,
        ):

            invalid_records += 1

            continue

        formatted_date = (
            format_nav_date(
                nav_date
            )
        )

        # ----------------------------------------------------
        # Clean NAV
        # ----------------------------------------------------

        nav_value = clean_nav(
            raw_nav
        )

        if nav_value is None:

            invalid_records += 1

            continue

        # ----------------------------------------------------
        # Duplicate date
        # ----------------------------------------------------

        if formatted_date in existing_dates:

            duplicate_records += 1

            continue

        # ----------------------------------------------------
        # Add new record
        # ----------------------------------------------------

        cleaned_data.append(
            {
                "nav": nav_value,
                "date": formatted_date,
            }
        )

        existing_dates.add(
            formatted_date
        )

        new_records += 1

    # ========================================================
    # SORT NEWEST -> OLDEST
    # ========================================================

    cleaned_data.sort(
        key=nav_date_sort_key,
        reverse=True,
    )

    return (
        cleaned_data,
        new_records,
        duplicate_records,
        invalid_records,
    )


# ============================================================
# PROCESS ONE SCHEME
# ============================================================

def process_scheme(scheme_data):
    """
    Process one scheme.

    MFAPI requests are performed concurrently.

    Database writes are performed one scheme at a time.

    Existing data is re-read immediately before saving
    so that data inserted while the API request was running
    is not accidentally overwritten.

    The final JSON order is always:

        newest -> oldest
    """

    scheme_id = scheme_data["id"]

    scheme_code = scheme_data[
        "scheme_code"
    ]

    scheme_name = scheme_data[
        "scheme_name"
    ]

    fund_house_name = scheme_data[
        "fund_house_name"
    ]

    isin_growth = scheme_data[
        "isin_growth"
    ]

    existing_data = (
        scheme_data["data"]
    )

    # ========================================================
    # FETCH MFAPI
    # ========================================================

    result = fetch_scheme_history(
        scheme_code
    )

    if result["error"]:

        return {
            "success": False,
            "scheme_code": scheme_code,
            "scheme_name": scheme_name,
            "fund_house": fund_house_name,
            "isin_growth": isin_growth,
            "api_records": 0,
            "new_records": 0,
            "duplicates": 0,
            "invalid": 0,
            "total_history": len(
                existing_data
                if isinstance(
                    existing_data,
                    list,
                )
                else []
            ),
            "error": result["error"],
        }

    api_records = result[
        "records"
    ]

    # ========================================================
    # INITIAL MERGE
    # ========================================================

    (
        merged_data,
        new_records,
        duplicate_records,
        invalid_records,
    ) = merge_nav_history(
        existing_data,
        api_records,
    )

    # ========================================================
    # DATABASE UPDATE
    # ========================================================
    #
    # IMPORTANT:
    #
    # Previously the code saved only when:
    #
    #     new_records > 0
    #
    # That caused an ordering problem.
    #
    # Example:
    #
    # Existing:
    #
    #     2006
    #     2007
    #     ...
    #     2026
    #
    # MFAPI:
    #
    #     All records already exist.
    #
    # Therefore:
    #
    #     new_records = 0
    #
    # The old code did not save the newly sorted order.
    #
    # Now we also save when:
    #
    #     merged_data != existing_data
    #
    # This fixes old data ordering without changing
    # the actual NAV values.
    # ========================================================

    data_needs_update = (
        merged_data != existing_data
    )

    if data_needs_update:

        try:

            with transaction.atomic():

                # ------------------------------------------------
                # Re-read latest database data.
                # ------------------------------------------------

                scheme = (
                    MutualFundScheme.objects
                    .get(
                        id=scheme_id
                    )
                )

                latest_data = (
                    scheme.data
                    or []
                )

                # ------------------------------------------------
                # Merge again using latest database state.
                # ------------------------------------------------

                (
                    final_data,
                    final_new_records,
                    final_duplicates,
                    final_invalid,
                ) = merge_nav_history(
                    latest_data,
                    api_records,
                )

                # ------------------------------------------------
                # Save ONLY when actual data differs.
                #
                # This handles both:
                #
                # 1. New NAV dates
                #
                # 2. Existing data in wrong order
                # ------------------------------------------------

                if final_data != latest_data:

                    scheme.data = final_data

                    scheme.save(
                        update_fields=[
                            "data",
                        ]
                    )

                    merged_data = final_data

                    new_records = (
                        final_new_records
                    )

                    duplicate_records = (
                        final_duplicates
                    )

                    invalid_records = (
                        final_invalid
                    )

                else:

                    merged_data = latest_data

                    new_records = 0

                    duplicate_records = (
                        final_duplicates
                    )

                    invalid_records = (
                        final_invalid
                    )

        except Exception as error:

            return {
                "success": False,
                "scheme_code": scheme_code,
                "scheme_name": scheme_name,
                "fund_house": fund_house_name,
                "isin_growth": isin_growth,
                "api_records": len(
                    api_records
                ),
                "new_records": 0,
                "duplicates": duplicate_records,
                "invalid": invalid_records,
                "total_history": len(
                    merged_data
                ),
                "error": str(error),
            }

    # ========================================================
    # FIND DATE RANGE
    # ========================================================

    valid_dates = []

    for entry in merged_data:

        try:

            valid_dates.append(
                datetime.strptime(
                    entry["date"],
                    "%d-%m-%Y",
                )
            )

        except (
            ValueError,
            TypeError,
            KeyError,
        ):

            continue

    oldest_date = None
    latest_date = None

    if valid_dates:

        oldest_date = (
            min(valid_dates)
            .strftime("%d-%m-%Y")
        )

        latest_date = (
            max(valid_dates)
            .strftime("%d-%m-%Y")
        )

    # ========================================================
    # RESULT
    # ========================================================

    return {
        "success": True,
        "scheme_code": scheme_code,
        "scheme_name": scheme_name,
        "fund_house": fund_house_name,
        "isin_growth": isin_growth,
        "api_records": len(
            api_records
        ),
        "new_records": new_records,
        "duplicates": duplicate_records,
        "invalid": invalid_records,
        "total_history": len(
            merged_data
        ),
        "oldest_date": oldest_date,
        "latest_date": latest_date,
        "error": None,
    }


# ============================================================
# DJANGO MANAGEMENT COMMAND
# ============================================================

class Command(BaseCommand):

    help = (
        "Backfill complete historical NAV data "
        "for mutual fund schemes using MFAPI."
    )

    # ========================================================
    # ARGUMENTS
    # ========================================================

    def add_arguments(
        self,
        parser,
    ):

        parser.add_argument(
            "--start-index",
            type=int,
            default=1,
            help=(
                "Starting scheme number "
                "(1-based, inclusive)."
            ),
        )

        parser.add_argument(
            "--end-index",
            type=int,
            default=None,
            help=(
                "Ending scheme number "
                "(1-based, inclusive)."
            ),
        )

        parser.add_argument(
            "--batch-size",
            type=int,
            default=BATCH_SIZE,
            help=(
                "Number of schemes processed "
                "in one batch."
            ),
        )

        parser.add_argument(
            "--workers",
            type=int,
            default=MAX_WORKERS,
            help=(
                "Number of concurrent MFAPI "
                "requests."
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

        start_index = options[
            "start_index"
        ]

        end_index = options[
            "end_index"
        ]

        batch_size = options[
            "batch_size"
        ]

        workers = options[
            "workers"
        ]

        # ====================================================
        # VALIDATION
        # ====================================================

        if start_index < 1:

            raise ValueError(
                "--start-index must be >= 1."
            )

        if end_index is not None:

            if end_index < start_index:

                raise ValueError(
                    "--end-index must be >= "
                    "--start-index."
                )

        if batch_size < 1:

            raise ValueError(
                "--batch-size must be >= 1."
            )

        if workers < 1:

            raise ValueError(
                "--workers must be >= 1."
            )

        # ====================================================
        # GET SCHEMES
        # ====================================================

        schemes_queryset = (
            MutualFundScheme.objects
            .select_related(
                "fund_house"
            )
            .order_by(
                "scheme_code"
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

        # ====================================================
        # CALCULATE RANGE
        # ====================================================

        if end_index is None:

            end_index = total_schemes

        if start_index > total_schemes:

            self.stdout.write(
                self.style.WARNING(
                    "Start index is greater than "
                    "total number of schemes."
                )
            )

            return

        end_index = min(
            end_index,
            total_schemes,
        )

        selected_count = (
            end_index
            - start_index
            + 1
        )

        # ====================================================
        # HEADER
        # ====================================================

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                "=" * 75
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "OPTIMIZED BULK HISTORICAL NAV BACKFILL"
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "=" * 75
            )
        )

        self.stdout.write("")

        self.stdout.write(
            f"Total schemes in database : "
            f"{total_schemes}"
        )

        self.stdout.write(
            f"Starting index             : "
            f"{start_index}"
        )

        self.stdout.write(
            f"Ending index               : "
            f"{end_index}"
        )

        self.stdout.write(
            f"Schemes in this run       : "
            f"{selected_count}"
        )

        self.stdout.write(
            f"Batch size                 : "
            f"{batch_size}"
        )

        self.stdout.write(
            f"Concurrent workers        : "
            f"{workers}"
        )

        self.stdout.write("")

        self.stdout.write(
            "JSON field used           : data"
        )

        self.stdout.write(
            "History order             : newest -> oldest"
        )

        self.stdout.write("")

        self.stdout.write(
            "Existing NAV history will "
            "NOT be deleted."
        )

        self.stdout.write(
            "Duplicate dates will be "
            "SKIPPED."
        )

        self.stdout.write(
            "Existing daily AMFI "
            "synchronization is NOT modified."
        )

        self.stdout.write("")

        # ====================================================
        # GLOBAL COUNTERS
        # ====================================================

        total_api_records = 0
        total_new_records = 0
        total_duplicates = 0
        total_invalid = 0

        successful_schemes = 0
        failed_schemes = 0

        failed_details = []

        processed_count = 0

        # ====================================================
        # LOAD ONLY REQUIRED RANGE
        # ====================================================

        schemes = list(
            schemes_queryset[
                start_index - 1:
                end_index
            ]
        )

        # ====================================================
        # PROCESS IN BATCHES
        # ====================================================

        for batch_start in range(
            0,
            len(schemes),
            batch_size,
        ):

            batch = schemes[
                batch_start:
                batch_start + batch_size
            ]

            actual_batch_start = (
                start_index
                + batch_start
            )

            actual_batch_end = (
                actual_batch_start
                + len(batch)
                - 1
            )

            self.stdout.write("")

            self.stdout.write(
                self.style.SUCCESS(
                    "-" * 75
                )
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"BATCH "
                    f"{actual_batch_start}"
                    f"-"
                    f"{actual_batch_end}"
                )
            )

            self.stdout.write(
                self.style.SUCCESS(
                    "-" * 75
                )
            )

            # =================================================
            # PREPARE DATA
            # =================================================

            batch_data = []

            for scheme in batch:

                batch_data.append(
                    {
                        "id": scheme.id,
                        "scheme_code": str(
                            scheme.scheme_code
                        ),
                        "scheme_name": (
                            scheme.scheme_name
                        ),
                        "fund_house_name": (
                            scheme.fund_house.name
                        ),
                        "isin_growth": (
                            scheme.isin_growth
                        ),
                        "data": (
                            scheme.data
                            or []
                        ),
                    }
                )

            # =================================================
            # CONCURRENT MFAPI FETCH
            # =================================================

            results = []

            with ThreadPoolExecutor(
                max_workers=workers
            ) as executor:

                future_map = {
                    executor.submit(
                        process_scheme,
                        scheme_data,
                    ): scheme_data
                    for scheme_data
                    in batch_data
                }

                for future in as_completed(
                    future_map
                ):

                    scheme_data = (
                        future_map[future]
                    )

                    try:

                        result = (
                            future.result()
                        )

                    except Exception as error:

                        result = {
                            "success": False,
                            "scheme_code": (
                                scheme_data[
                                    "scheme_code"
                                ]
                            ),
                            "scheme_name": (
                                scheme_data[
                                    "scheme_name"
                                ]
                            ),
                            "fund_house": (
                                scheme_data[
                                    "fund_house_name"
                                ]
                            ),
                            "isin_growth": (
                                scheme_data[
                                    "isin_growth"
                                ]
                            ),
                            "api_records": 0,
                            "new_records": 0,
                            "duplicates": 0,
                            "invalid": 0,
                            "total_history": len(
                                scheme_data[
                                    "data"
                                ]
                            ),
                            "error": str(
                                error
                            ),
                        }

                    results.append(
                        result
                    )

            # =================================================
            # DISPLAY BATCH RESULTS
            # =================================================

            results.sort(
                key=lambda item: int(
                    item[
                        "scheme_code"
                    ]
                )
                if str(
                    item[
                        "scheme_code"
                    ]
                ).isdigit()
                else 0
            )

            for result in results:

                processed_count += 1

                absolute_index = (
                    start_index
                    + processed_count
                    - 1
                )

                scheme_code = result[
                    "scheme_code"
                ]

                if result["success"]:

                    successful_schemes += 1

                    total_api_records += (
                        result[
                            "api_records"
                        ]
                    )

                    total_new_records += (
                        result[
                            "new_records"
                        ]
                    )

                    total_duplicates += (
                        result[
                            "duplicates"
                        ]
                    )

                    total_invalid += (
                        result[
                            "invalid"
                        ]
                    )

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"[{absolute_index}/"
                            f"{total_schemes}] "
                            f"{scheme_code} "
                            f"| API: "
                            f"{result['api_records']} "
                            f"| New: "
                            f"{result['new_records']} "
                            f"| Dup: "
                            f"{result['duplicates']} "
                            f"| History: "
                            f"{result['total_history']} "
                            f"| Latest: "
                            f"{result['latest_date'] or 'N/A'}"
                        )
                    )

                else:

                    failed_schemes += 1

                    failed_details.append(
                        {
                            "scheme_code": (
                                scheme_code
                            ),
                            "scheme_name": (
                                result[
                                    "scheme_name"
                                ]
                            ),
                            "error": (
                                result[
                                    "error"
                                ]
                            ),
                        }
                    )

                    self.stdout.write(
                        self.style.ERROR(
                            f"[{absolute_index}/"
                            f"{total_schemes}] "
                            f"{scheme_code} "
                            f"| FAILED | "
                            f"{result['error']}"
                        )
                    )

        # ====================================================
        # FINAL SUMMARY
        # ====================================================

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                "=" * 75
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "BULK HISTORICAL NAV BACKFILL COMPLETED"
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "=" * 75
            )
        )

        self.stdout.write("")

        self.stdout.write(
            f"Total schemes in database : "
            f"{total_schemes}"
        )

        self.stdout.write(
            f"Range processed            : "
            f"{start_index} - {end_index}"
        )

        self.stdout.write(
            f"Schemes processed          : "
            f"{processed_count}"
        )

        self.stdout.write(
            f"Successful schemes         : "
            f"{successful_schemes}"
        )

        self.stdout.write(
            f"Failed schemes             : "
            f"{failed_schemes}"
        )

        self.stdout.write("")

        self.stdout.write(
            f"Total MFAPI records        : "
            f"{total_api_records}"
        )

        self.stdout.write(
            f"Total new records added    : "
            f"{total_new_records}"
        )

        self.stdout.write(
            f"Total duplicates skipped   : "
            f"{total_duplicates}"
        )

        self.stdout.write(
            f"Total invalid records      : "
            f"{total_invalid}"
        )

        # ====================================================
        # FAILED SCHEMES
        # ====================================================

        if failed_details:

            self.stdout.write("")

            self.stdout.write(
                self.style.ERROR(
                    "FAILED SCHEMES"
                )
            )

            for failed in failed_details:

                self.stdout.write(
                    f"- "
                    f"{failed['scheme_code']} "
                    f"| "
                    f"{failed['scheme_name']}"
                )

                self.stdout.write(
                    f"  Error: "
                    f"{failed['error']}"
                )

        # ====================================================
        # IMPORTANT MESSAGE
        # ====================================================

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                "Existing daily AMFI "
                "synchronization was NOT modified."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Existing JSON data was NOT deleted."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Duplicate NAV dates were NOT added."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "NAV data is stored newest -> oldest."
            )
        )

        self.stdout.write("")
# import time
# from datetime import datetime
#
# import requests
#
# from django.core.management.base import BaseCommand
# from django.db import transaction
#
# from apps.mutual_funds.models import MutualFundScheme
#
#
# # ============================================================
# # MFAPI
# # ============================================================
#
# MFAPI_URL = "https://api.mfapi.in/mf/{scheme_code}"
#
#
# # ============================================================
# # SETTINGS
# # ============================================================
#
# REQUEST_TIMEOUT = 30
#
# # Small delay between requests so that we do not aggressively
# # hit MFAPI.
# REQUEST_DELAY = 0.5
#
#
# # ============================================================
# # COMMAND
# # ============================================================
#
# class Command(BaseCommand):
#
#     help = (
#         "Backfill complete historical NAV data for "
#         "all mutual fund schemes using MFAPI."
#     )
#
#     # ========================================================
#     # HANDLE
#     # ========================================================
#
#     def handle(self, *args, **options):
#
#         self.stdout.write("")
#         self.stdout.write(
#             self.style.SUCCESS(
#                 "=================================================="
#             )
#         )
#         self.stdout.write(
#             self.style.SUCCESS(
#                 "STARTING BULK HISTORICAL NAV BACKFILL"
#             )
#         )
#         self.stdout.write(
#             self.style.SUCCESS(
#                 "=================================================="
#             )
#         )
#         self.stdout.write("")
#
#         # ====================================================
#         # GET ALL SCHEMES
#         # ====================================================
#
#         schemes = (
#             MutualFundScheme.objects
#             .select_related("fund_house")
#             .order_by("scheme_code")
#         )
#
#         total_schemes = schemes.count()
#
#         if total_schemes == 0:
#
#             self.stdout.write(
#                 self.style.WARNING(
#                     "No mutual fund schemes found."
#                 )
#             )
#
#             return
#
#         self.stdout.write(
#             f"Total schemes found : {total_schemes}"
#         )
#
#         self.stdout.write("")
#
#         # ====================================================
#         # GLOBAL COUNTERS
#         # ====================================================
#
#         total_mfapi_records = 0
#         total_new_records = 0
#         total_duplicates = 0
#         total_invalid = 0
#         total_failed = 0
#         total_completed = 0
#
#         failed_schemes = []
#
#         # ====================================================
#         # PROCESS EVERY SCHEME
#         # ====================================================
#
#         for index, scheme in enumerate(
#             schemes,
#             start=1,
#         ):
#
#             self.stdout.write("")
#             self.stdout.write(
#                 self.style.SUCCESS(
#                     "--------------------------------------------------"
#                 )
#             )
#
#             self.stdout.write(
#                 f"[{index}/{total_schemes}] "
#                 f"Processing scheme: "
#                 f"{scheme.scheme_code}"
#             )
#
#             self.stdout.write(
#                 f"Scheme Name : {scheme.scheme_name}"
#             )
#
#             self.stdout.write(
#                 f"Fund House  : {scheme.fund_house.name}"
#             )
#
#             self.stdout.write(
#                 f"ISIN Growth : "
#                 f"{scheme.isin_growth or 'N/A'}"
#             )
#
#             try:
#
#                 result = self.backfill_scheme(
#                     scheme
#                 )
#
#                 # ==================================================
#                 # ADD GLOBAL COUNTS
#                 # ==================================================
#
#                 total_mfapi_records += (
#                     result["total_records"]
#                 )
#
#                 total_new_records += (
#                     result["new_records"]
#                 )
#
#                 total_duplicates += (
#                     result["duplicates"]
#                 )
#
#                 total_invalid += (
#                     result["invalid_records"]
#                 )
#
#                 total_completed += 1
#
#                 # ==================================================
#                 # RESULT
#                 # ==================================================
#
#                 self.stdout.write(
#                     self.style.SUCCESS(
#                         f"Completed scheme "
#                         f"{scheme.scheme_code}"
#                     )
#                 )
#
#                 self.stdout.write(
#                     f"  MFAPI records     : "
#                     f"{result['total_records']}"
#                 )
#
#                 self.stdout.write(
#                     f"  New records       : "
#                     f"{result['new_records']}"
#                 )
#
#                 self.stdout.write(
#                     f"  Duplicates        : "
#                     f"{result['duplicates']}"
#                 )
#
#                 self.stdout.write(
#                     f"  Invalid records   : "
#                     f"{result['invalid_records']}"
#                 )
#
#                 self.stdout.write(
#                     f"  Total history     : "
#                     f"{result['total_history']}"
#                 )
#
#                 self.stdout.write(
#                     f"  Oldest date       : "
#                     f"{result['oldest_date']}"
#                 )
#
#                 self.stdout.write(
#                     f"  Latest date       : "
#                     f"{result['latest_date']}"
#                 )
#
#             except Exception as error:
#
#                 total_failed += 1
#
#                 failed_schemes.append(
#                     {
#                         "scheme_code": str(
#                             scheme.scheme_code
#                         ),
#                         "scheme_name": (
#                             scheme.scheme_name
#                         ),
#                         "error": str(error),
#                     }
#                 )
#
#                 self.stdout.write(
#                     self.style.ERROR(
#                         f"FAILED scheme "
#                         f"{scheme.scheme_code}"
#                     )
#                 )
#
#                 self.stdout.write(
#                     f"  Error: {error}"
#                 )
#
#             # ==================================================
#             # DELAY
#             # ==================================================
#
#             if index < total_schemes:
#
#                 time.sleep(
#                     REQUEST_DELAY
#                 )
#
#         # ====================================================
#         # FINAL SUMMARY
#         # ====================================================
#
#         self.stdout.write("")
#         self.stdout.write(
#             self.style.SUCCESS(
#                 "=================================================="
#             )
#         )
#
#         self.stdout.write(
#             self.style.SUCCESS(
#                 "BULK HISTORICAL NAV BACKFILL COMPLETED"
#             )
#         )
#
#         self.stdout.write(
#             self.style.SUCCESS(
#                 "=================================================="
#             )
#         )
#
#         self.stdout.write("")
#
#         self.stdout.write(
#             f"Total schemes found : "
#             f"{total_schemes}"
#         )
#
#         self.stdout.write(
#             f"Schemes completed   : "
#             f"{total_completed}"
#         )
#
#         self.stdout.write(
#             f"Schemes failed      : "
#             f"{total_failed}"
#         )
#
#         self.stdout.write("")
#
#         self.stdout.write(
#             f"Total MFAPI records : "
#             f"{total_mfapi_records}"
#         )
#
#         self.stdout.write(
#             f"New records added   : "
#             f"{total_new_records}"
#         )
#
#         self.stdout.write(
#             f"Duplicates skipped  : "
#             f"{total_duplicates}"
#         )
#
#         self.stdout.write(
#             f"Invalid records     : "
#             f"{total_invalid}"
#         )
#
#         # ====================================================
#         # FAILED SCHEMES
#         # ====================================================
#
#         if failed_schemes:
#
#             self.stdout.write("")
#             self.stdout.write(
#                 self.style.ERROR(
#                     "FAILED SCHEMES"
#                 )
#             )
#
#             for failed in failed_schemes:
#
#                 self.stdout.write(
#                     f"- {failed['scheme_code']} "
#                     f"| {failed['scheme_name']}"
#                 )
#
#                 self.stdout.write(
#                     f"  Error: {failed['error']}"
#                 )
#
#         # ====================================================
#         # IMPORTANT
#         # ====================================================
#
#         self.stdout.write("")
#         self.stdout.write(
#             self.style.SUCCESS(
#                 "Existing daily AMFI synchronization "
#                 "was NOT modified."
#             )
#         )
#
#         self.stdout.write("")
#
#     # ========================================================
#     # BACKFILL ONE SCHEME
#     # ========================================================
#
#     def backfill_scheme(
#         self,
#         scheme,
#     ):
#
#         scheme_code = str(
#             scheme.scheme_code
#         ).strip()
#
#         url = MFAPI_URL.format(
#             scheme_code=scheme_code
#         )
#
#         # ====================================================
#         # REQUEST MFAPI
#         # ====================================================
#
#         response = requests.get(
#             url,
#             timeout=REQUEST_TIMEOUT,
#         )
#
#         response.raise_for_status()
#
#         data = response.json()
#
#         # ====================================================
#         # VALIDATE RESPONSE
#         # ====================================================
#
#         if data.get("status") != "SUCCESS":
#
#             raise ValueError(
#                 f"MFAPI returned status: "
#                 f"{data.get('status')}"
#             )
#
#         records = data.get(
#             "data",
#             []
#         )
#
#         if not isinstance(
#             records,
#             list,
#         ):
#
#             raise ValueError(
#                 "MFAPI data is not a list."
#             )
#
#         # ====================================================
#         # EXISTING HISTORY
#         # ====================================================
#
#         history = scheme.nav_history or []
#
#         if not isinstance(
#             history,
#             list,
#         ):
#
#             history = []
#
#         # ====================================================
#         # EXISTING DATES
#         #
#         # This makes duplicate checking fast.
#         # ====================================================
#
#         existing_dates = set()
#
#         for entry in history:
#
#             if not isinstance(
#                 entry,
#                 dict,
#             ):
#
#                 continue
#
#             date_value = entry.get(
#                 "date"
#             )
#
#             if date_value:
#
#                 existing_dates.add(
#                     str(date_value)
#                 )
#
#         # ====================================================
#         # COUNTERS
#         # ====================================================
#
#         total_records = len(
#             records
#         )
#
#         new_records = 0
#         duplicates = 0
#         invalid_records = 0
#
#         oldest_date = None
#         latest_date = None
#
#         # ====================================================
#         # PROCESS MFAPI RECORDS
#         # ====================================================
#
#         for record in records:
#
#             if not isinstance(
#                 record,
#                 dict,
#             ):
#
#                 invalid_records += 1
#
#                 continue
#
#             raw_date = record.get(
#                 "date"
#             )
#
#             raw_nav = record.get(
#                 "nav"
#             )
#
#             if not raw_date or raw_nav is None:
#
#                 invalid_records += 1
#
#                 continue
#
#             # ==================================================
#             # DATE
#             #
#             # MFAPI:
#             #
#             # 25-06-2013
#             #
#             # Existing nav_history:
#             #
#             # 25-06-2013
#             # ==================================================
#
#             try:
#
#                 parsed_date = datetime.strptime(
#                     str(raw_date).strip(),
#                     "%d-%m-%Y",
#                 ).date()
#
#             except ValueError:
#
#                 invalid_records += 1
#
#                 continue
#
#             formatted_date = (
#                 parsed_date.strftime(
#                     "%d-%m-%Y"
#                 )
#             )
#
#             # ==================================================
#             # NAV
#             # ==================================================
#
#             nav_value = str(
#                 raw_nav
#             ).strip()
#
#             if not nav_value:
#
#                 invalid_records += 1
#
#                 continue
#
#             # ==================================================
#             # DUPLICATE
#             # ==================================================
#
#             if formatted_date in existing_dates:
#
#                 duplicates += 1
#
#                 continue
#
#             # ==================================================
#             # ADD HISTORY
#             # ==================================================
#
#             history.append(
#                 {
#                     "date": formatted_date,
#                     "nav": nav_value,
#                 }
#             )
#
#             existing_dates.add(
#                 formatted_date
#             )
#
#             new_records += 1
#
#             # ==================================================
#             # DATE RANGE
#             # ==================================================
#
#             if (
#                 oldest_date is None
#                 or parsed_date < oldest_date
#             ):
#
#                 oldest_date = parsed_date
#
#             if (
#                 latest_date is None
#                 or parsed_date > latest_date
#             ):
#
#                 latest_date = parsed_date
#
#         # ====================================================
#         # SORT HISTORY
#         #
#         # Oldest → newest
#         # ====================================================
#
#         def history_date_key(entry):
#
#             try:
#
#                 return datetime.strptime(
#                     entry["date"],
#                     "%d-%m-%Y",
#                 ).date()
#
#             except (
#                 KeyError,
#                 ValueError,
#                 TypeError,
#             ):
#
#                 return datetime.min.date()
#
#         history.sort(
#             key=history_date_key
#         )
#
#         # ====================================================
#         # SAVE
#         # ====================================================
#
#         with transaction.atomic():
#
#             scheme.nav_history = history
#
#             scheme.save(
#                 update_fields=[
#                     "nav_history",
#                 ]
#             )
#
#         # ====================================================
#         # GET ACTUAL DATE RANGE
#         # ====================================================
#
#         if history:
#
#             valid_dates = []
#
#             for entry in history:
#
#                 try:
#
#                     valid_dates.append(
#                         datetime.strptime(
#                             entry["date"],
#                             "%d-%m-%Y",
#                         ).date()
#                     )
#
#                 except (
#                     KeyError,
#                     ValueError,
#                     TypeError,
#                 ):
#
#                     continue
#
#             if valid_dates:
#
#                 oldest_date = min(
#                     valid_dates
#                 )
#
#                 latest_date = max(
#                     valid_dates
#                 )
#
#         # ====================================================
#         # RESULT
#         # ====================================================
#
#         return {
#             "total_records": total_records,
#             "new_records": new_records,
#             "duplicates": duplicates,
#             "invalid_records": invalid_records,
#             "total_history": len(history),
#             "oldest_date": (
#                 oldest_date.strftime(
#                     "%d-%m-%Y"
#                 )
#                 if oldest_date
#                 else "N/A"
#             ),
#             "latest_date": (
#                 latest_date.strftime(
#                     "%d-%m-%Y"
#                 )
#                 if latest_date
#                 else "N/A"
#             ),
#         }