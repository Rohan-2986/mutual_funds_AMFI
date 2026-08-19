import json
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import admin

from .models import (
    Portfolio,
    PortfolioImport,
)


# ============================================================
# JSON ORDER HELPERS
# ============================================================


def order_portfolio_totals(value):
    """
    Force the requested order for Admin display.

    PostgreSQL JSONB does not guarantee object key order.
    """

    if not isinstance(
        value,
        dict,
    ):
        return value

    return {
        "total_cost_value": value.get(
            "total_cost_value"
        ),

        "total_market_value": value.get(
            "total_market_value"
        ),

        "total_gain": value.get(
            "total_gain"
        ),

        "total_gain_percentage": (
            format_percentage(
                value.get(
                    "total_gain_percentage"
                )
            )
        ),

        "total_holdings": value.get(
            "total_holdings"
        ),
    }


def order_mutual_fund_details(value):
    """
    Force the requested order for every mutual-fund object.
    """

    if not isinstance(
        value,
        list,
    ):
        return value

    ordered = []

    for holding in value:

        if not isinstance(
            holding,
            dict,
        ):
            ordered.append(
                holding
            )
            continue

        ordered.append(
            {
                "amc": holding.get(
                    "amc"
                ),

                "amfi_code": holding.get(
                    "amfi_code"
                ),

                "isin": holding.get(
                    "isin"
                ),

                "scheme_name": holding.get(
                    "scheme_name"
                ),

                "asset_type": holding.get(
                    "asset_type"
                ),

                "folio_number": holding.get(
                    "folio_number"
                ),

                "nav": holding.get(
                    "nav"
                ),

                "units": holding.get(
                    "units"
                ),

                "nav_date": holding.get(
                    "nav_date"
                ),

                "current_value": holding.get(
                    "current_value"
                ),

                "invested_value": holding.get(
                    "invested_value"
                ),
            }
        )

    return ordered


def format_percentage(value):
    """
    Format percentage for Admin presentation only.
    """

    if value in (
        None,
        "",
    ):
        return value

    try:

        return format(
            Decimal(
                str(value)
            ),
            ".2f",
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):

        return value


# ============================================================
# PRETTY JSON WIDGET
# ============================================================


class PrettyJSONWidget(
    forms.Textarea
):
    """
    Pretty-print JSON in Django Admin while explicitly
    controlling the requested dictionary order.
    """

    def format_value(self, value):

        if value in (
            None,
            "",
        ):

            return ""

        try:

            if isinstance(
                value,
                str,
            ):

                value = json.loads(
                    value
                )

            # ------------------------------------------------
            # Apply requested ordering.
            # ------------------------------------------------

            if isinstance(
                value,
                dict,
            ) and (
                "total_cost_value" in value
                or "total_market_value" in value
                or "total_gain" in value
            ):

                value = order_portfolio_totals(
                    value
                )

            elif isinstance(
                value,
                list,
            ):

                value = (
                    order_mutual_fund_details(
                        value
                    )
                )

            return json.dumps(
                value,
                indent=4,
                ensure_ascii=False,
            )

        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):

            return super().format_value(
                value
            )


# ============================================================
# PORTFOLIO ADMIN FORM
# ============================================================


class PortfolioAdminForm(
    forms.ModelForm
):

    class Meta:
        model = Portfolio

        fields = "__all__"

        widgets = {
            "portfolio_totals": (
                PrettyJSONWidget(
                    attrs={
                        "rows": 12,
                        "style": (
                            "font-family: monospace; "
                            "white-space: pre;"
                        ),
                    }
                )
            ),

            "mutual_fund_details": (
                PrettyJSONWidget(
                    attrs={
                        "rows": 35,
                        "style": (
                            "font-family: monospace; "
                            "white-space: pre;"
                        ),
                    }
                )
            ),
        }


# ============================================================
# PORTFOLIO ADMIN
# ============================================================


@admin.register(Portfolio)
class PortfolioAdmin(
    admin.ModelAdmin
):

    form = PortfolioAdminForm

    list_display = (
        "id",
        "username",
        "email",
        "contact",
        "pan",
        "updated_at",
    )

    search_fields = (
        "username",
        "email",
        "contact",
        "pan",
    )

    readonly_fields = (
        "updated_at",
    )

    ordering = (
        "-updated_at",
    )

    fieldsets = (
        (
            "Investor Information",
            {
                "fields": (
                    "username",
                    "email",
                    "contact",
                    "pan",
                ),
            },
        ),

        (
            "Portfolio Totals",
            {
                "fields": (
                    "portfolio_totals",
                ),
            },
        ),

        (
            "Mutual Fund Details",
            {
                "fields": (
                    "mutual_fund_details",
                ),
            },
        ),

        (
            "System Information",
            {
                "fields": (
                    "updated_at",
                ),
            },
        ),
    )


# ============================================================
# PORTFOLIO IMPORT ADMIN
# ============================================================


@admin.register(
    PortfolioImport
)
class PortfolioImportAdmin(
    admin.ModelAdmin
):

    list_display = (
        "id",
        "portfolio",
        "source",
        "status",
        "file_name",
        "records_found",
        "records_created",
        "records_updated",
        "started_at",
        "completed_at",
        "created_at",
    )

    list_filter = (
        "source",
        "status",
        "created_at",
    )

    search_fields = (
        "portfolio__username",
        "portfolio__email",
        "portfolio__pan",
        "file_name",
        "error_message",
    )

    readonly_fields = (
        "created_at",
        "started_at",
        "completed_at",
    )

    ordering = (
        "-created_at",
    )