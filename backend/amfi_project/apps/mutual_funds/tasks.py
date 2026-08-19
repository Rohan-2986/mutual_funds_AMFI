from celery import shared_task

from apps.mutual_funds.services.nav_sync import sync_nav_data


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def sync_daily_nav(self):
    """
    Automatically synchronize the latest available
    AMFI NAV data.

    Celery Beat will trigger this task according
    to the configured schedule.
    """

    log = sync_nav_data()

    return {
        "status": log.status,
        "records_received": log.records_received,
        "records_created": log.records_created,
        "new_schemes": log.new_schemes,
        "deactivated_schemes": log.deactivated_schemes,
        "duplicate_records": log.duplicate_records,
        "errors": log.error_count,
    }