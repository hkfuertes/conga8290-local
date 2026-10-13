"""PC-only OEM bootstrap, email auth and bounded owned-Conga selection.

No Android/ADB/Frida imports, redirects, token persistence, robot commands,
logout, retries or arbitrary actions. New-session effects remain unverified.
"""
import hmac
import re

from cryptography.hazmat.primitives.asymmetric import rsa

from .oem_auth_request import build_auth_request, auth_api
from .oem_candidate_request import build_candidate_request, derive_ch_key, normalize_endpoint
from .oem_login_payload import AUTH_FLOWS, email_token_payload, username_token_payload, email_password_payload, selected_login_session
from .oem_readonly_api import read_api, select_robot

CONGA_PRODUCT = 'kofl9ubyyyfznpxw'


def selected_email_token(value):
    if not isinstance(value, dict):
        raise ValueError('unsupported_email_token_result')
    token, modulus, exponent = value.get('token'), value.get('publicKey'), value.get('exponent')
    if (not isinstance(token, str) or not 1 <= len(token) <= 4096 or '\0' in token or
            not isinstance(modulus, str) or not re.fullmatch(r'[0-9]{128,2500}', modulus) or
            not isinstance(exponent, str) or not re.fullmatch(r'[0-9]{1,10}', exponent)):
        raise ValueError('complete_official_email_token_required')
    public = rsa.RSAPublicNumbers(int(exponent), int(modulus)).public_key()
    if not 1024 <= public.key_size <= 8192:
        raise ValueError('unsupported_official_rsa_key_size')
    return {'token': token, 'publicKey': modulus, 'exponent': exponent}


