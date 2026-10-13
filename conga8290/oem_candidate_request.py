"""Offline LIST-request builder using reconstructed OEM material and live context.

The candidate is verified against isolated native routines, NOT full command-0
initialization. A caller must obtain an approved session/context in memory and
perform a bounded authenticated trial to establish server acceptance.
"""
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlsplit
import uuid

from .cloud_protocol import derive_request_key, encrypt_et3, sign_request
from .oem_readonly_api import HOSTS, READS


def normalize_endpoint(value):
    if not isinstance(value, str) or not value:
        raise ValueError('effective_account_endpoint_required')
    if '://' not in value:
        value = 'https://' + value
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or
            parsed.password or parsed.port not in [None, 443] or parsed.query or
            parsed.fragment or parsed.path not in ['', '/', '/api.json']):
        raise ValueError('unverified_effective_account_endpoint')
    return 'https://' + parsed.hostname + '/api.json'


def base_request_body(context, ch_key):
    """Fresh request metadata shared by the two LISTs and explicit auth flow."""
    if not isinstance(ch_key, str) or not re.fullmatch(r'[a-f0-9]{8}', ch_key):
        raise ValueError('verified_native_ch_key_required')
    if not all(isinstance(context.get(n), str) and context[n] for n in ['mAppId', 'mAppVersion', 'mTtid', 'mDeviceId']):
        raise ValueError('verified_application_context_required')
    request_id = str(uuid.uuid4())
    body = {'clientId': context['mAppId'],
            'appVersion': context['mAppVersion'], 'ttid': context['mTtid'],
            'deviceId': context['mDeviceId'], 'os': 'Android', 'lang': 'en',
            'et': '3', 'cp': 'gzip', 'chKey': ch_key, 'requestId': request_id,
            'time': str(int(time.time()))}
    for field, name in [('sdkVersion', 'mSdkVersion'), ('deviceCoreVersion', 'mDeviceCoreVersion'),
                        ('channel', 'mChannel'), ('appRnVersion', 'mAppRNVersion')]:
        if context.get(name):
            body[field] = context[name]
    return body


def build_candidate_request(session, context, material, ch_key, kind, gid=None):
    if kind not in READS or (kind == 'homes' and gid is not None):
        raise ValueError('unapproved_read_request')
    if kind == 'devices' and (not isinstance(gid, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', gid)):
        raise ValueError('home_list_gid_required')
    if not all(isinstance(session.get(n), str) and session[n] for n in ['sid', 'ecode']):
        raise ValueError('complete_session_required')
    body = base_request_body(context, ch_key)
    body.update(a=READS[kind][0], v=READS[kind][1], sid=session['sid'])
    key = derive_request_key(body['requestId'], material, session['ecode'])
    # Language is request-local response preference, not a changed app setting.
    # The runtime's system/device metadata are intentionally not invented.
    if kind == 'devices':
        payload = json.dumps({'gid': int(gid)}, separators=(',', ':')).encode()
        body['postData'] = encrypt_et3(payload, key)
    body['sign'] = sign_request(body, material)
    return {'status': 'reconstructed_in_memory', 'endpoint': normalize_endpoint(session['mobile_api_url']),
            'body': body, 'response_key_bytes': list(key)}


def derive_ch_key(app_id, package, fingerprint):
    # Real ELF getChKey(0x16a60) validated with synthetic inputs: a NUL at
    # hex digest +16 truncates substr(8,16) to EIGHT ASCII characters.
    return hmac.new(app_id.encode('ascii'), package + b'_' + fingerprint, hashlib.sha256).hexdigest()[8:16]
