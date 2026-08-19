from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal, InvalidOperation
import threading
import time

import requests
from requests.adapters import HTTPAdapter

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

# Number of concurrent MFAPI requests.
#
# 30 provides strong concurrency without creating
# an unnecessarily large number of simultaneous requests.
MAX_WORKERS = 30


# Number of schemes processed in one batch.
BATCH_SIZE = 100


# HTTP timeout for one request.
REQUEST_TIMEOUT = 30


# Number of retries for temporary failures.
MAX_RETRIES = 2


# Initial retry delay.
RETRY_DELAY = 1


# HTTP connection pool size per worker.
CONNECTION_POOL_SIZE = 2


# ============================================================
# THREAD LOCAL HTTP SESSION
# ============================================================

_thread_local = threading.local()


def get_http_session():
    """
    Return one reusable requests.Session for the current thread.

    Each worker gets its own Session.

    HTTP connections can therefore be reused between requests.
    """

    session = getattr(
        _thread_local,
        "session",
        None,
    )

    if session is None:

        session = requests.Session()

        adapter = HTTPAdapter(
            pool_connections=CONNECTION_POOL_SIZE,
            pool_maxsize=CONNECTION_POOL_SIZE,
            max_retries=0,
        )

        session.mount(
            "https://",
            adapter,
        )

        session.mount(
            "http://",
            adapter,
        )

        _thread_local.session = session

    return session


# ============================================================
# NAV CLEANER
# ============================================================

