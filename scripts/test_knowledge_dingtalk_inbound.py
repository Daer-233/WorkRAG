"""Run with LangBot's DingTalk SDK and client available on PYTHONPATH."""
import asyncio
import json
import unittest

from dingtalk_stream import CallbackMessage
from langbot.libs.dingtalk_api.api import DingTalkClient
from langbot.libs.dingtalk_api.EchoHandler import EchoTextHandler


def callback(message_id, delivery_id):
    return CallbackMessage.from_dict({
        'headers': {'messageId': delivery_id},
        'data': json.dumps({'msgId': message_id}),
    })


class Client:
    _start_inbound_task = DingTalkClient._start_inbound_task
    _MAX_INBOUND_TASKS = 2

    def __init__(self):
        self._inbound_tasks = set()
        self.release = asyncio.Event()
        self.dispatched = []

    async def update_incoming_message(self, incoming):
        self.dispatched.append(incoming.message_id)
        await self.release.wait()


class InboundTests(unittest.IsolatedAsyncioTestCase):
    async def test_acknowledges_before_generation_and_deduplicates_retries(self):
        client = Client()
        handler = EchoTextHandler(client)
        self.assertEqual((await asyncio.wait_for(handler.raw_process(callback('one', 'a')), 0.5)).code, 200)
        self.assertEqual((await handler.raw_process(callback('two', 'b'))).code, 200)
        duplicate = await handler.raw_process(callback('one', 'c'))
        self.assertEqual(duplicate.code, 200)
        self.assertEqual(duplicate.headers.message_id, 'c')
        self.assertEqual((await handler.raw_process(callback('three', 'd'))).code, 500)
        client.release.set()
        await asyncio.gather(*tuple(client._inbound_tasks))
        self.assertEqual((await handler.raw_process(callback('one', 'e'))).code, 200)
        self.assertEqual((await handler.raw_process(callback('three', 'f'))).code, 200)
        await asyncio.gather(*tuple(client._inbound_tasks))
        self.assertCountEqual(client.dispatched, ['one', 'two', 'three'])


if __name__ == '__main__':
    unittest.main()
