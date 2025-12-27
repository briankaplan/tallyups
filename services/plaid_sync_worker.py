#!/usr/bin/env python3
"""
================================================================================
Plaid Transaction Sync Worker
================================================================================
Author: Claude Code
Created: 2025-12-20

Background worker for automatic Plaid transaction synchronization.

FEATURES:
---------
- Periodic sync of all active Items
- Intelligent scheduling based on last sync time
- Error recovery with exponential backoff
- Concurrent sync with rate limiting
- Business classification of new transactions
- Receipt matching integration

USAGE:
------
Run as standalone script:
    python services/plaid_sync_worker.py

Run in background:
    python services/plaid_sync_worker.py --daemon

Run once (cron-compatible):
    python services/plaid_sync_worker.py --once

Environment Variables:
    PLAID_SYNC_INTERVAL: Sync interval in seconds (default: 3600 = 1 hour)
    PLAID_SYNC_CONCURRENT: Max concurrent syncs (default: 3)
    PLAID_SYNC_ENABLED: Enable/disable worker (default: true)

================================================================================
"""

import os
import sys
import time
import signal
import logging
import argparse
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Logger
try:
    from logging_config import get_logger, init_logging
    init_logging()
    logger = get_logger(__name__)
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

class SyncWorkerConfig:
    """Configuration for the sync worker."""

    def __init__(self):
        # Sync interval in seconds (default 1 hour)
        self.sync_interval = int(os.environ.get('PLAID_SYNC_INTERVAL', 3600))

        # Maximum concurrent syncs
        self.max_concurrent = int(os.environ.get('PLAID_SYNC_CONCURRENT', 3))

        # Minimum time between syncs for same Item (prevent hammering)
        self.min_sync_gap = int(os.environ.get('PLAID_MIN_SYNC_GAP', 300))  # 5 minutes

        # Enable/disable worker
        self.enabled = os.environ.get('PLAID_SYNC_ENABLED', 'true').lower() == 'true'

        # Error backoff configuration
        self.initial_backoff = 60  # 1 minute
        self.max_backoff = 3600  # 1 hour
        self.backoff_multiplier = 2

    def __repr__(self):
        return (
            f"SyncWorkerConfig("
            f"interval={self.sync_interval}s, "
            f"concurrent={self.max_concurrent}, "
            f"enabled={self.enabled})"
        )


# =============================================================================
# SYNC WORKER
# =============================================================================

