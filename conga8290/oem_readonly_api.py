"""Bounded read-only OEM HTTPS requests and shared authenticated response decoder.

Public read_api accepts only two LIST actions. Auth uses a separate validator
before the internal transport. Sessions/keys stay in memory; no robot commands,
HA writes, response/session dumps or redirects.
"""
import hmac
import hashlib
import json
import ssl
import re
from urllib.parse import urlsplit, urlencode
from urllib.request import build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler, Request
from urllib.error import HTTPError
import zlib

from .cloud_protocol import decrypt_et3

HOSTS = {'a1.tuyaeu.com', 'a1-us.iotbing.com', 'a1-in.iotbing.com', 'a1.iot334.com'}
READS = {'homes': ('m.life.home.space.list', '1.0'),
         'devices': ('m.life.my.group.device.list', '2.2')}
MAX_RESPONSE = 2 * 1048576


class OemReadError(ValueError):
    def __init__(self, category, http_status=None, safe_diagnostics=None):
        super().__init__('oem_read_failed')
        self.category = category
        self.http_status = http_status
        self.safe_diagnostics = safe_diagnostics


def rejection_category(envelope):
    code = str(envelope.get('errorCode', envelope.get('code', ''))).upper()
    if code in ['USER_SESSION_INVALID', 'USER_SESSION_EXPIRED', 'USER_TOKEN_EXPIRED', 'USER_SESSION_NOT_EXIST']:
        return 'session_rejected'
    if code in ['SIGN_INVALID', 'SIGN_ERROR', 'SIGNATURE_INVALID', 'ILLEGAL_SIGN']:
        return 'signature_rejected'
    if code in ['CAPTCHA_REQUIRED', 'MFA_REQUIRED', 'USER_SECONDARY_VERIFICATION']:
        return 'human_verification_required'
    # Return a finite category only, never a server-supplied message/code. OEM
    # gateways use additional symbolic variants, including the historic SING typo.
    if any(label in code for label in ['CAPTCHA', 'MFA', 'VERIFICATION', 'RISK', 'SECURITY_CHECK']):
        return 'human_verification_required'
    if 'SESSION' in code or 'SID_INVALID' in code:
        return 'session_rejected'
    if any(label in code for label in ['SIGN', 'SING_VALIDATE', 'HMAC']):
        return 'signature_rejected'
    if any(label in code for label in ['APP_VERIFY', 'APPVERIF', 'ATTEST', 'INTEGRITY']):
        return 'application_integrity_rejected'
    if any(label in code for label in ['APPKEY', 'APP_KEY', 'CLIENTID', 'CLIENT_ID', 'TTID', 'APP_SECRET', 'CLIENT_SECRET']):
        return 'application_identity_rejected'
    if any(label in code for label in ['PARAM', 'REQUEST_TIME', 'TIMESTAMP']):
        return 'request_parameters_rejected'
    if any(label in code for label in ['PERMISSION', 'DENIED', 'API_NOT', 'API_INVALID']):
        return 'api_permission_rejected'
    # Authentication hints stay finite; they are not proof of a wrong password.
    # For example a correct password encrypted/framed incorrectly can be rejected
    # as credentials too. Never export raw server codes or messages.
    if any(label in code for label in ['_LOCKED', 'LOGIN_LOCK', 'TOO_FREQUENT', 'TOO_MANY', 'RATE_LIMIT']):
        return 'account_or_rate_limited'
    if (any(label in code for label in ['PASSWORD', 'PASSWD']) and
            any(label in code for label in ['ERROR', 'WRONG', 'NOT_MATCH', 'INCORRECT', 'INVALID'])):
        return 'credentials_rejected'
    if any(label in code for label in ['WHAT_USERNAME_ERROR', 'USER_NOT_EXIST', 'USERNAME_NOT_EXIST', 'ACCOUNT_NOT_EXIST', 'ACCOUNT_DISABLED', 'USER_DISABLED']):
        return 'account_rejected'
    if 'TOKEN' in code and any(label in code for label in ['INVALID', 'EXPIRE', 'NOT_EXIST', 'ERROR']):
        return 'auth_token_rejected'
    if code in ['SERVICE_UNAVAILABLE', 'SERVER_BUSY', 'SYSTEM_ERROR']:
        return 'service_unavailable'
    # OEM errors sometimes have numeric codes. Classify a few explicit phrases
    # in the transient message; neither code nor message leaves this process.
    message = str(envelope.get('errorMsg', envelope.get('msg', ''))).lower()
    for phrases, category in [(['captcha', 'multi-factor', 'verification required'], 'human_verification_required'),
                              (['app verification', 'app verify', 'attestation', 'integrity'], 'application_integrity_rejected'),
                              (['sign invalid', 'sign error', 'signature', 'sign validate', 'sing validate'], 'signature_rejected'),
                              (['session invalid', 'session expired', 'invalid session'], 'session_rejected'),
                              (['clientid', 'appkey', 'app key', 'ttid', 'client secret'], 'application_identity_rejected'),
                              (['illegal parameter', 'invalid parameter', 'timestamp'], 'request_parameters_rejected'),
                              # Localized server text is protocol data, not CLI language.
                              (['too many attempts', 'too many requests', 'too frequent', 'account locked', 'demasiados intentos', 'cuenta bloqueada'], 'account_or_rate_limited'),
                              (['incorrect username or password', 'incorrect password', 'invalid password', 'password error', 'password does not match', 'wrong password', 'usuario o contraseña incorrect', 'contraseña incorrect', 'contrasena incorrect'], 'credentials_rejected'),
                              (['account does not exist', 'user does not exist', 'account not found', 'usuario no existe', 'cuenta no existe'], 'account_rejected'),
                              (['token expired', 'invalid token', 'token inválido', 'token caducado'], 'auth_token_rejected'),
                              (['service unavailable', 'server busy', 'servicio no disponible'], 'service_unavailable')]:
        if any(phrase in message for phrase in phrases):
            return category
    return 'unclassified_server_rejection'


