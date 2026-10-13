"""Offline payload helpers used by the verified OEM-UI rootless login route.

No Android/root, HTTP, prompts, logging or persistence here. Other accounts/regions
and CAPTCHA/MFA flows remain unverified. The CLI defaults to a masked password
prompt; explicit password arguments are allowed with an exposure warning.
"""
import hashlib
import re

from .cloud_protocol import encrypt_password_digest

# ThingApiParams.checkAPIName rewrites the thing namespace before transport.
# UserApi uses token version 1.0 and GwBroadcastMonitorService.mVersion = 3.0.
AUTH_ACTIONS = {'email_token': ('smartlife.m.user.email.token.create', '1.0'),
                'username_token': ('smartlife.m.user.username.token.get', '2.0'),
                'email_password': ('smartlife.m.user.email.password.login', '3.0')}
AUTH_FLOWS = {'sdk-email': 'email_token', 'oem-ui': 'username_token'}
LOGIN_OPTIONS = {'sdk-email': '{"group": 1}',
                 'oem-ui': '{"group": 1,"mfaCode": ""}'}


def email_token_payload(country_code, email):
    if not isinstance(country_code, str) or not re.fullmatch(r'[1-9][0-9]{0,2}', country_code):
        raise ValueError('explicit_country_code_required')
    if not isinstance(email, str) or not 3 <= len(email) <= 254 or email.count('@') != 1 or any(c.isspace() or ord(c) < 32 for c in email):
        raise ValueError('local_email_required')
    return {'countryCode': country_code, 'email': email}


def username_token_payload(country_code, email):
    """LoginRepository.e -> LoginBusiness.B: email username, NOT uid login."""
    email_token_payload(country_code, email)
    return {'countryCode': country_code, 'username': email, 'isUid': False}


def email_password_payload(country_code, email, password, token_result, *, auth_flow='sdk-email'):
    if auth_flow not in AUTH_FLOWS:
        raise ValueError('untraced_auth_flow')
    payload = email_token_payload(country_code, email)
    if not isinstance(password, str) or not password:
        raise ValueError('local_password_required')
    if not isinstance(token_result, dict) or not isinstance(token_result.get('token'), str) or not token_result['token']:
        raise ValueError('official_email_token_required')
    modulus, exponent = token_result.get('publicKey'), token_result.get('exponent')
    if not isinstance(modulus, str) or not isinstance(exponent, str):
        raise ValueError('official_decimal_rsa_parameters_required')
    digest = hashlib.md5(password.encode('utf8')).hexdigest()
    # Unlike the SDK's fallback branch, NEVER transmit a bare password digest
    # when token/RSA parsing fails. Synthetic tests prove exact framing only.
    encrypted = encrypt_password_digest(digest, modulus, exponent)
    payload.update(passwd=encrypted, token=token_result['token'], ifencrypt=1,
                    options=LOGIN_OPTIONS[auth_flow])
    return payload


def selected_login_session(result):
    if not isinstance(result, dict):
        raise ValueError('unsupported_login_result')
    sid, ecode = result.get('sid'), result.get('ecode')
    if not isinstance(sid, str) or not 8 <= len(sid) <= 1024 or '\0' in sid:
        raise ValueError('complete_login_session_required')
    if not isinstance(ecode, str) or not 1 <= len(ecode) <= 1024 or '\0' in ecode:
        raise ValueError('complete_login_session_required')
    domain = result.get('domain')
    endpoint = domain.get('mobileApiUrl') if isinstance(domain, dict) else None
    # Never retain the full User profile, email, UID, extra account codes, etc.
    return {'sid': sid, 'ecode': ecode, 'mobile_api_url': endpoint}
