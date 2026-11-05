"""DingTalk Stream receiver used by the local LangBot deployment."""
import asyncio
from collections import OrderedDict
import logging
import time

import dingtalk_stream
from dingtalk_stream import AckMessage


LOG = logging.getLogger(__name__)
RECENT_TTL = 15 * 60
RECENT_LIMIT = 4096


class EchoTextHandler(dingtalk_stream.ChatbotHandler):
    def __init__(self, client):
        super().__init__()
        self.client = client
        self.incoming_message = None
        self._processing = set()
        self._recent = OrderedDict()

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        message_id = incoming.message_id or callback.headers.message_id
        now = time.monotonic()
        while self._recent and next(iter(self._recent.values())) <= now:
            self._recent.popitem(last=False)
        if message_id in self._processing or message_id in self._recent:
            LOG.info('Acknowledged duplicate DingTalk message without dispatch')
            return AckMessage.STATUS_OK, 'OK'

        # Accept once before acknowledging, using the client's bounded task
        # tracker so stopping the adapter also stops these background runs.
        if message_id:
            self._processing.add(message_id)
        if not self.client._start_inbound_task(self._dispatch(incoming, message_id)):
            self._processing.discard(message_id)
            return AckMessage.STATUS_SYSTEM_EXCEPTION, 'Inbound capacity reached'
        return AckMessage.STATUS_OK, 'OK'

    async def _dispatch(self, incoming, message_id):
        try:
            await self.client.update_incoming_message(incoming)
        except Exception as error:
            LOG.error('DingTalk message dispatch failed (%s)', type(error).__name__)
        finally:
            if message_id:
                self._processing.discard(message_id)
                self._recent[message_id] = time.monotonic() + RECENT_TTL
                while len(self._recent) > RECENT_LIMIT:
                    self._recent.popitem(last=False)

    async def get_incoming_message(self):
        while self.incoming_message is None:
            await asyncio.sleep(0.1)
        return self.incoming_message
