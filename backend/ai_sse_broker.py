import queue
import threading
import time
import logging

logger = logging.getLogger(__name__)


class AISSEBroker:
    def __init__(self):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        logger.debug(f"SSE subscriber added (total: {len(self._subscribers)})")
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)
        logger.debug(f"SSE subscriber removed (total: {len(self._subscribers)})")

    def publish(self, event: dict):
        event["ts"] = int(time.time() * 1000)
        with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except Exception:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)