class PlaidSyncWorker:
    """
    Background worker for Plaid transaction synchronization.

    Periodically syncs transactions for all active Items and handles
    error recovery with exponential backoff.
    """

    def __init__(self, config: Optional[SyncWorkerConfig] = None):
        """
        Initialize the sync worker.

        Args:
            config: Worker configuration (uses defaults if None)
        """
        self.config = config or SyncWorkerConfig()
        self._running = False
        self._stop_event = threading.Event()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._error_counts: Dict[str, int] = {}
        self._last_sync_times: Dict[str, datetime] = {}

        logger.info(f"PlaidSyncWorker initialized: {self.config}")

    def start(self, daemon: bool = False):
        """
        Start the sync worker.

        Args:
            daemon: If True, run in daemon thread (exits when main thread exits)
        """
        if self._running:
            logger.warning("Worker already running")
            return

        if not self.config.enabled:
            logger.warning("Sync worker is disabled (PLAID_SYNC_ENABLED=false)")
            return

        self._running = True
        self._stop_event.clear()

        if daemon:
            thread = threading.Thread(target=self._run_loop, daemon=True)
            thread.start()
            logger.info("Sync worker started in daemon mode")
        else:
            logger.info("Sync worker starting...")
            self._run_loop()

    def stop(self):
        """Stop the sync worker gracefully."""
        if not self._running:
            return

        logger.info("Stopping sync worker...")
        self._running = False
        self._stop_event.set()

        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None

        logger.info("Sync worker stopped")

    def run_once(self) -> Dict[str, Any]:
        """
        Run a single sync cycle for all Items.

        Returns:
            Dict with sync results
        """
        logger.info("Running single sync cycle")
        return self._sync_all_items()

    def _run_loop(self):
        """Main sync loop."""
        logger.info(f"Starting sync loop (interval={self.config.sync_interval}s)")

        while self._running and not self._stop_event.is_set():
            try:
                # Run sync cycle
                results = self._sync_all_items()
                logger.info(f"Sync cycle complete: {results}")

                # Wait for next cycle
                self._stop_event.wait(timeout=self.config.sync_interval)

            except Exception as e:
                logger.error(f"Sync loop error: {e}")
                # Wait before retrying
                self._stop_event.wait(timeout=60)

        logger.info("Sync loop ended")

    def _sync_all_items(self) -> Dict[str, Any]:
        """
        Sync all active Plaid Items.

        Returns:
            Dict with:
                - total: Number of Items processed
                - success: Number of successful syncs
                - failed: Number of failed syncs
                - skipped: Number of skipped syncs
                - transactions_added: Total transactions added
        """
        try:
            from services.plaid_service import get_plaid_service, is_plaid_configured

            if not is_plaid_configured():
                logger.warning("Plaid not configured, skipping sync")
                return {'total': 0, 'error': 'Plaid not configured'}

            plaid = get_plaid_service()

            # Get all Items (all users)
            from db_mysql import get_mysql_db
            db = get_mysql_db()
            conn = db.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT item_id, user_id, institution_name, status,
                           last_successful_sync, last_sync_attempt
                    FROM plaid_items
                    WHERE status = 'active'
                    ORDER BY last_successful_sync IS NOT NULL, last_successful_sync ASC
                """)
                items = cursor.fetchall()
            finally:
                db.return_connection(conn)

            if not items:
                logger.info("No active Items to sync")
                return {'total': 0, 'message': 'No active Items'}

            logger.info(f"Found {len(items)} active Items to sync")

            # Filter out recently synced Items
            items_to_sync = []
            skipped = 0
            for item in items:
                item_id = item['item_id']
                last_sync = self._last_sync_times.get(item_id)

                if last_sync:
                    time_since_sync = (datetime.now() - last_sync).total_seconds()
                    if time_since_sync < self.config.min_sync_gap:
                        skipped += 1
                        continue

                # Check for error backoff
                error_count = self._error_counts.get(item_id, 0)
                if error_count > 0:
                    backoff = min(
                        self.config.initial_backoff * (self.config.backoff_multiplier ** (error_count - 1)),
                        self.config.max_backoff
                    )
                    if last_sync and (datetime.now() - last_sync).total_seconds() < backoff:
                        skipped += 1
                        continue

                items_to_sync.append(item)

            # Sync Items concurrently
            results = {
                'total': len(items),
                'processed': 0,
                'success': 0,
                'failed': 0,
                'skipped': skipped,
                'transactions_added': 0,
                'transactions_modified': 0,
                'transactions_removed': 0,
                'transactions_imported': 0
            }

            with ThreadPoolExecutor(max_workers=self.config.max_concurrent) as executor:
                futures = {
                    executor.submit(self._sync_item, item): item
                    for item in items_to_sync
                }

                for future in as_completed(futures):
                    item = futures[future]
                    item_id = item['item_id']

                    try:
                        result = future.result()
                        results['processed'] += 1

                        if result['success']:
                            results['success'] += 1
                            results['transactions_added'] += result.get('added', 0)
                            results['transactions_modified'] += result.get('modified', 0)
                            results['transactions_removed'] += result.get('removed', 0)
                            results['transactions_imported'] += result.get('imported', 0)

                            # Reset error count on success
                            self._error_counts[item_id] = 0
                        else:
                            results['failed'] += 1
                            self._error_counts[item_id] = self._error_counts.get(item_id, 0) + 1

                        self._last_sync_times[item_id] = datetime.now()

                    except Exception as e:
                        logger.error(f"Sync failed for {item_id}: {e}")
                        results['failed'] += 1
                        self._error_counts[item_id] = self._error_counts.get(item_id, 0) + 1

            return results

        except Exception as e:
            logger.error(f"Sync all items error: {e}")
            return {'total': 0, 'error': str(e)}

    def _sync_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sync a single Plaid Item.

        Args:
            item: Item dict from database

        Returns:
            Dict with sync result
        """
        item_id = item['item_id']
        institution = item.get('institution_name', 'Unknown')

        logger.info(f"Syncing {institution} ({item_id})")

        try:
            from services.plaid_service import get_plaid_service

            plaid = get_plaid_service()
            result = plaid.sync_transactions(item_id, sync_type='incremental')

            logger.info(
                f"Synced {institution}: "
                f"+{result.added} ~{result.modified} -{result.removed}"
            )

            # Trigger business classification for new transactions
            if result.added > 0:
                self._classify_new_transactions(item_id)

            # Auto-import to main transactions table
            imported = 0
            if result.added > 0:
                imported = self._import_to_main_table(item['user_id'])

            return {
                'success': result.success,
                'item_id': item_id,
                'added': result.added,
                'modified': result.modified,
                'removed': result.removed,
                'imported': imported
            }

        except Exception as e:
            logger.error(f"Sync error for {item_id}: {e}")
            return {
                'success': False,
                'item_id': item_id,
                'error': str(e)
            }

    def _classify_new_transactions(self, item_id: str):
        """
        Run business classification on new transactions.

        Args:
            item_id: The Item that was synced
        """
        try:
            from db_mysql import get_mysql_db

            db = get_mysql_db()
            conn = db.get_connection()
            try:
                cursor = conn.cursor()

                # Get account's default business type
                cursor.execute("""
                    SELECT pa.account_id, pa.default_business_type
                    FROM plaid_accounts pa
                    WHERE pa.item_id = %s AND pa.default_business_type IS NOT NULL
                """, (item_id,))
                account_defaults = {
                    row['account_id']: row['default_business_type']
                    for row in cursor.fetchall()
                }

                if account_defaults:
                    # Apply default business types to new transactions
                    for account_id, business_type in account_defaults.items():
                        cursor.execute("""
                            UPDATE plaid_transactions
                            SET business_type = %s
                            WHERE account_id = %s
                            AND processing_status = 'new'
                            AND business_type IS NULL
                        """, (business_type, account_id))

                    conn.commit()
                    logger.info(f"Applied business types to new transactions for {item_id}")

            finally:
                db.return_connection(conn)

        except Exception as e:
            logger.warning(f"Failed to classify transactions: {e}")

    def _import_to_main_table(self, user_id: str) -> int:
        """
        Import new transactions from staging to main transactions table.

        Args:
            user_id: User identifier

        Returns:
            Number of transactions imported
        """
        try:
            from services.plaid_service import get_plaid_service

            plaid = get_plaid_service()
            result = plaid.import_to_transactions(user_id)

            if result.get('success'):
                imported = result.get('imported', 0)
                if imported > 0:
                    logger.info(f"Auto-imported {imported} transactions to main table")
                return imported
            else:
                logger.warning(f"Import failed: {result.get('message', 'Unknown error')}")
                return 0

        except Exception as e:
            logger.error(f"Failed to import transactions: {e}")
            return 0


