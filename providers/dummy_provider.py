# providers/dummy_provider.py — simulates an external platform
from __future__ import annotations
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from core.integrations import Provider, register

@register
class DummyProvider(Provider):
    key = "dummy"
    # Pretend it has same 3 services for every business
    def fetch_services(self) -> List[Dict]:
        return [
            {"id": 101, "name": "Exam (ext)", "duration_min": 30, "price": "£80"},
            {"id": 102, "name": "Whitening (ext)", "duration_min": 60, "price": "£300"},
            {"id": 103, "name": "Filling (ext)", "duration_min": 45, "price": "£150"},
        ]

    def fetch_slots(self, service_id: Optional[int], date_str: str) -> List[str]:
        if not service_id: return []
        # Always return 09:00–17:00 every 30 mins minus lunch (12:00)
        day = datetime.strptime(date_str, "%Y-%m-%d")
        step = 30
        slots=[]
        cur = day.replace(hour=9,minute=0,second=0,microsecond=0)
        end = day.replace(hour=17,minute=0,second=0,microsecond=0)
        while cur < end:
            if cur.hour != 12:  # skip lunch
                slots.append(cur.strftime("%Y-%m-%d %H:%M"))
            cur += timedelta(minutes=step)
        return slots

    def create_booking(self, payload: Dict) -> Dict:
        # Simulate external ID
        return {"external_id": f"dummy_{int(datetime.utcnow().timestamp())}"}

    def cancel_booking(self, external_id: str) -> bool:
        return True
