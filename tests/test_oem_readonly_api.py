"""Synthetic-only HTTPS relay guards and exact robot selection. No network."""
import gzip
import hashlib
import json
import unittest

from conga8290.cloud_protocol import encrypt_et3
from conga8290.oem_readonly_api import validate_prepared, decode_result, bounded_gzip, select_robot, rejection_category


def prepared(kind='homes'):
    body = {'a': 'm.life.home.space.list', 'v': '1.0', 'sid': 'synthetic-session',
            'sign': 'synthetic-signature', 'requestId': 'synthetic-request', 'et': '3'}
    if kind == 'devices':
        body.update(a='m.life.my.group.device.list', v='2.2', postData='synthetic-ciphertext')
    return {'status': 'prepared_in_memory', 'endpoint': 'https://a1.tuyaeu.com/api.json',
            'body': body, 'response_key_bytes': list(bytes(range(16)))}


class ReadonlyApiTests(unittest.TestCase):
    def test_encrypted_business_envelope_is_decrypted_before_success_check(self):
        key = b'0123456789abcdef'
        clear = json.dumps({'success': True, 'result': [{'id': 123}]}).encode()
        ciphertext = encrypt_et3(gzip.compress(clear), key)
        timestamp = 1234567890
        signature = hashlib.md5(f'result={ciphertext}||t={timestamp}||{key.decode()}'.encode()).hexdigest()
        outer = {'result': ciphertext, 't': timestamp, 'sign': signature}
        self.assertEqual(decode_result(outer, key), [{'id': 123}])

    def test_encrypted_envelope_signature_and_gcm_must_verify(self):
        key = b'0123456789abcdef'
        ciphertext = encrypt_et3(b'{"success":true,"result":[]}', key)
        with self.assertRaises(ValueError):
            decode_result({'result': ciphertext, 't': 123, 'sign': '0' * 32}, key)
        with self.assertRaises(ValueError):
            decode_result({'result': ciphertext}, key)

    def test_rejection_only_exposes_finite_category(self):
        for code, category in [('SING_VALIDATE_FAILED', 'signature_rejected'),
                               ('ILLEGAL_APPKEY', 'application_identity_rejected'),
                               ('ILLEGAL_PARAMS', 'request_parameters_rejected'),
                               ('USER_SESSION_INVALID', 'session_rejected'),
                               ('CAPTCHA_REQUIRED', 'human_verification_required')]:
            self.assertEqual(rejection_category({'errorCode': code, 'errorMsg': 'synthetic-secret'}), category)

    def test_login_rejections_classify_without_exporting_code_or_message(self):
        for code, category in [('WHAT_PASSWORD_ERROR', 'credentials_rejected'),
                               ('USERNAME_OR_PASSWORD_WRONG', 'credentials_rejected'),
                               ('USER_PASSWD_NOT_MATCH', 'credentials_rejected'),
                               ('WHAT_USERNAME_ERROR', 'account_rejected'),
                               ('USER_NOT_EXIST', 'account_rejected'),
                               ('LOGIN_TOO_FREQUENT', 'account_or_rate_limited'),
                               ('USER_PASSWORD_LOCKED', 'account_or_rate_limited'),
                               ('TOKEN_INVALID', 'auth_token_rejected'),
                               ('SERVICE_UNAVAILABLE', 'service_unavailable')]:
            self.assertEqual(rejection_category({'errorCode': code, 'errorMsg': 'synthetic-secret'}), category)

    def test_localized_login_messages_have_only_finite_categories(self):
        for message, category in [('Incorrect username or password: synthetic@example.invalid', 'credentials_rejected'),
                                  ('Usuario o contraseña incorrectos: synthetic@example.invalid', 'credentials_rejected'),
                                  ('Account does not exist: synthetic@example.invalid', 'account_rejected'),
                                  ('Demasiados intentos. synthetic-secret', 'account_or_rate_limited'),
                                  ('Token expired: synthetic-secret', 'auth_token_rejected')]:
            self.assertEqual(rejection_category({'errorCode': 123456, 'errorMsg': message}), category)
    def test_two_explicit_reads_only(self):
        for kind in ['homes', 'devices']:
            validate_prepared(prepared(kind), {'sid': 'synthetic-session'}, kind)
        value = prepared()
        value['body']['a'] = 'm.life.device.control'
        with self.assertRaises(ValueError):
            validate_prepared(value, {'sid': 'synthetic-session'}, 'homes')

    def test_https_exact_origin_path_and_no_credential_url(self):
        for url in ['http://a1.tuyaeu.com/api.json', 'https://unverified.example/api.json',
                    'https://a1.tuyaeu.com/api.json?sid=synthetic',
                    'https://user:pass@a1.tuyaeu.com/api.json', 'https://a1.tuyaeu.com/other']:
            value = prepared()
            value['endpoint'] = url
            with self.assertRaises(ValueError):
                validate_prepared(value, {'sid': 'synthetic-session'}, 'homes')

    def test_session_binding_and_key_validation(self):
        value = prepared()
        with self.assertRaises(ValueError):
            validate_prepared(value, {'sid': 'different-session'}, 'homes')
        value['response_key_bytes'][0] = 999
        with self.assertRaises(ValueError):
            validate_prepared(value, {'sid': 'synthetic-session'}, 'homes')

    def test_result_stays_in_memory_and_authentication_required(self):
        data = [{'id': 123}]
        key = bytes(range(16))
        ciphertext = encrypt_et3(json.dumps(data).encode(), key)
        for value in [data, json.dumps(data), ciphertext]:
            self.assertEqual(decode_result({'success': True, 'result': value}, key), data)
        with self.assertRaises(ValueError):
            decode_result({'success': False, 'result': data}, key)
        self.assertEqual(bounded_gzip(gzip.compress(b'synthetic')), b'synthetic')

    def test_only_reference_robot_key_selected(self):
        devices = [{'devId': 'other', 'localKey': 'do-not-select-me!'},
                   {'devId': 'expected', 'localKey': 'synthetic-key-16', 'productId': 'test'}]
        # Exactly sixteen characters required, not arbitrary cache fields.
        devices[1]['localKey'] = '0123456789abcdef'
        self.assertEqual(select_robot(devices, 'expected'),
                         {'id': 'expected', 'local_key': '0123456789abcdef', 'product_id': 'test'})
        self.assertIsNone(select_robot(devices, 'absent'))
        with self.assertRaises(ValueError):
            select_robot(devices + [devices[1]], 'expected')
