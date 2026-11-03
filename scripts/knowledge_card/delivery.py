"""A run-scoped, trailing-edge card writer. Never manufactures answer deltas."""
import asyncio

from .model import CardState, wire_params


class CardDelivery:
    def __init__(self, send, *, state=None, interval=.5):
        self.state = state or CardState()
        self.send = send
        self.interval = interval
        self.pending = None
        self.closed = False
        self.lock = asyncio.Lock()
        self.error = None

    async def _flush(self):
        async with self.lock:
            await self.send(wire_params(self.state.params()))

    async def _later(self):
        try:
            await asyncio.sleep(self.interval)
            await self._flush()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = exc

    async def push(self, event):
        if self.error:
            raise self.error
        if self.closed:
            raise RuntimeError('Card run has ended')
        previous = self.state.stage
        self.state.apply(event)
        immediate = previous != self.state.stage or event['type'] in ('run.started','run.completed','run.failed')
        if immediate:
            if self.pending:
                # An in-flight HTTP update may still reach the server after
                # cancellation. Settle it before sending a newer terminal state.
                await asyncio.gather(self.pending, return_exceptions=True)
                self.pending = None
            await self._flush()
        elif not self.pending or self.pending.done():
            self.pending = asyncio.create_task(self._later())
        if event['type'] in ('run.completed','run.failed'):
            self.closed = True

    async def cancel(self):
        if not self.closed:
            await self.push({'type':'run.failed'})
