import requests
from datetime import date, timedelta

from apps.mutual_funds.services.parser import parse_amfi_report


AMFI_NAV_URL = (
    "https://portal.amfiindia.com/"
    "DownloadNAVHistoryReport_Po.aspx"
)


def download_nav_report(date):
    """
    Download the AMFI NAV report for the requested date.

    Args:
        date: Date string in format DD-Mon-YYYY
              Example: 11-Aug-2026

    Returns:
        str: Raw AMFI response text
    """

    params = {
        "frmdt": date
    }

    response = requests.get(
        AMFI_NAV_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    return response.text


def download_latest_available_nav_report(
    start_date: date,
    max_days_back: int = 10,
):
    """
    Find the latest AMFI NAV report that contains
    actual parsed NAV records.

    The function starts from start_date.

    If AMFI returns a response but that response contains
    no valid NAV records, the function checks the previous
    calendar date.

    Example:

        11-Aug-2026 -> 0 records
        10-Aug-2026 -> valid records

    Then 10-Aug-2026 is selected.

    Returns:
        tuple:
            raw_data
            actual_nav_date
            records
    """

    current_date = start_date

    for _ in range(max_days_back + 1):

        date_string = current_date.strftime("%d-%b-%Y")

        print(
            f"Trying AMFI NAV date: {date_string}"
        )

        try:
            raw_data = download_nav_report(date_string)

            # IMPORTANT:
            # AMFI can return a non-empty response even when
            # there is no actual NAV data.
            #
            # Therefore, we must parse the response and check
            # the number of valid NAV records.
            records = parse_amfi_report(raw_data)

        except Exception as exc:
            print(
                f"Error while checking {date_string}: {exc}"
            )

            records = []

        print(
            f"Parsed records for {date_string}: "
            f"{len(records)}"
        )

        # Actual NAV data found
        if records:

            print(
                f"Valid AMFI NAV data found for: "
                f"{date_string}"
            )

            return (
                raw_data,
                current_date,
                records
            )

        # No valid NAV data
        print(
            f"No valid NAV records for {date_string}. "
            f"Trying previous date..."
        )

        current_date -= timedelta(days=1)

    raise ValueError(
        f"No valid AMFI NAV data found within "
        f"{max_days_back} days before "
        f"{start_date}."
    )