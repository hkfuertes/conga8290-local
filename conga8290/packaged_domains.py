"""Offline reconstruction of DomainHelper's packaged domain configuration.

Returns ONLY public region/HTTPS mobile-API candidates, not the complete config
or its embedded encryption key. No network and no effective-account claim.
"""
import base64
import hashlib
import json
from urllib.parse import urlsplit
import zipfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from .packaged_oem_identity import APK, APK_SHA256


def decode_domains(encoded):
    if not isinstance(encoded, bytes) or len(encoded) > 0x100000:
        raise ValueError('invalid_domain_config_size')
    raw = base64.b64decode(b''.join(encoded.split()), validate=True)
    if len(raw) < 49:
        raise ValueError('truncated_domain_config')
    # DomainHelper.java:187-195 and AESCTRUtil.java:81-86.
    decryptor = Cipher(algorithms.AES(raw[:32]), modes.CTR(raw[32:48])).decryptor()
    clear = (decryptor.update(raw[48:]) + decryptor.finalize()).decode('utf-8')
    tree = json.loads(clear.replace('\\', ''))  # Exact SDK normalization.
    if not isinstance(tree, list) or not 1 <= len(tree) <= 32:
        raise ValueError('unsupported_domain_config_shape')
    rows, regions = [], set()
    for item in tree:
        region = item.get('region')
        config = item.get('regionConfig', {})
        url = config.get('mobileApiUrl')
        if not isinstance(region, str) or region in regions or not isinstance(url, str):
            raise ValueError('invalid_domain_entry')
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
                parsed.password or parsed.port not in [None, 443] or
                parsed.path not in ['', '/'] or parsed.query or parsed.fragment):
            raise ValueError('unsupported_mobile_api_url')
        regions.add(region)
        rows.append({'region': region, 'default': item.get('defaultConfig') is True,
                     'mobile_api_url': url, 'region_code': config.get('regionCode')})
    return rows


def packaged_domains():
    if hashlib.sha256(APK.read_bytes()).hexdigest() != APK_SHA256:
        raise ValueError('unexpected_apk_artifact')
    with zipfile.ZipFile(APK) as archive:
        if 'assets/t_cdc.tcfg' in archive.namelist():
            raise ValueError('custom_domain_override_requires_separate_analysis')
        return decode_domains(archive.read('assets/thing_domains_v1/regions'))
