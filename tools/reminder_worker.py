#!/usr/bin/env python3
# tools/reminder_worker.py — Background worker for processing appointment reminders
# Run as a daemon or scheduled job to send reminders

"""
Reminder Worker for LocusAI

This worker periodically checks for due reminders and sends them.

Usage:
    # Run as continuous daemon (recommended for production):
    python tools/reminder_worker.py --daemon

    # Run once and exit (for cron jobs):
    python tools/reminder_worker.py --once

    # Dry run (don't actually send, just log):
    python tools/reminder_worker.py --dry-run

    # Custom interval (seconds between checks):
    python tools/reminder_worker.py --daemon --interval 60

Environment Variables:
    REMINDER_INTERVAL: Seconds between checks (default: 60)
    REMINDER_BATCH_SIZE: Max reminders per batch (default: 50)
"""

import os
import sys
import time
import signal
import logging
import argparse
from datetime import datetime

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.db import init_db
from core.reminders import process_due_reminders, get_reminder_stats

# ============================================================================
# Logging Configuration
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(PROJECT_ROOT, "logs", "reminder_worker.log"))
    ]
)
logger = logging.getLogger("reminder_worker")

# ============================================================================
# Configuration
# ============================================================================

DEFAULT_INTERVAL = int(os.getenv("REMINDER_INTERVAL", "60"))  # seconds
DEFAULT_BATCH_SIZE = int(os.getenv("REMINDER_BATCH_SIZE", "50"))

# ============================================================================
# Worker State
# ============================================================================

_shutdown_requested = False


def _signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _shutdown_requested = True


# Register signal handlers
signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)

# ============================================================================
# Worker Functions
# ============================================================================

def run_once(batch_size: int = DEFAULT_BATCH_SIZE, dry_run: bool = False) -> dict:
    """Process due reminders once.

    Args:
        batch_size: Maximum reminders to process
        dry_run: If True, don't actually send (just log)

    Returns:
        Stats dict with sent/failed counts
    """
    logger.info(f"Processing due reminders (batch_size={batch_size}, dry_run={dry_run})")

    if dry_run:
        from core.reminders import get_due_reminders
        reminders = get_due_reminders(limit=batch_size)
        logger.info(f"DRY RUN: Would process {len(reminders)} reminders")
        for r in reminders:
            logger.info(
                f"  - Reminder {r['reminder_id']}: "
                f"{r['type']}/{r['channel']} for appointment {r['appointment_id']} "
                f"({r['customer_name']})"
            )
        return {"sent": 0, "failed": 0, "total": len(reminders), "dry_run": True}

    stats = process_due_reminders(batch_size=batch_size)

    if stats["total"] > 0:
        logger.info(
            f"Processed {stats['total']} reminders: "
            f"{stats['sent']} sent, {stats['failed']} failed"
        )

    return stats


def run_daemon(
    interval: int = DEFAULT_INTERVAL,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False
):
    """Run as a continuous daemon.

    Args:
        interval: Seconds between processing runs
        batch_size: Maximum reminders per batch
        dry_run: If True, don't actually send
    """
    global _shutdown_requested

    logger.info(f"Starting reminder daemon (interval={interval}s, batch_size={batch_size})")

    # Initialize database
    init_db()

    total_sent = 0
    total_failed = 0
    runs = 0

    while not _shutdown_requested:
        try:
            runs += 1
            stats = run_once(batch_size=batch_size, dry_run=dry_run)

            if not dry_run:
                total_sent += stats.get("sent", 0)
                total_failed += stats.get("failed", 0)

            # Log periodic summary
            if runs % 60 == 0:  # Every 60 runs (e.g., hourly at 1min interval)
                logger.info(
                    f"Worker summary: {runs} runs, "
                    f"{total_sent} sent, {total_failed} failed"
                )

        except Exception as e:
            logger.error(f"Error in reminder processing: {e}", exc_info=True)

        # Sleep with shutdown check
        for _ in range(interval):
            if _shutdown_requested:
                break
            time.sleep(1)

    logger.info(
        f"Reminder daemon shutting down. "
        f"Total: {runs} runs, {total_sent} sent, {total_failed} failed"
    )


def show_stats():
    """Display reminder statistics."""
    init_db()

    stats = get_reminder_stats(days=30)

    print("\n=== Reminder Statistics (Last 30 Days) ===\n")
    print(f"Total Reminders: {stats['total']}")

    print("\nBy Status:")
    for status, count in sorted(stats.get("by_status", {}).items()):
        print(f"  {status}: {count}")

    print("\nBy Channel:")
    for channel, count in sorted(stats.get("by_channel", {}).items()):
        print(f"  {channel}: {count}")

    print()


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="LocusAI Reminder Worker - Process and send appointment reminders"
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--daemon", "-d",
        action="store_true",
        help="Run as continuous daemon"
    )
    mode_group.add_argument(
        "--once", "-o",
        action="store_true",
        help="Run once and exit"
    )
    mode_group.add_argument(
        "--stats", "-s",
        action="store_true",
        help="Show reminder statistics"
    )

    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Seconds between checks (daemon mode, default: {DEFAULT_INTERVAL})"
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Max reminders per batch (default: {DEFAULT_BATCH_SIZE})"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually send reminders, just log what would be sent"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Ensure logs directory exists
    os.makedirs(os.path.join(PROJECT_ROOT, "logs"), exist_ok=True)

    if args.stats:
        show_stats()
    elif args.daemon:
        run_daemon(
            interval=args.interval,
            batch_size=args.batch_size,
            dry_run=args.dry_run
        )
    elif args.once:
        init_db()
        stats = run_once(batch_size=args.batch_size, dry_run=args.dry_run)
        print(f"Processed {stats.get('total', 0)} reminders")
        sys.exit(0 if stats.get("failed", 0) == 0 else 1)


if __name__ == "__main__":
    main()
