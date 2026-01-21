# providers/local_provider.py — uses local DB hours/closures/appointments
from __future__ import annotations
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from core.integrations import Provider, register
from core.db import get_conn

@register
class LocalProvider(Provider):
    key = "local"

    def fetch_services(self) -> List[Dict]:
        with get_conn() as con:
            rows = con.execute("SELECT id,name,duration_min,price FROM services WHERE business_id=? AND active=1 ORDER BY name", (self.business_id,)).fetchall()
        return [dict(r) for r in rows]

    def _day_hours(self, con, day: datetime):
        wd = day.weekday()
        row = con.execute("""
          SELECT open_time,close_time,closed FROM business_hours
          WHERE business_id=? AND weekday=?
        """, (self.business_id, wd)).fetchone()
        if not row or row["closed"] or not row["open_time"] or not row["close_time"]:
            return None
        return row["open_time"], row["close_time"]

    def _is_closed(self, con, day: datetime) -> bool:
        d = day.strftime("%Y-%m-%d")
        return bool(con.execute("SELECT 1 FROM closures WHERE business_id=? AND date=?", (self.business_id, d)).fetchone())

    def _appointments_on(self, con, date_str: str):
        return con.execute("""
          SELECT id, COALESCE(start_at, created_at) AS start_at, service
          FROM appointments
          WHERE business_id=? AND date(COALESCE(start_at, created_at))=date(?)
          ORDER BY start_at
        """, (self.business_id, date_str)).fetchall()

    def fetch_slots(self, service_id: Optional[int], date_str: str) -> List[str]:
        if not service_id: return []
        with get_conn() as con:
            svc = con.execute("SELECT duration_min FROM services WHERE id=? AND business_id=?", (service_id,self.business_id)).fetchone()
            if not svc: return []
            dur = svc["duration_min"]
            day = datetime.strptime(date_str, "%Y-%m-%d")
            if self._is_closed(con, day): return []
            hours = self._day_hours(con, day)
            if not hours: return []
            open_h, close_h = hours
            h1,m1 = map(int, open_h.split(":")); h2,m2 = map(int, close_h.split(":"))
            start = day.replace(hour=h1, minute=m1, second=0, microsecond=0)
            end   = day.replace(hour=h2, minute=m2, second=0, microsecond=0)

            # build busy intervals
            appts = self._appointments_on(con, date_str)
            busy=[]
            for a in appts:
                try:
                    a_start = datetime.strptime(a["start_at"], "%Y-%m-%d %H:%M")
                except:
                    try: a_start = datetime.fromisoformat(a["start_at"])
                    except: continue
                adur = dur
                if a["service"]:
                    row = con.execute("SELECT duration_min FROM services WHERE business_id=? AND name=?", (self.business_id, a["service"])).fetchone()
                    if row: adur = row["duration_min"]
                busy.append((a_start, a_start+timedelta(minutes=adur)))

            slots=[]
            step=timedelta(minutes=15)
            cur=start
            while cur + timedelta(minutes=dur) <= end:
                slot_end = cur + timedelta(minutes=dur)
                conflict = any(not (slot_end <= b0 or b1 <= cur) for (b0,b1) in busy)
                if not conflict:
                    slots.append(cur.strftime("%Y-%m-%d %H:%M"))
                cur += step
            return slots

    def create_booking(self, payload: Dict) -> Dict:
        # Up to you: you can also write to appointments here, but we already do it elsewhere.
        return {"external_id": None}

    def cancel_booking(self, external_id: str) -> bool:
        return True
