from django.db import models


# ============================================================
# FUND HOUSE
# ============================================================

class FundHouse(models.Model):

    name = models.CharField(
        max_length=255,
        unique=True,
    )

    number_of_schemes = models.PositiveIntegerField(
        default=0,
    )

    is_active = models.BooleanField(
        default=True,
    )

    def __str__(self):
        return self.name


# ============================================================
# MUTUAL FUND SCHEME
# ============================================================

class MutualFundScheme(models.Model):

    fund_house = models.ForeignKey(
        FundHouse,
        on_delete=models.PROTECT,
        related_name="schemes",
    )

    # --------------------------------------------------------
    # Scheme information
    # --------------------------------------------------------

    scheme_code = models.CharField(
        max_length=50,
        unique=True,
    )

    scheme_name = models.CharField(
        max_length=500,
    )

    scheme_type = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    scheme_category = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    isin_growth = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    isin_div_payout = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    isin_div_reinvestment = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    # --------------------------------------------------------
    # Status
    # --------------------------------------------------------

    is_active = models.BooleanField(
        default=True,
    )

    # --------------------------------------------------------
    # COMPLETE NAV HISTORY
    #
    # Every available NAV date is stored.
    #
    # Example:
    #
    # [
    #     {
    #         "date": "10-08-2026",
    #         "nav": "212.76080"
    #     },
    #     {
    #         "date": "11-08-2026",
    #         "nav": "213.12000"
    #     }
    # ]
    #
    # No 100-day limit.
    # No automatic deletion of old NAV history.
    # --------------------------------------------------------

    data = models.JSONField(
        default=list,
        blank=True,
    )

    def __str__(self):
        return (
            f"{self.scheme_code} - "
            f"{self.scheme_name}"
        )


# ============================================================
# NAV SYNC LOG
# ============================================================

class NAVSyncLog(models.Model):

    STATUS_CHOICES = [
        ("SUCCESS", "Success"),
        ("PARTIAL", "Partial"),
        ("FAILED", "Failed"),
    ]

    started_at = models.DateTimeField()

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
    )

    records_received = models.PositiveIntegerField(
        default=0,
    )

    records_created = models.PositiveIntegerField(
        default=0,
    )

    new_schemes = models.PositiveIntegerField(
        default=0,
    )

    deactivated_schemes = models.PositiveIntegerField(
        default=0,
    )

    duplicate_records = models.PositiveIntegerField(
        default=0,
    )

    error_count = models.PositiveIntegerField(
        default=0,
    )

    error_message = models.TextField(
        blank=True,
        null=True,
    )

    source_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
    )

    def __str__(self):
        return (
            f"{self.started_at} - "
            f"{self.status}"
        )


