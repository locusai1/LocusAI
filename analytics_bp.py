# analytics_bp.py — Comprehensive Analytics Dashboard
# Enterprise-grade analytics with real-time metrics and beautiful visualizations

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, g

from core.db import get_conn

logger = logging.getLogger(__name__)

analytics_bp = Blueprint("analytics", __name__)


# =============================================================================
# Authentication Helpers
# =============================================================================

def _user() -> Optional[dict]:
    return session.get("user")


def _need_login():
    if _user() is None:
        flash("Please log in to continue.", "err")
        return redirect(url_for("auth.login"))
    return None


# =============================================================================
# Date Range Helpers
# =============================================================================

def _parse_date_range(range_key: str) -> Tuple[str, str, str]:
    """
    Parse a date range key into start_date, end_date, and label.
    Returns ISO format dates (YYYY-MM-DD).
    """
    today = datetime.now().date()

    ranges = {
        "today": (today, today, "Today"),
        "yesterday": (today - timedelta(days=1), today - timedelta(days=1), "Yesterday"),
        "7d": (today - timedelta(days=6), today, "Last 7 Days"),
        "30d": (today - timedelta(days=29), today, "Last 30 Days"),
        "90d": (today - timedelta(days=89), today, "Last 90 Days"),
        "this_month": (today.replace(day=1), today, "This Month"),
        "last_month": (
            (today.replace(day=1) - timedelta(days=1)).replace(day=1),
            today.replace(day=1) - timedelta(days=1),
            "Last Month"
        ),
        "this_year": (today.replace(month=1, day=1), today, "This Year"),
    }

    if range_key in ranges:
        start, end, label = ranges[range_key]
        return start.isoformat(), end.isoformat(), label

    # Default to last 30 days
    start, end, label = ranges["30d"]
    return start.isoformat(), end.isoformat(), label


def _get_comparison_range(start_date: str, end_date: str) -> Tuple[str, str]:
    """Get the previous period for comparison."""
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    period_days = (end - start).days + 1

    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)

    return prev_start.isoformat(), prev_end.isoformat()


# =============================================================================
# Data Aggregation Functions
# =============================================================================

def _get_overview_stats(business_id: int, start_date: str, end_date: str) -> Dict[str, Any]:
    """Get high-level overview statistics."""
    with get_conn() as con:
        # Total conversations
        conversations = con.execute("""
            SELECT COUNT(*) as total,
                   COUNT(CASE WHEN escalated = 1 THEN 1 END) as escalated
            FROM sessions
            WHERE business_id = ?
              AND date(created_at) BETWEEN ? AND ?
        """, (business_id, start_date, end_date)).fetchone()

        # Total appointments
        appointments = con.execute("""
            SELECT COUNT(*) as total,
                   COUNT(CASE WHEN status = 'confirmed' THEN 1 END) as confirmed,
                   COUNT(CASE WHEN status = 'cancelled' THEN 1 END) as cancelled,
                   COUNT(CASE WHEN status = 'no_show' THEN 1 END) as no_show
            FROM appointments
            WHERE business_id = ?
              AND date(created_at) BETWEEN ? AND ?
        """, (business_id, start_date, end_date)).fetchone()

        # Total messages
        messages = con.execute("""
            SELECT COUNT(*) as total,
                   COUNT(CASE WHEN sender = 'user' THEN 1 END) as user_msgs,
                   COUNT(CASE WHEN sender = 'bot' THEN 1 END) as bot_msgs
            FROM messages m
            JOIN sessions s ON m.session_id = s.id
            WHERE s.business_id = ?
              AND date(m.timestamp) BETWEEN ? AND ?
        """, (business_id, start_date, end_date)).fetchone()

        # New customers
        customers = con.execute("""
            SELECT COUNT(*) as total
            FROM customers
            WHERE business_id = ?
              AND date(created_at) BETWEEN ? AND ?
        """, (business_id, start_date, end_date)).fetchone()

        # Escalations
        escalations = con.execute("""
            SELECT COUNT(*) as total,
                   COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                   COUNT(CASE WHEN status = 'resolved' THEN 1 END) as resolved
            FROM escalations
            WHERE business_id = ?
              AND date(created_at) BETWEEN ? AND ?
        """, (business_id, start_date, end_date)).fetchone()

        return {
            "conversations": {
                "total": conversations["total"] or 0,
                "escalated": conversations["escalated"] or 0,
                "escalation_rate": round((conversations["escalated"] or 0) / max(conversations["total"] or 1, 1) * 100, 1)
            },
            "appointments": {
                "total": appointments["total"] or 0,
                "confirmed": appointments["confirmed"] or 0,
                "cancelled": appointments["cancelled"] or 0,
                "no_show": appointments["no_show"] or 0,
                "confirmation_rate": round((appointments["confirmed"] or 0) / max(appointments["total"] or 1, 1) * 100, 1)
            },
            "messages": {
                "total": messages["total"] or 0,
                "user": messages["user_msgs"] or 0,
                "bot": messages["bot_msgs"] or 0,
                "avg_per_session": round((messages["total"] or 0) / max(conversations["total"] or 1, 1), 1)
            },
            "customers": {
                "new": customers["total"] or 0
            },
            "escalations": {
                "total": escalations["total"] or 0,
                "pending": escalations["pending"] or 0,
                "resolved": escalations["resolved"] or 0,
                "resolution_rate": round((escalations["resolved"] or 0) / max(escalations["total"] or 1, 1) * 100, 1)
            }
        }