def rejection_diagnostics(envelope):
    code = envelope.get('errorCode', envelope.get('code'))
    return {'error_code_field_present': code is not None,
            'error_code_numeric': isinstance(code, (int, float)) or isinstance(code, str) and code.isdigit(),
            'error_code_symbolic': isinstance(code, str) and bool(re.fullmatch(r'[A-Z]+(?:_[A-Z]+)+', code)),
            'error_message_field_present': bool(envelope.get('errorMsg', envelope.get('msg'))),
            'success_boolean_false': envelope.get('success') is False,
            'known_envelope_fields': [k for k in ['success', 'errorCode', 'errorMsg', 'code', 'msg', 'result', 'status', 'data'] if k in envelope]}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_prepared(prepared, session, kind):
    if kind not in READS or prepared.get('status') not in ['prepared_in_memory', 'reconstructed_in_memory']:
        raise ValueError('unapproved_read_request')
    parsed = urlsplit(prepared.get('endpoint', ''))
    if (parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or
            parsed.password or parsed.port not in [None, 443] or parsed.path != '/api.json' or
            parsed.query or parsed.fragment):
        raise ValueError('unverified_oem_endpoint')
    body = prepared.get('body')
    if not isinstance(body, dict) or not all(isinstance(v, str) for v in body.values()):
        raise ValueError('invalid_sdk_body')
    if (body.get('a'), body.get('v')) != READS[kind]:
        raise ValueError('unapproved_api_action')
    sid = body.get('sid')
    if not isinstance(sid, str) or not isinstance(session.get('sid'), str) or not hmac.compare_digest(sid, session['sid']):
        raise ValueError('sdk_body_session_mismatch')
    if not body.get('sign') or not body.get('requestId') or body.get('et') != '3':
        raise ValueError('missing_sdk_crypto_fields')
    if kind == 'devices' and not body.get('postData'):
        raise ValueError('missing_group_query')
    key = prepared.get('response_key_bytes')
    if not isinstance(key, list) or len(key) != 16 or not all(type(v) is int and 0 <= v <= 255 for v in key):
        raise ValueError('invalid_sdk_response_key')
    return body, bytes(key)


