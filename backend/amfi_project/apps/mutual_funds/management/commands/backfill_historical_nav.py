from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.mutual_funds.models import MutualFundScheme


# ============================================================
# MFAPI
# ============================================================

MFAPI_BASE_URL = "https://api.mfapi.in/mf"

DEFAULT_WORKERS = 10
REQUEST_TIMEOUT = 30


# ============================================================
# CLEAN NAV
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

    try:
        Decimal(value)
    except (
        InvalidOperation,
        ValueError,
    ):
        return None

    return value


# ============================================================
# PARSE DATE
# ============================================================

def parse_nav_date(value):
    """
    MFAPI date format:

        25-06-2013

    Returns datetime object.
    """

    return datetime.strptime(
        str(value).strip(),
        "%d-%m-%Y",
    )


# ============================================================
# FETCH ONE SCHEME FROM MFAPI
# ============================================================

def fetch_mfapi_scheme(scheme_code):
    """
    Fetch complete historical NAV data for one scheme.

    IMPORTANT:
    Only the scheme code is sent to MFAPI.

    No database information is sent.
    """

    url = (
        f"{MFAPI_BASE_URL}/"
        f"{scheme_code}"
    )

    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("status") != "SUCCESS":
        raise ValueError(
            f"MFAPI returned status "
            f"{data.get('status')}"
        )

    records = data.get("data") or []

    if not records:
        raise ValueError(
            "MFAPI returned no NAV records."
        )

    return records


# ============================================================
# MERGE HISTORY SAFELY
# ============================================================

def merge_nav_history(
    scheme_code,
    records,
):
    """
    Merge MFAPI historical records into the existing
    nav_history.

    Existing records are NEVER deleted.

    Existing dates are NEVER overwritten.

    Only missing dates are added.

    The scheme is freshly loaded from PostgreSQL before
    saving so the bulk worker does not save a stale
    MutualFundScheme object.
    """

    new_records = 0
    duplicates = 0
    invalid = 0

    # --------------------------------------------------------
    # Lock the scheme while merging
    # --------------------------------------------------------

    with transaction.atomic():

        scheme = (
            MutualFundScheme.objects
            .select_for_update()
            .get(
                scheme_code=str(
                    scheme_code
                ).strip()
            )
        )

        history = scheme.nav_history or []

        if not isinstance(history, list):
            history = []

        # ----------------------------------------------------
        # Existing dates
        # ----------------------------------------------------

        existing_dates = set()

        for entry in history:

            if not isinstance(entry, dict):
                continue

            entry_date = entry.get("date")

            if entry_date:
                existing_dates.add(
                    str(entry_date).strip()
                )

        # ----------------------------------------------------
        # Process MFAPI records
        # ----------------------------------------------------

        for record in records:

            try:

                raw_date = record.get("date")
                raw_nav = record.get("nav")

                if not raw_date or raw_nav is None:
                    invalid += 1
                    continue

                # --------------------------------------------
                # DATE
                # --------------------------------------------

                parsed_date = parse_nav_date(
                    raw_date
                )

                formatted_date = (
                    parsed_date.strftime(
                        "%d-%m-%Y"
                    )
                )

                # --------------------------------------------
                # NAV
                # --------------------------------------------

                nav_value = clean_nav(
                    raw_nav
                )

                if nav_value is None:
                    invalid += 1
                    continue

                # --------------------------------------------
                # DUPLICATE
                # --------------------------------------------

                if formatted_date in existing_dates:

                    duplicates += 1
                    continue

                # --------------------------------------------
                # ADD HISTORY
                # --------------------------------------------

                history.append(
                    {
                        "nav": nav_value,
                        "date": formatted_date,
                    }
                )

                existing_dates.add(
                    formatted_date
                )

                new_records += 1

            except (
                ValueError,
                TypeError,
                KeyError,
            ):
                invalid += 1

        # ----------------------------------------------------
        # SORT HISTORY
        # ----------------------------------------------------

        def history_date(entry):

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

        history.sort(
            key=history_date
        )

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        if new_records > 0:

            scheme.nav_history = history

            scheme.save(
                update_fields=[
                    "nav_history",
                ]
            )

        # ----------------------------------------------------
        # DATE INFORMATION
        # ----------------------------------------------------

        valid_dates = []

        for entry in history:

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

            oldest_date = min(
                valid_dates
            ).strftime(
                "%d-%m-%Y"
            )

            latest_date = max(
                valid_dates
            ).strftime(
                "%d-%m-%Y"
            )

        total_stored = len(history)

    return {
        "new_records": new_records,
        "duplicates": duplicates,
        "invalid": invalid,
        "total_stored": total_stored,
        "oldest_date": oldest_date,
        "latest_date": latest_date,
    }


