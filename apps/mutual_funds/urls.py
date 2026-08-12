from django.urls import path

from .views import (
    FundHouseListAPIView,
    MutualFundSchemeListAPIView,
    MutualFundSchemeDetailAPIView,
    MutualFundNAVHistoryAPIView,
    MutualFundNAVHistoryDateAPIView,
    FundHouseSchemesAPIView,
)

urlpatterns = [

    # ========================================================
    # FUND HOUSES
    # ========================================================

    path(
        "",
        FundHouseListAPIView.as_view(),
        name="fund-house-list",
    ),

    # ========================================================
    # ALL SCHEMES
    # ========================================================

    path(
        "schemes/",
        MutualFundSchemeListAPIView.as_view(),
        name="scheme-list",
    ),

    # ========================================================
    # PARTICULAR SCHEME
    # ========================================================

    path(
        "schemes/<str:scheme_code>/",
        MutualFundSchemeDetailAPIView.as_view(),
        name="scheme-detail",
    ),

    # ========================================================
    # COMPLETE NAV HISTORY
    # Scheme Code OR ISIN
    # ========================================================

    path(
        "schemes/<str:scheme_identifier>/nav-history/",
        MutualFundNAVHistoryAPIView.as_view(),
        name="mutual-fund-nav-history",
    ),

    # ========================================================
    # NAV FOR PARTICULAR DATE
    # Scheme Code OR ISIN
    # ========================================================

    path(
        "schemes/<str:scheme_identifier>/nav-history/<str:nav_date>/",
        MutualFundNAVHistoryDateAPIView.as_view(),
        name="mutual-fund-nav-history-date",
    ),

    # ========================================================
    # FUND HOUSE → SCHEMES
    # ========================================================

    path(
        "fund-houses/<int:fund_house_id>/schemes/",
        FundHouseSchemesAPIView.as_view(),
        name="fund-house-schemes",
    ),
]
# from django.urls import path
#
# from .views import (
#     FundHouseListAPIView,
#     MutualFundSchemeListAPIView,
#     MutualFundSchemeDetailAPIView,
#     MutualFundNAVHistoryAPIView,
#     MutualFundNAVHistoryDateAPIView,
#     FundHouseSchemesAPIView,
# )
#
#
# urlpatterns = [
#
#     # ========================================================
#     # FUND HOUSES
#     # ========================================================
#
#     path(
#         "",
#         FundHouseListAPIView.as_view(),
#         name="fund-house-list",
#     ),
#
#     # ========================================================
#     # ALL SCHEMES
#     # ========================================================
#
#     path(
#         "schemes/",
#         MutualFundSchemeListAPIView.as_view(),
#         name="scheme-list",
#     ),
#
#     # ========================================================
#     # PARTICULAR SCHEME
#     # ========================================================
#
#     path(
#         "schemes/<str:scheme_code>/",
#         MutualFundSchemeDetailAPIView.as_view(),
#         name="scheme-detail",
#     ),
#
#     # ========================================================
#     # COMPLETE NAV HISTORY
#     # ========================================================
#
#     path(
#         "schemes/<str:scheme_code>/nav-history/",
#         MutualFundNAVHistoryAPIView.as_view(),
#         name="scheme-nav-history",
#     ),
#
#     # ========================================================
#     # NAV FOR PARTICULAR DATE
#     # ========================================================
#
#     path(
#         "schemes/<str:scheme_code>/nav-history/<str:date>/",
#         MutualFundNAVHistoryDateAPIView.as_view(),
#         name="scheme-nav-history-date",
#     ),
#
#     # ========================================================
#     # FUND HOUSE → SCHEMES
#     # ========================================================
#
#     path(
#         "fund-houses/<int:fund_house_id>/schemes/",
#         FundHouseSchemesAPIView.as_view(),
#         name="fund-house-schemes",
#     ),
# ]