def _get_trend_data(business_id: int, start_date: str, end_date: str, granularity: str = "day") -> Dict[str, List]:
    """Get time-series data for trend charts."""
    # SECURITY: Use pre-defined queries to avoid SQL injection
    # Each granularity has its own safe query - no string interpolation

    with get_conn() as con:
        if granularity == "hour":
            # Hourly grouping
            conversations = con.execute("""
                SELECT strftime('%Y-%m-%d %H:00', created_at) as period,
                       COUNT(*) as count
                FROM sessions
                WHERE business_id = ?
                  AND date(created_at) BETWEEN ? AND ?
                GROUP BY strftime('%Y-%m-%d %H:00', created_at)
                ORDER BY period
            """, (business_id, start_date, end_date)).fetchall()

            appointments = con.execute("""
                SELECT strftime('%Y-%m-%d %H:00', created_at) as period,
                       COUNT(*) as count
                FROM appointments
                WHERE business_id = ?
                  AND date(created_at) BETWEEN ? AND ?
                GROUP BY strftime('%Y-%m-%d %H:00', created_at)
                ORDER BY period
            """, (business_id, start_date, end_date)).fetchall()

            messages = con.execute("""
                SELECT strftime('%Y-%m-%d %H:00', m.timestamp) as period,
                       COUNT(*) as count
                FROM messages m
                JOIN sessions s ON m.session_id = s.id
                WHERE s.business_id = ?
                  AND date(m.timestamp) BETWEEN ? AND ?
                GROUP BY strftime('%Y-%m-%d %H:00', m.timestamp)
                ORDER BY period
            """, (business_id, start_date, end_date)).fetchall()

        elif granularity == "week":
            # Weekly grouping
            conversations = con.execute("""
                SELECT strftime('%Y-W%W', created_at) as period,
                       COUNT(*) as count
                FROM sessions
                WHERE business_id = ?
                  AND date(created_at) BETWEEN ? AND ?
                GROUP BY strftime('%Y-W%W', created_at)
                ORDER BY period
            """, (business_id, start_date, end_date)).fetchall()

            appointments = con.execute("""
                SELECT strftime('%Y-W%W', created_at) as period,
                       COUNT(*) as count
                FROM appointments
                WHERE business_id = ?
                  AND date(created_at) BETWEEN ? AND ?
                GROUP BY strftime('%Y-W%W', created_at)
                ORDER BY period
            """, (business_id, start_date, end_date)).fetchall()

            messages = con.execute("""
                SELECT strftime('%Y-W%W', m.timestamp) as period,
                       COUNT(*) as count
                FROM messages m
                JOIN sessions s ON m.session_id = s.id
                WHERE s.business_id = ?
                  AND date(m.timestamp) BETWEEN ? AND ?
                GROUP BY strftime('%Y-W%W', m.timestamp)
                ORDER BY period
            """, (business_id, start_date, end_date)).fetchall()

        else:
            # Daily grouping (default)
            conversations = con.execute("""
                SELECT strftime('%Y-%m-%d', created_at) as period,
                       COUNT(*) as count
                FROM sessions
                WHERE business_id = ?
                  AND date(created_at) BETWEEN ? AND ?
                GROUP BY strftime('%Y-%m-%d', created_at)
                ORDER BY period
            """, (business_id, start_date, end_date)).fetchall()

            appointments = con.execute("""
                SELECT strftime('%Y-%m-%d', created_at) as period,
                       COUNT(*) as count
                FROM appointments
                WHERE business_id = ?
                  AND date(created_at) BETWEEN ? AND ?
                GROUP BY strftime('%Y-%m-%d', created_at)
                ORDER BY period
            """, (business_id, start_date, end_date)).fetchall()

            messages = con.execute("""
                SELECT strftime('%Y-%m-%d', m.timestamp) as period,
                       COUNT(*) as count
                FROM messages m
                JOIN sessions s ON m.session_id = s.id
                WHERE s.business_id = ?
                  AND date(m.timestamp) BETWEEN ? AND ?
                GROUP BY strftime('%Y-%m-%d', m.timestamp)
                ORDER BY period
            """, (business_id, start_date, end_date)).fetchall()

        return {
            "labels": [r["period"] for r in conversations] or [r["period"] for r in appointments],
            "conversations": [r["count"] for r in conversations],
            "appointments": [r["count"] for r in appointments],
            "messages": [r["count"] for r in messages]
        }