# ============================================================
# DJANGO COMMAND
# ============================================================

class Command(BaseCommand):

    help = (
        "Backfill complete historical NAV data "
        "from MFAPI for one mutual fund scheme."
    )

    # ========================================================
    # ARGUMENTS
    # ========================================================

    def add_arguments(self, parser):

        parser.add_argument(
            "--scheme-code",
            type=str,
            help=(
                "Backfill one scheme using "
                "scheme code."
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

        scheme_code = options.get(
            "scheme_code"
        )

        if not scheme_code:

            raise CommandError(
                "Please provide "
                "--scheme-code <scheme_code>."
            )

        scheme_code = str(
            scheme_code
        ).strip()

        # ====================================================
        # FIND SCHEME
        # ====================================================

        scheme = (
            MutualFundScheme.objects
            .select_related(
                "fund_house"
            )
            .filter(
                scheme_code=scheme_code
            )
            .first()
        )

        if scheme is None:

            raise CommandError(
                f"Scheme {scheme_code} "
                f"does not exist."
            )

        # ====================================================
        # DISPLAY
        # ====================================================

        self.stdout.write("")

        self.stdout.write(
            self.style.WARNING(
                "Starting historical NAV backfill..."
            )
        )

        self.stdout.write(
            f"Scheme Code : "
            f"{scheme.scheme_code}"
        )

        self.stdout.write(
            f"Scheme Name : "
            f"{scheme.scheme_name}"
        )

        self.stdout.write(
            f"Fund House  : "
            f"{scheme.fund_house.name}"
        )

        self.stdout.write(
            f"ISIN Growth : "
            f"{scheme.isin_growth}"
        )

        # ====================================================
        # FETCH
        # ====================================================

        try:

            records = fetch_mfapi_scheme(
                scheme.scheme_code
            )

        except Exception as error:

            raise CommandError(
                f"MFAPI request failed: "
                f"{error}"
            )

        self.stdout.write(
            f"MFAPI returned "
            f"{len(records)} NAV records."
        )

        # ====================================================
        # MERGE
        # ====================================================

        result = merge_nav_history(
            scheme_code=scheme.scheme_code,
            records=records,
        )

        # ====================================================
        # RESULT
        # ====================================================

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                "Historical NAV backfill completed."
            )
        )

        self.stdout.write(
            f"Total MFAPI records : "
            f"{len(records)}"
        )

        self.stdout.write(
            f"New records added   : "
            f"{result['new_records']}"
        )

        self.stdout.write(
            f"Duplicates skipped  : "
            f"{result['duplicates']}"
        )

        self.stdout.write(
            f"Invalid records     : "
            f"{result['invalid']}"
        )

        self.stdout.write(
            f"Total stored history: "
            f"{result['total_stored']}"
        )

        self.stdout.write(
            f"Oldest NAV date     : "
            f"{result['oldest_date']}"
        )

        self.stdout.write(
            f"Latest NAV date     : "
            f"{result['latest_date']}"
        )

        self.stdout.write("")

        self.stdout.write(
            "Existing daily AMFI "
            "synchronization was not modified."
        )


