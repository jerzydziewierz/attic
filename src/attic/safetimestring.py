import datetime
import pytz
import re
import pathlib

def datetime_to_safestring(timestamp: datetime.datetime) -> str:
    unsafestring = datetime.datetime.now(tz=pytz.UTC).isoformat(timespec='microseconds')
    safestring = re.sub(r'[/:*?"<>|.]', '_', unsafestring)
    return safestring


def safestring_to_datetime(safestring: str) -> datetime.datetime:
    unsafestring = re.sub(r'[_]', ':', safestring)
    return datetime.datetime.fromisoformat(unsafestring)


def timefolders(root_folder, datetime):
    iso_datetime_str = datetime.isoformat(timespec='microseconds')
    folder_names_inner = iso_datetime_str.split('T')[0].split('-')
    full_folder_name = pathlib.Path(root_folder, *folder_names_inner)
    return full_folder_name




def test_datetime_safestring_conversion():
    log = lambda x: None
    timestamp = datetime.datetime.now(tz=pytz.UTC)
    log(timestamp)
    safestring = datetime_to_safestring(timestamp)
    log(safestring)
    timestamp_recovered = safestring_to_datetime(safestring)
    log(timestamp_recovered)
    timedelta = timestamp_recovered - timestamp
    timedelta_seconds = timedelta.total_seconds()
    assert (timedelta_seconds < 1e-2)
    log(timedelta_seconds)


test_datetime_safestring_conversion()
