import concurrent.futures
import time
import requests
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.mutual_funds.models import MutualFundScheme

MAX_WORKERS = 30
BATCH_SIZE = 100
REQUEST_TIMEOUT = 30
MAX_RETRIES = 2
RETRY_DELAY = 1

_thread_local = None


def get_session():
    global _thread_local
    import threading
    if _thread_local is None:
        _thread_local = threading.local()
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=MAX_WORKERS,
            pool_maxsize=MAX_WORKERS,
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _thread_local.session = s
    return _thread_local.session


def clean_nav(nav):
    if nav is None:
        return None
    try:
        s = str(nav).strip()
        if not s or s.lower() == "n.a.":
            return None
        float(s)
        return s
    except (ValueError, TypeError):
        return None


def parse_mfapi_date(date_str):
    """MFAPI dates are dd-mm-yyyy. Returns a datetime.date or None."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%d-%m-%Y").date()
    except (ValueError, TypeError):
        return None


def format_nav_date(d):
    return d.strftime("%d-%m-%Y")


def clean_existing_history(data):
    """
    Returns a list of cleaned {nav, date} dicts from whatever is
    currently stored, dropping malformed entries.
    """
    cleaned = []
    if not isinstance(data, list):
        return cleaned
    for entry in data:
        if not isinstance(entry, dict):
            continue
        nav = clean_nav(entry.get("nav"))
        d = parse_mfapi_date(entry.get("date"))
        if nav is None or d is None:
            continue
        cleaned.append({"nav": nav, "date": format_nav_date(d)})
    return cleaned


def clean_api_records(api_data):
    """
    Cleans raw MFAPI records.
    Returns (cleaned_unique_list, duplicate_api_record_count)
    where cleaned_unique_list has ONE entry per date (first occurrence wins)
    and duplicate_api_record_count is how many extra dated rows MFAPI sent
    for dates it had already sent in this same response.
    """
    seen_dates = set()
    cleaned = []
    duplicate_api_records = 0

    if not isinstance(api_data, list):
        return cleaned, duplicate_api_records

    for entry in api_data:
        if not isinstance(entry, dict):
            continue
        nav = clean_nav(entry.get("nav"))
        d = parse_mfapi_date(entry.get("date"))
        if nav is None or d is None:
            continue

        date_str = format_nav_date(d)
        if date_str in seen_dates:
            duplicate_api_records += 1
            continue

        seen_dates.add(date_str)
        cleaned.append({"nav": nav, "date": date_str})

    return cleaned, duplicate_api_records


def sort_nav_data(data):
    def key(entry):
        d = parse_mfapi_date(entry.get("date"))
        return d or datetime.min.date()
    return sorted(data, key=key, reverse=True)


def get_date_range(data):
    if not data:
        return None, None
    dates = [parse_mfapi_date(e.get("date")) for e in data]
    dates = [d for d in dates if d]
    if not dates:
        return None, None
    return min(dates), max(dates)


def fetch_scheme_history(scheme_code):
    """
    Fetches full history for a scheme from MFAPI with retries.
    Returns the raw 'data' list from MFAPI, or None on failure.
    """
    url = f"https://api.mfapi.in/mf/{scheme_code}"
    session = get_session()

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                payload = resp.json()
                return payload.get("data", [])
            else:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
        except (requests.RequestException, ValueError):
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return None


def process_scheme(scheme_id, scheme_code):
    """
    Fetches MFAPI history for one scheme and merges it into the DB
    without destroying existing data, and WITHOUT creating duplicate
    dates.

    Returns a stats dict:
        {
            "scheme_code": scheme_code,
            "status": "ok" | "no_api_data" | "error",
            "api_records": int,
            "api_duplicate_records": int,
            "existing_before": int,
            "new_records": int,
            "existing_matches": int,   # MFAPI dates that already existed in DB
            "final_history": int,
            "error": str | None,
        }
    """
    stats = {
        "scheme_code": scheme_code,
        "status": "ok",
        "api_records": 0,
        "api_duplicate_records": 0,
        "existing_before": 0,
        "new_records": 0,
        "existing_matches": 0,
        "final_history": 0,
        "error": None,
    }

    raw_api_data = fetch_scheme_history(scheme_code)

    if raw_api_data is None:
        stats["status"] = "error"
        stats["error"] = "fetch_failed"
        return stats

    if not raw_api_data:
        stats["status"] = "no_api_data"
        return stats

    # Clean + de-dupe the API response itself.
    api_cleaned, api_duplicate_records = clean_api_records(raw_api_data)
    api_dates = set(entry["date"] for entry in api_cleaned)

    try:
        with transaction.atomic():
            scheme = MutualFundScheme.objects.select_for_update().get(id=scheme_id)

            cleaned_existing = clean_existing_history(scheme.data)

            # --- SNAPSHOT taken BEFORE any mutation ---
            original_existing_dates = set(
                entry["date"] for entry in cleaned_existing
            )
            existing_before_count = len(cleaned_existing)

            # Dates MFAPI returned that were ALREADY in the DB before this run.
            existing_matches = len(api_dates & original_existing_dates)

            # Build a lookup of existing entries by date for the merge.
            existing_by_date = {e["date"]: e for e in cleaned_existing}

            new_records = 0
            for entry in api_cleaned:
                date_str = entry["date"]
                if date_str in original_existing_dates:
                    # Already present -> never overwrite existing NAV value.
                    continue
                existing_by_date[date_str] = entry
                new_records += 1

            merged = list(existing_by_date.values())
            merged_sorted = sort_nav_data(merged)

            scheme.data = merged_sorted
            scheme.save(update_fields=["data"])

            stats["api_records"] = len(api_cleaned)
            stats["api_duplicate_records"] = api_duplicate_records
            stats["existing_before"] = existing_before_count
            stats["new_records"] = new_records
            stats["existing_matches"] = existing_matches
            stats["final_history"] = len(merged_sorted)

    except MutualFundScheme.DoesNotExist:
        stats["status"] = "error"
        stats["error"] = "scheme_not_found"
    except Exception as e:
        stats["status"] = "error"
        stats["error"] = str(e)

    return stats


class Command(BaseCommand):
    help = "Backfill complete historical NAV data from MFAPI into MutualFundScheme.data"

    def add_arguments(self, parser):
        parser.add_argument("--start-index", type=int, default=1)
        parser.add_argument("--end-index", type=int, default=None)
        parser.add_argument("--workers", type=int, default=MAX_WORKERS)

    def handle(self, *args, **options):
        start_index = options["start_index"]
        end_index = options["end_index"]
        workers = options["workers"]

        qs = MutualFundScheme.objects.order_by("scheme_code").values_list(
            "id", "scheme_code"
        )
        all_schemes = list(qs)
        total_schemes = len(all_schemes)

        if end_index is None:
            end_index = total_schemes

        # 1-based inclusive indices, as used in the examples.
        selected = all_schemes[start_index - 1:end_index]

        self.stdout.write(
            f"Processing schemes {start_index} to {end_index} "
            f"({len(selected)} schemes) with {workers} workers"
        )

        total_api_records = 0
        total_api_duplicate_records = 0
        total_new_records = 0
        total_existing_matches = 0
        total_errors = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_index = {
                executor.submit(process_scheme, scheme_id, scheme_code): idx
                for idx, (scheme_id, scheme_code) in enumerate(
                    selected, start=start_index
                )
            }

            for future in concurrent.futures.as_completed(future_to_index):
                idx = future_to_index[future]
                stats = future.result()

                if stats["status"] == "ok":
                    total_api_records += stats["api_records"]
                    total_api_duplicate_records += stats["api_duplicate_records"]
                    total_new_records += stats["new_records"]
                    total_existing_matches += stats["existing_matches"]

                    self.stdout.write(
                        f"[{idx}/{total_schemes}] {stats['scheme_code']} | "
                        f"API: {stats['api_records']} | "
                        f"New: {stats['new_records']} | "
                        f"Dup: {stats['existing_matches']} | "
                        f"History: {stats['final_history']}"
                    )
                elif stats["status"] == "no_api_data":
                    self.stdout.write(
                        f"[{idx}/{total_schemes}] {stats['scheme_code']} | "
                        f"No API data"
                    )
                else:
                    total_errors += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"[{idx}/{total_schemes}] {stats['scheme_code']} | "
                            f"ERROR: {stats['error']}"
                        )
                    )

        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Total MFAPI records        : {total_api_records}")
        self.stdout.write(f"Total API-internal dupes   : {total_api_duplicate_records}")
        self.stdout.write(f"Total new records added    : {total_new_records}")
        self.stdout.write(f"Total duplicates skipped   : {total_existing_matches}")
        self.stdout.write(f"Total errors               : {total_errors}")
        self.stdout.write("=" * 60)