from rest_framework import serializers

from apps.mutual_funds.models import (
    FundHouse,
    MutualFundScheme,
)


# ============================================================
# FUND HOUSE SERIALIZER
# ============================================================

class FundHouseSerializer(serializers.ModelSerializer):
    """
    Returns basic Fund House / AMC information.
    """

    class Meta:
        model = FundHouse

        fields = [
            "id",
            "name",
            "number_of_schemes",
            "is_active",
        ]


# ============================================================
# SCHEME LIST SERIALIZER
# ============================================================

class MutualFundSchemeListSerializer(
    serializers.ModelSerializer
):
    """
    Used by:

        GET /api/mutual-funds/schemes/

    Returns basic scheme information.

    Complete NAV data is intentionally not included here
    because returning the complete history for every scheme
    would make the response unnecessarily large.
    """

    fund_house = serializers.CharField(
        source="fund_house.name",
        read_only=True,
    )

    class Meta:
        model = MutualFundScheme

        fields = [
            "scheme_code",
            "scheme_name",
            "fund_house",
            "scheme_type",
            "scheme_category",
            "isin_growth",
            "isin_div_payout",
            "isin_div_reinvestment",
            "is_active",
        ]


# ============================================================
# SCHEME DETAIL SERIALIZER
# ============================================================

class MutualFundSchemeDetailSerializer(
    serializers.ModelSerializer
):
    """
    Used by:

        GET /api/mutual-funds/schemes/<scheme_code>/

    Returns complete scheme information.

    NAV data is not included in this endpoint.
    """

    fund_house = serializers.CharField(
        source="fund_house.name",
        read_only=True,
    )

    class Meta:
        model = MutualFundScheme

        fields = [
            "scheme_code",
            "scheme_name",
            "fund_house",
            "scheme_type",
            "scheme_category",
            "isin_growth",
            "isin_div_payout",
            "isin_div_reinvestment",
            "is_active",
        ]


# ============================================================
# NAV HISTORY / DATA SERIALIZER
# ============================================================

class NAVHistorySerializer(
    serializers.ModelSerializer
):
    """
    Used by:

        GET /api/mutual-funds/schemes/<scheme_code>/nav-history/

    Returns complete scheme information plus the complete
    NAV data stored inside the JSONField named `data`.
    """

    fund_house = serializers.CharField(
        source="fund_house.name",
        read_only=True,
    )

    data = serializers.SerializerMethodField()

    class Meta:
        model = MutualFundScheme

        fields = [
            "scheme_code",
            "scheme_name",
            "fund_house",
            "scheme_type",
            "scheme_category",
            "isin_growth",
            "isin_div_payout",
            "isin_div_reinvestment",
            "is_active",
            "data",
        ]

    def get_data(self, obj):
        """
        Return NAV data exactly as stored in the database.

        Expected structure:

        [
            {
                "date": "15-07-2026",
                "nav": "13.7982"
            }
        ]
        """

        data = obj.data

        if not data:
            return []

        return data


# ============================================================
# DATE-SPECIFIC NAV SERIALIZER
# ============================================================

class NAVHistoryDateSerializer(
    serializers.Serializer
):
    """
    Used by:

        GET /api/mutual-funds/schemes/<scheme_code>/
        nav-history/<date>/

    Example:

        /schemes/152076/nav-history/2026-07-15/
    """

    scheme_code = serializers.CharField()

    scheme_name = serializers.CharField()

    fund_house = serializers.CharField()

    scheme_type = serializers.CharField(
        allow_null=True
    )

    scheme_category = serializers.CharField(
        allow_null=True
    )

    isin_growth = serializers.CharField(
        allow_null=True
    )

    isin_div_payout = serializers.CharField(
        allow_null=True
    )

    isin_div_reinvestment = serializers.CharField(
        allow_null=True
    )

    is_active = serializers.BooleanField()

    date = serializers.CharField()

    nav = serializers.CharField()
