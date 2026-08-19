from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

from rest_framework import serializers

from .models import (
    Portfolio,
    PortfolioImport,
)


# ============================================================
# USER REGISTRATION
# ============================================================


class RegisterSerializer(serializers.ModelSerializer):
    """
    Serializer for optional user registration.

    JWT authentication remains available for future
    transactional features such as KYC, BUY and SELL.

    Financial planning and CAS upload do NOT require JWT.
    """

    password = serializers.CharField(
        write_only=True,
        min_length=8,
        validators=[validate_password],
    )

    password_confirm = serializers.CharField(
        write_only=True,
    )

    class Meta:
        model = User

        fields = (
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "password_confirm",
        )

    def validate_email(self, value):
        email = value.strip().lower()

        if User.objects.filter(
            email__iexact=email
        ).exists():
            raise serializers.ValidationError(
                "A user with this email already exists."
            )

        return email

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {
                    "password_confirm": (
                        "Passwords do not match."
                    )
                }
            )

        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm")

        password = validated_data.pop("password")

        return User.objects.create_user(
            password=password,
            **validated_data,
        )


# ============================================================
# USER
# ============================================================


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = User

        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
        )

        read_only_fields = fields


# ============================================================
# PORTFOLIO
# ============================================================


class PortfolioSerializer(serializers.ModelSerializer):
    """
    Main Portfolio serializer.

    The serializer explicitly orders JSON output because
    PostgreSQL JSONB does not guarantee key order.

    Database values remain unchanged.
    """

    class Meta:
        model = Portfolio

        fields = (
            "id",
            "username",
            "email",
            "contact",
            "pan",
            "portfolio_totals",
            "mutual_fund_details",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "updated_at",
        )

    def validate_username(self, value):
        if value is None:
            return None

        value = str(value).strip()

        return value or None

    def validate_email(self, value):
        if value is None:
            return None

        value = str(value).strip().lower()

        return value or None

    def validate_contact(self, value):
        if value is None:
            return None

        value = str(value).strip()

        return value or None

    def validate_pan(self, value):
        if value is None:
            return None

        value = str(value).strip().upper()

        if not value:
            return None

        if len(value) != 10:
            raise serializers.ValidationError(
                "PAN must contain exactly 10 characters."
            )

        return value

    def validate_portfolio_totals(self, value):
        if value is None:
            return {}

        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "portfolio_totals must be a JSON object."
            )

        return value

    def validate_mutual_fund_details(self, value):
        if value is None:
            return []

        if not isinstance(value, list):
            raise serializers.ValidationError(
                "mutual_fund_details must be a JSON array."
            )

        for index, item in enumerate(
            value,
            start=1,
        ):
            if not isinstance(item, dict):
                raise serializers.ValidationError(
                    {
                        "mutual_fund_details": (
                            f"Item {index} must be a JSON object."
                        )
                    }
                )

        return value

    def to_representation(self, instance):
        """
        Explicitly control the output order of JSON data.

        This affects API presentation only.

        It does NOT modify the database.
        """

        data = super().to_representation(
            instance
        )

        data["portfolio_totals"] = (
            order_portfolio_totals(
                data.get(
                    "portfolio_totals"
                )
            )
        )

        data["mutual_fund_details"] = (
            order_mutual_fund_details(
                data.get(
                    "mutual_fund_details"
                )
            )
        )

        return data


# ============================================================
# PORTFOLIO DETAIL
# ============================================================


class PortfolioDetailSerializer(
    serializers.ModelSerializer
):
    """
    Detailed Portfolio serializer.

    Explicitly orders:
        portfolio_totals
        mutual_fund_details

    for GET API responses.
    """

    total_holdings = serializers.SerializerMethodField()

    import_count = serializers.SerializerMethodField()

    class Meta:
        model = Portfolio

        fields = (
            "id",
            "username",
            "email",
            "contact",
            "pan",
            "portfolio_totals",
            "mutual_fund_details",
            "total_holdings",
            "import_count",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "total_holdings",
            "import_count",
            "updated_at",
        )

    def get_total_holdings(self, obj):
        details = obj.mutual_fund_details

        if not isinstance(
            details,
            list,
        ):
            return 0

        return len(details)

    def get_import_count(self, obj):
        return obj.imports.count()

    def to_representation(self, instance):
        """
        Explicitly control JSON output order.
        """

        data = super().to_representation(
            instance
        )

        data["portfolio_totals"] = (
            order_portfolio_totals(
                data.get(
                    "portfolio_totals"
                )
            )
        )

        data["mutual_fund_details"] = (
            order_mutual_fund_details(
                data.get(
                    "mutual_fund_details"
                )
            )
        )

        return data


# ============================================================
# PORTFOLIO IMPORT
# ============================================================


class PortfolioImportSerializer(
    serializers.ModelSerializer
):

    class Meta:
        model = PortfolioImport

        fields = (
            "id",
            "portfolio",
            "source",
            "status",
            "file_name",
            "records_found",
            "records_created",
            "records_updated",
            "error_message",
            "started_at",
            "completed_at",
            "created_at",
        )

        read_only_fields = (
            "id",
            "records_found",
            "records_created",
            "records_updated",
            "error_message",
            "started_at",
            "completed_at",
            "created_at",
        )


