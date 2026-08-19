from django.contrib import admin
from django.db.models import Q
from django.db.models.fields.json import KeyTextTransform


from .models import (
    FundHouse,
    MutualFundScheme,
    NAVSyncLog,
)


# ============================================================
# ADMIN SITE
# ============================================================

admin.site.site_header = "AMFI Mutual Fund Administration"
admin.site.site_title = "AMFI Admin"
admin.site.index_title = "Mutual Fund Management"


# ============================================================
# FUND HOUSE ADMIN
# ============================================================

@admin.register(FundHouse)
class FundHouseAdmin(admin.ModelAdmin):

    # --------------------------------------------------------
    # LIST DISPLAY
    # --------------------------------------------------------

    list_display = (
        "name",
        "number_of_schemes",
        "active_status",
    )

    list_display_links = (
        "name",
    )

    # --------------------------------------------------------
    # SEARCH
    # --------------------------------------------------------

    search_fields = (
        "name",
    )

    # --------------------------------------------------------
    # FILTERS
    # --------------------------------------------------------

    list_filter = (
        "is_active",
    )

    # --------------------------------------------------------
    # ORDERING
    # --------------------------------------------------------

    ordering = (
        "name",
    )

    # --------------------------------------------------------
    # PAGINATION
    # --------------------------------------------------------

    list_per_page = 50

    # --------------------------------------------------------
    # PERFORMANCE
    # --------------------------------------------------------

    show_full_result_count = False

    # --------------------------------------------------------
    # FORM
    # --------------------------------------------------------

    fields = (
        "name",
        "number_of_schemes",
        "is_active",
    )

    readonly_fields = (
        "number_of_schemes",
    )

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    @admin.display(
        description="Status",
        boolean=True,
        ordering="is_active",
    )
    def active_status(self, obj):
        return obj.is_active


# ============================================================
# MUTUAL FUND SCHEME ADMIN
# ============================================================

