from datetime import datetime

from django.db.models import Prefetch
from django.db.models.fields.json import KT

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.mutual_funds.models import (
    FundHouse,
    MutualFundScheme,
)

from .serializers import (
    MutualFundSchemeListSerializer,
    MutualFundSchemeDetailSerializer,
)


# =============================================================================
# COMMON HELPERS
# =============================================================================


def get_scheme_by_identifier(identifier):
    """
    Find a MutualFundScheme using either:

        1. scheme_code
        2. isin_growth

    Example:

        122612
        INF579M01183
    """

    identifier = str(identifier).strip()

    queryset = (
        MutualFundScheme.objects
        .select_related("fund_house")
    )

    if identifier.isdigit():

        return queryset.filter(
            scheme_code=identifier
        ).first()

    return queryset.filter(
        isin_growth__iexact=identifier
    ).first()


def get_nav_data(scheme):
    """
    Return NAV history stored in the MutualFundScheme.data JSON field.

    Always returns a list.

    Database order:

        NEWEST -> OLDEST
    """

    data = scheme.data

    if not isinstance(data, list):
        return []

    return data


def build_scheme_data(scheme):
    """
    Common scheme response structure.
    """

    return {
        "scheme_code": str(scheme.scheme_code),
        "scheme_name": scheme.scheme_name,
        "fund_house": scheme.fund_house.name,
        "scheme_type": scheme.scheme_type,
        "scheme_category": scheme.scheme_category,
        "isin_growth": scheme.isin_growth,
        "isin_div_payout": scheme.isin_div_payout,
        "isin_div_reinvestment": scheme.isin_div_reinvestment,
        "is_active": scheme.is_active,
    }


def get_latest_nav_history_entry(scheme):
    """
    Return latest NAV from the data JSON field.

    The project stores NAV history:

        NEWEST -> OLDEST

    Therefore the first valid entry is the latest NAV.
    """

    history = get_nav_data(scheme)

    if not history:
        return None

    for entry in history:

        if not isinstance(entry, dict):
            continue

        nav = entry.get("nav")
        date_string = entry.get("date")

        if nav is None or not date_string:
            continue

        return entry

    return None


# =============================================================================
# FUND HOUSE LIST
# =============================================================================


class FundHouseListAPIView(APIView):
    """
    GET /api/mutual-funds/

    Returns all active fund houses with their active schemes.

    Each scheme contains:

        latest_nav
        latest_nav_date

    PERFORMANCE OPTIMIZATION:

    The complete `data` JSON field is NOT loaded into Python.

    PostgreSQL extracts:

        data[0].nav
        data[0].date

    directly from the database.

    This is important because `data` contains the complete
    historical NAV history.
    """

    def get(self, request):

        # ---------------------------------------------------------------------
        # ACTIVE SCHEMES
        # ---------------------------------------------------------------------

        active_scheme_queryset = (
            MutualFundScheme.objects
            .filter(
                is_active=True
            )
            .select_related(
                "fund_house"
            )
            .annotate(
                latest_nav_from_data=KT(
                    "data__0__nav"
                ),
                latest_nav_date_from_data=KT(
                    "data__0__date"
                ),
            )
            .defer(
                "data"
            )
            .order_by(
                "scheme_code"
            )
        )

        # ---------------------------------------------------------------------
        # FUND HOUSES
        # ---------------------------------------------------------------------

        fund_houses = (
            FundHouse.objects
            .filter(
                is_active=True
            )
            .prefetch_related(
                Prefetch(
                    "schemes",
                    queryset=active_scheme_queryset,
                    to_attr="active_schemes",
                )
            )
            .order_by(
                "name"
            )
        )

        response_data = []

        # ---------------------------------------------------------------------
        # BUILD RESPONSE
        # ---------------------------------------------------------------------

        for fund_house in fund_houses:

            scheme_list = []

            for scheme in fund_house.active_schemes:

                scheme_data = build_scheme_data(
                    scheme
                )

                # -------------------------------------------------------------
                # LATEST NAV
                # -------------------------------------------------------------

                latest_nav = getattr(
                    scheme,
                    "latest_nav_from_data",
                    None,
                )

                latest_nav_date = getattr(
                    scheme,
                    "latest_nav_date_from_data",
                    None,
                )

                if latest_nav is not None:

                    scheme_data["latest_nav"] = str(
                        latest_nav
                    )

                    scheme_data["latest_nav_date"] = (
                        latest_nav_date
                    )

                else:

                    scheme_data["latest_nav"] = None
                    scheme_data["latest_nav_date"] = None

                scheme_list.append(
                    scheme_data
                )

            response_data.append(
                {
                    "id": fund_house.id,
                    "name": fund_house.name,
                    "number_of_schemes": len(
                        scheme_list
                    ),
                    "is_active": fund_house.is_active,
                    "schemes": scheme_list,
                }
            )

        return Response(
            response_data,
            status=status.HTTP_200_OK,
        )


