"""Read-only Telegram identity/chat check; sends no messages or AI requests."""
import os
import requests


def main():
    token=os.environ.get('CHECK_BOT_TOKEN')
    chat=os.environ.get('CHECK_CHAT_ID')
    if not token or not chat:
        raise SystemExit('Telegram test secrets missing.')
    for method, payload in [('getMe',{}), ('getChat',{'chat_id':chat})]:
        try:
            response=requests.post(f'https://api.telegram.org/bot{token}/{method}',json=payload,timeout=20)
            data=response.json()
        except (requests.RequestException,ValueError):
            raise SystemExit('Telegram connection failed; credentials hidden.') from None
        if not response.ok or not data.get('ok'):
            raise SystemExit('Telegram identity/chat check failed; credentials hidden.')
        if method=='getMe':
            if not data['result'].get('is_bot'):
                raise SystemExit('Not a bot identity.')
            print('Telegram bot identity verified.')
        else:
            print('Telegram chat accessible; no message sent.')


if __name__=='__main__':
    main()
