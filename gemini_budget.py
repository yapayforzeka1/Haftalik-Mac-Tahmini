"""Persistent request budget for this bot; never stores keys or model output.

The workflow serializes production and TEST jobs and saves the ledger after
either. Requests made by other tools/projects are not visible to this ledger.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

from storage import StateError, load_json, save_json


class BudgetDeferred(Exception):
    def __init__(self, category, retry_after):
        super().__init__(category)
        self.category = category
        self.retry_after = retry_after.isoformat()


class GeminiRequestBudget:
    def __init__(self, path, model, *, rpm=5, rpd=20, clock=None,
                 monotonic=None, sleep=None):
        if type(rpm) is not int or type(rpd) is not int or min(rpm, rpd) < 1:
            raise ValueError('Gemini budget limits must be positive integers')
        self.path = Path(path)
        self.model = model
        self.rpm, self.rpd = rpm, rpd
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic or time.monotonic
        self.sleep = sleep or time.sleep
        self.lock = threading.Lock()

    def reserve(self, deadline=None):
        """Persist each attempt BEFORE calling Gemini, including retries.

        Use a rolling minute and Google's Pacific calendar day. A reservation
        is conservative: even a later transport/SDK failure remains counted.
        Never wait if doing so leaves less than a 30-second request window.
        """
        while True:
            with self.lock:
                now = self.clock().astimezone(timezone.utc)
                pacific = now.astimezone(ZoneInfo('America/Los_Angeles'))
                day = pacific.date().isoformat()
                reset = datetime.combine(pacific.date() + timedelta(days=1),
                                         datetime.min.time(), pacific.tzinfo)
                reset = reset.astimezone(timezone.utc)
                doc = load_json(self.path, {})
                if doc and (doc.get('schema') != 1 or not isinstance(doc.get('models'), dict)):
                    raise StateError('Gemini budget archive schema invalid')
                doc = doc or {'schema': 1, 'models': {}}
                item = doc['models'].get(self.model, {'day': day, 'attempts': 0, 'recent': []})
                try:
                    if (not isinstance(item, dict) or type(item.get('attempts')) is not int
                            or item['attempts'] < 0 or not isinstance(item.get('recent'), list)):
                        raise ValueError()
                    datetime.strptime(item['day'], '%Y-%m-%d')
                    recent = [datetime.fromisoformat(s) for s in item['recent']]
                    if any(t.tzinfo is None or t > now for t in recent):
                        raise ValueError()
                except (ValueError, TypeError, KeyError):
                    raise StateError('Gemini budget entry invalid') from None
                recent = sorted(t for t in recent if (now - t).total_seconds() < 60)
                attempts = item['attempts'] if item['day'] == day else 0
                if attempts >= self.rpd:
                    raise BudgetDeferred('LOCAL_DAILY_BUDGET', reset)
                if deadline is not None and self.monotonic() + 30 >= deadline:
                    raise BudgetDeferred('LOCAL_REQUEST_WINDOW', now + timedelta(minutes=5))
                if len(recent) >= self.rpm:
                    ready = recent[-self.rpm] + timedelta(seconds=60.1)
                    wait = max(0.1, (ready - now).total_seconds())
                    if deadline is not None and self.monotonic() + wait + 30 >= deadline:
                        raise BudgetDeferred('LOCAL_MINUTE_BUDGET', ready)
                else:
                    recent.append(now)
                    doc['models'][self.model] = {
                        'day': day, 'attempts': attempts + 1,
                        'recent': [t.isoformat() for t in recent],
                    }
                    save_json(self.path, doc)
                    print(f'GEMINI BUDGET | attempts={attempts + 1}/{self.rpd}', flush=True)
                    return
            self.sleep(wait)
