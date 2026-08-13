from datetime import datetime

from django.contrib import admin

from .models import (
    FundHouse,
    MutualFundScheme,
    NAVSyncLog,
)


# ============================================================
# FUND HOUSE ADMIN
# ============================================================

@admin.register(FundHouse)
class FundHouseAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "number_of_schemes",
        "is_active",
    )

    search_fields = (
        "name",
    )

    list_filter = (
        "is_active",
    )


# ============================================================
# MUTUAL FUND SCHEME ADMIN
# ============================================================

@admin.register(MutualFundScheme)
class MutualFundSchemeAdmin(admin.ModelAdmin):

    list_display = (
        "scheme_code",
        "scheme_name",
        "fund_house",
        "isin_growth",
        "scheme_type",
        "scheme_category",
        "latest_nav",
        "latest_nav_date",
        "is_active",
    )

    # --------------------------------------------------------
    # ADMIN SEARCH
    #
    # Search using:
    #
    # 122612
    #
    # OR:
    #
    # INF579M01183
    #
    # OR:
    #
    # scheme name
    #
    # OR:
    #
    # fund house
    # --------------------------------------------------------

    search_fields = (
        "scheme_code",
        "isin_growth",
        "scheme_name",
        "fund_house__name",
    )

    list_filter = (
        "is_active",
        "scheme_type",
        "scheme_category",
        "fund_house",
    )

    ordering = (
        "scheme_code",
    )

    # ========================================================
    # LATEST NAV
    # ========================================================

    @admin.display(
        description="Latest NAV",
        ordering=False,
    )
    def latest_nav(self, obj):
        """
        Return the latest NAV from data.

        data structure:

        [
            {
                "nav": "24.2839",
                "date": "10-08-2026"
            },
            {
                "nav": "24.2752",
                "date": "11-08-2026"
            }
        ]

        Result:

            24.2752
        """

        history = obj.data or []

        if not isinstance(history, list):
            return "-"

        valid_entries = []

        for entry in history:

            if not isinstance(entry, dict):
                continue

            nav = entry.get("nav")
            date_value = entry.get("date")

            if nav is None or not date_value:
                continue

            try:
                parsed_date = datetime.strptime(
                    str(date_value).strip(),
                    "%d-%m-%Y",
                )
            except (ValueError, TypeError):
                continue

            valid_entries.append(
                (
                    parsed_date,
                    nav,
                )
            )

        if not valid_entries:
            return "-"

        latest_entry = max(
            valid_entries,
            key=lambda item: item[0],
        )

        return latest_entry[1]

    # ========================================================
    # LATEST NAV DATE
    # ========================================================

    @admin.display(
        description="Latest NAV Date",
        ordering=False,
    )
    def latest_nav_date(self, obj):
        """
        Return the date belonging to the latest NAV.

        Example:

            11-08-2026
        """

        history = obj.data or []

        if not isinstance(history, list):
            return "-"

        latest_date = None

        for entry in history:

            if not isinstance(entry, dict):
                continue

            date_value = entry.get("date")

            if not date_value:
                continue

            try:
                parsed_date = datetime.strptime(
                    str(date_value).strip(),
                    "%d-%m-%Y",
                )
            except (ValueError, TypeError):
                continue

            if (
                latest_date is None
                or parsed_date > latest_date
            ):
                latest_date = parsed_date

        if latest_date is None:
            return "-"

        return latest_date.strftime(
            "%d-%m-%Y"
        )


# ============================================================
# NAV SYNC LOG ADMIN
# ============================================================

@admin.register(NAVSyncLog)
class NAVSyncLogAdmin(admin.ModelAdmin):

    list_display = (
        "started_at",
        "completed_at",
        "status",
        "records_received",
        "records_created",
        "new_schemes",
        "duplicate_records",
        "error_count",
    )

    list_filter = (
        "status",
    )

    search_fields = (
        "source_url",
        "error_message",
    )

    ordering = (
        "-started_at",
    )

    readonly_fields = (
        "started_at",
        "completed_at",
    )