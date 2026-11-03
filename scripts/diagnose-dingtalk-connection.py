"""Run inside LangBot; inspect Stream handshake without sending messages."""
import argparse
import json
import logging
from pathlib import Path

import requests
import dingtalk_stream


def main():
    parser=argparse.ArgumentParser();parser.add_argument('private_config');args=parser.parse_args()
    path=Path(args.private_config)
    assert path.parent==Path('/tmp') and path.name.startswith('knowledge-dingtalk-')
    report={}
    try:
        value=json.loads(path.read_text(encoding='utf-8'))['bot']['adapter_config']
        logging.disable(logging.CRITICAL)
        # Constructor registers the same subscriptions as the live adapter.
        client=dingtalk_stream.DingTalkStreamClient(dingtalk_stream.Credential(value['client_id'],value['client_secret']))
        client._is_event_required=True
        client.register_callback_handler(dingtalk_stream.chatbot.ChatbotMessage.TOPIC,dingtalk_stream.CallbackHandler())
        client.register_callback_handler(dingtalk_stream.CallbackHandler.TOPIC_CARD_CALLBACK,dingtalk_stream.CallbackHandler())
        post=requests.post
        def checked(*a,**kw):
            response=post(*a,**kw,timeout=20)
            report['http_status']=response.status_code
            try:
                data=response.json()
                report['code']=data.get('code',data.get('errcode'))
                text=str(data.get('message',data.get('errmsg','')))
                for field in ('client_id','client_secret'):
                    text=text.replace(str(value[field]),'[redacted]')
                report['message']=text[:300]
                report['has_endpoint']=bool(data.get('endpoint'))
                report['has_ticket']=bool(data.get('ticket'))
            except ValueError:
                report['not_json']=True
            return response
        requests.post=checked
        connection=client.open_connection()
        report['handshake_ready']=bool(connection and connection.get('endpoint') and connection.get('ticket'))
    except Exception as exc:
        report['error_type']=type(exc).__name__
    finally:
        path.unlink(missing_ok=True)
    print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':main()