# ============================================================
# PORTFOLIO TOTALS ORDERING
# ============================================================


def order_portfolio_totals(value):
    """
    Return portfolio totals in the exact requested order:

        total_cost_value
        total_market_value
        total_gain
        total_gain_percentage
        total_holdings

    The stored database value is NOT changed.

    Gain percentage is formatted to 2 decimal places for API
    presentation only.
    """

    if not isinstance(
        value,
        dict,
    ):
        return value

    total_gain_percentage = (
        value.get(
            "total_gain_percentage"
        )
    )

    total_gain_percentage = (
        format_percentage(
            total_gain_percentage
        )
    )

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
            total_gain_percentage
        ),

        "total_holdings": value.get(
            "total_holdings"
        ),
    }


# ============================================================
# MUTUAL FUND DETAILS ORDERING
# ============================================================


def order_mutual_fund_details(value):
    """
    Return each mutual-fund dictionary in the exact requested
    order:

        amc
        amfi_code
        isin
        scheme_name
        asset_type
        folio_number
        nav
        units
        nav_date
        current_value
        invested_value
    """

    if not isinstance(
        value,
        list,
    ):
        return value

    ordered_details = []

    for holding in value:

        if not isinstance(
            holding,
            dict,
        ):
            ordered_details.append(
                holding
            )
            continue

        ordered_details.append(
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

    return ordered_details


# ============================================================
# PERCENTAGE DISPLAY
# ============================================================


def format_percentage(value):
    """
    Format gain percentage to exactly two decimal places.

    Example:

        1.5801726824439515
        ->
        1.58

    This changes API presentation only.

    Underlying calculations/database values remain unchanged.
    """

    if value in (
        None,
        "",
    ):
        return value

    try:

        decimal_value = Decimal(
            str(value)
        )

        return format(
            decimal_value,
            ".2f",
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):

        return value
# from django.contrib.auth.models import User
# from django.contrib.auth.password_validation import validate_password
#
# from rest_framework import serializers
#
# from .models import (
#     Portfolio,
#     PortfolioImport,
# )
#
#
# # ============================================================
# # USER REGISTRATION
# # ============================================================
#
#
# class RegisterSerializer(serializers.ModelSerializer):
#     """
#     Serializer used to create a new SmartWealth user.
#
#     Endpoint:
#
#         POST /api/auth/register/
#
#     Authentication is NOT required for the public
#     financial-planning / CAS workflow.
#
#     This serializer remains available for future
#     authenticated functionality.
#     """
#
#     password = serializers.CharField(
#         write_only=True,
#         min_length=8,
#         validators=[validate_password],
#     )
#
#     password_confirm = serializers.CharField(
#         write_only=True,
#     )
#
#     class Meta:
#         model = User
#
#         fields = (
#             "username",
#             "email",
#             "first_name",
#             "last_name",
#             "password",
#             "password_confirm",
#         )
#
#     def validate_email(self, value):
#         """
#         Prevent duplicate email addresses.
#         """
#
#         email = value.strip().lower()
#
#         if User.objects.filter(
#             email__iexact=email
#         ).exists():
#             raise serializers.ValidationError(
#                 "A user with this email already exists."
#             )
#
#         return email
#
#     def validate(self, attrs):
#         """
#         Make sure both password fields match.
#         """
#
#         if attrs["password"] != attrs["password_confirm"]:
#             raise serializers.ValidationError(
#                 {
#                     "password_confirm": (
#                         "Passwords do not match."
#                     )
#                 }
#             )
#
#         return attrs
#
#     def create(self, validated_data):
#         """
#         Create the user using Django's create_user()
#         so that the password is securely hashed.
#         """
#
#         validated_data.pop("password_confirm")
#
#         password = validated_data.pop("password")
#
#         user = User.objects.create_user(
#             password=password,
#             **validated_data,
#         )
#
#         return user
#
#
# # ============================================================
# # USER
# # ============================================================
#
#
# class UserSerializer(serializers.ModelSerializer):
#     """
#     Serializer for authenticated user's information.
#
#     Used by:
#
#         GET /api/auth/me/
#
#     This is separate from Portfolio ownership.
#
#     A Portfolio does NOT require a Django User.
#     """
#
#     class Meta:
#         model = User
#
#         fields = (
#             "id",
#             "username",
#             "email",
#             "first_name",
#             "last_name",
#         )
#
#         read_only_fields = fields
#
#
# # ============================================================
# # PORTFOLIO
# # ============================================================
#
#
# class PortfolioSerializer(serializers.ModelSerializer):
#     """
#     Main serializer for the new JSON-based Portfolio model.
#
#     The Portfolio represents the investor's CAS-derived
#     financial portfolio.
#
#     Authentication is intentionally NOT required.
#
#     The portfolio contains:
#
#         - Investor identity
#         - Portfolio-level totals
#         - All mutual-fund holdings
#     """
#
#     class Meta:
#         model = Portfolio
#
#         fields = (
#             "id",
#             "username",
#             "email",
#             "contact",
#             "pan",
#             "portfolio_totals",
#             "mutual_fund_details",
#             "updated_at",
#         )
#
#         read_only_fields = (
#             "id",
#             "updated_at",
#         )
#
#     def validate_username(self, value):
#         """
#         Normalize the investor's name.
#         """
#
#         if value is None:
#             return value
#
#         value = value.strip()
#
#         return value or None
#
#     def validate_email(self, value):
#         """
#         Normalize email address when supplied.
#         """
#
#         if value is None:
#             return value
#
#         value = value.strip().lower()
#
#         return value or None
#
#     def validate_contact(self, value):
#         """
#         Normalize contact number.
#
#         We keep this validation intentionally lightweight
#         because CAS formats can vary.
#         """
#
#         if value is None:
#             return value
#
#         value = value.strip()
#
#         return value or None
#
#     def validate_pan(self, value):
#         """
#         Normalize PAN.
#
#         PAN is stored in uppercase.
#         """
#
#         if value is None:
#             return value
#
#         value = value.strip().upper()
#
#         if value == "":
#             return None
#
#         return value
#
#     def validate_portfolio_totals(self, value):
#         """
#         portfolio_totals must always be a JSON object.
#         """
#
#         if value is None:
#             return {}
#
#         if not isinstance(value, dict):
#             raise serializers.ValidationError(
#                 "portfolio_totals must be a JSON object."
#             )
#
#         return value
#
#     def validate_mutual_fund_details(self, value):
#         """
#         mutual_fund_details must always be a JSON array.
#
#         Each item represents one mutual-fund holding
#         extracted from the CAS.
#         """
#
#         if value is None:
#             return []
#
#         if not isinstance(value, list):
#             raise serializers.ValidationError(
#                 "mutual_fund_details must be a JSON array."
#             )
#
#         for index, holding in enumerate(value):
#             if not isinstance(holding, dict):
#                 raise serializers.ValidationError(
#                     {
#                         "mutual_fund_details": (
#                             f"Item {index} must be a JSON object."
#                         )
#                     }
#                 )
#
#         return value
#
#     def validate(self, attrs):
#         """
#         Perform portfolio-level validation.
#
#         We intentionally do not enforce a rigid list of
#         holding fields here because CAS formats can vary.
#
#         The CAS parser/service layer is responsible for
#         normalizing the actual CAS data.
#         """
#
#         portfolio_totals = attrs.get(
#             "portfolio_totals"
#         )
#
#         mutual_fund_details = attrs.get(
#             "mutual_fund_details"
#         )
#
#         if portfolio_totals is not None:
#             if not isinstance(
#                 portfolio_totals,
#                 dict,
#             ):
#                 raise serializers.ValidationError(
#                     {
#                         "portfolio_totals": (
#                             "Portfolio totals must be a JSON object."
#                         )
#                     }
#                 )
#
#         if mutual_fund_details is not None:
#             if not isinstance(
#                 mutual_fund_details,
#                 list,
#             ):
#                 raise serializers.ValidationError(
#                     {
#                         "mutual_fund_details": (
#                             "Mutual fund details must be a JSON array."
#                         )
#                     }
#                 )
#
#         return attrs
#
#
# # ============================================================
# # PORTFOLIO DETAIL
# # ============================================================
#
#
# class PortfolioDetailSerializer(
#     serializers.ModelSerializer
# ):
#     """
#     Detailed portfolio serializer.
#
#     Since all mutual-fund holdings now live inside
#     mutual_fund_details, no separate PortfolioHolding
#     query is required.
#     """
#
#     total_holdings = serializers.SerializerMethodField()
#
#     class Meta:
#         model = Portfolio
#
#         fields = (
#             "id",
#             "username",
#             "email",
#             "contact",
#             "pan",
#             "portfolio_totals",
#             "mutual_fund_details",
#             "total_holdings",
#             "updated_at",
#         )
#
#         read_only_fields = (
#             "id",
#             "total_holdings",
#             "updated_at",
#         )
#
#     def get_total_holdings(self, obj):
#         """
#         Return the number of mutual-fund holdings stored
#         inside mutual_fund_details.
#         """
#
#         details = obj.mutual_fund_details
#
#         if not isinstance(details, list):
#             return 0
#
#         return len(details)
#
#
# # ============================================================
# # PORTFOLIO IMPORT
# # ============================================================
#
#
# class PortfolioImportSerializer(
#     serializers.ModelSerializer
# ):
#     """
#     Serializer for CAS/API/manual portfolio imports.
#
#     This model stores import-processing information only.
#
#     IMPORTANT:
#
#         CAS passwords must NEVER be stored here.
#     """
#
#     class Meta:
#         model = PortfolioImport
#
#         fields = (
#             "id",
#             "portfolio",
#             "source",
#             "status",
#             "file_name",
#             "records_found",
#             "records_created",
#             "records_updated",
#             "error_message",
#             "started_at",
#             "completed_at",
#             "created_at",
#         )
#
#         read_only_fields = (
#             "id",
#             "records_found",
#             "records_created",
#             "records_updated",
#             "error_message",
#             "started_at",
#             "completed_at",
#             "created_at",
#         )