def _get_hourly_distribution(business_id: int, start_date: str, end_date: str) -> Dict[str, List]:
    """Get distribution of activity by hour of day."""
    with get_conn() as con:
        hourly = con.execute("""
            SELECT CAST(strftime('%H', created_at) AS INTEGER) as hour,
                   COUNT(*) as count
            FROM sessions
            WHERE business_id = ?
              AND date(created_at) BETWEEN ? AND ?
            GROUP BY hour
            ORDER BY hour
        """, (business_id, start_date, end_date)).fetchall()

        # Fill in all 24 hours
        hour_map = {r["hour"]: r["count"] for r in hourly}
        counts = [hour_map.get(h, 0) for h in range(24)]
        labels = [f"{h:02d}:00" for h in range(24)]

        return {"labels": labels, "counts": counts}


def _get_daily_distribution(business_id: int, start_date: str, end_date: str) -> Dict[str, List]:
    """Get distribution of activity by day of week."""
    with get_conn() as con:
        daily = con.execute("""
            SELECT CAST(strftime('%w', created_at) AS INTEGER) as dow,
                   COUNT(*) as count
            FROM sessions
            WHERE business_id = ?
              AND date(created_at) BETWEEN ? AND ?
            GROUP BY dow
            ORDER BY dow
        """, (business_id, start_date, end_date)).fetchall()

        # Fill in all 7 days (0=Sunday, 6=Saturday)
        day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        day_map = {r["dow"]: r["count"] for r in daily}
        counts = [day_map.get(d, 0) for d in range(7)]

        return {"labels": day_names, "counts": counts}


def _get_appointment_status_breakdown(business_id: int, start_date: str, end_date: str) -> Dict[str, Any]:
    """Get appointment status distribution."""
    with get_conn() as con:
        statuses = con.execute("""
            SELECT status, COUNT(*) as count
            FROM appointments
            WHERE business_id = ?
              AND date(created_at) BETWEEN ? AND ?
            GROUP BY status
        """, (business_id, start_date, end_date)).fetchall()

        status_map = {r["status"]: r["count"] for r in statuses}

        return {
            "labels": ["Pending", "Confirmed", "Cancelled", "No Show", "Completed"],
            "counts": [
                status_map.get("pending", 0),
                status_map.get("confirmed", 0),
                status_map.get("cancelled", 0),
                status_map.get("no_show", 0),
                status_map.get("completed", 0)
            ],
            "colors": ["#f59e0b", "#10b981", "#ef4444", "#6b7280", "#3b82f6"]
        }


