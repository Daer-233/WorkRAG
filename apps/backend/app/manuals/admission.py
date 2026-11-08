"""Bounded admission for CPU retrieval shared with background indexing."""
from threading import Lock,BoundedSemaphore,get_ident

class RetrievalGate:
    def __init__(self,max_pending=32):
        self._lock=Lock(); self._slots=BoundedSemaphore(max_pending); self._owner=None

    def acquire(self,blocking=True,timeout=-1):
        if self._owner==get_ident(): return False
        if not blocking:
            acquired=self._lock.acquire(False)
            if acquired: self._owner=get_ident()
            return acquired
        if not self._slots.acquire(False): return False
        try:
            acquired=self._lock.acquire(timeout=timeout)
            if acquired: self._owner=get_ident()
            return acquired
        finally: self._slots.release()

    def release(self):
        self._owner=None; self._lock.release()

    def locked(self): return self._lock.locked()