@admin.register(MutualFundScheme)
class MutualFundSchemeAdmin(admin.ModelAdmin):

    # ========================================================
    # LIST DISPLAY
    # ========================================================

    list_display = (
        "scheme_code",
        "scheme_name_display",
        "fund_house",
        "isin_growth",
        "scheme_type",
        "scheme_category",
        "latest_nav",
        "latest_nav_date",
        "active_status",
    )

    list_display_links = (
        "scheme_code",
        "scheme_name_display",
    )

    # ========================================================
    # SEARCH
    # ========================================================

    search_fields = (
        "scheme_code",
        "isin_growth",
        "scheme_name",
        "fund_house__name",
    )

    search_help_text = (
        "Search by scheme code, ISIN, scheme name, "
        "or fund house."
    )

    # ========================================================
    # FILTERS
    # ========================================================

    list_filter = (
        "is_active",
        "scheme_type",
        "scheme_category",
        "fund_house",
    )

    # ========================================================
    # DEFAULT ORDERING
    # ========================================================

    ordering = (
        "scheme_code",
    )

    # ========================================================
    # PAGINATION
    # ========================================================

    list_per_page = 25

    # Do not run an expensive COUNT(*) for every request.
    show_full_result_count = False

    # ========================================================
    # DATABASE OPTIMIZATION
    # ========================================================

    list_select_related = (
        "fund_house",
    )

    # ========================================================
    # FORM FIELD GROUPING
    # ========================================================

    fieldsets = (
        (
            "Scheme Information",
            {
                "fields": (
                    "scheme_code",
                    "scheme_name",
                    "fund_house",
                ),
            },
        ),
        (
            "Classification",
            {
                "fields": (
                    "scheme_type",
                    "scheme_category",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "ISIN Information",
            {
                "fields": (
                    "isin_growth",
                    "isin_div_payout",
                    "isin_div_reinvestment",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "is_active",
                ),
            },
        ),
        (
            "NAV History",
            {
                "fields": (
                    "data",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )

    # ========================================================
    # QUERYSET OPTIMIZATION
    # ========================================================

    def get_queryset(self, request):

        queryset = super().get_queryset(request)

        # ----------------------------------------------------
        # IMPORTANT
        #
        # data contains potentially thousands of NAV records.
        #
        # The Admin LIST page does NOT need the entire JSON.
        #
        # We therefore defer loading the huge JSON column.
        #
        # Only data[0].nav and data[0].date are extracted by
        # PostgreSQL for the list page.
        # ----------------------------------------------------

        queryset = (
            queryset
            .select_related(
                "fund_house",
            )
            .annotate(
                admin_latest_nav=KeyTextTransform(
                    "nav",
                    KeyTextTransform(
                        "0",
                        "data",
                    ),
                ),
                admin_latest_nav_date=KeyTextTransform(
                    "date",
                    KeyTextTransform(
                        "0",
                        "data",
                    ),
                ),
            )
            .defer(
                "data",
            )
        )

        return queryset

    # ========================================================
    # SCHEME NAME
    # ========================================================

    @admin.display(
        description="Scheme Name",
        ordering="scheme_name",
    )
    def scheme_name_display(self, obj):

        return obj.scheme_name

    # ========================================================
    # LATEST NAV
    # ========================================================

    @admin.display(
        description="Latest NAV",
        ordering=False,
    )
    def latest_nav(self, obj):

        value = getattr(
            obj,
            "admin_latest_nav",
            None,
        )

        if value is None:
            return "-"

        return value

    # ========================================================
    # LATEST NAV DATE
    # ========================================================

    @admin.display(
        description="Latest NAV Date",
        ordering=False,
    )
    def latest_nav_date(self, obj):

        value = getattr(
            obj,
            "admin_latest_nav_date",
            None,
        )

        if value is None:
            return "-"

        return value

    # ========================================================
    # ACTIVE STATUS
    # ========================================================

    @admin.display(
        description="Status",
        boolean=True,
        ordering="is_active",
    )
    def active_status(self, obj):

        return obj.is_active

    # ========================================================
    # CUSTOM SEARCH OPTIMIZATION
    # ========================================================

    def get_search_results(
        self,
        request,
        queryset,
        search_term,
    ):

        search_term = search_term.strip()

        if not search_term:

            return (
                queryset,
                False,
            )

        # ----------------------------------------------------
        # SCHEME CODE
        #
        # Example:
        #
        # 122612
        #
        # Exact lookup is much cheaper than broad text search.
        # ----------------------------------------------------

        if search_term.isdigit():

            queryset = queryset.filter(
                scheme_code=search_term,
            )

            return (
                queryset,
                False,
            )

        # ----------------------------------------------------
        # ISIN
        #
        # Example:
        #
        # INF579M01183
        # ----------------------------------------------------

        if search_term.upper().startswith(
            "INF"
        ):

            queryset = queryset.filter(
                isin_growth__iexact=search_term,
            )

            return (
                queryset,
                False,
            )

        # ----------------------------------------------------
        # NORMAL TEXT SEARCH
        #
        # Scheme name / Fund House
        # ----------------------------------------------------

        queryset = queryset.filter(
            Q(
                scheme_name__icontains=search_term,
            )
            |
            Q(
                fund_house__name__icontains=search_term,
            )
        )

        return (
            queryset,
            False,
        )

    # ========================================================
    # SAVE
    # ========================================================

    def save_model(
        self,
        request,
        obj,
        form,
        change,
    ):

        super().save_model(
            request,
            obj,
            form,
            change,
        )


# ============================================================
# NAV SYNC LOG ADMIN
# ============================================================

@admin.register(NAVSyncLog)
class NAVSyncLogAdmin(admin.ModelAdmin):

    # ========================================================
    # LIST DISPLAY
    # ========================================================

    list_display = (
        "started_at",
        "completed_at",
        "status",
        "records_received",
        "records_created",
        "new_schemes",
        "deactivated_schemes",
        "duplicate_records",
        "error_count",
    )

    # ========================================================
    # FILTERS
    # ========================================================

    list_filter = (
        "status",
    )

    # ========================================================
    # SEARCH
    # ========================================================

    search_fields = (
        "source_url",
        "error_message",
    )

    # ========================================================
    # ORDERING
    # ========================================================

    ordering = (
        "-started_at",
    )

    # ========================================================
    # PAGINATION
    # ========================================================

    list_per_page = 25

    show_full_result_count = False

    # ========================================================
    # READ ONLY
    # ========================================================

    readonly_fields = (
        "started_at",
        "completed_at",
    )

    # ========================================================
    # FORM
    # ========================================================

    fieldsets = (
        (
            "Synchronization",
            {
                "fields": (
                    "started_at",
                    "completed_at",
                    "status",
                    "source_url",
                ),
            },
        ),
        (
            "Statistics",
            {
                "fields": (
                    "records_received",
                    "records_created",
                    "new_schemes",
                    "deactivated_schemes",
                    "duplicate_records",
                    "error_count",
                ),
            },
        ),
        (
            "Errors",
            {
                "fields": (
                    "error_message",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )