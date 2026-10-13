"""Bounded certificate extraction from the supplied APK signing block.

Extraction is NOT cryptographic verification of the APK signing scheme. The
caller must separately enforce artifact identity; certificates are public data.
"""
import hashlib
import struct


def lp32(data, offset=0):
    if offset < 0 or offset + 4 > len(data):
        raise ValueError('truncated_signing_record')
    size = struct.unpack_from('<I', data, offset)[0]
    start, end = offset + 4, offset + 4 + size
    if end > len(data):
        raise ValueError('truncated_signing_record')
    return data[start:end], end


def signing_certificate(apk):
    eocd = apk.rfind(b'PK\x05\x06', max(0, len(apk) - 65557))
    if eocd < 0 or eocd + 22 > len(apk):
        raise ValueError('apk_eocd_missing')
    comment_size = struct.unpack_from('<H', apk, eocd + 20)[0]
    if eocd + 22 + comment_size != len(apk):
        raise ValueError('apk_eocd_not_at_end')
    directory = struct.unpack_from('<I', apk, eocd + 16)[0]
    if not 24 <= directory <= eocd or apk[directory - 16:directory] != b'APK Sig Block 42':
        raise ValueError('apk_signing_block_missing')
    size = struct.unpack_from('<Q', apk, directory - 24)[0]
    start = directory - size - 8
    if start < 0 or size < 24 or struct.unpack_from('<Q', apk, start)[0] != size:
        raise ValueError('apk_signing_block_size_invalid')
    position, end = start + 8, directory - 24
    schemes = {}
    while position < end:
        if position + 12 > end:
            raise ValueError('truncated_signing_pair')
        pair_size = struct.unpack_from('<Q', apk, position)[0]
        pair_end = position + 8 + pair_size
        if pair_size < 4 or pair_end > end:
            raise ValueError('truncated_signing_pair')
        scheme = struct.unpack_from('<I', apk, position + 8)[0]
        if scheme in schemes:
            raise ValueError('duplicate_signing_scheme')
        schemes[scheme] = apk[position + 12:pair_end]
        position = pair_end
    scheme = 0x7109871a if 0x7109871a in schemes else 0xf05368c0
    if scheme not in schemes:
        raise ValueError('supported_signing_scheme_missing')
    signers, _ = lp32(schemes[scheme])
    signer, remaining = lp32(signers)
    if remaining != len(signers):
        raise ValueError('multiple_apk_signers_not_supported')
    signed_data, _ = lp32(signer)
    _, position = lp32(signed_data)  # digest records
    certificates, _ = lp32(signed_data, position)
    certificate, _ = lp32(certificates)
    if not 32 <= len(certificate) <= 16384:
        raise ValueError('invalid_signing_certificate_size')
    return certificate


def native_certificate_fingerprint(certificate):
    # cloud-native-context-material.asm: MessageDigest SHA256 -> uppercase hex,
    # then append ':' after each pair except the last. Not an MD5 fingerprint.
    digest = hashlib.sha256(certificate).hexdigest().upper()
    return ':'.join(digest[i:i + 2] for i in range(0, len(digest), 2)).encode('ascii')
