import typing
import sqlite3
import pathlib
from .safetimestring import datetime_to_safestring, timefolders
def make_renew_database_link(state):
    def renew_database_link() -> typing.Tuple[sqlite3.Cursor, sqlite3.Connection]:

        nonlocal state # enclose from outer scope
        pathlib.Path(q_stream_path).mkdir(parents=True, exist_ok=True)
        safedatestring = datetime_to_safestring(datetime.datetime.now(tz=pytz.UTC))
        file_name = f'{safedatestring}.sqlite'
        # prepare folder name
        # folder per day should be sufficient for this application
        full_folder_name = timefolders(q_stream_path, datetime.datetime.now(tz=pytz.UTC))
        full_folder_name.mkdir(parents=True, exist_ok=True)
        sqlite_db_path = full_folder_name.joinpath(file_name)
        stdout(f'{q_stream_idx=} | topic={state['configs'][q_stream_idx]['prefix']} |  creating new file {sqlite_db_path}')
        sqlite_connection_r = sqlite3.connect(sqlite_db_path)
        sqlite_cursor_r = sqlite_connection_r.cursor()
        sqlite_cursor_r.execute(
            'CREATE TABLE IF NOT EXISTS data (reception_timestamp INTEGER, topic TEXT, payload BLOB)')
        # this is so that at read time, the data can be quickly filtered by topic.
        sqlite_cursor_r.execute(
            'CREATE INDEX IF NOT EXISTS topics ON data (topic)')
        sqlite_connection_r.commit()
        # save the cursor and connection to the shared state for use by interested parties.
        state['streams'][q_stream_idx]['sqlite_cursor'] = sqlite_cursor_r
        state['streams'][q_stream_idx]['sqlite_connection'] = sqlite_connection_r
        # important: set the expiration time for the next rotation
        next_rotation_time_r = time.time() + log_rotation_time
        state['streams'][q_stream_idx]['next_rotation_time'] = next_rotation_time_r
        return sqlite_cursor_r, sqlite_connection_r
    return renew_database_link