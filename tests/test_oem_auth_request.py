"""Synthetic auth framing and safety gates; all network I/O is mocked."""
import json
import unittest
from unittest.mock import patch

from conga8290.cloud_protocol import decrypt_et3, derive_request_key
from conga8290.oem_auth_request import build_auth_request, validate_auth_prepared, auth_api


class AuthRequestTests(unittest.TestCase):
    def setUp(self):
        self.context = {'mAppId': 'synthetic-id', 'mAppVersion': '1.2.9',
                        'mTtid': 'synthetic-ttid', 'mDeviceId': 'synthetic-client'}
        self.material = b'synthetic\0binary-material'
        self.payload = {'countryCode': '34', 'email': 'synthetic@example.invalid'}

    def prepared(self, kind='email_token'):
        payload = dict(self.payload)
        if kind == 'email_password':
            payload.update(passwd='ab' * 256, token='synthetic-token', ifencrypt=1, options='{"group": 1}')
        return build_auth_request(self.context, self.material, '1234abcd', kind, payload, 'https://a1.tuyaeu.com')

    def test_token_uses_null_ecode_and_no_existing_session(self):
        value = self.prepared()
        body, key = validate_auth_prepared(value, self.context, self.material, 'email_token')
        self.assertNotIn('sid', body)
        self.assertNotIn('ecode', body)
        self.assertEqual(key, derive_request_key(body['requestId'], self.material, None))
        self.assertEqual(json.loads(decrypt_et3(body['postData'], key)), self.payload)

    def test_no_unapproved_action_body_or_origin(self):
        for changes in [{'a': 'm.life.device.control'}, {'sid': 'synthetic-session'}, {'sign': 'bad'}]:
            value = self.prepared()
            value['body'].update(changes)
            with self.assertRaises(ValueError):
                validate_auth_prepared(value, self.context, self.material, 'email_token')
        value = self.prepared()
        value['endpoint'] = 'https://unverified.example/api.json'
        with self.assertRaises(ValueError):
            validate_auth_prepared(value, self.context, self.material, 'email_token')

    def test_login_needs_new_explicit_session_approval_before_network(self):
        value = self.prepared('email_password')
        with patch('conga8290.oem_auth_request._https_exchange') as exchange:
            with self.assertRaises(ValueError):
                auth_api(value, self.context, self.material, 'email_password')
            exchange.assert_not_called()
            auth_api(value, self.context, self.material, 'email_password', allow_new_session=True)
            exchange.assert_called_once()

    def test_token_only_never_calls_a_login_action(self):
        value = self.prepared()
        with patch('conga8290.oem_auth_request._https_exchange', return_value={'token': 'synthetic'}) as exchange:
            self.assertEqual(auth_api(value, self.context, self.material, 'email_token'), {'token': 'synthetic'})
            self.assertEqual(exchange.call_args.args[1]['a'], 'smartlife.m.user.email.token.create')

    def test_ui_username_token_is_allowlisted_and_not_a_login(self):
        payload = {'countryCode': '34', 'username': 'synthetic@example.invalid', 'isUid': False}
        value = build_auth_request(self.context, self.material, '1234abcd', 'username_token', payload, 'https://a1.tuyaeu.com')
        body, key = validate_auth_prepared(value, self.context, self.material, 'username_token')
        self.assertEqual((body['a'], body['v']), ('smartlife.m.user.username.token.get', '2.0'))
        self.assertNotIn('sid', body)
        self.assertEqual(json.loads(decrypt_et3(body['postData'], key)), payload)
        with patch('conga8290.oem_auth_request._https_exchange') as exchange:
            auth_api(value, self.context, self.material, 'username_token')
            exchange.assert_called_once()

    def test_ui_token_rejects_uid_login_and_type_coercion(self):
        for is_uid in [True, 0, 1, 'false']:
            with self.assertRaises(ValueError):
                build_auth_request(self.context, self.material, '1234abcd', 'username_token',
                                   {'countryCode': '34', 'username': 'synthetic@example.invalid', 'isUid': is_uid}, 'https://a1.tuyaeu.com')

    def test_ui_password_options_are_exact_empty_challenge_not_arbitrary_mfa(self):
        value = self.prepared('email_password')
        key = bytes(value['response_key_bytes'])
        payload = json.loads(decrypt_et3(value['body']['postData'], key))
        payload['options'] = '{"group": 1,"mfaCode": ""}'
        ui = build_auth_request(self.context, self.material, '1234abcd', 'email_password', payload, 'https://a1.tuyaeu.com')
        validate_auth_prepared(ui, self.context, self.material, 'email_password')
        payload['options'] = '{"group": 1,"mfaCode": "synthetic-code"}'
        with self.assertRaises(ValueError):
            build_auth_request(self.context, self.material, '1234abcd', 'email_password', payload, 'https://a1.tuyaeu.com')
