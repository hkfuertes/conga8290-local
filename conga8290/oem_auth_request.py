"""Fixed OEM auth actions: one of two tokens + email login, no automatic retries.

Only explicit local input may be used. Login creates a new account session and
must be authorized separately from token-only probing; no logout/control APIs.
"""
import hmac
import json
import re

from .cloud_protocol import derive_request_key, encrypt_et3, decrypt_et3, sign_request
from .oem_candidate_request import base_request_body, normalize_endpoint
from .oem_login_payload import AUTH_ACTIONS, LOGIN_OPTIONS, email_token_payload
from .oem_readonly_api import _https_exchange


def validate_auth_payload(kind, payload):
    expected = {'countryCode', 'email'}
    if kind == 'email_password':
        expected |= {'passwd', 'token', 'ifencrypt', 'options'}
    elif kind == 'username_token':
        expected = {'countryCode', 'username', 'isUid'}
    elif kind != 'email_token':
        raise ValueError('unapproved_auth_action')
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError('unexpected_auth_payload_fields')
    if kind == 'username_token':
        email_token_payload(payload['countryCode'], payload['username'])
        if payload['isUid'] is not False:
            raise ValueError('email_username_not_uid_required')
    else:
        email_token_payload(payload['countryCode'], payload['email'])
    if kind == 'email_password':
        if (type(payload['ifencrypt']) is not int or payload['ifencrypt'] != 1 or
                payload['options'] not in LOGIN_OPTIONS.values() or
                not isinstance(payload['token'], str) or not 1 <= len(payload['token']) <= 4096 or
                not isinstance(payload['passwd'], str) or
                not re.fullmatch(r'[a-f0-9]{256,2048}', payload['passwd']) or len(payload['passwd']) % 2):
            raise ValueError('encrypted_official_login_payload_required')


def build_auth_request(context, material, ch_key, kind, payload, endpoint):
    validate_auth_payload(kind, payload)
    body = base_request_body(context, ch_key)
    body.update(a=AUTH_ACTIONS[kind][0], v=AUTH_ACTIONS[kind][1])
    # Pre-login requests use NULL ecode, not a phone's sid or an empty ecode.
    key = derive_request_key(body['requestId'], material, None)
    body['postData'] = encrypt_et3(json.dumps(payload, separators=(',', ':')).encode(), key)
    body['sign'] = sign_request(body, material)
    return {'status': 'rootless_auth_prepared', 'endpoint': normalize_endpoint(endpoint),
            'body': body, 'response_key_bytes': list(key)}


def validate_auth_prepared(prepared, context, material, kind):
    if kind not in AUTH_ACTIONS or prepared.get('status') != 'rootless_auth_prepared':
        raise ValueError('unapproved_auth_request')
    if normalize_endpoint(prepared.get('endpoint')) != prepared['endpoint']:
        raise ValueError('noncanonical_auth_endpoint')
    body = prepared.get('body')
    if not isinstance(body, dict) or not all(isinstance(v, str) for v in body.values()):
        raise ValueError('invalid_auth_request_body')
    if (body.get('a'), body.get('v')) != AUTH_ACTIONS[kind] or 'sid' in body or 'ecode' in body:
        raise ValueError('auth_must_not_use_existing_session')
    for name, source in [('clientId', 'mAppId'), ('ttid', 'mTtid'), ('deviceId', 'mDeviceId'), ('appVersion', 'mAppVersion')]:
        if not hmac.compare_digest(body.get(name, ''), context[source]):
            raise ValueError('auth_client_context_mismatch')
    if body.get('et') != '3':
        raise ValueError('authenticated_encryption_required')
    key = derive_request_key(body.get('requestId'), material, None)
    if prepared.get('response_key_bytes') != list(key):
        raise ValueError('auth_response_key_mismatch')
    if not hmac.compare_digest(body.get('sign', ''), sign_request(body, material)):
        raise ValueError('auth_signature_mismatch')
    payload = json.loads(decrypt_et3(body.get('postData'), key))
    validate_auth_payload(kind, payload)
    return body, key


def auth_api(prepared, context, material, kind, *, allow_new_session=False):
    # Guard BEFORE preparing network I/O. Token-only does not authenticate/create
    # a session. Never turn a token-only probe into a password login implicitly.
    if kind == 'email_password' and not allow_new_session:
        raise ValueError('new_session_approval_required')
    body, key = validate_auth_prepared(prepared, context, material, kind)
    return _https_exchange(prepared['endpoint'], body, key)