# =============================================================================
# ALL SCHEMES
# =============================================================================


class MutualFundSchemeListAPIView(APIView):
    """
    GET /api/mutual-funds/schemes/

    Returns all active mutual fund schemes.

    Complete NAV history is intentionally not returned.
    """

    def get(self, request):

        schemes = (
            MutualFundScheme.objects
            .filter(
                is_active=True
            )
            .select_related(
                "fund_house"
            )
            .defer(
                "data"
            )
            .order_by(
                "scheme_code"
            )
        )

        serializer = MutualFundSchemeListSerializer(
            schemes,
            many=True,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


# =============================================================================
# SINGLE SCHEME
# =============================================================================


class MutualFundSchemeDetailAPIView(APIView):
    """
    GET /api/mutual-funds/schemes/<scheme_identifier>/

    <scheme_identifier> can be:

        Scheme code:
            122612

        OR

        ISIN:
            INF579M01183
    """

    def get(
        self,
        request,
        scheme_identifier,
    ):

        scheme = get_scheme_by_identifier(
            scheme_identifier
        )

        if scheme is None:

            return Response(
                {
                    "detail": (
                        f"Scheme or ISIN "
                        f"'{scheme_identifier}' not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = MutualFundSchemeDetailSerializer(
            scheme
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


# =============================================================================
# COMPLETE NAV HISTORY
# =============================================================================


class MutualFundNAVHistoryAPIView(APIView):
    """
    GET /api/mutual-funds/schemes/<scheme_identifier>/nav-history/

    Returns complete NAV history stored in:

        MutualFundScheme.data

    Output order:

        NEWEST -> OLDEST
    """

    def get(
        self,
        request,
        scheme_identifier,
    ):

        scheme = get_scheme_by_identifier(
            scheme_identifier
        )

        if scheme is None:

            return Response(
                {
                    "detail": (
                        f"Scheme or ISIN "
                        f"'{scheme_identifier}' not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        response_data = build_scheme_data(
            scheme
        )

        history = []

        for entry in get_nav_data(scheme):

            if not isinstance(entry, dict):
                continue

            if not entry.get("date"):
                continue

            if entry.get("nav") is None:
                continue

            history.append(
                {
                    "nav": str(
                        entry["nav"]
                    ),
                    "date": entry["date"],
                }
            )

        # ---------------------------------------------------------------------
        # SORT NEWEST -> OLDEST
        #
        # This matches the database/Admin/backfill order.
        # ---------------------------------------------------------------------

        try:

            history.sort(
                key=lambda item: datetime.strptime(
                    item["date"],
                    "%d-%m-%Y",
                ),
                reverse=True,
            )

        except (ValueError, TypeError):

            pass

        response_data["data"] = history

        return Response(
            response_data,
            status=status.HTTP_200_OK,
        )


# =============================================================================
# NAV HISTORY FOR SPECIFIC DATE
# =============================================================================


class MutualFundNAVHistoryDateAPIView(APIView):
    """
    GET /api/mutual-funds/schemes/<scheme_identifier>/nav-history/<nav_date>/

    Example:

        /api/mutual-funds/schemes/122612/nav-history/2026-08-11/

    API date format:

        YYYY-MM-DD

    Database JSON date format:

        DD-MM-YYYY
    """

    def get(
        self,
        request,
        scheme_identifier,
        nav_date,
    ):

        # =====================================================================
        # DATE VALIDATION
        # =====================================================================

        try:

            requested_date = datetime.strptime(
                nav_date,
                "%Y-%m-%d",
            ).date()

        except ValueError:

            return Response(
                {
                    "detail": (
                        "Invalid date format. "
                        "Use YYYY-MM-DD."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # =====================================================================
        # FIND SCHEME
        # =====================================================================

        scheme = get_scheme_by_identifier(
            scheme_identifier
        )

        if scheme is None:

            return Response(
                {
                    "detail": (
                        f"Scheme or ISIN "
                        f"'{scheme_identifier}' not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # =====================================================================
        # CONVERT DATE
        # =====================================================================

        stored_date = requested_date.strftime(
            "%d-%m-%Y"
        )

        nav_record = None

        # =====================================================================
        # FIND NAV IN `data`
        # =====================================================================

        for entry in get_nav_data(scheme):

            if not isinstance(entry, dict):
                continue

            if entry.get("date") != stored_date:
                continue

            if entry.get("nav") is None:
                continue

            nav_record = {
                "nav": str(
                    entry["nav"]
                ),
                "date": entry["date"],
            }

            break

        # =====================================================================
        # NAV NOT FOUND
        # =====================================================================

        if nav_record is None:

            return Response(
                {
                    "detail": (
                        f"NAV not found for "
                        f"'{scheme_identifier}' on "
                        f"{stored_date}."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # =====================================================================
        # RESPONSE
        # =====================================================================

        response_data = build_scheme_data(
            scheme
        )

        response_data["data"] = [
            nav_record
        ]

        return Response(
            response_data,
            status=status.HTTP_200_OK,
        )


# =============================================================================
# SCHEMES BY FUND HOUSE
# =============================================================================


class FundHouseSchemesAPIView(APIView):
    """
    GET /api/mutual-funds/fund-houses/<fund_house_id>/schemes/

    Returns all active schemes belonging to a fund house.

    Existing scheme fields are preserved.

    Additional fields:

        latest_nav
        latest_nav_date

    Example:

        {
            "scheme_code": "122612",
            "scheme_name": "...",
            "fund_house": "...",
            "scheme_type": "...",
            "scheme_category": "...",
            "isin_growth": "INF579M01183",
            "isin_div_payout": "...",
            "isin_div_reinvestment": "...",
            "is_active": true,
            "latest_nav": "24.2921",
            "latest_nav_date": "12-08-2026"
        }
    """

    def get(
        self,
        request,
        fund_house_id,
    ):

        # =====================================================================
        # FIND FUND HOUSE
        # =====================================================================

        try:

            fund_house = (
                FundHouse.objects
                .only(
                    "id",
                    "name",
                )
                .get(
                    id=fund_house_id
                )
            )

        except FundHouse.DoesNotExist:

            return Response(
                {
                    "detail": (
                        f"Fund House "
                        f"{fund_house_id} not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # =====================================================================
        # GET ACTIVE SCHEMES
        #
        # IMPORTANT:
        #
        # We extract only the first NAV object from JSON.
        #
        # We do NOT load the complete historical `data` field.
        #
        # This keeps the endpoint faster even when schemes contain
        # thousands of historical NAV records.
        # =====================================================================

        schemes = (
            MutualFundScheme.objects
            .filter(
                fund_house_id=fund_house_id,
                is_active=True,
            )
            .select_related(
                "fund_house"
            )
            .annotate(
                latest_nav_from_data=KT(
                    "data__0__nav"
                ),
                latest_nav_date_from_data=KT(
                    "data__0__date"
                ),
            )
            .defer(
                "data"
            )
            .order_by(
                "scheme_code"
            )
        )

        # =====================================================================
        # SERIALIZE EXISTING FIELDS
        #
        # IMPORTANT:
        #
        # The existing serializer is still used.
        #
        # Therefore all existing scheme fields remain exactly as before.
        # =====================================================================

        serialized_schemes = MutualFundSchemeListSerializer(
            schemes,
            many=True,
        ).data

        # =====================================================================
        # ADD ONLY THE TWO REQUESTED FIELDS
        #
        # latest_nav
        # latest_nav_date
        #
        # The order of `schemes` queryset and serializer output is preserved,
        # so we can safely match each serialized scheme with its queryset row.
        # =====================================================================

        for scheme_data, scheme in zip(
            serialized_schemes,
            schemes,
        ):

            latest_nav = getattr(
                scheme,
                "latest_nav_from_data",
                None,
            )

            latest_nav_date = getattr(
                scheme,
                "latest_nav_date_from_data",
                None,
            )

            if latest_nav is not None:

                scheme_data["latest_nav"] = str(
                    latest_nav
                )

            else:

                scheme_data["latest_nav"] = None

            if latest_nav_date is not None:

                scheme_data["latest_nav_date"] = (
                    latest_nav_date
                )

            else:

                scheme_data["latest_nav_date"] = None

        # =====================================================================
        # RESPONSE
        # =====================================================================

        return Response(
            {
                "fund_house": fund_house.name,
                "scheme_count": len(
                    serialized_schemes
                ),
                "schemes": serialized_schemes,
            },
            status=status.HTTP_200_OK,
        )
# from datetime import datetime
#
# from django.db.models import Prefetch
# from django.db.models.fields.json import KT
#
# from rest_framework import status
# from rest_framework.response import Response
# from rest_framework.views import APIView
#
# from apps.mutual_funds.models import (
#     FundHouse,
#     MutualFundScheme,
# )
#
# from .serializers import (
#     MutualFundSchemeListSerializer,
#     MutualFundSchemeDetailSerializer,
# )
#
#
# # =============================================================================
# # COMMON HELPERS
# # =============================================================================
#
#
# def get_scheme_by_identifier(identifier):
#     """
#     Find a MutualFundScheme using either:
#
#         1. scheme_code
#         2. isin_growth
#
#     Example:
#
#         122612
#         INF579M01183
#     """
#
#     identifier = str(identifier).strip()
#
#     queryset = (
#         MutualFundScheme.objects
#         .select_related("fund_house")
#     )
#
#     if identifier.isdigit():
#         return queryset.filter(
#             scheme_code=identifier
#         ).first()
#
#     return queryset.filter(
#         isin_growth__iexact=identifier
#     ).first()
#
#
# def get_nav_data(scheme):
#     """
#     Return NAV history stored in the MutualFundScheme.data JSON field.
#
#     Always returns a list.
#     """
#
#     data = scheme.data
#
#     if not isinstance(data, list):
#         return []
#
#     return data
#
#
# def build_scheme_data(scheme):
#     """
#     Common scheme response structure.
#     """
#
#     return {
#         "scheme_code": str(scheme.scheme_code),
#         "scheme_name": scheme.scheme_name,
#         "fund_house": scheme.fund_house.name,
#         "scheme_type": scheme.scheme_type,
#         "scheme_category": scheme.scheme_category,
#         "isin_growth": scheme.isin_growth,
#         "isin_div_payout": scheme.isin_div_payout,
#         "isin_div_reinvestment": scheme.isin_div_reinvestment,
#         "is_active": scheme.is_active,
#     }
#
#
# def get_latest_nav_history_entry(scheme):
#     """
#     Return latest NAV from the data JSON field.
#
#     This helper is used by endpoints where the complete
#     data field is already loaded.
#
#     Assumes data is stored newest -> oldest.
#     """
#
#     history = get_nav_data(scheme)
#
#     if not history:
#         return None
#
#     for entry in history:
#
#         if not isinstance(entry, dict):
#             continue
#
#         nav = entry.get("nav")
#         date_string = entry.get("date")
#
#         if nav is None or not date_string:
#             continue
#
#         return entry
#
#     return None
#
#
# # =============================================================================
# # FUND HOUSE LIST
# # =============================================================================
#
#
# class FundHouseListAPIView(APIView):
#     """
#     GET /api/mutual-funds/
#
#     Returns all active fund houses with their active schemes.
#
#     Each scheme contains:
#
#         latest_nav
#         latest_nav_date
#
#     PERFORMANCE OPTIMIZATION:
#
#     The complete `data` JSON field is NOT loaded into Python.
#
#     PostgreSQL extracts:
#
#         data[0].nav
#         data[0].date
#
#     directly from the database.
#
#     This is important because `data` contains the complete
#     historical NAV history.
#     """
#
#     def get(self, request):
#
#         # ---------------------------------------------------------------------
#         # ACTIVE SCHEMES
#         #
#         # IMPORTANT:
#         #
#         # We annotate only the first NAV record.
#         #
#         # We also defer `data` so Django does NOT transfer the
#         # complete historical JSON from PostgreSQL.
#         # ---------------------------------------------------------------------
#
#         active_scheme_queryset = (
#             MutualFundScheme.objects
#             .filter(is_active=True)
#             .select_related("fund_house")
#             .annotate(
#                 latest_nav_from_data=KT(
#                     "data__0__nav"
#                 ),
#                 latest_nav_date_from_data=KT(
#                     "data__0__date"
#                 ),
#             )
#             .defer("data")
#             .order_by("scheme_code")
#         )
#
#         # ---------------------------------------------------------------------
#         # FUND HOUSES
#         # ---------------------------------------------------------------------
#
#         fund_houses = (
#             FundHouse.objects
#             .filter(is_active=True)
#             .prefetch_related(
#                 Prefetch(
#                     "schemes",
#                     queryset=active_scheme_queryset,
#                     to_attr="active_schemes",
#                 )
#             )
#             .order_by("name")
#         )
#
#         response_data = []
#
#         # ---------------------------------------------------------------------
#         # BUILD RESPONSE
#         # ---------------------------------------------------------------------
#
#         for fund_house in fund_houses:
#
#             scheme_list = []
#
#             for scheme in fund_house.active_schemes:
#
#                 scheme_data = build_scheme_data(
#                     scheme
#                 )
#
#                 # -------------------------------------------------------------
#                 # LATEST NAV
#                 #
#                 # IMPORTANT:
#                 #
#                 # Do NOT access scheme.data here.
#                 #
#                 # The values were already extracted by PostgreSQL.
#                 # -------------------------------------------------------------
#
#                 latest_nav = getattr(
#                     scheme,
#                     "latest_nav_from_data",
#                     None,
#                 )
#
#                 latest_nav_date = getattr(
#                     scheme,
#                     "latest_nav_date_from_data",
#                     None,
#                 )
#
#                 if latest_nav is not None:
#
#                     scheme_data["latest_nav"] = str(
#                         latest_nav
#                     )
#
#                     scheme_data["latest_nav_date"] = (
#                         latest_nav_date
#                     )
#
#                 else:
#
#                     scheme_data["latest_nav"] = None
#                     scheme_data["latest_nav_date"] = None
#
#                 scheme_list.append(
#                     scheme_data
#                 )
#
#             response_data.append(
#                 {
#                     "id": fund_house.id,
#                     "name": fund_house.name,
#                     "number_of_schemes": len(
#                         scheme_list
#                     ),
#                     "is_active": fund_house.is_active,
#                     "schemes": scheme_list,
#                 }
#             )
#
#         return Response(
#             response_data,
#             status=status.HTTP_200_OK,
#         )
#
#
# # =============================================================================
# # ALL SCHEMES
# # =============================================================================
#
#
# class MutualFundSchemeListAPIView(APIView):
#     """
#     GET /api/mutual-funds/schemes/
#
#     Returns all active mutual fund schemes.
#     """
#
#     def get(self, request):
#
#         schemes = (
#             MutualFundScheme.objects
#             .filter(is_active=True)
#             .select_related("fund_house")
#             .defer("data")
#             .order_by("scheme_code")
#         )
#
#         serializer = MutualFundSchemeListSerializer(
#             schemes,
#             many=True,
#         )
#
#         return Response(
#             serializer.data,
#             status=status.HTTP_200_OK,
#         )
#
#
# # =============================================================================
# # SINGLE SCHEME
# # =============================================================================
#
#
# class MutualFundSchemeDetailAPIView(APIView):
#     """
#     GET /api/mutual-funds/schemes/<scheme_identifier>/
#
#     <scheme_identifier> can be:
#
#         Scheme code:
#             122612
#
#         OR
#
#         ISIN:
#             INF579M01183
#     """
#
#     def get(
#         self,
#         request,
#         scheme_identifier,
#     ):
#
#         scheme = get_scheme_by_identifier(
#             scheme_identifier
#         )
#
#         if scheme is None:
#
#             return Response(
#                 {
#                     "detail": (
#                         f"Scheme or ISIN "
#                         f"'{scheme_identifier}' not found."
#                     )
#                 },
#                 status=status.HTTP_404_NOT_FOUND,
#             )
#
#         serializer = MutualFundSchemeDetailSerializer(
#             scheme
#         )
#
#         return Response(
#             serializer.data,
#             status=status.HTTP_200_OK,
#         )
#
#
# # =============================================================================
# # COMPLETE NAV HISTORY
# # =============================================================================
#
#
# class MutualFundNAVHistoryAPIView(APIView):
#     """
#     GET /api/mutual-funds/schemes/<scheme_identifier>/nav-history/
#
#     Returns complete NAV history stored in:
#
#         MutualFundScheme.data
#     """
#
#     def get(
#         self,
#         request,
#         scheme_identifier,
#     ):
#
#         scheme = get_scheme_by_identifier(
#             scheme_identifier
#         )
#
#         if scheme is None:
#
#             return Response(
#                 {
#                     "detail": (
#                         f"Scheme or ISIN "
#                         f"'{scheme_identifier}' not found."
#                     )
#                 },
#                 status=status.HTTP_404_NOT_FOUND,
#             )
#
#         response_data = build_scheme_data(
#             scheme
#         )
#
#         history = []
#
#         for entry in get_nav_data(scheme):
#
#             if not isinstance(entry, dict):
#                 continue
#
#             if not entry.get("date"):
#                 continue
#
#             if entry.get("nav") is None:
#                 continue
#
#             history.append(
#                 {
#                     "nav": str(
#                         entry["nav"]
#                     ),
#                     "date": entry["date"],
#                 }
#             )
#
#         # ---------------------------------------------------------------------
#         # Sort oldest -> newest
#         # ---------------------------------------------------------------------
#
#         try:
#
#             history.sort(
#                 key=lambda item: datetime.strptime(
#                     item["date"],
#                     "%d-%m-%Y",
#                 )
#             )
#
#         except (ValueError, TypeError):
#
#             pass
#
#         # ---------------------------------------------------------------------
#         # DATABASE FIELD:
#         #
#         #     data
#         #
#         # API RESPONSE:
#         #
#         #     data
#         # ---------------------------------------------------------------------
#
#         response_data["data"] = history
#
#         return Response(
#             response_data,
#             status=status.HTTP_200_OK,
#         )
#
#
# # =============================================================================
# # NAV HISTORY FOR SPECIFIC DATE
# # =============================================================================
#
#
# class MutualFundNAVHistoryDateAPIView(APIView):
#     """
#     GET /api/mutual-funds/schemes/<scheme_identifier>/nav-history/<nav_date>/
#
#     Example:
#
#         /api/mutual-funds/schemes/122612/nav-history/2026-08-11/
#
#     API date format:
#
#         YYYY-MM-DD
#
#     Database JSON date format:
#
#         DD-MM-YYYY
#     """
#
#     def get(
#         self,
#         request,
#         scheme_identifier,
#         nav_date,
#     ):
#
#         # =====================================================================
#         # DATE VALIDATION
#         # =====================================================================
#
#         try:
#
#             requested_date = datetime.strptime(
#                 nav_date,
#                 "%Y-%m-%d",
#             ).date()
#
#         except ValueError:
#
#             return Response(
#                 {
#                     "detail": (
#                         "Invalid date format. "
#                         "Use YYYY-MM-DD."
#                     )
#                 },
#                 status=status.HTTP_400_BAD_REQUEST,
#             )
#
#         # =====================================================================
#         # FIND SCHEME
#         # =====================================================================
#
#         scheme = get_scheme_by_identifier(
#             scheme_identifier
#         )
#
#         if scheme is None:
#
#             return Response(
#                 {
#                     "detail": (
#                         f"Scheme or ISIN "
#                         f"'{scheme_identifier}' not found."
#                     )
#                 },
#                 status=status.HTTP_404_NOT_FOUND,
#             )
#
#         # =====================================================================
#         # CONVERT DATE
#         # =====================================================================
#
#         stored_date = requested_date.strftime(
#             "%d-%m-%Y"
#         )
#
#         nav_record = None
#
#         # =====================================================================
#         # FIND NAV IN `data`
#         # =====================================================================
#
#         for entry in get_nav_data(scheme):
#
#             if not isinstance(entry, dict):
#                 continue
#
#             if entry.get("date") != stored_date:
#                 continue
#
#             if entry.get("nav") is None:
#                 continue
#
#             nav_record = {
#                 "nav": str(
#                     entry["nav"]
#                 ),
#                 "date": entry["date"],
#             }
#
#             break
#
#         # =====================================================================
#         # NAV NOT FOUND
#         # =====================================================================
#
#         if nav_record is None:
#
#             return Response(
#                 {
#                     "detail": (
#                         f"NAV not found for "
#                         f"'{scheme_identifier}' on "
#                         f"{stored_date}."
#                     )
#                 },
#                 status=status.HTTP_404_NOT_FOUND,
#             )
#
#         # =====================================================================
#         # RESPONSE
#         # =====================================================================
#
#         response_data = build_scheme_data(
#             scheme
#         )
#
#         response_data["data"] = [
#             nav_record
#         ]
#
#         return Response(
#             response_data,
#             status=status.HTTP_200_OK,
#         )
#
#
# # =============================================================================
# # SCHEMES BY FUND HOUSE
# # =============================================================================
#
#
# class FundHouseSchemesAPIView(APIView):
#     """
#     GET /api/mutual-funds/fund-houses/<fund_house_id>/schemes/
#
#     Returns all active schemes belonging to a fund house.
#     """
#
#     def get(
#         self,
#         request,
#         fund_house_id,
#     ):
#
#         try:
#
#             fund_house = (
#                 FundHouse.objects
#                 .only(
#                     "id",
#                     "name",
#                 )
#                 .get(
#                     id=fund_house_id
#                 )
#             )
#
#         except FundHouse.DoesNotExist:
#
#             return Response(
#                 {
#                     "detail": (
#                         f"Fund House "
#                         f"{fund_house_id} not found."
#                     )
#                 },
#                 status=status.HTTP_404_NOT_FOUND,
#             )
#
#         schemes = (
#             MutualFundScheme.objects
#             .filter(
#                 fund_house_id=fund_house_id,
#                 is_active=True,
#             )
#             .select_related("fund_house")
#             .defer("data")
#             .order_by("scheme_code")
#         )
#
#         serializer = MutualFundSchemeListSerializer(
#             schemes,
#             many=True,
#         )
#
#         return Response(
#             {
#                 "fund_house": fund_house.name,
#                 "scheme_count": schemes.count(),
#                 "schemes": serializer.data,
#             },
#             status=status.HTTP_200_OK,
#         )
