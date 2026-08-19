from django.urls import path

from .views import (
    RegisterAPIView,
    LoginAPIView,
    RefreshTokenAPIView,
    MeAPIView,
    LogoutAPIView,
    PortfolioListCreateAPIView,
    PortfolioDetailAPIView,
    CASPortfolioImportAPIView,
)


urlpatterns = [

    # ========================================================
    # OPTIONAL AUTHENTICATION
    # ========================================================

    path(
        "auth/register/",
        RegisterAPIView.as_view(),
        name="auth-register",
    ),

    path(
        "auth/login/",
        LoginAPIView.as_view(),
        name="auth-login",
    ),

    path(
        "auth/refresh/",
        RefreshTokenAPIView.as_view(),
        name="auth-refresh",
    ),

    path(
        "auth/me/",
        MeAPIView.as_view(),
        name="auth-me",
    ),

    path(
        "auth/logout/",
        LogoutAPIView.as_view(),
        name="auth-logout",
    ),

    # ========================================================
    # PUBLIC FINANCIAL PLANNING
    # ========================================================

    path(
        "portfolios/",
        PortfolioListCreateAPIView.as_view(),
        name="portfolio-list-create",
    ),

    path(
        "portfolios/<int:id>/",
        PortfolioDetailAPIView.as_view(),
        name="portfolio-detail",
    ),

    # ========================================================
    # PUBLIC CAS IMPORT
    # ========================================================

    path(
        "portfolios/import-cas/",
        CASPortfolioImportAPIView.as_view(),
        name="portfolio-import-cas",
    ),
]