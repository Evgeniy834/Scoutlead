
# state.py
import datetime

next_run_time: datetime.datetime | None = None
next_manual_run_time: datetime.datetime | None = None
is_search_running: bool = False