# =============================================================================
# SIGNAL HANDLERS
# =============================================================================

_worker: Optional[PlaidSyncWorker] = None


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, shutting down...")
    if _worker:
        _worker.stop()
    sys.exit(0)


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Main entry point."""
    global _worker

    parser = argparse.ArgumentParser(description='Plaid Transaction Sync Worker')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    parser.add_argument('--daemon', action='store_true', help='Run as daemon')
    parser.add_argument('--interval', type=int, help='Sync interval in seconds')
    args = parser.parse_args()

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create configuration
    config = SyncWorkerConfig()
    if args.interval:
        config.sync_interval = args.interval

    # Create worker
    _worker = PlaidSyncWorker(config)

    if args.once:
        # Run once and exit
        results = _worker.run_once()
        print(f"\nSync Results:")
        print(f"  Total Items: {results.get('total', 0)}")
        print(f"  Successful:  {results.get('success', 0)}")
        print(f"  Failed:      {results.get('failed', 0)}")
        print(f"  Skipped:     {results.get('skipped', 0)}")
        print(f"  Transactions Added:    {results.get('transactions_added', 0)}")
        print(f"  Transactions Modified: {results.get('transactions_modified', 0)}")
        print(f"  Transactions Removed:  {results.get('transactions_removed', 0)}")
        print(f"  Transactions Imported: {results.get('transactions_imported', 0)}")
    else:
        # Run continuously
        _worker.start(daemon=args.daemon)

        if args.daemon:
            # Keep main thread alive
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        # If not daemon, start() blocks until stop()


if __name__ == '__main__':
    main()
