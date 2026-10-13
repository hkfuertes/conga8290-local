"""Pure synthetic auth payload tests; no real credentials or network."""
import hashlib
import unittest

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from conga8290.oem_login_payload import AUTH_ACTIONS, email_token_payload, email_password_payload, selected_login_session


class LoginPayloadTests(unittest.TestCase):
    def test_shipped_ui_token_fields_and_login_options(self):
        from conga8290.oem_login_payload import username_token_payload
        self.assertEqual(AUTH_ACTIONS['username_token'], ('smartlife.m.user.username.token.get', '2.0'))
        self.assertEqual(username_token_payload('34', 'synthetic@example.invalid'),
                         {'countryCode': '34', 'username': 'synthetic@example.invalid', 'isUid': False})
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        numbers = private.public_key().public_numbers()
        token = {'token': 'synthetic-token', 'publicKey': str(numbers.n), 'exponent': str(numbers.e)}
        value = email_password_payload('34', 'synthetic@example.invalid', 'synthetic-password', token, auth_flow='oem-ui')
        self.assertEqual(value['options'], '{"group": 1,"mfaCode": ""}')
        self.assertEqual(private.decrypt(bytes.fromhex(value['passwd']), padding.PKCS1v15()),
                         hashlib.md5(b'synthetic-password').hexdigest().encode())

    def test_shipped_login_versions_and_namespace(self):
        self.assertEqual(AUTH_ACTIONS['email_token'], ('smartlife.m.user.email.token.create', '1.0'))
        self.assertEqual(AUTH_ACTIONS['email_password'], ('smartlife.m.user.email.password.login', '3.0'))

    def test_rsa_encrypted_md5_hex_and_string_options(self):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        numbers = private.public_key().public_numbers()
        token = {'token': 'synthetic-token', 'publicKey': str(numbers.n), 'exponent': str(numbers.e)}
        value = email_password_payload('34', 'synthetic@example.invalid', 'synthetic-password', token)
        clear = private.decrypt(bytes.fromhex(value['passwd']), padding.PKCS1v15())
        self.assertEqual(clear, hashlib.md5(b'synthetic-password').hexdigest().encode())
        self.assertEqual(value['ifencrypt'], 1)
        self.assertEqual(value['options'], '{"group": 1}')
        self.assertNotIn('password', value)

    def test_no_unencrypted_fallback_or_guessed_account_input(self):
        for token in [{}, {'token': 'synthetic'}, {'token': 'synthetic', 'publicKey': 'bad', 'exponent': 'bad'}]:
            with self.assertRaises(ValueError):
                email_password_payload('34', 'synthetic@example.invalid', 'synthetic-password', token)
        with self.assertRaises(ValueError):
            email_token_payload('', 'synthetic@example.invalid')

    def test_login_result_selects_session_only(self):
        result = {'sid': 'synthetic-session', 'ecode': 'synthetic-ecode', 'email': 'ignored@example.invalid',
                  'uid': 'ignored-user', 'domain': {'mobileApiUrl': 'https://a1.tuyaeu.com'}, 'extras': {'ignored': 123}}
        self.assertEqual(selected_login_session(result),
                         {'sid': 'synthetic-session', 'ecode': 'synthetic-ecode', 'mobile_api_url': 'https://a1.tuyaeu.com'})
