---
name: discord.py tasks.loop daily scheduling
description: How to schedule a once-per-day background job in discord.py without it firing immediately on every bot restart.
---

`discord.ext.tasks.loop(hours=24)` runs its first iteration immediately when `.start()` is called, then waits 24h. For a bot that gets restarted often (deploys, crashes, workflow restarts), this means a "morning scan" style job fires every time the process restarts, not just once a day at the intended time.

**Fix:** use the `time=` parameter instead, with a timezone-aware `datetime.time`:

```python
from datetime import time
from zoneinfo import ZoneInfo
from discord.ext import tasks

MORNING_SCAN_TIME = time(hour=9, minute=35, tzinfo=ZoneInfo("America/New_York"))

@tasks.loop(time=MORNING_SCAN_TIME)
async def morning_scan():
    ...
```

This waits until the next occurrence of that clock time before firing, regardless of when the loop was started — safe across restarts.