def _get_top_services(business_id: int, start_date: str, end_date: str, limit: int = 5) -> List[Dict]:
    """Get most popular services by appointment count."""
    with get_conn() as con:
        services = con.execute("""
            SELECT a.service, COUNT(*) as count,
                   COALESCE(s.price, 0) as price
            FROM appointments a
            LEFT JOIN services s ON a.service = s.name AND s.business_id = a.business_id
            WHERE a.business_id = ?
              AND date(a.created_at) BETWEEN ? AND ?
              AND a.service IS NOT NULL AND a.service != ''
            GROUP BY a.service
            ORDER BY count DESC
            LIMIT ?
        """, (business_id, start_date, end_date, limit)).fetchall()

        return [{"name": r["service"], "count": r["count"], "revenue": r["count"] * r["price"]} for r in services]


def _get_escalation_reasons(business_id: int, start_date: str, end_date: str) -> Dict[str, List]:
    """Get breakdown of escalation reasons."""
    with get_conn() as con:
        reasons = con.execute("""
            SELECT reason, COUNT(*) as count
            FROM escalations
            WHERE business_id = ?
              AND date(created_at) BETWEEN ? AND ?
            GROUP BY reason
            ORDER BY count DESC
            LIMIT 10
        """, (business_id, start_date, end_date)).fetchall()

        return {
            "labels": [r["reason"][:40] + "..." if len(r["reason"]) > 40 else r["reason"] for r in reasons],
            "counts": [r["count"] for r in reasons]
        }


def _get_conversion_funnel(business_id: int, start_date: str, end_date: str) -> Dict[str, int]:
    """Get conversion funnel metrics."""
    with get_conn() as con:
        # Total sessions
        sessions = con.execute("""
            SELECT COUNT(*) as count FROM sessions
            WHERE business_id = ? AND date(created_at) BETWEEN ? AND ?
        """, (business_id, start_date, end_date)).fetchone()["count"]

        # Sessions with 2+ messages (engaged)
        engaged = con.execute("""
            SELECT COUNT(DISTINCT s.id) as count
            FROM sessions s
            JOIN messages m ON m.session_id = s.id
            WHERE s.business_id = ? AND date(s.created_at) BETWEEN ? AND ?
            GROUP BY s.id
            HAVING COUNT(m.id) >= 2
        """, (business_id, start_date, end_date)).fetchall()
        engaged_count = len(engaged)

        # Sessions with booking intent detected (approximation via appointments)
        appointments = con.execute("""
            SELECT COUNT(*) as count FROM appointments
            WHERE business_id = ? AND date(created_at) BETWEEN ? AND ?
        """, (business_id, start_date, end_date)).fetchone()["count"]

        # Confirmed appointments
        confirmed = con.execute("""
            SELECT COUNT(*) as count FROM appointments
            WHERE business_id = ? AND date(created_at) BETWEEN ? AND ?
              AND status IN ('confirmed', 'completed')
        """, (business_id, start_date, end_date)).fetchone()["count"]

        return {
            "sessions": sessions,
            "engaged": engaged_count,
            "bookings": appointments,
            "confirmed": confirmed
        }