class RootlessClient:
    def __init__(self, context, material, ch_key, endpoint, *, auth_flow='sdk-email'):
        if auth_flow not in AUTH_FLOWS:
            raise ValueError('untraced_auth_flow')
        self.auth_flow = auth_flow
        self.context = context
        self.material = material
        self.ch_key = ch_key
        self.endpoint = normalize_endpoint(endpoint)
        self.auth_attempts = 0
        self.read_attempts = 0
        self._identity = None
        self._email_token = None
        self.session = None
        self._home_ids = set()
        self._robot_keys = {}

    @classmethod
    def from_package(cls, region='EU', *, auth_flow='sdk-email'):
        if auth_flow not in AUTH_FLOWS:
            raise ValueError('untraced_auth_flow')
        from .packaged_client_context import packaged_client_context
        from .packaged_domains import packaged_domains
        from .oem_bootstrap_fixture import derive_candidate
        from .apk_signing_identity import signing_certificate, native_certificate_fingerprint
        from .packaged_oem_identity import APK
        from .native_oem_material import MaterialFixture
        context = packaged_client_context()
        app_id, material = derive_candidate()
        if not hmac.compare_digest(app_id, context['mAppId']):
            raise ValueError('packaged_registration_mismatch')
        fingerprint = native_certificate_fingerprint(signing_certificate(APK.read_bytes()))
        ch_key = derive_ch_key(app_id, b'es.cecotec.forceclima', fingerprint)
        native = MaterialFixture()
        native.constructors()
        if native.native_ch_key(app_id.encode(), b'es.cecotec.forceclima', fingerprint) != ch_key.encode():
            raise ValueError('native_ch_key_mismatch')
        endpoints = [row['mobile_api_url'] for row in packaged_domains() if row['region'] == region]
        if len(endpoints) != 1:
            raise ValueError('one_packaged_region_required')
        return cls(context, material, ch_key, endpoints[0], auth_flow=auth_flow)

    def email_token(self, country_code, email):
        if self.auth_attempts:
            raise ValueError('auth_retries_not_allowed')
        kind = AUTH_FLOWS[self.auth_flow]
        payload = (username_token_payload(country_code, email) if kind == 'username_token'
                   else email_token_payload(country_code, email))
        prepared = build_auth_request(self.context, self.material, self.ch_key, kind, payload, self.endpoint)
        self.auth_attempts += 1
        result = auth_api(prepared, self.context, self.material, kind)
        self._email_token = selected_email_token(result)
        self._identity = country_code, email
        # Return only success, not a login token, RSA modulus, or arbitrary account
        # result. Kept privately for one subsequent, separately approved login.
        return True

    def login(self, password, *, allow_new_session=False):
        if not allow_new_session:
            raise ValueError('new_session_approval_required')
        if self.auth_attempts != 1 or self._email_token is None or self._identity is None:
            raise ValueError('one_official_token_before_login_required')
        country_code, email = self._identity
        payload = email_password_payload(country_code, email, password, self._email_token, auth_flow=self.auth_flow)
        prepared = build_auth_request(self.context, self.material, self.ch_key, 'email_password', payload, self.endpoint)
        self.auth_attempts += 1
        try:
            result = auth_api(prepared, self.context, self.material, 'email_password', allow_new_session=True)
            session = selected_login_session(result)
            # Do not fall back to packaged routing when the account override is
            # missing or unverified; authentication is not approval for any host.
            session['mobile_api_url'] = normalize_endpoint(session['mobile_api_url'])
            self.session = session
            return True
        finally:
            self._email_token = None
            self._identity = None

    def list_homes(self):
        if self.session is None or self.read_attempts:
            raise ValueError('one_authenticated_home_list_required')
        prepared = build_candidate_request(self.session, self.context, self.material, self.ch_key, 'homes')
        self.read_attempts += 1
        value = read_api(prepared, self.session, 'homes')
        if not isinstance(value, list) or len(value) > 100:
            raise ValueError('unsupported_home_list_shape')
        homes = []
        for item in value:
            if not isinstance(item, dict):
                continue
            gid = item.get('gid', item.get('id'))
            if type(gid) is int:
                gid = str(gid)
            if not isinstance(gid, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', gid):
                continue
            if gid not in self._home_ids:
                homes.append({'gid': gid, 'name': item.get('name')})
                self._home_ids.add(gid)
        return homes

    def list_robots(self, gid):
        if self.session is None or self.read_attempts != 1 or gid not in self._home_ids:
            raise ValueError('selected_home_from_list_required')
        prepared = build_candidate_request(self.session, self.context, self.material, self.ch_key, 'devices', gid)
        self.read_attempts += 1
        value = read_api(prepared, self.session, 'devices')
        if isinstance(value, dict):
            value = value.get('devices', value.get('list'))
        if not isinstance(value, list) or len(value) > 500:
            raise ValueError('unsupported_device_list_shape')
        robots = []
        for item in value:
            if not isinstance(item, dict) or item.get('productId') != CONGA_PRODUCT:
                continue
            dev_id = item.get('devId')
            if not isinstance(dev_id, str) or not dev_id:
                raise ValueError('supported_robot_id_missing')
            selected = select_robot(value, dev_id)
            if dev_id in self._robot_keys:
                raise ValueError('robot_not_uniquely_listed')
            self._robot_keys[dev_id] = selected['local_key']
            robots.append({'id': dev_id, 'name': item.get('name')})
        return robots

    def select_robot(self, dev_id):
        if self.read_attempts != 2 or dev_id not in self._robot_keys:
            raise ValueError('listed_conga_selection_required')
        selected = {'id': dev_id, 'local_key': self._robot_keys[dev_id]}
        self._robot_keys.clear()
        return selected

    def close(self):
        # Local disposal, NOT a server logout; no promise of secure RAM erasure.
        self.session = None
        self._email_token = None
        self._identity = None
        self._home_ids.clear()
        self._robot_keys.clear()

    def recover_robot(self, expected_id):
        if self.session is None or self.read_attempts:
            raise ValueError('one_authenticated_recovery_required')
        if not isinstance(expected_id, str) or not expected_id:
            raise ValueError('exact_reference_robot_id_required')
        prepared = build_candidate_request(self.session, self.context, self.material, self.ch_key, 'homes')
        self.read_attempts += 1
        homes = read_api(prepared, self.session, 'homes')
        if not isinstance(homes, list):
            raise ValueError('unsupported_home_list_shape')
        gids = []
        for item in homes:
            gid = item.get('gid', item.get('id')) if isinstance(item, dict) else None
            if type(gid) is int and 0 < gid < 10**19:
                gids.append(str(gid))
        for gid in list(dict.fromkeys(gids))[:2]:
            prepared = build_candidate_request(self.session, self.context, self.material, self.ch_key, 'devices', gid)
            self.read_attempts += 1
            robot = select_robot(read_api(prepared, self.session, 'devices'), expected_id)
            if robot:
                return {'id': robot['id'], 'local_key': robot['local_key']}
        raise ValueError('reference_robot_not_recovered_in_bounded_lists')
