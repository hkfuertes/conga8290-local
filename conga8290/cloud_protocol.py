"""Offline primitives reconstructed from Cecotec 1.2.9's shipped ThingClips SDK.

NOT a working cloud-login client. Native key-material initialisation and the
actual OEM account flow still need evidence. No HTTP, storage or logging.
See docs/cloud-bootstrap.md and evidence/decompiled/cloud-*.java.
"""
import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ThingApiSignManager.java:23. The current SDK does not sign every parameter.
SIGNED_FIELDS = frozenset([
    'a', 'v', 'lat', 'lon', 'lang', 'deviceId', 'appVersion', 'ttid',
    'isH5', 'h5Token', 'os', 'clientId', 'postData', 'time', 'requestId',
    'et', 'n4h5', 'sid', 'chKey', 'sp',
])


def postdata_hash(postdata):
    """SDK's rearranged MD5 hex, NOT ordinary MD5 or base64."""
    if not isinstance(postdata, str):
        raise ValueError('postdata_must_be_string')
    if not postdata:
        return ''
    digest = hashlib.md5(postdata.encode('utf-8')).hexdigest()
    return digest[8:16] + digest[:8] + digest[24:] + digest[16:24]


def canonical_sign_input(params):
    """Prepare signature input without mutating params or computing a signature.

    postData must already be the EXACT transmitted plaintext/ciphertext string.
    This is not an API key, native signer, or a JSON serializer.
    """
    parts = []
    for name in sorted(SIGNED_FIELDS):
        value = params.get(name)
        if value is None or value == '':
            continue
        if not isinstance(value, str):
            raise ValueError('signed_values_must_be_strings')
        if name == 'postData':
            value = postdata_hash(value)
        parts.append(name + '=' + value)
    return '||'.join(parts)


def derive_request_key(request_id, native_key_material, ecode=None):
    """SDK AES key: first 16 ASCII hex chars of HMAC-SHA256(requestId, material).

    The requestId is the HMAC KEY, not its message. Session requests append
    '_' + ecode to the native material. None and empty ecode differ in the SDK.
    Whole material initialisation remains unverified; do NOT substitute the
    robot's local_key or raw appSecret. Compared with the real ARM64 function
    in offline emulation using synthetic material. Only requestId/ecode use
    JNI strings; initialised material is a length-counted binary C++ string.
    """
    if (not isinstance(request_id, str) or not request_id or not request_id.isascii()
            or '\0' in request_id):
        raise ValueError('nonempty_ascii_request_id_required')
    if not isinstance(native_key_material, bytes) or not native_key_material:
        raise ValueError('nonempty_native_key_material_required')
    message = native_key_material
    if ecode is not None:
        if not isinstance(ecode, str) or not ecode.isascii() or '\0' in ecode:
            raise ValueError('ascii_session_ecode_required')
        message += b'_' + ecode.encode('ascii')
    return hmac.new(request_id.encode('ascii'), message, hashlib.sha256).hexdigest()[:16].encode('ascii')


def sign_request(params, native_key_material):
    """Reconstruct the SDK's final HMAC step with supplied, INITIALISED material.

    Static command-1 branch (0x153bc..0x15468); native HMAC itself verified against
    RFC 4231 in emulation. Not validation of command-1 initialisation, OEM material
    or acceptance by a cloud server. postData must be the transmitted body string.
    """
    if not isinstance(native_key_material, bytes) or not native_key_material:
        raise ValueError('nonempty_native_key_material_required')
    message = canonical_sign_input(params).encode('utf-8')
    return hmac.new(native_key_material, message, hashlib.sha256).hexdigest()


def encrypt_et3(plaintext, key, *, nonce=None):
    """Base64(nonce[12] + AES-GCM ciphertext + tag[16]); no key derivation.

    Omit nonce in real use. Supplying one exists only for independent fixtures;
    never reuse a nonce with the same key.
    """
    if not isinstance(plaintext, bytes) or not isinstance(key, bytes):
        raise ValueError('plaintext_and_key_must_be_bytes')
    nonce = os.urandom(12) if nonce is None else nonce
    if not isinstance(nonce, bytes) or len(nonce) != 12:
        raise ValueError('nonce_must_be_12_bytes')
    ciphertext_tag = AESGCM(key).encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + ciphertext_tag).decode('ascii')


def decrypt_et3(encoded, key):
    """Authenticate/decrypt the SDK envelope; don't decode/decompress responses."""
    if not isinstance(encoded, str) or not isinstance(key, bytes):
        raise ValueError('encoded_must_be_string_and_key_bytes')
    packet = base64.b64decode(encoded, validate=True)
    if len(packet) < 28:
        raise ValueError('envelope_too_short')
    return AESGCM(key).decrypt(packet[:12], packet[12:], None)


def encrypt_password_digest(digest_hex, modulus_decimal, exponent_decimal):
    """RSA PKCS#1 v1.5 over the MD5 hex string, using token's DECIMAL n/e.

    Static SDK reconstruction; no live login verified. Unlike the SDK's error
    fallback, this helper never silently downgrades to an unencrypted digest.
    """
    if (not isinstance(digest_hex, str) or len(digest_hex) != 32
            or any(c not in '0123456789abcdef' for c in digest_hex)):
        raise ValueError('lowercase_md5_hex_required')
    if not all(isinstance(v, str) and v.isascii() and v.isdecimal()
               for v in [modulus_decimal, exponent_decimal]):
        raise ValueError('decimal_public_key_components_required')
    public = rsa.RSAPublicNumbers(int(exponent_decimal), int(modulus_decimal)).public_key()
    return public.encrypt(digest_hex.encode('ascii'), padding.PKCS1v15()).hex()
