from datetime import datetime

from django.db.models import Q

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.mutual_funds.models import (
    FundHouse,
    MutualFundScheme,
)

from .serializers import (
    FundHouseSerializer,
    MutualFundSchemeListSerializer,
    MutualFundSchemeDetailSerializer,
    NAVHistorySerializer,
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

    Only one identifier is required.
    """

    identifier = str(identifier).strip()

    return (
        MutualFundScheme.objects
        .select_related("fund_house")
        .filter(
            Q(scheme_code=identifier)
            | Q(isin_growth__iexact=identifier)
        )
        .first()
    )


def build_scheme_data(scheme):
    """
    Common scheme response structure.

    This function is reused by APIs so we do not repeat
    the same scheme fields everywhere.
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
    Return the latest NAV entry from nav_history.

    Example return:

        {
            "nav": "24.2752",
            "date": "11-08-2026"
        }

    Returns None if no NAV history exists.
    """

    history = scheme.nav_history or []

    valid_entries = [
        entry
        for entry in history
        if (
            isinstance(entry, dict)
            and entry.get("date")
            and entry.get("nav") is not None
        )
    ]

    if not valid_entries:
        return None

    return max(
        valid_entries,
        key=lambda entry: datetime.strptime(
            entry["date"],
            "%d-%m-%Y",
        ),
    )


# =============================================================================
# FUND HOUSE LIST
# =============================================================================


class FundHouseListAPIView(APIView):
    """
    GET /api/mutual-funds/

    Returns all active fund houses with their active schemes.

    Each scheme also contains its latest NAV:

        "latest_nav": "24.2752",
        "latest_nav_date": "11-08-2026"
    """

    def get(self, request):

        fund_houses = (
            FundHouse.objects
            .filter(is_active=True)
            .prefetch_related("schemes")
            .order_by("name")
        )

        response_data = []

        for fund_house in fund_houses:

            active_schemes = [
                scheme
                for scheme in fund_house.schemes.all()
                if scheme.is_active
            ]

            scheme_list = []

            for scheme in active_schemes:

                scheme_data = build_scheme_data(
                    scheme
                )

                latest_nav = get_latest_nav_history_entry(
                    scheme
                )

                if latest_nav:

                    scheme_data["latest_nav"] = (
                        latest_nav["nav"]
                    )

                    scheme_data["latest_nav_date"] = (
                        latest_nav["date"]
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
    """

    def get(self, request):

        schemes = (
            MutualFundScheme.objects
            .filter(is_active=True)
            .select_related("fund_house")
            .order_by("scheme_code")
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

    <scheme_identifier> can be:

        Scheme code:
            122612

        OR

        ISIN:
            INF579M01183

    Returns complete NAV history.
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

        data = build_scheme_data(
            scheme
        )

        history = []

        for entry in scheme.nav_history or []:

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
        # Sort oldest -> newest
        # ---------------------------------------------------------------------

        try:

            history.sort(
                key=lambda item: datetime.strptime(
                    item["date"],
                    "%d-%m-%Y",
                )
            )

        except ValueError:
            pass

        data["nav_history"] = history

        return Response(
            data,
            status=status.HTTP_200_OK,
        )


# =============================================================================
# NAV HISTORY FOR SPECIFIC DATE
# =============================================================================


class MutualFundNAVHistoryDateAPIView(APIView):
    """
    GET /api/mutual-funds/schemes/<scheme_identifier>/nav-history/<nav_date>/

    Example using scheme code:

        /api/mutual-funds/schemes/122612/nav-history/2026-08-11/

    Example using ISIN:

        /api/mutual-funds/schemes/INF579M01183/nav-history/2026-08-11/
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
        # DATE STORED IN JSON
        # =====================================================================

        stored_date = requested_date.strftime(
            "%d-%m-%Y"
        )

        nav_record = None

        for entry in scheme.nav_history or []:

            if not isinstance(entry, dict):
                continue

            if entry.get("date") == stored_date:

                nav_record = {
                    "nav": str(
                        entry.get("nav")
                    ),
                    "date": entry.get("date"),
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

        data = build_scheme_data(
            scheme
        )

        data["nav_history"] = [
            nav_record
        ]

        return Response(
            data,
            status=status.HTTP_200_OK,
        )


# =============================================================================
# SCHEMES BY FUND HOUSE
# =============================================================================


class FundHouseSchemesAPIView(APIView):
    """
    GET /api/mutual-funds/fund-houses/<fund_house_id>/schemes/

    Returns all active schemes belonging to a fund house.
    """

    def get(
        self,
        request,
        fund_house_id,
    ):

        try:

            fund_house = FundHouse.objects.get(
                id=fund_house_id
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

        schemes = (
            MutualFundScheme.objects
            .filter(
                fund_house=fund_house,
                is_active=True,
            )
            .select_related("fund_house")
            .order_by("scheme_code")
        )

        serializer = MutualFundSchemeListSerializer(
            schemes,
            many=True,
        )

        return Response(
            {
                "fund_house": fund_house.name,
                "scheme_count": schemes.count(),
                "schemes": serializer.data,
            },
            status=status.HTTP_200_OK,
        )
# from datetime import datetime
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
#     FundHouseSerializer,
#     MutualFundSchemeListSerializer,
#     MutualFundSchemeDetailSerializer,
#     NAVHistorySerializer,
#     NAVHistoryDateSerializer,
# )
#
#
# # =============================================================================
# # HELPER FUNCTIONS
# # =============================================================================
#
# def get_latest_nav_history(nav_history):
#     """
#     Return the latest NAV entry from a scheme's nav_history.
#
#     Database format:
#
#         [
#             {
#                 "nav": "24.2839",
#                 "date": "10-08-2026"
#             },
#             {
#                 "nav": "24.2752",
#                 "date": "11-08-2026"
#             }
#         ]
#
#     Returns only:
#
#         {
#             "nav": "24.2752",
#             "date": "11-08-2026"
#         }
#
#     If no valid NAV history exists, returns an empty list.
#     """
#
#     if not isinstance(nav_history, list):
#         return []
#
#     valid_entries = []
#
#     for entry in nav_history:
#
#         if not isinstance(entry, dict):
#             continue
#
#         nav = entry.get("nav")
#         date_string = entry.get("date")
#
#         if not nav or not date_string:
#             continue
#
#         try:
#             parsed_date = datetime.strptime(
#                 str(date_string),
#                 "%d-%m-%Y",
#             ).date()
#
#         except (ValueError, TypeError):
#             continue
#
#         valid_entries.append(
#             (
#                 parsed_date,
#                 {
#                     "nav": str(nav),
#                     "date": str(date_string),
#                 },
#             )
#         )
#
#     if not valid_entries:
#         return []
#
#     # Latest date first
#     valid_entries.sort(
#         key=lambda item: item[0],
#         reverse=True,
#     )
#
#     return [valid_entries[0][1]]
#
#
# def build_scheme_data(scheme, include_latest_nav=False):
#     """
#     Build the common scheme response structure.
#
#     This avoids repeating the same scheme fields in multiple APIs.
#
#     include_latest_nav=True is used ONLY by:
#
#         GET /api/mutual-funds/
#
#     """
#
#     data = {
#         "scheme_code": str(
#             scheme.scheme_code
#         ),
#
#         "scheme_name": (
#             scheme.scheme_name
#         ),
#
#         "fund_house": (
#             scheme.fund_house.name
#         ),
#
#         "scheme_type": (
#             scheme.scheme_type
#         ),
#
#         "scheme_category": (
#             scheme.scheme_category
#         ),
#
#         "isin_growth": (
#             scheme.isin_growth
#         ),
#
#         "isin_div_payout": (
#             scheme.isin_div_payout
#         ),
#
#         "isin_div_reinvestment": (
#             scheme.isin_div_reinvestment
#         ),
#
#         "is_active": (
#             scheme.is_active
#         ),
#     }
#
#     # -------------------------------------------------------------------------
#     # IMPORTANT
#     #
#     # Latest NAV is added ONLY when requested.
#     #
#     # This is currently used only by:
#     #
#     # GET /api/mutual-funds/
#     # -------------------------------------------------------------------------
#
#     if include_latest_nav:
#
#         data["nav_history"] = get_latest_nav_history(
#             scheme.nav_history
#         )
#
#     return data
#
#
# # =============================================================================
# # FUND HOUSE LIST
# # =============================================================================
#
# class FundHouseListAPIView(APIView):
#     """
#     GET /api/mutual-funds/
#
#     Returns all active fund houses with their active schemes.
#
#     For THIS endpoint only, every scheme contains its latest NAV:
#
#         "nav_history": [
#             {
#                 "nav": "24.2752",
#                 "date": "11-08-2026"
#             }
#         ]
#
#     Complete NAV history is NOT returned here.
#     """
#
#     def get(self, request):
#
#         fund_houses = (
#             FundHouse.objects
#             .filter(is_active=True)
#             .prefetch_related("schemes")
#             .order_by("name")
#         )
#
#         response_data = []
#
#         for fund_house in fund_houses:
#
#             # ---------------------------------------------------------------
#             # Active schemes
#             # ---------------------------------------------------------------
#
#             active_schemes = [
#                 scheme
#                 for scheme in fund_house.schemes.all()
#                 if scheme.is_active
#             ]
#
#             # ---------------------------------------------------------------
#             # Build scheme response
#             # ---------------------------------------------------------------
#
#             scheme_list = []
#
#             for scheme in active_schemes:
#
#                 scheme_data = build_scheme_data(
#                     scheme=scheme,
#                     include_latest_nav=True,
#                 )
#
#                 scheme_list.append(
#                     scheme_data
#                 )
#
#             # ---------------------------------------------------------------
#             # Fund house response
#             # ---------------------------------------------------------------
#
#             response_data.append(
#                 {
#                     "id": fund_house.id,
#
#                     "name": fund_house.name,
#
#                     "number_of_schemes": len(
#                         scheme_list
#                     ),
#
#                     "is_active": fund_house.is_active,
#
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
# class MutualFundSchemeListAPIView(APIView):
#     """
#     GET /api/mutual-funds/schemes/
#
#     Returns all active schemes.
#
#     This endpoint does NOT change its NAV-history behavior.
#     """
#
#     def get(self, request):
#
#         schemes = (
#             MutualFundScheme.objects
#             .filter(is_active=True)
#             .select_related("fund_house")
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
# # SINGLE SCHEME DETAIL
# # =============================================================================
#
# class MutualFundSchemeDetailAPIView(APIView):
#     """
#     GET /api/mutual-funds/schemes/<scheme_code>/
#
#     Returns complete information for one scheme.
#     """
#
#     def get(self, request, scheme_code):
#
#         try:
#
#             scheme = (
#                 MutualFundScheme.objects
#                 .select_related("fund_house")
#                 .get(
#                     scheme_code=str(scheme_code)
#                 )
#             )
#
#         except MutualFundScheme.DoesNotExist:
#
#             return Response(
#                 {
#                     "detail": (
#                         f"Scheme {scheme_code} "
#                         "not found."
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
# class MutualFundNAVHistoryAPIView(APIView):
#     """
#     GET /api/mutual-funds/schemes/<scheme_code>/nav-history/
#
#     Returns scheme information plus complete NAV history.
#     """
#
#     def get(self, request, scheme_code):
#
#         try:
#
#             scheme = (
#                 MutualFundScheme.objects
#                 .select_related("fund_house")
#                 .get(
#                     scheme_code=str(scheme_code)
#                 )
#             )
#
#         except MutualFundScheme.DoesNotExist:
#
#             return Response(
#                 {
#                     "detail": (
#                         f"Scheme {scheme_code} "
#                         "not found."
#                     )
#                 },
#                 status=status.HTTP_404_NOT_FOUND,
#             )
#
#         serializer = NAVHistorySerializer(
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
# # NAV HISTORY FOR A SPECIFIC DATE
# # =============================================================================
#
# # =============================================================================
# # NAV HISTORY FOR A SPECIFIC DATE
# # =============================================================================
#
# class MutualFundNAVHistoryDateAPIView(APIView):
#     """
#     GET /api/mutual-funds/schemes/<scheme_code>/nav-history/<date>/
#
#     Example:
#     /api/mutual-funds/schemes/122612/nav-history/2026-08-11/
#
#     Returns complete scheme information with the NAV for the
#     requested date inside nav_history.
#     """
#
#     def get(self, request, scheme_code, date):
#
#         # ---------------------------------------------------------------------
#         # 1. VALIDATE DATE
#         # ---------------------------------------------------------------------
#
#         try:
#             requested_date = datetime.strptime(
#                 date,
#                 "%Y-%m-%d",
#             ).date()
#
#         except ValueError:
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
#         # ---------------------------------------------------------------------
#         # 2. GET SCHEME
#         # ---------------------------------------------------------------------
#
#         try:
#             scheme = (
#                 MutualFundScheme.objects
#                 .select_related("fund_house")
#                 .get(
#                     scheme_code=str(scheme_code)
#                 )
#             )
#
#         except MutualFundScheme.DoesNotExist:
#
#             return Response(
#                 {
#                     "detail": (
#                         f"Scheme {scheme_code} not found."
#                     )
#                 },
#                 status=status.HTTP_404_NOT_FOUND,
#             )
#
#         # ---------------------------------------------------------------------
#         # 3. CONVERT DATE TO STORED FORMAT
#         #
#         # Database:
#         #
#         # "11-08-2026"
#         #
#         # API URL:
#         #
#         # "2026-08-11"
#         # ---------------------------------------------------------------------
#
#         stored_date = requested_date.strftime(
#             "%d-%m-%Y"
#         )
#
#         # ---------------------------------------------------------------------
#         # 4. FIND NAV IN nav_history
#         # ---------------------------------------------------------------------
#
#         nav_record = None
#
#         for item in scheme.nav_history or []:
#
#             if not isinstance(item, dict):
#                 continue
#
#             if item.get("date") == stored_date:
#
#                 nav_record = {
#                     "nav": str(
#                         item.get("nav")
#                     ),
#                     "date": item.get("date"),
#                 }
#
#                 break
#
#         # ---------------------------------------------------------------------
#         # 5. NAV NOT FOUND
#         # ---------------------------------------------------------------------
#
#         if nav_record is None:
#
#             return Response(
#                 {
#                     "detail": (
#                         f"NAV not found for scheme "
#                         f"{scheme_code} on "
#                         f"{stored_date}."
#                     )
#                 },
#                 status=status.HTTP_404_NOT_FOUND,
#             )
#
#         # ---------------------------------------------------------------------
#         # 6. BUILD RESPONSE
#         # ---------------------------------------------------------------------
#
#         response_data = {
#             "scheme_code": str(
#                 scheme.scheme_code
#             ),
#
#             "scheme_name": (
#                 scheme.scheme_name
#             ),
#
#             "fund_house": (
#                 scheme.fund_house.name
#             ),
#
#             "scheme_type": (
#                 scheme.scheme_type
#             ),
#
#             "scheme_category": (
#                 scheme.scheme_category
#             ),
#
#             "isin_growth": (
#                 scheme.isin_growth
#             ),
#
#             "isin_div_payout": (
#                 scheme.isin_div_payout
#             ),
#
#             "isin_div_reinvestment": (
#                 scheme.isin_div_reinvestment
#             ),
#
#             "is_active": (
#                 scheme.is_active
#             ),
#
#             # -------------------------------------------------------------
#             # IMPORTANT:
#             # Requested NAV is returned as a LIST inside nav_history.
#             # -------------------------------------------------------------
#
#             "nav_history": [
#                 nav_record
#             ],
#         }
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
# class FundHouseSchemesAPIView(APIView):
#     """
#     GET /api/mutual-funds/fund-houses/<fund_house_id>/schemes/
#
#     Returns all active schemes belonging to a specific fund house.
#
#     Example:
#
#         /api/mutual-funds/fund-houses/1/schemes/
#     """
#
#     def get(
#         self,
#         request,
#         fund_house_id,
#     ):
#
#         # ---------------------------------------------------------------------
#         # Retrieve fund house
#         # ---------------------------------------------------------------------
#
#         try:
#
#             fund_house = FundHouse.objects.get(
#                 id=fund_house_id
#             )
#
#         except FundHouse.DoesNotExist:
#
#             return Response(
#                 {
#                     "detail": (
#                         f"Fund House "
#                         f"{fund_house_id} "
#                         "not found."
#                     )
#                 },
#                 status=status.HTTP_404_NOT_FOUND,
#             )
#
#         # ---------------------------------------------------------------------
#         # Retrieve schemes
#         # ---------------------------------------------------------------------
#
#         schemes = (
#             MutualFundScheme.objects
#             .filter(
#                 fund_house=fund_house,
#                 is_active=True,
#             )
#             .select_related("fund_house")
#             .order_by("scheme_code")
#         )
#
#         # ---------------------------------------------------------------------
#         # Serialize
#         # ---------------------------------------------------------------------
#
#         serializer = MutualFundSchemeListSerializer(
#             schemes,
#             many=True,
#         )
#
#         return Response(
#             {
#                 "fund_house": fund_house.name,
#
#                 "scheme_count": schemes.count(),
#
#                 "schemes": serializer.data,
#             },
#             status=status.HTTP_200_OK,
#         )