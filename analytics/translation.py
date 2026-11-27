"""Optional on-demand Google Cloud Translation Basic v2.
Only review body is sent. No credentials are stored in repository.
"""
import html
import json
import os
import urllib.parse
import urllib.request
from functools import lru_cache

@lru_cache(maxsize=1024)
def translate_review_body(body):
    key=os.environ.get('GOOGLE_TRANSLATE_API_KEY','').strip()
    if not key:
        raise RuntimeError('Translation is not configured. Set GOOGLE_TRANSLATE_API_KEY on the dashboard server.')
    if not body or not body.strip():return ''
    endpoint='https://translation.googleapis.com/language/translate/v2?'+urllib.parse.urlencode({'key':key})
    data=json.dumps({'q':body,'target':'en','format':'text'}).encode('utf-8')
    request=urllib.request.Request(endpoint,data=data,headers={'Content-Type':'application/json; charset=utf-8'},method='POST')
    try:
        with urllib.request.urlopen(request,timeout=20) as response:
            result=json.loads(response.read())
    except Exception as exc:
        # Do not reveal the URL (which contains the API key) in the UI error.
        raise RuntimeError('Translation could not be completed. Check API access, billing, and network connectivity.') from None
    return html.unescape(result['data']['translations'][0]['translatedText'])
