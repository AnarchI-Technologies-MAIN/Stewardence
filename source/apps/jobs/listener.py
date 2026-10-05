from __future__ import annotations

import logging
import time
from collections.abc import Callable

import psycopg
from psycopg import sql

logger = logging.getLogger(__name__)


class EventDrivenJobListener:
    CHANNEL = "agentledger_job_channel"

    def __init__(
        self,
        *,
        worker_id: str,
        listener_dsn: str,
        recovery_interval_seconds: int = 30,
        connection_factory=psycopg.connect,
        sleeper=time.sleep,
    ):
        self.worker_id = worker_id
        self.listener_dsn = listener_dsn
        self.recovery_interval_seconds = recovery_interval_seconds
        self.connection_factory = connection_factory
        self.sleeper = sleeper

    def run_connected_cycle(
        self,
        drain_queue: Callable[[str], None],
        *,
        max_wakeups: int | None = None,
    ) -> None:
        with self.connection_factory(
            self.listener_dsn,
            autocommit=True,
        ) as connection:
            connection.execute(
                sql.SQL("LISTEN {}").format(sql.Identifier(self.CHANNEL))
            )
            drain_queue(self.worker_id)
            wakeups = 0
            while max_wakeups is None or wakeups < max_wakeups:
                for _notification in connection.notifies(
                    timeout=self.recovery_interval_seconds,
                    stop_after=1,
                ):
                    pass
                drain_queue(self.worker_id)
                wakeups += 1

    def run(self, drain_queue: Callable[[str], None]) -> None:
        while True:
            try:
                self.run_connected_cycle(drain_queue)
            except psycopg.OperationalError:
                logger.exception("Job listener connection lost")
                self.sleeper(5)
