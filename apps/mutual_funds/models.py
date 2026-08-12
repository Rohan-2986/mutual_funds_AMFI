# from django.db import models
#
#
# # ============================================================
# # FUND HOUSE
# # ============================================================
#
# class FundHouse(models.Model):
#     name = models.CharField(
#         max_length=255,
#         unique=True
#     )
#
#     number_of_schemes = models.PositiveIntegerField(
#         default=0
#     )
#
#     is_active = models.BooleanField(
#         default=True
#     )
#
#     def __str__(self):
#         return f"{self.name} - {self.number_of_schemes} schemes"
#
#
# # ============================================================
# # MUTUAL FUND SCHEME
# # ============================================================
#
# class MutualFundScheme(models.Model):
#     fund_house = models.ForeignKey(
#         FundHouse,
#         on_delete=models.PROTECT,
#         related_name="schemes"
#     )
#
#     scheme_code = models.CharField(
#         max_length=50,
#         unique=True
#     )
#
#     scheme_name = models.CharField(
#         max_length=500
#     )
#
#     isin_div_payout = models.CharField(
#         max_length=50,
#         blank=True,
#         null=True
#     )
#
#     isin_div_reinvestment = models.CharField(
#         max_length=50,
#         blank=True,
#         null=True
#     )
#
#     is_active = models.BooleanField(
#         default=True
#     )
#
#     # AMFI scheme lifecycle tracking
#     first_seen_date = models.DateField(
#         null=True,
#         blank=True
#     )
#
#     last_seen_date = models.DateField(
#         null=True,
#         blank=True
#     )
#
#     deactivated_date = models.DateField(
#         null=True,
#         blank=True
#     )
#
#     class Meta:
#         ordering = [
#             "fund_house__name",
#             "scheme_name",
#         ]
#
#     def __str__(self):
#         return f"{self.scheme_code} - {self.scheme_name}"
#
#
# # ============================================================
# # MUTUAL FUND NAV
# # ============================================================
#
# class MutualFundNAV(models.Model):
#     # One scheme can have many NAV records.
#     # The scheme itself is stored only once in MutualFundScheme.
#     scheme = models.ForeignKey(
#         MutualFundScheme,
#         on_delete=models.PROTECT,
#         related_name="nav_history"
#     )
#
#     nav = models.DecimalField(
#         max_digits=20,
#         decimal_places=4
#     )
#
#     repurchase_price = models.DecimalField(
#         max_digits=20,
#         decimal_places=4,
#         null=True,
#         blank=True
#     )
#
#     sale_price = models.DecimalField(
#         max_digits=20,
#         decimal_places=4,
#         null=True,
#         blank=True
#     )
#
#     nav_date = models.DateField()
#
#     class Meta:
#         constraints = [
#             models.UniqueConstraint(
#                 fields=[
#                     "scheme",
#                     "nav_date"
#                 ],
#                 name="unique_scheme_nav_date"
#             )
#         ]
#
#         indexes = [
#             models.Index(
#                 fields=["scheme", "-nav_date"],
#                 name="nav_scheme_date_idx"
#             ),
#             models.Index(
#                 fields=["nav_date"],
#                 name="nav_date_idx"
#             ),
#         ]
#
#         ordering = [
#             "-nav_date"
#         ]
#
#     def __str__(self):
#         return (
#             f"{self.scheme.scheme_name} - "
#             f"{self.nav} - "
#             f"{self.nav_date}"
#         )
#
#
# # ============================================================
# # NAV SYNC LOG
# # ============================================================
#
# class NAVSyncLog(models.Model):
#
#     STATUS_CHOICES = [
#         ("SUCCESS", "Success"),
#         ("PARTIAL", "Partial"),
#         ("FAILED", "Failed"),
#     ]
#
#     started_at = models.DateTimeField()
#
#     completed_at = models.DateTimeField(
#         null=True,
#         blank=True
#     )
#
#     status = models.CharField(
#         max_length=20,
#         choices=STATUS_CHOICES
#     )
#
#     records_received = models.PositiveIntegerField(
#         default=0
#     )
#
#     records_created = models.PositiveIntegerField(
#         default=0
#     )
#
#     new_schemes = models.PositiveIntegerField(
#         default=0
#     )
#
#     deactivated_schemes = models.PositiveIntegerField(
#         default=0
#     )
#
#     duplicate_records = models.PositiveIntegerField(
#         default=0
#     )
#
#     error_count = models.PositiveIntegerField(
#         default=0
#     )
#
#     error_message = models.TextField(
#         blank=True,
#         null=True
#     )
#
#     source_url = models.URLField(
#         max_length=1000,
#         blank=True,
#         null=True
#     )
#
#     def __str__(self):
#         return f"{self.started_at} - {self.status}"
#
#
# ####################################################################################################################################################################################
#
#
# # from django.db import models
# #
# #
# # # ============================================================
# # # FUND HOUSE
# # # ============================================================
# #
# # class FundHouse(models.Model):
# #     name = models.CharField(
# #         max_length=255,
# #         unique=True
# #     )
# #
# #     number_of_schemes = models.PositiveIntegerField(
# #         default=0
# #     )
# #
# #     is_active = models.BooleanField(
# #         default=True
# #     )
# #
# #     created_at = models.DateTimeField(
# #         auto_now_add=True
# #     )
# #
# #     updated_at = models.DateTimeField(
# #         auto_now=True
# #     )
# #
# #     def __str__(self):
# #         return f"{self.name} - {self.number_of_schemes} schemes"
# #
# #
# # # ============================================================
# # # MUTUAL FUND SCHEME
# # # ============================================================
# #
# # class MutualFundScheme(models.Model):
# #
# #     fund_house = models.ForeignKey(
# #         FundHouse,
# #         on_delete=models.PROTECT,
# #         related_name="schemes"
# #     )
# #
# #     scheme_code = models.CharField(
# #         max_length=50,
# #         unique=True
# #     )
# #
# #     scheme_name = models.CharField(
# #         max_length=500
# #     )
# #
# #     isin_div_payout = models.CharField(
# #         max_length=50,
# #         blank=True,
# #         null=True
# #     )
# #
# #     isin_div_reinvestment = models.CharField(
# #         max_length=50,
# #         blank=True,
# #         null=True
# #     )
# #
# #     is_active = models.BooleanField(
# #         default=True
# #     )
# #
# #     first_seen_date = models.DateField(
# #         null=True,
# #         blank=True
# #     )
# #
# #     last_seen_date = models.DateField(
# #         null=True,
# #         blank=True
# #     )
# #
# #     deactivated_date = models.DateField(
# #         null=True,
# #         blank=True
# #     )
# #
# #     created_at = models.DateTimeField(
# #         auto_now_add=True
# #     )
# #
# #     updated_at = models.DateTimeField(
# #         auto_now=True
# #     )
# #
# #     def __str__(self):
# #         return (
# #             f"{self.scheme_code} - "
# #             f"{self.scheme_name}"
# #         )
# #
# #
# # # ============================================================
# # # MUTUAL FUND NAV
# # # ============================================================
# #
# # class MutualFundNAV(models.Model):
# #
# #     scheme = models.ForeignKey(
# #         MutualFundScheme,
# #         on_delete=models.PROTECT,
# #         related_name="nav_history"
# #     )
# #
# #     nav = models.DecimalField(
# #         max_digits=20,
# #         decimal_places=4
# #     )
# #
# #     repurchase_price = models.DecimalField(
# #         max_digits=20,
# #         decimal_places=4,
# #         null=True,
# #         blank=True
# #     )
# #
# #     sale_price = models.DecimalField(
# #         max_digits=20,
# #         decimal_places=4,
# #         null=True,
# #         blank=True
# #     )
# #
# #     nav_date = models.DateField()
# #
# #     created_at = models.DateTimeField(
# #         auto_now_add=True
# #     )
# #
# #     class Meta:
# #         constraints = [
# #             models.UniqueConstraint(
# #                 fields=[
# #                     "scheme",
# #                     "nav_date"
# #                 ],
# #                 name="unique_scheme_nav_date"
# #             )
# #         ]
# #
# #         ordering = [
# #             "-nav_date"
# #         ]
# #
# #     def __str__(self):
# #         return (
# #             f"{self.scheme.scheme_name} - "
# #             f"{self.nav} - "
# #             f"{self.nav_date}"
# #         )
# #
# #
# # # ============================================================
# # # NAV SYNC LOG
# # # ============================================================
# #
# # class NAVSyncLog(models.Model):
# #
# #     STATUS_CHOICES = [
# #         ("SUCCESS", "Success"),
# #         ("PARTIAL", "Partial"),
# #         ("FAILED", "Failed"),
# #     ]
# #
# #     started_at = models.DateTimeField()
# #
# #     completed_at = models.DateTimeField(
# #         null=True,
# #         blank=True
# #     )
# #
# #     status = models.CharField(
# #         max_length=20,
# #         choices=STATUS_CHOICES
# #     )
# #
# #     records_received = models.PositiveIntegerField(
# #         default=0
# #     )
# #
# #     records_created = models.PositiveIntegerField(
# #         default=0
# #     )
# #
# #     new_schemes = models.PositiveIntegerField(
# #         default=0
# #     )
# #
# #     deactivated_schemes = models.PositiveIntegerField(
# #         default=0
# #     )
# #
# #     duplicate_records = models.PositiveIntegerField(
# #         default=0
# #     )
# #
# #     error_count = models.PositiveIntegerField(
# #         default=0
# #     )
# #
# #     error_message = models.TextField(
# #         blank=True,
# #         null=True
# #     )
# #
# #     source_url = models.URLField(
# #         max_length=1000,
# #         blank=True,
# #         null=True
# #     )
# #
# #     def __str__(self):
# #         return (
# #             f"{self.started_at} - "
# #             f"{self.status}"
# #         )

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

    nav_history = models.JSONField(
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


