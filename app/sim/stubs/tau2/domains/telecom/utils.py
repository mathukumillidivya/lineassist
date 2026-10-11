from datetime import date, datetime


def get_now() -> datetime:
    return datetime(2025, 2, 25, 12, 8, 0)


def get_today() -> date:
    return date(2025, 2, 25)

TELECOM_DB_PATH = None          # the databases are passed in as JSON, not read from disk
TELECOM_USER_DB_PATH = None
