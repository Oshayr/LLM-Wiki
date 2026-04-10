#!/usr/bin/env python3
"""circuit_breaker.py — Circuit breaker for external API calls.

Usage:
    python3 circuit_breaker.py check <endpoint>                  — Is it safe to call?
    python3 circuit_breaker.py record <endpoint> <success|fail>  — Record call result
    python3 circuit_breaker.py status                            — Show all endpoints
    python3 circuit_breaker.py reset <endpoint>                  — Force reset to closed

States: closed (normal) -> open (failing, skip calls) -> half-open (try one call).
Prevents cascading failures from external API outages.
"""

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wiki_logging import get_logger
from exceptions import CircuitOpenError

logger = get_logger(__name__)


# Failure threshold to trip the breaker
FAILURE_THRESHOLD = 5
# Seconds to wait before trying again (half-open)
COOLDOWN_SECONDS = 300
# Failures to clear after consecutive successes
SUCCESS_THRESHOLD = 3


class CircuitBreaker:
    """Circuit breaker pattern for external API endpoints."""

    def __init__(self, cache_dir: Path = None):
        if cache_dir is None:
            cache_dir = Path(".wiki/cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "circuit_breaker.db"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS endpoints (
                name TEXT PRIMARY KEY,
                state TEXT DEFAULT 'closed',
                failure_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                last_failure TEXT,
                last_success TEXT,
                last_state_change TEXT,
                total_calls INTEGER DEFAULT 0,
                total_failures INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def check(self, endpoint: str) -> dict:
        """Check if an endpoint is safe to call.

        Returns {allowed: bool, state: str, ...}.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM endpoints WHERE name = ?", (endpoint,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            logger.debug("Endpoint not tracked yet, defaulting to closed", extra={"endpoint": endpoint})
            return {"allowed": True, "state": "closed", "endpoint": endpoint}

        state = row[1]
        failure_count = row[2]
        last_failure = row[4]

        if state == "closed":
            conn.close()
            logger.debug("Circuit check: closed", extra={"endpoint": endpoint})
            return {"allowed": True, "state": "closed", "endpoint": endpoint}

        if state == "open":
            # Check if cooldown has passed
            if last_failure:
                try:
                    last_fail_dt = datetime.fromisoformat(last_failure.replace("Z", "+00:00"))
                    elapsed = (datetime.now(UTC) - last_fail_dt).total_seconds()
                    if elapsed > COOLDOWN_SECONDS:
                        # Transition to half-open
                        conn.execute(
                            "UPDATE endpoints SET state = 'half-open', last_state_change = ? WHERE name = ?",
                            (datetime.now(UTC).isoformat(), endpoint),
                        )
                        conn.commit()
                        conn.close()
                        logger.info("Circuit state transition: open -> half-open", extra={"endpoint": endpoint, "cooldown_elapsed_seconds": elapsed})
                        return {"allowed": True, "state": "half-open", "endpoint": endpoint}
                except ValueError:
                    pass

            conn.close()
            cooldown_remaining = max(0, COOLDOWN_SECONDS - elapsed) if last_failure else COOLDOWN_SECONDS
            logger.debug("Circuit check: open (cooldown active)", extra={"endpoint": endpoint, "failures": failure_count, "cooldown_remaining_seconds": cooldown_remaining})
            return {
                "allowed": False,
                "state": "open",
                "endpoint": endpoint,
                "failures": failure_count,
                "cooldown_remaining": cooldown_remaining,
            }

        if state == "half-open":
            conn.close()
            logger.debug("Circuit check: half-open", extra={"endpoint": endpoint})
            return {"allowed": True, "state": "half-open", "endpoint": endpoint}

        conn.close()
        return {"allowed": True, "state": state, "endpoint": endpoint}

    def record(self, endpoint: str, success: bool) -> dict:
        """Record the result of an API call."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(UTC).isoformat()

        # Ensure endpoint exists
        conn.execute(
            "INSERT OR IGNORE INTO endpoints (name, last_state_change) VALUES (?, ?)",
            (endpoint, now),
        )

        cursor = conn.cursor()
        cursor.execute("SELECT state, failure_count, success_count FROM endpoints WHERE name = ?", (endpoint,))
        row = cursor.fetchone()
        state = row[0]
        failure_count = row[1]
        success_count = row[2]

        if success:
            new_success_count = success_count + 1
            conn.execute(
                """UPDATE endpoints SET
                   total_calls = total_calls + 1, last_success = ?,
                   success_count = ? WHERE name = ?""",
                (now, new_success_count, endpoint),
            )

            if state == "half-open" and new_success_count >= SUCCESS_THRESHOLD:
                # Recovered — close the circuit
                conn.execute(
                    "UPDATE endpoints SET state = 'closed', failure_count = 0, success_count = 0, last_state_change = ? WHERE name = ?",
                    (now, endpoint),
                )
                logger.info("Circuit state transition: half-open -> closed (recovered)", extra={"endpoint": endpoint, "consecutive_successes": new_success_count})
                state = "closed"
            elif state == "half-open":
                logger.debug("Circuit half-open: success recorded", extra={"endpoint": endpoint, "success_count": new_success_count})
                state = "half-open"

        else:
            new_failure_count = failure_count + 1
            conn.execute(
                """UPDATE endpoints SET
                   total_calls = total_calls + 1, total_failures = total_failures + 1,
                   last_failure = ?, failure_count = ?, success_count = 0 WHERE name = ?""",
                (now, new_failure_count, endpoint),
            )

            if new_failure_count >= FAILURE_THRESHOLD and state != "open":
                conn.execute(
                    "UPDATE endpoints SET state = 'open', last_state_change = ? WHERE name = ?",
                    (now, endpoint),
                )
                logger.warning("Circuit state transition: closed/half-open -> open (failure threshold exceeded)", extra={"endpoint": endpoint, "failure_count": new_failure_count, "threshold": FAILURE_THRESHOLD})
                state = "open"
            elif state == "half-open":
                # Failed during half-open — back to open
                conn.execute(
                    "UPDATE endpoints SET state = 'open', last_state_change = ? WHERE name = ?",
                    (now, endpoint),
                )
                logger.warning("Circuit state transition: half-open -> open (failed during probe)", extra={"endpoint": endpoint})
                state = "open"
            else:
                logger.debug("Circuit failure recorded", extra={"endpoint": endpoint, "failure_count": new_failure_count})

        conn.commit()
        conn.close()
        return {"endpoint": endpoint, "state": state, "success": success}

    def status(self) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM endpoints ORDER BY name")
        results = []
        for row in cursor.fetchall():
            results.append({
                "endpoint": row[0],
                "state": row[1],
                "failure_count": row[2],
                "success_count": row[3],
                "last_failure": row[4],
                "last_success": row[5],
                "total_calls": row[7],
                "total_failures": row[8],
            })
        conn.close()
        return results

    def reset(self, endpoint: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """UPDATE endpoints SET state = 'closed', failure_count = 0,
               success_count = 0, last_state_change = ? WHERE name = ?""",
            (now, endpoint),
        )
        conn.commit()
        conn.close()
        logger.info("Circuit manually reset to closed", extra={"endpoint": endpoint})
        return {"endpoint": endpoint, "state": "closed", "reset": True}


def main():
    parser = argparse.ArgumentParser(
        description="Circuit breaker for external APIs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    check_p = subparsers.add_parser("check", help="Check if endpoint is safe to call")
    check_p.add_argument("endpoint")

    rec_p = subparsers.add_parser("record", help="Record call result")
    rec_p.add_argument("endpoint")
    rec_p.add_argument("result", choices=["success", "fail"])

    status_p = subparsers.add_parser("status", help="Show all endpoints")

    reset_p = subparsers.add_parser("reset", help="Force reset to closed")
    reset_p.add_argument("endpoint")

    args = parser.parse_args()
    cb = CircuitBreaker()

    if args.command == "check":
        result = cb.check(args.endpoint)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["allowed"] else 1)

    elif args.command == "record":
        result = cb.record(args.endpoint, args.result == "success")
        print(json.dumps(result, indent=2))

    elif args.command == "status":
        results = cb.status()
        print(json.dumps(results, indent=2))

    elif args.command == "reset":
        result = cb.reset(args.endpoint)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