def bounded_gzip(data):
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    value = decompressor.decompress(data, MAX_RESPONSE + 1)
    if len(value) > MAX_RESPONSE or decompressor.unconsumed_tail or not decompressor.eof:
        raise ValueError('gzip_response_budget_exceeded')
    return value


def decode_result(envelope, key, _depth=0):
    if not isinstance(envelope, dict):
        raise ValueError('unsupported_oem_envelope')
    if 'success' not in envelope and isinstance(envelope.get('result'), str):
        # Business.decryptResponse: the outer BusinessEncryptResponse encrypts
        # the ENTIRE BusinessResponse, including success/errorCode, not just the
        # success result. Verify its MD5 binding and GCM before interpreting it.
        if _depth or not isinstance(envelope.get('sign'), str) or type(envelope.get('t')) is not int:
            raise ValueError('unsupported_encrypted_business_envelope')
        ciphertext = envelope['result']
        if len(ciphertext) > MAX_RESPONSE:
            raise ValueError('encrypted_business_envelope_budget_exceeded')
        canonical = f'result={ciphertext}||t={envelope["t"]}||'.encode() + key
        expected = hashlib.md5(canonical).hexdigest()
        if not hmac.compare_digest(expected, envelope['sign'].lower()):
            raise ValueError('encrypted_business_response_signature_invalid')
        clear = decrypt_et3(ciphertext, key)
        if clear[:2] == b'\x1f\x8b':
            clear = bounded_gzip(clear)
        if len(clear) > MAX_RESPONSE:
            raise ValueError('decrypted_business_response_budget_exceeded')
        return decode_result(json.loads(clear), key, _depth=1)
    if envelope.get('success') is not True:
        raise OemReadError(rejection_category(envelope), safe_diagnostics=rejection_diagnostics(envelope))
    result = envelope.get('result')
    if isinstance(result, (list, dict)):
        return result
    if not isinstance(result, str) or len(result) > MAX_RESPONSE:
        raise ValueError('unsupported_oem_result')
    if result.lstrip().startswith(('[', '{')):
        return json.loads(result)
    clear = decrypt_et3(result, key)
    if clear[:2] == b'\x1f\x8b':
        clear = bounded_gzip(clear)
    if len(clear) > MAX_RESPONSE:
        raise ValueError('oem_result_budget_exceeded')
    return json.loads(clear)


def read_api(prepared, session, kind):
    body, key = validate_prepared(prepared, session, kind)
    return _https_exchange(prepared['endpoint'], body, key)


def _https_exchange(endpoint, body, key):
    """Internal transport; callers MUST apply their fixed-action validator first.

    Public LIST and auth entry points keep separate allowlists. This helper never
    accepts a user-supplied arbitrary action/URL through a CLI.
    """
    # No token in argv, URL query or retained request file. HTTPS only; ignore
    # environmental proxies and never follow a credential-bearing redirect.
    request = Request(endpoint, data=urlencode(body).encode(), method='POST',
                      headers={'Content-Type': 'application/x-www-form-urlencoded',
                               'Accept-Encoding': 'gzip'})
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError('http_response_budget_exceeded')
            if response.headers.get('Content-Encoding', '').lower() == 'gzip':
                raw = bounded_gzip(raw)
            envelope = json.loads(raw)
    except HTTPError as exc:
        # Do not read/store the arbitrary response body or exception message.
        raise OemReadError('http_read_rejected', exc.code) from None
    return decode_result(envelope, key)


def select_robot(value, expected_id):
    if isinstance(value, dict):
        value = value.get('devices', value.get('list'))
    if not isinstance(value, list):
        raise ValueError('unsupported_device_list_shape')
    matches = [v for v in value if isinstance(v, dict) and v.get('devId') == expected_id]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError('robot_not_uniquely_listed')
    robot = matches[0]
    key = robot.get('localKey')
    if not isinstance(key, str) or len(key) != 16 or not key.isascii():
        raise ValueError('robot_key_missing_in_cloud_read')
    return {'id': expected_id, 'local_key': key, 'product_id': robot.get('productId')}
