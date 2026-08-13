import time

import requests

from django.core.management.base import BaseCommand

from apps.mutual_funds.models import (
    FundHouse,
    MutualFundScheme,
)


# ============================================================
# MFAPI CONFIGURATION
# ============================================================

MFAPI_BASE_URL = "https://api.mfapi.in/mf"

# Number of schemes requested from MFAPI in one list request.
DEFAULT_PAGE_SIZE = 100

# Small delay between individual scheme requests.
# This helps avoid sending requests too aggressively.
REQUEST_DELAY = 0.10

REQUEST_TIMEOUT = 30


# ============================================================
# MANAGEMENT COMMAND
# ============================================================

class Command(BaseCommand):

    help = (
        "Import mutual fund scheme and fund house metadata "
        "from MFAPI without modifying existing NAV history."
    )

    # ========================================================
    # COMMAND ARGUMENTS
    # ========================================================

    def add_arguments(self, parser):

        parser.add_argument(
            "--max-pages",
            type=int,
            default=None,
            help=(
                "Maximum number of MFAPI list pages to process. "
                "Example: --max-pages 1"
            ),
        )

        parser.add_argument(
            "--page-size",
            type=int,
            default=DEFAULT_PAGE_SIZE,
            help=(
                "Number of schemes requested per MFAPI list request."
            ),
        )

        parser.add_argument(
            "--start-offset",
            type=int,
            default=0,
            help=(
                "Starting MFAPI offset. Useful for resuming "
                "a previously interrupted import."
            ),
        )

        parser.add_argument(
            "--delay",
            type=float,
            default=REQUEST_DELAY,
            help=(
                "Delay in seconds between individual scheme "
                "metadata requests."
            ),
        )

    # ========================================================
    # MAIN COMMAND
    # ========================================================

    def handle(self, *args, **options):

        max_pages = options["max_pages"]
        page_size = options["page_size"]
        start_offset = options["start_offset"]
        delay = options["delay"]

        if page_size <= 0:
            self.stdout.write(
                self.style.ERROR(
                    "page-size must be greater than 0."
                )
            )
            return

        if start_offset < 0:
            self.stdout.write(
                self.style.ERROR(
                    "start-offset cannot be negative."
                )
            )
            return

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Starting historical scheme metadata import..."
            )
        )

        self.stdout.write(
            f"MFAPI page size : {page_size}"
        )

        self.stdout.write(
            f"Starting offset : {start_offset}"
        )

        if max_pages is not None:
            self.stdout.write(
                f"Maximum pages  : {max_pages}"
            )
        else:
            self.stdout.write(
                "Maximum pages  : ALL"
            )

        self.stdout.write("")

        # ====================================================
        # COUNTERS
        # ====================================================

        total_api_schemes = 0
        processed_schemes = 0

        new_fund_houses = 0
        existing_fund_houses = 0

        new_schemes = 0
        existing_schemes = 0

        skipped_schemes = 0
        failed_schemes = 0

        page_number = 0
        offset = start_offset

        # ====================================================
        # SESSION
        # ====================================================

        session = requests.Session()

        session.headers.update(
            {
                "User-Agent": (
                    "AMFI-Mutual-Fund-Project/1.0 "
                    "(historical metadata importer)"
                )
            }
        )

        # ====================================================
        # PAGINATION
        # ====================================================

        while True:

            # -----------------------------------------------
            # MAX PAGE CHECK
            # -----------------------------------------------

            if (
                max_pages is not None
                and page_number >= max_pages
            ):
                break

            page_number += 1

            list_url = (
                f"{MFAPI_BASE_URL}"
                f"?limit={page_size}"
                f"&offset={offset}"
            )

            self.stdout.write(
                self.style.WARNING(
                    f"[Page {page_number}] "
                    f"Requesting schemes "
                    f"(offset={offset}, limit={page_size})"
                )
            )

            # =================================================
            # GET SCHEME LIST
            # =================================================

            try:

                response = session.get(
                    list_url,
                    timeout=REQUEST_TIMEOUT,
                )

                response.raise_for_status()

                scheme_list = response.json()

            except requests.RequestException as error:

                self.stdout.write(
                    self.style.ERROR(
                        f"MFAPI request failed: {error}"
                    )
                )

                self.stdout.write(
                    self.style.ERROR(
                        "Import stopped safely."
                    )
                )

                break

            except ValueError as error:

                self.stdout.write(
                    self.style.ERROR(
                        f"Invalid JSON received from MFAPI: {error}"
                    )
                )

                break

            # =================================================
            # VALIDATE LIST RESPONSE
            # =================================================

            if not isinstance(scheme_list, list):

                self.stdout.write(
                    self.style.ERROR(
                        "Unexpected MFAPI scheme-list response."
                    )
                )

                break

            # -------------------------------------------------
            # NO MORE RECORDS
            # -------------------------------------------------

            if not scheme_list:

                self.stdout.write(
                    self.style.SUCCESS(
                        "MFAPI returned no more schemes."
                    )
                )

                break

            total_api_schemes += len(scheme_list)

            # =================================================
            # PROCESS EACH SCHEME
            # =================================================

            for item_number, item in enumerate(
                scheme_list,
                start=1,
            ):

                if not isinstance(item, dict):

                    skipped_schemes += 1

                    continue

                scheme_code = item.get(
                    "schemeCode"
                )

                scheme_name_from_list = item.get(
                    "schemeName"
                )

                if not scheme_code:

                    skipped_schemes += 1

                    self.stdout.write(
                        self.style.WARNING(
                            "Skipping record without scheme code."
                        )
                    )

                    continue

                scheme_code = str(
                    scheme_code
                ).strip()

                # =================================================
                # GET COMPLETE SCHEME METADATA
                # =================================================

                metadata_url = (
                    f"{MFAPI_BASE_URL}"
                    f"/{scheme_code}"
                )

                try:

                    metadata_response = (
                        session.get(
                            metadata_url,
                            timeout=REQUEST_TIMEOUT,
                        )
                    )

                    metadata_response.raise_for_status()

                    metadata_payload = (
                        metadata_response.json()
                    )

                except requests.RequestException as error:

                    failed_schemes += 1

                    self.stdout.write(
                        self.style.ERROR(
                            f"[{scheme_code}] "
                            f"Metadata request failed: "
                            f"{error}"
                        )
                    )

                    continue

                except ValueError as error:

                    failed_schemes += 1

                    self.stdout.write(
                        self.style.ERROR(
                            f"[{scheme_code}] "
                            f"Invalid metadata JSON: "
                            f"{error}"
                        )
                    )

                    continue

                # =================================================
                # GET META OBJECT
                # =================================================

                metadata = {}

                if isinstance(
                    metadata_payload,
                    dict,
                ):

                    metadata = (
                        metadata_payload.get(
                            "meta"
                        )
                        or {}
                    )

                if not isinstance(
                    metadata,
                    dict,
                ):

                    metadata = {}

                # =================================================
                # BASIC INFORMATION
                # =================================================

                fund_house_name = (
                    metadata.get(
                        "fund_house"
                    )
                    or ""
                ).strip()

                scheme_name = (
                    metadata.get(
                        "scheme_name"
                    )
                    or scheme_name_from_list
                    or ""
                ).strip()

                scheme_type = (
                    metadata.get(
                        "scheme_type"
                    )
                    or None
                )

                scheme_category = (
                    metadata.get(
                        "scheme_category"
                    )
                    or None
                )

                isin_growth = (
                    metadata.get(
                        "isin_growth"
                    )
                    or None
                )

                isin_div_reinvestment = (
                    metadata.get(
                        "isin_div_reinvestment"
                    )
                    or None
                )

                # -------------------------------------------------
                # MFAPI does not always provide dividend payout
                # separately.
                # -------------------------------------------------

                isin_div_payout = (
                    metadata.get(
                        "isin_div_payout"
                    )
                    or None
                )

                # =================================================
                # REQUIRED VALIDATION
                # =================================================

                if not fund_house_name:

                    skipped_schemes += 1

                    self.stdout.write(
                        self.style.WARNING(
                            f"[{scheme_code}] "
                            f"Skipped because fund house "
                            f"metadata is missing."
                        )
                    )

                    continue

                if not scheme_name:

                    skipped_schemes += 1

                    self.stdout.write(
                        self.style.WARNING(
                            f"[{scheme_code}] "
                            f"Skipped because scheme name "
                            f"is missing."
                        )
                    )

                    continue

                # =================================================
                # FUND HOUSE
                # =================================================

                fund_house, fund_house_created = (
                    FundHouse.objects.get_or_create(
                        name=fund_house_name,
                        defaults={
                            "number_of_schemes": 0,
                            "is_active": True,
                        },
                    )
                )

                if fund_house_created:

                    new_fund_houses += 1

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"NEW FUND HOUSE: "
                            f"{fund_house_name}"
                        )
                    )

                else:

                    existing_fund_houses += 1

                # =================================================
                # SCHEME
                # =================================================

                scheme, scheme_created = (
                    MutualFundScheme.objects.get_or_create(
                        scheme_code=scheme_code,
                        defaults={
                            "fund_house": fund_house,
                            "scheme_name": scheme_name,
                            "scheme_type": scheme_type,
                            "scheme_category": scheme_category,
                            "isin_growth": isin_growth,
                            "isin_div_payout": (
                                isin_div_payout
                            ),
                            "isin_div_reinvestment": (
                                isin_div_reinvestment
                            ),
                            "is_active": True,

                            # IMPORTANT:
                            #
                            # Do NOT modify existing
                            # historical NAV data.
                            #
                            "nav_history": [],
                        },
                    )
                )

                # =================================================
                # NEW SCHEME
                # =================================================

                if scheme_created:

                    new_schemes += 1

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"NEW SCHEME: "
                            f"{scheme_code} | "
                            f"{scheme_name}"
                        )
                    )

                # =================================================
                # EXISTING SCHEME
                # =================================================

                else:

                    existing_schemes += 1

                    # ------------------------------------------------
                    # IMPORTANT:
                    #
                    # We only fill missing metadata.
                    #
                    # We DO NOT replace existing values blindly.
                    #
                    # We DO NOT touch nav_history.
                    # ------------------------------------------------

                    changed_fields = []

                    if (
                        not scheme.fund_house_id
                        or scheme.fund_house_id
                        != fund_house.id
                    ):

                        scheme.fund_house = (
                            fund_house
                        )

                        changed_fields.append(
                            "fund_house"
                        )

                    if (
                        not scheme.scheme_name
                        and scheme_name
                    ):

                        scheme.scheme_name = (
                            scheme_name
                        )

                        changed_fields.append(
                            "scheme_name"
                        )

                    if (
                        not scheme.scheme_type
                        and scheme_type
                    ):

                        scheme.scheme_type = (
                            scheme_type
                        )

                        changed_fields.append(
                            "scheme_type"
                        )

                    if (
                        not scheme.scheme_category
                        and scheme_category
                    ):

                        scheme.scheme_category = (
                            scheme_category
                        )

                        changed_fields.append(
                            "scheme_category"
                        )

                    if (
                        not scheme.isin_growth
                        and isin_growth
                    ):

                        scheme.isin_growth = (
                            isin_growth
                        )

                        changed_fields.append(
                            "isin_growth"
                        )

                    if (
                        not scheme.isin_div_payout
                        and isin_div_payout
                    ):

                        scheme.isin_div_payout = (
                            isin_div_payout
                        )

                        changed_fields.append(
                            "isin_div_payout"
                        )

                    if (
                        not scheme.isin_div_reinvestment
                        and isin_div_reinvestment
                    ):

                        scheme.isin_div_reinvestment = (
                            isin_div_reinvestment
                        )

                        changed_fields.append(
                            "isin_div_reinvestment"
                        )

                    if changed_fields:

                        scheme.save(
                            update_fields=(
                                changed_fields
                            )
                        )

                processed_schemes += 1

                # =================================================
                # PROGRESS
                # =================================================

                if (
                    processed_schemes % 10 == 0
                ):

                    self.stdout.write(
                        f"Processed: "
                        f"{processed_schemes} | "
                        f"New schemes: "
                        f"{new_schemes} | "
                        f"Existing: "
                        f"{existing_schemes}"
                    )

                # =================================================
                # REQUEST DELAY
                # =================================================

                if delay > 0:

                    time.sleep(delay)

            # =================================================
            # NEXT PAGE
            # =================================================

            offset += page_size

            # =================================================
            # LAST PARTIAL PAGE
            # =================================================

            if len(scheme_list) < page_size:

                self.stdout.write(
                    self.style.SUCCESS(
                        "Final MFAPI page reached."
                    )
                )

                break

        # ========================================================
        # UPDATE FUND HOUSE COUNTS
        #
        # ========================================================

        self.stdout.write("")
        self.stdout.write(
            "Updating FundHouse scheme counts..."
        )

        for fund_house in FundHouse.objects.all():

            active_scheme_count = (
                fund_house.schemes
                .filter(is_active=True)
                .count()
            )

            fund_house.number_of_schemes = (
                active_scheme_count
            )

            fund_house.is_active = (
                active_scheme_count > 0
            )

            fund_house.save(
                update_fields=[
                    "number_of_schemes",
                    "is_active",
                ]
            )

        # ========================================================
        # FINAL RESULT
        # ========================================================

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "================================================"
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Historical scheme metadata import completed."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "================================================"
            )
        )

        self.stdout.write(
            f"MFAPI schemes received : "
            f"{total_api_schemes}"
        )

        self.stdout.write(
            f"Schemes processed      : "
            f"{processed_schemes}"
        )

        self.stdout.write(
            f"New fund houses        : "
            f"{new_fund_houses}"
        )

        self.stdout.write(
            f"Existing fund houses   : "
            f"{existing_fund_houses}"
        )

        self.stdout.write(
            f"New schemes            : "
            f"{new_schemes}"
        )

        self.stdout.write(
            f"Existing schemes       : "
            f"{existing_schemes}"
        )

        self.stdout.write(
            f"Skipped schemes        : "
            f"{skipped_schemes}"
        )

        self.stdout.write(
            f"Failed schemes         : "
            f"{failed_schemes}"
        )

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                "Existing nav_history was NOT modified."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Existing daily AMFI synchronization "
                "was NOT modified."
            )
        )

        self.stdout.write("")