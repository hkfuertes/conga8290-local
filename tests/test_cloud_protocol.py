"""Offline synthetic cryptography tests. No phone, account, secret or network."""
import base64
import hashlib
import hmac
import unittest

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from conga8290.cloud_protocol import (
    canonical_sign_input, decrypt_et3, encrypt_et3,
    derive_request_key, encrypt_password_digest, postdata_hash, sign_request,
)


class CloudProtocolTests(unittest.TestCase):
    def test_rearranged_md5(self):
        # MD5('abc') = 900150983cd24fb0d6963f7d28e17f72.
        self.assertEqual(postdata_hash('abc'), '3cd24fb09001509828e17f72d6963f7d')
        self.assertEqual(postdata_hash(''), '')

    def test_canonical_order_filtering_and_no_mutation(self):
        params = {'v': '1.0', 'a': 'synthetic', 'postData': 'abc',
                  'sdkVersion': 'ignored', 'imei': 'ignored', 'sid': '',
                  'chKey': 'synthetic', 'time': '1700000000'}
        before = dict(params)
        self.assertEqual(canonical_sign_input(params),
                         'a=synthetic||chKey=synthetic||postData='
                         '3cd24fb09001509828e17f72d6963f7d||time=1700000000||v=1.0')
        self.assertEqual(params, before)
        with self.assertRaises(ValueError):
            canonical_sign_input({'time': 1700000000})

    def test_et3_nist_gcm_vector_and_nonce_prefix(self):
        # NIST GCM test vector: 128-bit zero key, zero nonce, one zero block.
        nonce = bytes(12)
        packet = base64.b64decode(encrypt_et3(bytes(16), bytes(16), nonce=nonce))
        self.assertEqual(packet[:12], nonce)
        self.assertEqual(packet[12:].hex(), '0388dace60b6a392f328c2b971b2fe78'
                                          'ab6e47d42cec13bdf53a67b21257bddf')

    def test_request_key_is_truncated_ascii_not_binary(self):
        request = '00000000-0000-4000-8000-000000000000'
        material = b'synthetic-native-secret'
        expected = hmac.new(request.encode(), material, hashlib.sha256).hexdigest()[:16].encode()
        key = derive_request_key(request, material)
        self.assertEqual(key, expected)
        self.assertEqual(len(key), 16)
        self.assertTrue(all(c in b'0123456789abcdef' for c in key))
        session = derive_request_key(request, material, 'synthetic-session-ecode')
        empty = derive_request_key(request, material, '')
        self.assertNotEqual(key, session)
        self.assertNotEqual(key, empty)
        self.assertNotEqual(session, empty)

    def test_request_key_rejects_missing_material_and_jni_nuls(self):
        for request, material, ecode in [('', b'synthetic', None),
                                         ('synthetic', b'', None),
                                         ('synthetic\0', b'synthetic', None),
                                         ('synthetic', b'synthetic', '\0')]:
            with self.assertRaises(ValueError):
                derive_request_key(request, material, ecode)

    def test_binary_native_material_preserves_embedded_nuls(self):
        # Command 0 decodes the carrier's hex key to raw bytes before joining.
        # Native HMAC receives the C++ string LENGTH, not strlen(material).
        material = b'example.package_SHA256_' + bytes(range(32)) + b'_synthetic-secret'
        request = 'synthetic-request'
        expected = hmac.new(request.encode(), material, hashlib.sha256).hexdigest()[:16].encode()
        self.assertEqual(derive_request_key(request, material), expected)
        params = {'a': 'synthetic.action', 'v': '1.0'}
        self.assertEqual(sign_request(params, material), hmac.new(
            material, canonical_sign_input(params).encode(), hashlib.sha256).hexdigest())

    def test_signature_canonicalisation_and_ciphertext_changes(self):
        params = {'a': 'synthetic.action', 'v': '1.0', 'postData': 'abc'}
        before = dict(params)
        expected = hmac.new(b'synthetic',
                            b'a=synthetic.action||postData=3cd24fb09001509828e17f72d6963f7d||v=1.0',
                            hashlib.sha256).hexdigest()
        self.assertEqual(sign_request(params, b'synthetic'), expected)
        self.assertEqual(params, before)
        changed = dict(params, postData='different-synthetic-body')
        self.assertNotEqual(sign_request(changed, b'synthetic'), expected)
        with self.assertRaises(ValueError):
            sign_request(params, b'')

    def test_et3_roundtrip_and_random_nonces(self):
        key = bytes(range(16))
        plaintext = '{"synthetic":"España"}'.encode()
        first = encrypt_et3(plaintext, key)
        second = encrypt_et3(plaintext, key)
        self.assertNotEqual(first, second)
        self.assertEqual(decrypt_et3(first, key), plaintext)

    def test_et3_rejects_tampering(self):
        key = bytes(16)
        packet = bytearray(base64.b64decode(encrypt_et3(b'synthetic', key)))
        packet[-1] ^= 1
        with self.assertRaises(InvalidTag):
            decrypt_et3(base64.b64encode(packet).decode(), key)

    def test_et3_rejects_bad_envelopes(self):
        with self.assertRaises(ValueError):
            decrypt_et3(base64.b64encode(bytes(27)).decode(), bytes(16))
        with self.assertRaises(ValueError):
            encrypt_et3(b'synthetic', bytes(16), nonce=bytes(11))

    def test_rsa_decimal_key_and_no_digest_fallback(self):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        numbers = private.public_key().public_numbers()
        digest = hashlib.md5(b'synthetic-password').hexdigest()
        ciphertext = encrypt_password_digest(digest, str(numbers.n), str(numbers.e))
        self.assertEqual(private.decrypt(bytes.fromhex(ciphertext), padding.PKCS1v15()),
                         digest.encode('ascii'))
        with self.assertRaises(ValueError):
            encrypt_password_digest(digest, 'not-a-decimal-modulus', '65537')


if __name__ == '__main__':
    unittest.main()