def _get_response_metrics(business_id: int, start_date: str, end_date: str) -> Dict[str, Any]:
    """Get AI response and performance metrics."""
    with get_conn() as con:
        # Average messages per session
        avg_msgs = con.execute("""
            SELECT AVG(msg_count) as avg_msgs
            FROM (
                SELECT s.id, COUNT(m.id) as msg_count
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                WHERE s.business_id = ? AND date(s.created_at) BETWEEN ? AND ?
                GROUP BY s.id
            )
        """, (business_id, start_date, end_date)).fetchone()

        # Sessions by message count buckets
        buckets = con.execute("""
            SELECT
                CASE
                    WHEN msg_count <= 2 THEN '1-2'
                    WHEN msg_count <= 5 THEN '3-5'
                    WHEN msg_count <= 10 THEN '6-10'
                    ELSE '10+'
                END as bucket,
                COUNT(*) as count
            FROM (
                SELECT s.id, COUNT(m.id) as msg_count
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                WHERE s.business_id = ? AND date(s.created_at) BETWEEN ? AND ?
                GROUP BY s.id
            )
            GROUP BY bucket
            ORDER BY
                CASE bucket
                    WHEN '1-2' THEN 1
                    WHEN '3-5' THEN 2
                    WHEN '6-10' THEN 3
                    ELSE 4
                END
        """, (business_id, start_date, end_date)).fetchall()

        return {
            "avg_messages_per_session": round(avg_msgs["avg_msgs"] or 0, 1),
            "session_length_distribution": {
                "labels": [r["bucket"] for r in buckets],
                "counts": [r["count"] for r in buckets]
            }
        }


def _get_customer_insights(business_id: int, start_date: str, end_date: str) -> Dict[str, Any]:
    """Get customer-related insights."""
    with get_conn() as con:
        # New vs returning (based on session count)
        customer_types = con.execute("""
            SELECT
                CASE WHEN session_count = 1 THEN 'new' ELSE 'returning' END as type,
                COUNT(*) as count
            FROM (
                SELECT customer_id, COUNT(*) as session_count
                FROM sessions
                WHERE business_id = ?
                  AND customer_id IS NOT NULL
                  AND date(created_at) BETWEEN ? AND ?
                GROUP BY customer_id
            )
            GROUP BY type
        """, (business_id, start_date, end_date)).fetchall()

        type_map = {r["type"]: r["count"] for r in customer_types}

        # Top customers by appointments
        top_customers = con.execute("""
            SELECT c.name, c.email, c.phone, COUNT(a.id) as appointment_count
            FROM customers c
            JOIN appointments a ON a.customer_id = c.id
            WHERE c.business_id = ?
              AND date(a.created_at) BETWEEN ? AND ?
            GROUP BY c.id
            ORDER BY appointment_count DESC
            LIMIT 5
        """, (business_id, start_date, end_date)).fetchall()

        return {
            "new_customers": type_map.get("new", 0),
            "returning_customers": type_map.get("returning", 0),
            "top_customers": [dict(r) for r in top_customers]
        }


def _calculate_change(current: int, previous: int) -> Dict[str, Any]:
    """Calculate percentage change between two values."""
    if previous == 0:
        if current > 0:
            return {"value": 100, "direction": "up"}
        return {"value": 0, "direction": "neutral"}

    change = ((current - previous) / previous) * 100
    direction = "up" if change > 0 else ("down" if change < 0 else "neutral")

    return {"value": round(abs(change), 1), "direction": direction}


# =============================================================================
# Routes
# =============================================================================

@analytics_bp.route("/analytics")
def analytics_index():
    """Main analytics dashboard."""
    redir = _need_login()
    if redir:
        return redir

    business_id = getattr(g, 'active_business_id', None)
    if not business_id:
        flash("Please select a business first.", "err")
        return redirect(url_for("dashboard"))

    # Get date range
    range_key = request.args.get("range", "30d")
    start_date, end_date, range_label = _parse_date_range(range_key)

    # Get comparison period
    prev_start, prev_end = _get_comparison_range(start_date, end_date)

    # Fetch all data
    current_stats = _get_overview_stats(business_id, start_date, end_date)
    previous_stats = _get_overview_stats(business_id, prev_start, prev_end)

    # Calculate changes
    changes = {
        "conversations": _calculate_change(
            current_stats["conversations"]["total"],
            previous_stats["conversations"]["total"]
        ),
        "appointments": _calculate_change(
            current_stats["appointments"]["total"],
            previous_stats["appointments"]["total"]
        ),
        "customers": _calculate_change(
            current_stats["customers"]["new"],
            previous_stats["customers"]["new"]
        ),
        "escalations": _calculate_change(
            current_stats["escalations"]["total"],
            previous_stats["escalations"]["total"]
        )
    }

    # Get chart data
    trends = _get_trend_data(business_id, start_date, end_date)
    hourly = _get_hourly_distribution(business_id, start_date, end_date)
    daily = _get_daily_distribution(business_id, start_date, end_date)
    appointment_status = _get_appointment_status_breakdown(business_id, start_date, end_date)
    top_services = _get_top_services(business_id, start_date, end_date)
    escalation_reasons = _get_escalation_reasons(business_id, start_date, end_date)
    funnel = _get_conversion_funnel(business_id, start_date, end_date)
    response_metrics = _get_response_metrics(business_id, start_date, end_date)
    customer_insights = _get_customer_insights(business_id, start_date, end_date)

    return render_template(
        "analytics.html",
        stats=current_stats,
        changes=changes,
        trends=trends,
        hourly=hourly,
        daily=daily,
        appointment_status=appointment_status,
        top_services=top_services,
        escalation_reasons=escalation_reasons,
        funnel=funnel,
        response_metrics=response_metrics,
        customer_insights=customer_insights,
        range_key=range_key,
        range_label=range_label,
        start_date=start_date,
        end_date=end_date
    )