def clean_nav(value):
    """
    Validate NAV and return it as a string.

    NAV is stored as a string inside JSON so decimal
    precision is preserved.
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
    Convert:

        25-06-2013

    into datetime.
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

    return value.strftime(
        "%d-%m-%Y"
    )


# ============================================================
# CLEAN EXISTING DATABASE HISTORY
# ============================================================

def clean_existing_history(existing_data):
    """
    Clean existing JSON NAV history.

    Rules:

    1. Invalid entries are ignored.
    2. Invalid dates are ignored.
    3. Invalid NAV values are ignored.
    4. Duplicate dates are removed.
    5. FIRST existing NAV value for a date is preserved.
    6. Existing NAV values are never replaced.
    7. Final order is NEWEST -> OLDEST.

    Returns:

        cleaned_data
        existing_dates
        duplicate_records
        invalid_records
    """

    if not isinstance(
        existing_data,
        list,
    ):

        existing_data = []

    cleaned_data = []

    existing_dates = set()

    duplicate_records = 0
    invalid_records = 0

    for entry in existing_data:

        # ----------------------------------------------------
        # Dictionary validation
        # ----------------------------------------------------

        if not isinstance(
            entry,
            dict,
        ):

            invalid_records += 1

            continue

        raw_date = entry.get(
            "date"
        )

        raw_nav = entry.get(
            "nav"
        )

        if not raw_date or raw_nav is None:

            invalid_records += 1

            continue

        date_value = str(
            raw_date
        ).strip()

        # ----------------------------------------------------
        # Date validation
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

            invalid_records += 1

            continue

        # ----------------------------------------------------
        # NAV validation
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

        if date_value in existing_dates:

            duplicate_records += 1

            # IMPORTANT:
            #
            # Keep the FIRST existing value.
            #
            # We never overwrite an existing NAV value.
            #

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
    # ALWAYS SORT NEWEST -> OLDEST
    # --------------------------------------------------------

    cleaned_data.sort(
        key=lambda entry: datetime.strptime(
            entry["date"],
            "%d-%m-%Y",
        ),
        reverse=True,
    )

    return (
        cleaned_data,
        existing_dates,
        duplicate_records,
        invalid_records,
    )


# ============================================================
# CLEAN MFAPI RECORDS
# ============================================================

def clean_api_records(api_records):
    """
    Clean and validate MFAPI records.

    Duplicate dates inside the MFAPI response are removed.

    Existing database records are NOT handled here.
    """

    cleaned_records = []

    api_dates = set()

    invalid_records = 0
    duplicate_api_records = 0

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
        # DATE
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

        formatted_date = format_nav_date(
            nav_date
        )

        # ----------------------------------------------------
        # NAV
        # ----------------------------------------------------

        nav_value = clean_nav(
            raw_nav
        )

        if nav_value is None:

            invalid_records += 1

            continue

        # ----------------------------------------------------
        # DUPLICATE INSIDE MFAPI
        # ----------------------------------------------------

        if formatted_date in api_dates:

            duplicate_api_records += 1

            continue

        api_dates.add(
            formatted_date
        )

        cleaned_records.append(
            {
                "nav": nav_value,
                "date": formatted_date,
            }
        )

    return (
        cleaned_records,
        api_dates,
        invalid_records,
        duplicate_api_records,
    )


# ============================================================
# SORT NAV DATA
# ============================================================

def sort_nav_data(data):
    """
    Sort NAV history:

        NEWEST -> OLDEST
    """

    data.sort(
        key=lambda entry: datetime.strptime(
            entry["date"],
            "%d-%m-%Y",
        ),
        reverse=True,
    )

    return data


# ============================================================
# GET DATE RANGE
# ============================================================

def get_date_range(data):
    """
    Return:

        oldest_date
        latest_date

    from NAV history.
    """

    if not data:

        return None, None

    oldest = None
    latest = None

    for entry in data:

        try:

            current_date = datetime.strptime(
                entry["date"],
                "%d-%m-%Y",
            )

        except (
            ValueError,
            TypeError,
            KeyError,
        ):

            continue

        if oldest is None or current_date < oldest:

            oldest = current_date

        if latest is None or current_date > latest:

            latest = current_date

    oldest_date = None
    latest_date = None

    if oldest:

        oldest_date = oldest.strftime(
            "%d-%m-%Y"
        )

    if latest:

        latest_date = latest.strftime(
            "%d-%m-%Y"
        )

    return (
        oldest_date,
        latest_date,
    )


# ============================================================
# FETCH ONE SCHEME
# ============================================================

def fetch_scheme_history(scheme_code):
    """
    Fetch complete historical NAV data from MFAPI.
    """

    url = MFAPI_URL.format(
        scheme_code=scheme_code
    )

    last_error = None

    session = get_http_session()

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:

            response = session.get(
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

            records = data.get(
                "data"
            ) or []

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
        "error": str(
            last_error
        ),
    }


# ============================================================
# PROCESS ONE SCHEME
# ============================================================

def process_scheme(scheme_data):
    """
    Fetch and safely merge one scheme.

    IMPORTANT:

    The database row is locked immediately before saving.

    This protects against another process changing the same
    scheme while MFAPI data was being downloaded.

    Final JSON order is ALWAYS:

        NEWEST -> OLDEST
    """

    scheme_id = scheme_data[
        "id"
    ]

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
        scheme_data.get(
            "data"
        )
        or []
    )

    if not isinstance(
        existing_data,
        list,
    ):

        existing_data = []

    # ========================================================
    # FETCH MFAPI
    # ========================================================

    result = fetch_scheme_history(
        scheme_code
    )

    if result["error"]:

        oldest_date, latest_date = (
            get_date_range(
                existing_data
            )
        )

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
            ),
            "latest_date": latest_date,
            "oldest_date": oldest_date,
            "error": result["error"],
        }

    api_records = result[
        "records"
    ]

    # ========================================================
    # CLEAN MFAPI RECORDS
    # ========================================================

    (
        cleaned_api_records,
        api_dates,
        invalid_records,
        duplicate_api_records,
    ) = clean_api_records(
        api_records
    )

    # ========================================================
    # DATABASE SAVE
    #
    # IMPORTANT:
    #
    # We lock the row and re-read the latest data.
    #
    # This is the final source of truth.
    # ========================================================

    try:

        with transaction.atomic():

            scheme = (
                MutualFundScheme.objects
                .select_for_update()
                .get(
                    id=scheme_id
                )
            )

            latest_data = (
                scheme.data
                or []
            )

            if not isinstance(
                latest_data,
                list,
            ):

                latest_data = []

            # ------------------------------------------------
            # CLEAN CURRENT DATABASE HISTORY
            # ------------------------------------------------

            (
                cleaned_existing,
                existing_dates,
                existing_duplicate_records,
                existing_invalid_records,
            ) = clean_existing_history(
                latest_data
            )


            # ------------------------------------------------
            # SNAPSHOT existing dates BEFORE merge mutates them
            # ------------------------------------------------

            original_existing_dates = set(existing_dates)
            # ------------------------------------------------
            # ADD ONLY MISSING MFAPI DATES
            # ------------------------------------------------

            final_new_records = 0

            for record in cleaned_api_records:

                record_date = record[
                    "date"
                ]

                # --------------------------------------------
                # Existing date
                # --------------------------------------------

                if record_date in existing_dates:

                    continue

                # --------------------------------------------
                # New date
                # --------------------------------------------

                cleaned_existing.append(
                    {
                        "nav": record[
                            "nav"
                        ],
                        "date": record[
                            "date"
                        ],
                    }
                )

                existing_dates.add(
                    record_date
                )

                final_new_records += 1

            # ------------------------------------------------
            # ALWAYS SORT
            #
            # This is the important fix.
            #
            # Even when:
            #
            #     final_new_records == 0
            #
            # existing history will still be normalized
            # to newest -> oldest.
            # ------------------------------------------------

            sort_nav_data(
                cleaned_existing
            )

            # ------------------------------------------------
            # TOTAL DUPLICATES
            # ------------------------------------------------
            total_duplicates = (
                duplicate_api_records
                + existing_duplicate_records
                + len(
                    api_dates
                    & original_existing_dates
                )
            )


            # ------------------------------------------------
            # TOTAL INVALID
            # ------------------------------------------------

            total_invalid = (
                invalid_records
                + existing_invalid_records
            )

            # ------------------------------------------------
            # DETERMINE WHETHER DATABASE MUST BE UPDATED
            #
            # Save if:
            #
            # 1. New records were added
            # 2. Existing history order was wrong
            # 3. Duplicate/invalid entries were cleaned
            #
            # This prevents unnecessary UPDATE queries.
            # ------------------------------------------------

            data_changed = (
                cleaned_existing
                != latest_data
            )

            if data_changed:

                scheme.data = (
                    cleaned_existing
                )

                scheme.save(
                    update_fields=[
                        "data",
                    ]
                )

            final_data = (
                cleaned_existing
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
            "duplicates": 0,
            "invalid": invalid_records,
            "total_history": len(
                existing_data
            ),
            "latest_date": None,
            "oldest_date": None,
            "error": str(error),
        }

    # ========================================================
    # DATE RANGE
    # ========================================================

    oldest_date, latest_date = (
        get_date_range(
            final_data
        )
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
        "new_records": final_new_records,
        "duplicates": total_duplicates,
        "invalid": total_invalid,
        "total_history": len(
            final_data
        ),
        "latest_date": latest_date,
        "oldest_date": oldest_date,
        "error": None,
    }


# ============================================================
# DJANGO MANAGEMENT COMMAND
# ============================================================

class Command(BaseCommand):

    help = (
        "Fast and safe complete historical NAV backfill "
        "for existing mutual fund schemes."
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
                "Number of schemes fetched "
                "per batch."
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
        # QUERYSET
        # ====================================================

        schemes_queryset = (
            MutualFundScheme.objects
            .select_related(
                "fund_house"
            )
            .only(
                "id",
                "scheme_code",
                "scheme_name",
                "isin_growth",
                "data",
                "fund_house__name",
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
        # RANGE
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
                "=" * 80
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "FAST + SAFE HISTORICAL NAV BACKFILL"
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "=" * 80
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
            f"Schemes in this run        : "
            f"{selected_count}"
        )

        self.stdout.write(
            f"Batch size                 : "
            f"{batch_size}"
        )

        self.stdout.write(
            f"Concurrent MFAPI workers   : "
            f"{workers}"
        )

        self.stdout.write("")

        self.stdout.write(
            "JSON field                 : data"
        )

        self.stdout.write(
            "History order              : newest -> oldest"
        )

        self.stdout.write(
            "Duplicate dates            : prevented"
        )

        self.stdout.write(
            "Existing NAV values        : preserved"
        )

        self.stdout.write(
            "Existing history           : never intentionally deleted"
        )

        self.stdout.write(
            "Daily AMFI sync            : not modified"
        )

        self.stdout.write("")

        # ====================================================
        # COUNTERS
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
        # PROCESS BATCHES
        # ====================================================

        for batch_start in range(
            start_index - 1,
            end_index,
            batch_size,
        ):

            batch_end = min(
                batch_start + batch_size,
                end_index,
            )

            # =================================================
            # LOAD ONLY THIS BATCH
            # =================================================

            batch = list(
                schemes_queryset[
                    batch_start:batch_end
                ]
            )

            actual_batch_start = (
                batch_start + 1
            )

            actual_batch_end = (
                batch_start
                + len(batch)
            )

            self.stdout.write("")

            self.stdout.write(
                self.style.SUCCESS(
                    "-" * 80
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
                    "-" * 80
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
            # CONCURRENT MFAPI FETCH + PROCESS
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
                            "latest_date": None,
                            "oldest_date": None,
                            "error": str(
                                error
                            ),
                        }

                    results.append(
                        result
                    )

            # =================================================
            # ORDER OUTPUT BY SCHEME CODE
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

            # =================================================
            # DISPLAY RESULTS
            # =================================================

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
                "=" * 80
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "HISTORICAL NAV BACKFILL COMPLETED"
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "=" * 80
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
        # FINAL SAFETY MESSAGE
        # ====================================================

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                "Existing JSON history was NOT intentionally deleted."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Existing NAV values were preserved."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Duplicate NAV dates were NOT added."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "NAV history is ALWAYS stored newest -> oldest."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Daily AMFI synchronization was NOT modified."
            )
        )

        self.stdout.write("")
