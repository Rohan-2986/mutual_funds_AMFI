from django.db import models


# ============================================================
# PORTFOLIO
# ============================================================


class Portfolio(models.Model):
    """
    Main portfolio container.

    This model is intentionally independent of Django's User
    model because financial planning and CAS analysis are
    public features.

    Both anonymous and logged-in users can use:

        - Financial planning
        - CAS upload
        - Portfolio analysis
        - Benchmark analysis
        - Suggestions
        - Reports

    Authentication/JWT is reserved for future transactional
    features such as buying/selling mutual funds.

    Investor identity comes from the CAS itself.
    """

    username = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    email = models.EmailField(
        max_length=255,
        blank=True,
        null=True,
    )

    contact = models.CharField(
        max_length=15,
        blank=True,
        null=True,
    )

    pan = models.CharField(
        max_length=10,
        unique=True,
        blank=True,
        null=True,
    )

    portfolio_totals = models.JSONField(
        default=dict,
        blank=True,
    )

    mutual_fund_details = models.JSONField(
        default=list,
        blank=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "-updated_at",
        ]

    def __str__(self):
        identity = (
            self.username
            or self.email
            or self.pan
            or f"Portfolio {self.pk}"
        )

        return str(identity)


# ============================================================
# PORTFOLIO IMPORT
# ============================================================


class PortfolioImport(models.Model):
    """
    Stores CAS import-processing information.

    This is an import/log table only.

    Actual financial portfolio data is stored in Portfolio.

    The CAS password is NEVER stored.
    """

    SOURCE_CHOICES = [
        ("CAS", "CAS"),
        ("API", "API"),
        ("MANUAL", "Manual"),
    ]

    STATUS_CHOICES = [
        ("UPLOADED", "Uploaded"),
        ("PROCESSING", "Processing"),
        ("SUCCESS", "Success"),
        ("PARTIAL", "Partial"),
        ("FAILED", "Failed"),
    ]

    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name="imports",
    )

    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default="CAS",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="UPLOADED",
    )

    file_name = models.CharField(
        max_length=500,
        blank=True,
        null=True,
    )

    records_found = models.PositiveIntegerField(
        default=0,
    )

    records_created = models.PositiveIntegerField(
        default=0,
    )

    records_updated = models.PositiveIntegerField(
        default=0,
    )

    error_message = models.TextField(
        blank=True,
        null=True,
    )

    started_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    completed_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = [
            "-created_at",
        ]

    def __str__(self):
        return (
            f"{self.portfolio} - "
            f"{self.source} - "
            f"{self.status}"
        )