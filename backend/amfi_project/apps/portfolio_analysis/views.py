from pathlib import Path
from tempfile import NamedTemporaryFile

from django.contrib.auth.models import User
from django.utils import timezone

from rest_framework import (
    generics,
    permissions,
    status,
)
from rest_framework.parsers import (
    MultiPartParser,
    FormParser,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from .models import (
    Portfolio,
)

from .serializers import (
    RegisterSerializer,
    UserSerializer,
    PortfolioSerializer,
    PortfolioDetailSerializer,
)

from .services.cas_parser import (
    CASProcessingError,
    parse_cas_pdf,
    extract_cas_portfolio_data,
    get_cas_summary,
)

from .services.portfolio_service import (
    import_cas_portfolio,
)


# ============================================================
# AUTHENTICATION
# ============================================================


class RegisterAPIView(
    generics.CreateAPIView
):
    queryset = User.objects.all()

    serializer_class = (
        RegisterSerializer
    )

    permission_classes = (
        permissions.AllowAny,
    )


class LoginAPIView(
    TokenObtainPairView
):
    permission_classes = (
        permissions.AllowAny,
    )


class RefreshTokenAPIView(
    TokenRefreshView
):
    permission_classes = (
        permissions.AllowAny,
    )


class MeAPIView(APIView):
    """
    Authenticated account information.

    This does NOT control financial planning.
    """

    permission_classes = (
        permissions.IsAuthenticated,
    )

    def get(self, request):

        serializer = UserSerializer(
            request.user
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class LogoutAPIView(APIView):

    permission_classes = (
        permissions.IsAuthenticated,
    )

    def post(self, request):

        refresh = request.data.get(
            "refresh"
        )

        if not refresh:

            return Response(
                {
                    "detail": (
                        "Refresh token is required."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:

            token = RefreshToken(
                refresh
            )

            token.blacklist()

            return Response(
                {
                    "detail": (
                        "Logout successful."
                    )
                },
                status=status.HTTP_200_OK,
            )

        except Exception:

            return Response(
                {
                    "detail": (
                        "Invalid or expired "
                        "refresh token."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


# ============================================================
# PUBLIC PORTFOLIO
# ============================================================


class PortfolioListCreateAPIView(
    generics.ListCreateAPIView
):
    """
    Public financial-planning endpoint.

    POST:
        Creates a planning portfolio.

    GET:
        Returns portfolios.

    No JWT required.
    """

    permission_classes = (
        permissions.AllowAny,
    )

    serializer_class = (
        PortfolioSerializer
    )

    queryset = (
        Portfolio.objects
        .all()
        .order_by("-updated_at")
    )


class PortfolioDetailAPIView(
    generics.RetrieveUpdateDestroyAPIView
):
    """
    Public portfolio endpoint.

    No JWT required.
    """

    permission_classes = (
        permissions.AllowAny,
    )

    serializer_class = (
        PortfolioDetailSerializer
    )

    queryset = Portfolio.objects.all()

    lookup_field = "id"


# ============================================================
# PUBLIC CAS IMPORT
# ============================================================


class CASPortfolioImportAPIView(
    APIView
):
    """
    Public CAS import endpoint.

    POST:

        /api/portfolios/import-cas/

    multipart/form-data:

        file
        password

    No JWT required.

    Works for:

        anonymous user
        logged-in user

    The CAS password is used only during parsing.
    """

    permission_classes = (
        permissions.AllowAny,
    )

    parser_classes = (
        MultiPartParser,
        FormParser,
    )

    MAX_FILE_SIZE = (
        10 * 1024 * 1024
    )

    def post(
        self,
        request,
    ):

        uploaded_file = request.FILES.get(
            "file"
        )

        if uploaded_file is None:

            return Response(
                {
                    "detail": (
                        "CAS PDF file is required."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_name = (
            uploaded_file.name
            or ""
        )

        if not file_name.lower().endswith(
            ".pdf"
        ):

            return Response(
                {
                    "detail": (
                        "Only PDF files are supported."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if (
            uploaded_file.size
            and uploaded_file.size
            > self.MAX_FILE_SIZE
        ):

            return Response(
                {
                    "detail": (
                        "CAS PDF is too large. "
                        "Maximum allowed size is 10 MB."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        password = request.data.get(
            "password"
        )

        if not password:

            return Response(
                {
                    "detail": (
                        "CAS PDF password is required."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        temporary_path = None

        try:

            # ------------------------------------------------
            # Temporary PDF
            # ------------------------------------------------

            with NamedTemporaryFile(
                suffix=".pdf",
                delete=False,
            ) as temporary_file:

                for chunk in uploaded_file.chunks():

                    temporary_file.write(
                        chunk
                    )

                temporary_path = (
                    temporary_file.name
                )

            # ------------------------------------------------
            # Parse
            # ------------------------------------------------

            parsed_data = parse_cas_pdf(
                pdf_path=temporary_path,
                password=password,
            )

            # ------------------------------------------------
            # Normalize complete CAS
            # ------------------------------------------------

            cas_data = (
                extract_cas_portfolio_data(
                    parsed_data
                )
            )

            investor = cas_data[
                "investor"
            ]

            portfolio_totals = (
                cas_data[
                    "portfolio_totals"
                ]
            )

            mutual_fund_details = (
                cas_data[
                    "mutual_fund_details"
                ]
            )

            if not mutual_fund_details:

                return Response(
                    {
                        "detail": (
                            "No mutual-fund holdings "
                            "were found in the CAS PDF."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # ------------------------------------------------
            # Save Portfolio
            # ------------------------------------------------

            result = import_cas_portfolio(
                investor=investor,
                portfolio_totals=portfolio_totals,
                mutual_fund_details=mutual_fund_details,
                file_name=file_name,
            )

            portfolio = result[
                "portfolio"
            ]

            # ------------------------------------------------
            # SUCCESS RESPONSE
            #
            # IMPORTANT:
            #
            # Do NOT return the complete portfolio object here.
            #
            # The frontend can use:
            #
            #     GET /api/portfolios/<portfolio_id>/
            #
            # to retrieve the complete portfolio later.
            # ------------------------------------------------

            return Response(
                {
                    "detail": (
                        "CAS portfolio imported "
                        "successfully."
                    ),

                    "portfolio_id": (
                        portfolio.id
                    ),

                    "import_id": (
                        result[
                            "portfolio_import"
                        ].id
                    ),

                    "status": (
                        result[
                            "status"
                        ]
                    ),

                    "records_found": (
                        result[
                            "records_found"
                        ]
                    ),

                    "records_created": (
                        result[
                            "records_created"
                        ]
                    ),

                    "records_updated": (
                        result[
                            "records_updated"
                        ]
                    ),

                    "records_failed": (
                        result[
                            "records_failed"
                        ]
                    ),

                    "errors": (
                        result[
                            "errors"
                        ]
                    ),
                },
                status=status.HTTP_200_OK,
            )

        except CASProcessingError as exc:

            return Response(
                {
                    "detail": str(exc)
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as exc:

            return Response(
                {
                    "detail": (
                        "An unexpected error occurred "
                        "while processing the CAS."
                    ),
                    "error": str(exc),
                },
                status=(
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                ),
            )

        finally:

            if temporary_path:

                try:

                    Path(
                        temporary_path
                    ).unlink(
                        missing_ok=True
                    )

                except Exception:

                    pass