@analytics_bp.route("/api/analytics/overview")
def api_overview():
    """API endpoint for real-time overview stats."""
    if _user() is None:
        return jsonify({"error": "Unauthorized"}), 401

    business_id = getattr(g, 'active_business_id', None)
    if not business_id:
        return jsonify({"error": "No business selected"}), 400

    range_key = request.args.get("range", "30d")
    start_date, end_date, _ = _parse_date_range(range_key)

    stats = _get_overview_stats(business_id, start_date, end_date)
    return jsonify(stats)


@analytics_bp.route("/api/analytics/trends")
def api_trends():
    """API endpoint for trend data."""
    if _user() is None:
        return jsonify({"error": "Unauthorized"}), 401

    business_id = getattr(g, 'active_business_id', None)
    if not business_id:
        return jsonify({"error": "No business selected"}), 400

    range_key = request.args.get("range", "30d")
    granularity = request.args.get("granularity", "day")
    start_date, end_date, _ = _parse_date_range(range_key)

    trends = _get_trend_data(business_id, start_date, end_date, granularity)
    return jsonify(trends)


@analytics_bp.route("/api/analytics/export")
def api_export():
    """Export analytics data as CSV."""
    if _user() is None:
        return jsonify({"error": "Unauthorized"}), 401

    business_id = getattr(g, 'active_business_id', None)
    if not business_id:
        return jsonify({"error": "No business selected"}), 400

    range_key = request.args.get("range", "30d")
    start_date, end_date, range_label = _parse_date_range(range_key)

    # Get all data
    stats = _get_overview_stats(business_id, start_date, end_date)
    trends = _get_trend_data(business_id, start_date, end_date)

    # Build CSV
    lines = [
        f"LocusAI Analytics Export",
        f"Period: {range_label} ({start_date} to {end_date})",
        "",
        "Overview Metrics",
        f"Total Conversations,{stats['conversations']['total']}",
        f"Escalation Rate,{stats['conversations']['escalation_rate']}%",
        f"Total Appointments,{stats['appointments']['total']}",
        f"Confirmation Rate,{stats['appointments']['confirmation_rate']}%",
        f"Total Messages,{stats['messages']['total']}",
        f"Avg Messages per Session,{stats['messages']['avg_per_session']}",
        f"New Customers,{stats['customers']['new']}",
        "",
        "Daily Trends",
        "Date,Conversations,Appointments,Messages"
    ]

    for i, label in enumerate(trends["labels"]):
        conv = trends["conversations"][i] if i < len(trends["conversations"]) else 0
        appt = trends["appointments"][i] if i < len(trends["appointments"]) else 0
        msgs = trends["messages"][i] if i < len(trends["messages"]) else 0
        lines.append(f"{label},{conv},{appt},{msgs}")

    csv_content = "\n".join(lines)

    from flask import Response
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=analytics_{start_date}_{end_date}.csv"}
    )