# from datetime import datetime
# from decimal import Decimal, InvalidOperation
#
# import requests
#
# from django.core.management.base import BaseCommand
#
# from apps.mutual_funds.models import MutualFundScheme
#
# MFAPI_BASE_URL = "https://api.mfapi.in/mf"
#
#
# class Command(BaseCommand):
#     help = "Backfill complete historical NAV data for mutual fund schemes."
#
#     def add_arguments(self, parser):
#         parser.add_argument(
#             "--scheme-code",
#             type=str,
#             help="Backfill historical NAV for one scheme only.",
#         )
#
#         parser.add_argument(
#             "--all",
#             action="store_true",
#             help="Backfill historical NAV for all mutual fund schemes.",
#         )
#
#     def handle(self, *args, **options):
#
#         scheme_code = options.get("scheme_code")
#         process_all = options.get("all")
#
#         # ============================================================
#         # VALIDATE ARGUMENTS
#         # ============================================================
#
#         if not scheme_code and not process_all:
#             self.stdout.write(
#                 self.style.ERROR(
#                     "Please provide either "
#                     "--scheme-code <scheme_code> "
#                     "or --all."
#                 )
#             )
#
#             return
#
#         if scheme_code and process_all:
#             self.stdout.write(
#                 self.style.ERROR(
#                     "Use either --scheme-code or --all, not both."
#                 )
#             )
#
#             return
#
#         # ============================================================
#         # SINGLE SCHEME
#         # ============================================================
#
#         if scheme_code:
#
#             try:
#
#                 scheme = MutualFundScheme.objects.select_related(
#                     "fund_house"
#                 ).get(
#                     scheme_code=str(scheme_code).strip()
#                 )
#
#             except MutualFundScheme.DoesNotExist:
#
#                 self.stdout.write(
#                     self.style.ERROR(
#                         f"Scheme {scheme_code} does not exist."
#                     )
#                 )
#
#                 return
#
#             self.backfill_scheme(scheme)
#
#             return
#
#         # ============================================================
#         # ALL SCHEMES
#         # ============================================================
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
#             self.stdout.write(
#                 self.style.WARNING(
#                     "No mutual fund schemes found."
#                 )
#             )
#
#             return
#
#         self.stdout.write("")
#         self.stdout.write(
#             self.style.SUCCESS(
#                 "Starting historical NAV backfill for ALL schemes..."
#             )
#         )
#         self.stdout.write(
#             f"Total schemes : {total_schemes}"
#         )
#         self.stdout.write("")
#
#         # ============================================================
#         # GLOBAL COUNTERS
#         # ============================================================
#
#         successful_schemes = 0
#         failed_schemes = 0
#
#         total_api_records = 0
#         total_new_records = 0
#         total_duplicates = 0
#         total_invalid = 0
#
#         # ============================================================
#         # PROCESS EVERY SCHEME
#         # ============================================================
#
#         for index, scheme in enumerate(
#                 schemes.iterator(),
#                 start=1,
#         ):
#
#             self.stdout.write(
#                 f"[{index}/{total_schemes}] "
#                 f"Processing scheme {scheme.scheme_code}..."
#             )
#
#             try:
#
#                 result = self.backfill_scheme(
#                     scheme,
#                     show_details=False,
#                 )
#
#                 successful_schemes += 1
#
#                 total_api_records += result["api_records"]
#                 total_new_records += result["new_records"]
#                 total_duplicates += result["duplicates"]
#                 total_invalid += result["invalid"]
#
#                 self.stdout.write(
#                     self.style.SUCCESS(
#                         f"    SUCCESS | "
#                         f"API: {result['api_records']} | "
#                         f"New: {result['new_records']} | "
#                         f"Duplicates: {result['duplicates']} | "
#                         f"Invalid: {result['invalid']}"
#                     )
#                 )
#
#             except Exception as error:
#
#                 failed_schemes += 1
#
#                 self.stdout.write(
#                     self.style.ERROR(
#                         f"    FAILED | "
#                         f"Scheme {scheme.scheme_code} | "
#                         f"{error}"
#                     )
#                 )
#
#                 # ----------------------------------------------------
#                 # IMPORTANT
#                 #
#                 # One failed scheme must NOT stop the entire process.
#                 # ----------------------------------------------------
#
#                 continue
#
#         # ============================================================
#         # FINAL SUMMARY
#         # ============================================================
#
#         self.stdout.write("")
#         self.stdout.write("=" * 70)
#
#         self.stdout.write(
#             self.style.SUCCESS(
#                 "Historical NAV backfill completed."
#             )
#         )
#
#         self.stdout.write("")
#         self.stdout.write(
#             f"Total schemes processed : {total_schemes}"
#         )
#
#         self.stdout.write(
#             f"Successful schemes      : {successful_schemes}"
#         )
#
#         self.stdout.write(
#             f"Failed schemes          : {failed_schemes}"
#         )
#
#         self.stdout.write("")
#
#         self.stdout.write(
#             f"Total MFAPI records     : {total_api_records}"
#         )
#
#         self.stdout.write(
#             f"Total new records       : {total_new_records}"
#         )
#
#         self.stdout.write(
#             f"Total duplicates skipped: {total_duplicates}"
#         )
#
#         self.stdout.write(
#             f"Total invalid records   : {total_invalid}"
#         )
#
#         self.stdout.write("")
#         self.stdout.write(
#             "Existing daily AMFI synchronization "
#             "was not modified."
#         )
#
#         self.stdout.write("=" * 70)
#
#     # ================================================================
#     # BACKFILL ONE SCHEME
#     # ================================================================
#
#     def backfill_scheme(
#             self,
#             scheme,
#             show_details=True,
#     ):
#
#         if show_details:
#             self.stdout.write("")
#             self.stdout.write(
#                 "Starting historical NAV backfill..."
#             )
#
#             self.stdout.write(
#                 f"Scheme Code : {scheme.scheme_code}"
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
#                 f"ISIN Growth : {scheme.isin_growth}"
#             )
#
#         # ============================================================
#         # FETCH MFAPI
#         # ============================================================
#
#         url = (
#             f"{MFAPI_BASE_URL}/"
#             f"{scheme.scheme_code}"
#         )
#
#         response = requests.get(
#             url,
#             timeout=30,
#         )
#
#         response.raise_for_status()
#
#         data = response.json()
#
#         # ============================================================
#         # VALIDATE RESPONSE
#         # ============================================================
#
#         if data.get("status") != "SUCCESS":
#             raise ValueError(
#                 f"MFAPI returned status: "
#                 f"{data.get('status')}"
#             )
#
#         records = data.get("data") or []
#
#         if not records:
#             raise ValueError(
#                 "MFAPI returned no NAV records."
#             )
#
#         api_records = len(records)
#
#         if show_details:
#             self.stdout.write(
#                 f"MFAPI returned "
#                 f"{api_records} NAV records."
#             )
#
#         # ============================================================
#         # EXISTING HISTORY
#         # ============================================================
#
#         history = scheme.nav_history or []
#
#         if not isinstance(history, list):
#             history = []
#
#         # ============================================================
#         # EXISTING DATES
#         #
#         # This makes duplicate checking much faster than checking
#         # every dictionary repeatedly.
#         # ============================================================
#
#         existing_dates = set()
#
#         for entry in history:
#
#             if not isinstance(entry, dict):
#                 continue
#
#             entry_date = entry.get("date")
#
#             if entry_date:
#                 existing_dates.add(
#                     str(entry_date).strip()
#                 )
#
#         # ============================================================
#         # COUNTERS
#         # ============================================================
#
#         new_records = 0
#         duplicates = 0
#         invalid = 0
#
#         # ============================================================
#         # PROCESS MFAPI RECORDS
#         # ============================================================
#
#         for record in records:
#
#             try:
#
#                 raw_date = record.get("date")
#                 raw_nav = record.get("nav")
#
#                 if not raw_date or raw_nav is None:
#                     invalid += 1
#                     continue
#
#                 # ----------------------------------------------------
#                 # DATE
#                 #
#                 # MFAPI format:
#                 #
#                 # 25-06-2013
#                 # ----------------------------------------------------
#
#                 parsed_date = datetime.strptime(
#                     str(raw_date).strip(),
#                     "%d-%m-%Y",
#                 )
#
#                 formatted_date = (
#                     parsed_date.strftime("%d-%m-%Y")
#                 )
#
#                 # ----------------------------------------------------
#                 # NAV
#                 # ----------------------------------------------------
#
#                 nav_value = str(
#                     raw_nav
#                 ).strip()
#
#                 if not nav_value:
#                     invalid += 1
#                     continue
#
#                 try:
#
#                     Decimal(nav_value)
#
#                 except (
#                         InvalidOperation,
#                         ValueError,
#                 ):
#
#                     invalid += 1
#                     continue
#
#                 # ----------------------------------------------------
#                 # DUPLICATE DATE
#                 # ----------------------------------------------------
#
#                 if formatted_date in existing_dates:
#                     duplicates += 1
#                     continue
#
#                 # ----------------------------------------------------
#                 # ADD HISTORY
#                 # ----------------------------------------------------
#
#                 history.append(
#                     {
#                         "nav": nav_value,
#                         "date": formatted_date,
#                     }
#                 )
#
#                 existing_dates.add(
#                     formatted_date
#                 )
#
#                 new_records += 1
#
#             except Exception:
#
#                 invalid += 1
#
#         # ============================================================
#         # SORT HISTORY
#         #
#         # Oldest date -> newest date
#         # ============================================================
#
#         def history_date(entry):
#
#             try:
#
#                 return datetime.strptime(
#                     entry["date"],
#                     "%d-%m-%Y",
#                 )
#
#             except (
#                     ValueError,
#                     TypeError,
#                     KeyError,
#             ):
#
#                 return datetime.min
#
#         history.sort(
#             key=history_date
#         )
#
#         # ============================================================
#         # SAVE
#         # ============================================================
#
#         if new_records > 0:
#             scheme.nav_history = history
#
#             scheme.save(
#                 update_fields=[
#                     "nav_history",
#                 ]
#             )
#
#         # ============================================================
#         # FINAL INFORMATION
#         # ============================================================
#
#         total_stored_history = len(
#             history
#         )
#
#         oldest_nav_date = None
#         latest_nav_date = None
#
#         valid_dates = []
#
#         for entry in history:
#
#             try:
#
#                 valid_dates.append(
#                     datetime.strptime(
#                         entry["date"],
#                         "%d-%m-%Y",
#                     )
#                 )
#
#             except (
#                     ValueError,
#                     TypeError,
#                     KeyError,
#             ):
#
#                 continue
#
#         if valid_dates:
#             oldest_nav_date = min(
#                 valid_dates
#             ).strftime("%d-%m-%Y")
#
#             latest_nav_date = max(
#                 valid_dates
#             ).strftime("%d-%m-%Y")
#
#         # ============================================================
#         # SINGLE SCHEME OUTPUT
#         # ============================================================
#
#         if show_details:
#             self.stdout.write("")
#
#             self.stdout.write(
#                 self.style.SUCCESS(
#                     "Historical NAV backfill completed."
#                 )
#             )
#
#             self.stdout.write(
#                 f"Total MFAPI records : {api_records}"
#             )
#
#             self.stdout.write(
#                 f"New records added   : {new_records}"
#             )
#
#             self.stdout.write(
#                 f"Duplicates skipped  : {duplicates}"
#             )
#
#             self.stdout.write(
#                 f"Invalid records     : {invalid}"
#             )
#
#             self.stdout.write(
#                 f"Total stored history: "
#                 f"{total_stored_history}"
#             )
#
#             self.stdout.write(
#                 f"Oldest NAV date     : "
#                 f"{oldest_nav_date}"
#             )
#
#             self.stdout.write(
#                 f"Latest NAV date     : "
#                 f"{latest_nav_date}"
#             )
#
#             self.stdout.write("")
#
#             self.stdout.write(
#                 "Existing daily AMFI synchronization "
#                 "was not modified."
#             )
#
#         return {
#             "api_records": api_records,
#             "new_records": new_records,
#             "duplicates": duplicates,
#             "invalid": invalid,
#             "total_stored": total_stored_history,
#             "oldest_date": oldest_nav_date,
#             "latest_date": latest_nav_date,
#         }
# # import requests
# #
# # from decimal import Decimal, InvalidOperation
# # from datetime import datetime
# #
# # from django.core.management.base import BaseCommand, CommandError
# # from django.db import transaction
# #
# # from apps.mutual_funds.models import (
# #     FundHouse,
# #     MutualFundScheme,
# # )
# #
# #
# # # ============================================================
# # # MFAPI SOURCE
# # # ============================================================
# #
# # MFAPI_URL = "https://api.mfapi.in/mf/{scheme_code}"
# #
# #
# # # ============================================================
# # # HELPERS
# # # ============================================================
# #
# # def clean_nav(value):
# #     """
# #     Convert NAV value into a clean string.
# #
# #     We store NAV inside JSON as a string so that
# #     Decimal precision is not lost.
# #     """
# #
# #     if value is None:
# #         return None
# #
# #     value = str(value).strip()
# #
# #     if not value:
# #         return None
# #
# #     try:
# #         Decimal(value)
# #     except (InvalidOperation, ValueError):
# #         return None
# #
# #     return value
# #
# #
# # def parse_mfapi_date(value):
# #     """
# #     Convert MFAPI date:
# #
# #         25-06-2013
# #
# #     into Python date.
# #     """
# #
# #     return datetime.strptime(
# #         value.strip(),
# #         "%d-%m-%Y",
# #     ).date()
# #
# #
# # def format_nav_date(value):
# #     """
# #     Convert Python date into our JSON format:
# #
# #         25-06-2013
# #     """
# #
# #     return value.strftime("%d-%m-%Y")
# #
# #
# # # ============================================================
# # # FETCH MFAPI DATA
# # # ============================================================
# #
# # def fetch_mfapi_scheme(scheme_code):
# #     """
# #     Fetch complete historical data for one scheme
# #     from MFAPI.
# #
# #     Example:
# #
# #         https://api.mfapi.in/mf/122612
# #     """
# #
# #     url = MFAPI_URL.format(
# #         scheme_code=scheme_code
# #     )
# #
# #     response = requests.get(
# #         url,
# #         timeout=60,
# #     )
# #
# #     response.raise_for_status()
# #
# #     data = response.json()
# #
# #     if data.get("status") != "SUCCESS":
# #         raise ValueError(
# #             f"MFAPI returned unsuccessful status for "
# #             f"scheme {scheme_code}."
# #         )
# #
# #     meta = data.get("meta") or {}
# #     history = data.get("data") or []
# #
# #     if not history:
# #         raise ValueError(
# #             f"No historical NAV data returned for "
# #             f"scheme {scheme_code}."
# #         )
# #
# #     return meta, history
# #
# #
# # # ============================================================
# # # DJANGO COMMAND
# # # ============================================================
# #
# # class Command(BaseCommand):
# #
# #     help = (
# #         "Backfill complete historical NAV data from MFAPI "
# #         "without modifying the existing daily AMFI sync."
# #     )
# #
# #     # --------------------------------------------------------
# #     # ARGUMENTS
# #     # --------------------------------------------------------
# #
# #     def add_arguments(self, parser):
# #
# #         parser.add_argument(
# #             "--scheme-code",
# #             type=str,
# #             help="Backfill one scheme using scheme code.",
# #         )
# #
# #         parser.add_argument(
# #             "--isin",
# #             type=str,
# #             help="Backfill one scheme using ISIN growth.",
# #         )
# #
# #     # --------------------------------------------------------
# #     # HANDLE
# #     # --------------------------------------------------------
# #
# #     def handle(self, *args, **options):
# #
# #         scheme_code = options.get(
# #             "scheme_code"
# #         )
# #
# #         isin = options.get(
# #             "isin"
# #         )
# #
# #         # ====================================================
# #         # AT LEAST ONE IDENTIFIER REQUIRED
# #         # ====================================================
# #
# #         if not scheme_code and not isin:
# #
# #             raise CommandError(
# #                 "Please provide either "
# #                 "--scheme-code or --isin."
# #             )
# #
# #         if scheme_code and isin:
# #
# #             raise CommandError(
# #                 "Use only one identifier at a time: "
# #                 "--scheme-code OR --isin."
# #             )
# #
# #         # ====================================================
# #         # FIND SCHEME
# #         # ====================================================
# #
# #         if scheme_code:
# #
# #             scheme = (
# #                 MutualFundScheme.objects
# #                 .select_related("fund_house")
# #                 .filter(
# #                     scheme_code=str(
# #                         scheme_code
# #                     ).strip()
# #                 )
# #                 .first()
# #             )
# #
# #         else:
# #
# #             scheme = (
# #                 MutualFundScheme.objects
# #                 .select_related("fund_house")
# #                 .filter(
# #                     isin_growth__iexact=str(
# #                         isin
# #                     ).strip()
# #                 )
# #                 .first()
# #             )
# #
# #         if scheme is None:
# #
# #             identifier = (
# #                 scheme_code
# #                 if scheme_code
# #                 else isin
# #             )
# #
# #             raise CommandError(
# #                 f"No MutualFundScheme found for "
# #                 f"identifier: {identifier}"
# #             )
# #
# #         # ====================================================
# #         # DISPLAY INFORMATION
# #         # ====================================================
# #
# #         self.stdout.write(
# #             self.style.WARNING(
# #                 "\nStarting historical NAV backfill..."
# #             )
# #         )
# #
# #         self.stdout.write(
# #             f"Scheme Code : {scheme.scheme_code}"
# #         )
# #
# #         self.stdout.write(
# #             f"Scheme Name : {scheme.scheme_name}"
# #         )
# #
# #         self.stdout.write(
# #             f"Fund House  : {scheme.fund_house.name}"
# #         )
# #
# #         self.stdout.write(
# #             f"ISIN Growth : {scheme.isin_growth}"
# #         )
# #
# #         # ====================================================
# #         # FETCH MFAPI
# #         # ====================================================
# #
# #         try:
# #
# #             meta, history = fetch_mfapi_scheme(
# #                 scheme.scheme_code
# #             )
# #
# #         except Exception as error:
# #
# #             raise CommandError(
# #                 f"Failed to fetch MFAPI data: {error}"
# #             )
# #
# #         # ====================================================
# #         # META INFORMATION
# #         # ====================================================
# #
# #         self.stdout.write(
# #             f"\nMFAPI returned {len(history)} NAV records."
# #         )
# #
# #         # ====================================================
# #         # EXISTING HISTORY
# #         # ====================================================
# #
# #         existing_history = (
# #             scheme.nav_history or []
# #         )
# #
# #         if not isinstance(
# #             existing_history,
# #             list,
# #         ):
# #             existing_history = []
# #
# #         # ====================================================
# #         # BUILD EXISTING DATE SET
# #         # ====================================================
# #
# #         existing_dates = set()
# #
# #         for entry in existing_history:
# #
# #             if not isinstance(
# #                 entry,
# #                 dict,
# #             ):
# #                 continue
# #
# #             entry_date = entry.get(
# #                 "date"
# #             )
# #
# #             if entry_date:
# #
# #                 existing_dates.add(
# #                     entry_date
# #                 )
# #
# #         # ====================================================
# #         # PROCESS HISTORICAL DATA
# #         # ====================================================
# #
# #         new_entries = []
# #
# #         invalid_records = 0
# #
# #         duplicate_records = 0
# #
# #         for item in history:
# #
# #             if not isinstance(
# #                 item,
# #                 dict,
# #             ):
# #                 invalid_records += 1
# #                 continue
# #
# #             raw_date = item.get(
# #                 "date"
# #             )
# #
# #             raw_nav = item.get(
# #                 "nav"
# #             )
# #
# #             if not raw_date or raw_nav is None:
# #
# #                 invalid_records += 1
# #                 continue
# #
# #             try:
# #
# #                 nav_date = parse_mfapi_date(
# #                     raw_date
# #                 )
# #
# #             except ValueError:
# #
# #                 invalid_records += 1
# #                 continue
# #
# #             nav = clean_nav(
# #                 raw_nav
# #             )
# #
# #             if nav is None:
# #
# #                 invalid_records += 1
# #                 continue
# #
# #             formatted_date = format_nav_date(
# #                 nav_date
# #             )
# #
# #             # ----------------------------------------------
# #             # DUPLICATE CHECK
# #             # ----------------------------------------------
# #
# #             if formatted_date in existing_dates:
# #
# #                 duplicate_records += 1
# #                 continue
# #
# #             # ----------------------------------------------
# #             # ADD NEW HISTORY
# #             # ----------------------------------------------
# #
# #             new_entries.append(
# #                 {
# #                     "date": formatted_date,
# #                     "nav": nav,
# #                 }
# #             )
# #
# #             existing_dates.add(
# #                 formatted_date
# #             )
# #
# #         # ====================================================
# #         # SORT HISTORY
# #         # ====================================================
# #
# #         combined_history = (
# #             existing_history
# #             + new_entries
# #         )
# #
# #         combined_history.sort(
# #             key=lambda entry: datetime.strptime(
# #                 entry["date"],
# #                 "%d-%m-%Y",
# #             )
# #         )
# #
# #         # ====================================================
# #         # SAVE
# #         # ====================================================
# #
# #         with transaction.atomic():
# #
# #             scheme.nav_history = (
# #                 combined_history
# #             )
# #
# #             scheme.save(
# #                 update_fields=[
# #                     "nav_history",
# #                 ]
# #             )
# #
# #         # ====================================================
# #         # RESULT
# #         # ====================================================
# #
# #         self.stdout.write("")
# #
# #         self.stdout.write(
# #             self.style.SUCCESS(
# #                 "Historical NAV backfill completed."
# #             )
# #         )
# #
# #         self.stdout.write(
# #             f"Total MFAPI records : {len(history)}"
# #         )
# #
# #         self.stdout.write(
# #             f"New records added   : {len(new_entries)}"
# #         )
# #
# #         self.stdout.write(
# #             f"Duplicates skipped  : {duplicate_records}"
# #         )
# #
# #         self.stdout.write(
# #             f"Invalid records     : {invalid_records}"
# #         )
# #
# #         self.stdout.write(
# #             f"Total stored history: "
# #             f"{len(combined_history)}"
# #         )
# #
# #         # ====================================================
# #         # DATE RANGE
# #         # ====================================================
# #
# #         if combined_history:
# #
# #             first_date = combined_history[0]["date"]
# #
# #             last_date = combined_history[-1]["date"]
# #
# #             self.stdout.write(
# #                 f"Oldest NAV date     : {first_date}"
# #             )
# #
# #             self.stdout.write(
# #                 f"Latest NAV date     : {last_date}"
# #             )
# #
# #         self.stdout.write(
# #             self.style.SUCCESS(
# #                 "\nExisting daily AMFI synchronization "
# #                 "was not modified."
# #             )
# #         )