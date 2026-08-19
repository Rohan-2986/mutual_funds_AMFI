# from datetime import datetime
#
# from django.core.management.base import BaseCommand, CommandError
#
# from apps.mutual_funds.services.nav_sync import sync_nav_data
#
#
# class Command(BaseCommand):
#     help = "Synchronize daily mutual fund NAV data from AMFI"
#
#     def add_arguments(self, parser):
#         parser.add_argument(
#             "--date",
#             type=str,
#             help="Date in DD-Mon-YYYY format, e.g. 09-Aug-2026",
#         )
#
#     def handle(self, *args, **options):
#
#         date_string = options.get("date")
#
#         # If --date is provided, convert it to a date object
#         if date_string:
#             try:
#                 sync_date = datetime.strptime(
#                     date_string,
#                     "%d-%b-%Y"
#                 ).date()
#
#             except ValueError:
#                 raise CommandError(
#                     "Invalid date format. Use DD-Mon-YYYY, "
#                     "for example: 09-Aug-2026"
#                 )
#         else:
#             # If no date is provided, sync_nav_data()
#             # will automatically use today's date
#             sync_date = None
#
#         self.stdout.write(
#             "Starting AMFI NAV synchronization..."
#         )
#
#         log = sync_nav_data(sync_date)
#
#         self.stdout.write(
#             f"NAV synchronization completed: {log.status}"
#         )
#
#         self.stdout.write(
#             f"Records received: {log.records_received}"
#         )
#
#         self.stdout.write(
#             f"Records created: {log.records_created}"
#         )
#
#         self.stdout.write(
#             f"New schemes: {log.new_schemes}"
#         )
#
#         self.stdout.write(
#             f"Deactivated schemes: {log.deactivated_schemes}"
#         )
#
#         self.stdout.write(
#             f"Duplicate records: {log.duplicate_records}"
#         )
#
#         self.stdout.write(
#             f"Errors: {log.error_count}"
#         )

from django.core.management.base import BaseCommand, CommandError
from datetime import datetime

from apps.mutual_funds.services.nav_sync import sync_nav_data


class Command(BaseCommand):
    help = "Synchronize daily mutual fund NAV data from AMFI."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            required=False,
            help="NAV date in DD-MMM-YYYY format. Example: 10-Aug-2026",
        )

        parser.add_argument('--dry-run', action='store_true', help='Parse without saving')

    def handle(self, *args, **options):

        date_string = options.get("date")

        sync_date = None

        # ========================================================
        # OPTIONAL DATE
        # ========================================================

        if date_string:

            try:
                sync_date = datetime.strptime(
                    date_string,
                    "%d-%b-%Y",
                ).date()

            except ValueError:
                raise CommandError(
                    "Invalid date format. "
                    "Use DD-MMM-YYYY. "
                    "Example: 10-Aug-2026"
                )

        # ========================================================
        # START SYNC
        # ========================================================

        self.stdout.write(
            self.style.WARNING(
                "Starting AMFI NAV synchronization..."
            )
        )

        try:

            log = sync_nav_data(
                sync_date=sync_date
            )

        except Exception as error:

            raise CommandError(
                f"NAV synchronization failed: {error}"
            )

        # ========================================================
        # RESULT
        # ========================================================

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                f"NAV synchronization completed: "
                f"{log.status}"
            )
        )

        self.stdout.write(
            f"Records received: "
            f"{log.records_received}"
        )

        self.stdout.write(
            f"Records created: "
            f"{log.records_created}"
        )

        self.stdout.write(
            f"New schemes: "
            f"{log.new_schemes}"
        )

        self.stdout.write(
            f"Deactivated schemes: "
            f"{log.deactivated_schemes}"
        )

        self.stdout.write(
            f"Duplicate records: "
            f"{log.duplicate_records}"
        )

        self.stdout.write(
            f"Errors: "
            f"{log.error_count}"
        )

        # ========================================================
        # ERROR DETAILS
        # ========================================================

        if log.error_message:

            self.stdout.write("")

            self.stdout.write(
                self.style.ERROR(
                    "Error details:"
                )
            )

            self.stdout.write(
                log.error_message
            )