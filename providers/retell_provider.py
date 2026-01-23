# providers/retell_provider.py — Retell AI voice provider
# Integrates voice calling with the provider pattern

from typing import List, Dict, Optional
from core.integrations import Provider, register


@register
class RetellProvider(Provider):
    """Retell AI voice provider.

    This provider handles voice-specific operations but inherits from the
    Provider base class for consistency with the integration system.

    Configuration (stored in integrations.account_json):
        {
            "api_key": "key_xxx",  # Can override global key
            "agent_id": "agent_xxx",
            "phone_number": "+14155551234"
        }
    """

    key = "retell"

    def __init__(self, business_id: int, config: dict):
        super().__init__(business_id, config)
        self.api_key = config.get("api_key")
        self.agent_id = config.get("agent_id")
        self.phone_number = config.get("phone_number")

    def fetch_services(self) -> List[Dict]:
        """Retell doesn't manage services - delegate to local provider."""
        from providers.local_provider import LocalProvider
        return LocalProvider(self.business_id, {}).fetch_services()

    def fetch_slots(self, service_id: Optional[int], date_str: str) -> List[str]:
        """Retell doesn't manage slots - delegate to local provider."""
        from providers.local_provider import LocalProvider
        return LocalProvider(self.business_id, {}).fetch_slots(service_id, date_str)

    def create_booking(self, payload: Dict) -> Dict:
        """Create booking via local provider (voice calls use same booking system)."""
        from providers.local_provider import LocalProvider
        return LocalProvider(self.business_id, {}).create_booking(payload)

    def cancel_booking(self, external_id: str) -> bool:
        """Cancel booking via local provider."""
        from providers.local_provider import LocalProvider
        return LocalProvider(self.business_id, {}).cancel_booking(external_id)

    # ========================================================================
    # Voice-Specific Methods
    # ========================================================================

    def get_agent_id(self) -> Optional[str]:
        """Get the Retell agent ID for this business."""
        if self.agent_id:
            return self.agent_id

        # Fall back to voice_settings
        from core.voice import get_voice_settings
        settings = get_voice_settings(self.business_id)
        return settings.get("retell_agent_id")

    def get_phone_number(self) -> Optional[str]:
        """Get the Retell phone number for this business."""
        if self.phone_number:
            return self.phone_number

        # Fall back to voice_settings
        from core.voice import get_voice_settings
        settings = get_voice_settings(self.business_id)
        return settings.get("retell_phone_number")

    def create_outbound_call(self, to_number: str, metadata: Optional[Dict] = None) -> Dict:
        """Create an outbound call using Retell.

        Args:
            to_number: Destination phone number (E.164 format)
            metadata: Optional metadata to include

        Returns:
            Call data from Retell API
        """
        from core.voice import get_retell_client, RetellClientError

        agent_id = self.get_agent_id()
        from_number = self.get_phone_number()

        if not agent_id:
            raise RetellClientError("No agent ID configured")
        if not from_number:
            raise RetellClientError("No phone number configured")

        client = get_retell_client()
        return client.create_phone_call(
            from_number=from_number,
            to_number=to_number,
            agent_id=agent_id,
            metadata={
                "business_id": self.business_id,
                **(metadata or {})
            }
        )

    def get_call_analytics(self, days: int = 30) -> Dict:
        """Get voice call analytics for this business.

        Args:
            days: Number of days to look back

        Returns:
            Analytics summary
        """
        from core.db import get_conn

        with get_conn() as con:
            # Total calls
            total = con.execute("""
                SELECT COUNT(*) as count FROM voice_calls
                WHERE business_id = ?
                  AND datetime(created_at) > datetime('now', ? || ' days')
            """, (self.business_id, -days)).fetchone()["count"]

            # Calls by direction
            by_direction = {}
            for row in con.execute("""
                SELECT direction, COUNT(*) as count FROM voice_calls
                WHERE business_id = ?
                  AND datetime(created_at) > datetime('now', ? || ' days')
                GROUP BY direction
            """, (self.business_id, -days)):
                by_direction[row["direction"]] = row["count"]

            # Average duration
            avg_duration = con.execute("""
                SELECT AVG(duration_seconds) as avg FROM voice_calls
                WHERE business_id = ?
                  AND duration_seconds IS NOT NULL
                  AND datetime(created_at) > datetime('now', ? || ' days')
            """, (self.business_id, -days)).fetchone()["avg"] or 0

            # Bookings from voice
            bookings = con.execute("""
                SELECT COUNT(*) as count FROM voice_calls
                WHERE business_id = ?
                  AND booking_confirmed = 1
                  AND datetime(created_at) > datetime('now', ? || ' days')
            """, (self.business_id, -days)).fetchone()["count"]

            # Transfers
            transfers = con.execute("""
                SELECT COUNT(*) as count FROM voice_calls
                WHERE business_id = ?
                  AND transferred = 1
                  AND datetime(created_at) > datetime('now', ? || ' days')
            """, (self.business_id, -days)).fetchone()["count"]

            # Total cost
            total_cost = con.execute("""
                SELECT SUM(cost_cents) as total FROM voice_calls
                WHERE business_id = ?
                  AND cost_cents IS NOT NULL
                  AND datetime(created_at) > datetime('now', ? || ' days')
            """, (self.business_id, -days)).fetchone()["total"] or 0

        return {
            "total_calls": total,
            "by_direction": by_direction,
            "avg_duration_seconds": round(avg_duration, 1),
            "bookings_confirmed": bookings,
            "transfers": transfers,
            "total_cost_cents": total_cost,
            "period_days": days,
        }

    def is_configured(self) -> bool:
        """Check if Retell is properly configured for this business."""
        return bool(self.get_agent_id() and self.get_phone_number())
