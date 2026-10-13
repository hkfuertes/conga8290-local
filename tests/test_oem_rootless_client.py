"""Synthetic end-to-end login and LIST flow; all HTTPS mocked, no phone."""
import json
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from conga8290.cloud_protocol import decrypt_et3
from conga8290.oem_rootless_client import RootlessClient


class RootlessFlowTests(unittest.TestCase):
    def setUp(self):
        self.context = {'mAppId': 'synthetic-id', 'mAppVersion': '1.2.9',
                        'mTtid': 'synthetic-ttid', 'mDeviceId': 'synthetic-installation'}
        self.client = RootlessClient(self.context, b'synthetic\0material', '1234abcd', 'https://a1.tuyaeu.com')
        self.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        numbers = self.rsa.public_key().public_numbers()
        self.token = {'token': 'synthetic-token', 'publicKey': str(numbers.n), 'exponent': str(numbers.e)}

    def auth(self, prepared, context, material, kind, **kwargs):
        payload = json.loads(decrypt_et3(prepared['body']['postData'], bytes(prepared['response_key_bytes'])))
        self.assertNotIn('sid', prepared['body'])
        if kind == 'email_token':
            return self.token
        self.assertTrue(kwargs['allow_new_session'])
        self.assertEqual(payload['token'], 'synthetic-token')
        self.assertEqual(len(self.rsa.decrypt(bytes.fromhex(payload['passwd']), padding.PKCS1v15())), 32)
        return {'sid': 'synthetic-session', 'ecode': 'synthetic-ecode', 'email': 'ignored-profile',
                'domain': {'mobileApiUrl': 'https://a1.tuyaeu.com'}}

    def test_explicit_login_then_exact_reference_robot_only(self):
        with patch('conga8290.oem_rootless_client.auth_api', side_effect=self.auth) as auth, patch('conga8290.oem_rootless_client.read_api', side_effect=[[{'gid': 123}], [{'devId': 'expected', 'localKey': '0123456789abcdef'}]]) as read:
            self.assertTrue(self.client.email_token('34', 'synthetic@example.invalid'))
            self.assertTrue(self.client.login('synthetic-password', allow_new_session=True))
            self.assertNotIn('email', self.client.session)
            self.assertEqual(self.client.recover_robot('expected'), {'id': 'expected', 'local_key': '0123456789abcdef'})
            self.assertEqual(auth.call_count, 2)
            self.assertEqual(read.call_count, 2)
        self.assertIsNone(self.client._email_token)

    def test_token_only_and_no_login_without_approval(self):
        with patch('conga8290.oem_rootless_client.auth_api', side_effect=self.auth) as auth:
            self.client.email_token('34', 'synthetic@example.invalid')
            with self.assertRaises(ValueError):
                self.client.login('synthetic-password')
            self.assertEqual(auth.call_count, 1)
            self.assertIsNone(self.client.session)

    def test_auth_failure_consumes_attempt_and_no_retry(self):
        with patch('conga8290.oem_rootless_client.auth_api', side_effect=ValueError('synthetic-failure')) as auth:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    self.client.email_token('34', 'synthetic@example.invalid')
            self.assertEqual(auth.call_count, 1)

    def test_list_budget_and_no_guessed_gid(self):
        self.client.session = {'sid': 'synthetic-session', 'ecode': 'synthetic-ecode', 'mobile_api_url': 'https://a1.tuyaeu.com'}
        with patch('conga8290.oem_rootless_client.read_api', side_effect=[[{'gid': 1}, {'gid': 2}, {'gid': 3}], [], []]) as read:
            with self.assertRaises(ValueError):
                self.client.recover_robot('expected')
            with self.assertRaises(ValueError):
                self.client.recover_robot('expected')
            self.assertEqual(read.call_count, 3)

    def test_ui_flow_pairs_username_token_and_empty_mfa_options_without_fallback(self):
        client = RootlessClient(self.context, b'synthetic\0material', '1234abcd', 'https://a1.tuyaeu.com', auth_flow='oem-ui')
        def ui_auth(prepared, context, material, kind, **kwargs):
            payload = json.loads(decrypt_et3(prepared['body']['postData'], bytes(prepared['response_key_bytes'])))
            if kind == 'username_token':
                self.assertEqual(payload, {'countryCode': '34', 'username': 'synthetic@example.invalid', 'isUid': False})
                return self.token
            self.assertEqual(kind, 'email_password')
            self.assertEqual(payload['options'], '{"group": 1,"mfaCode": ""}')
            return self.auth(prepared, context, material, kind, **kwargs)
        with patch('conga8290.oem_rootless_client.auth_api', side_effect=ui_auth) as auth:
            client.email_token('34', 'synthetic@example.invalid')
            client.login('synthetic-password', allow_new_session=True)
            self.assertEqual(auth.call_count, 2)
        self.assertEqual(client.auth_attempts, 2)
        self.assertIsNotNone(client.session)

    def test_ui_token_failure_has_no_legacy_retry(self):
        client = RootlessClient(self.context, b'synthetic\0material', '1234abcd', 'https://a1.tuyaeu.com', auth_flow='oem-ui')
        with patch('conga8290.oem_rootless_client.auth_api', side_effect=ValueError('synthetic-failure')) as auth:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    client.email_token('34', 'synthetic@example.invalid')
            self.assertEqual(auth.call_count, 1)
            self.assertEqual(auth.call_args.args[3], 'username_token')

    def test_unknown_auth_flow_is_rejected(self):
        with self.assertRaises(ValueError):
            RootlessClient(self.context, b'synthetic\0material', '1234abcd', 'https://a1.tuyaeu.com', auth_flow='untraced-flow')
