"""PC-only, read-only OEM bootstrap candidate from the supplied APK.

NO login/network, user credentials, phone/root, storage of application material
or device-key retrieval. Native command-0 validation preceding its join segment
is not executed here; this cannot prove cloud acceptance or whole OEM init.
"""
import argparse
import hashlib
import hmac
import json
import re
import zipfile

from .apk_signing_identity import signing_certificate, native_certificate_fingerprint
from .native_crypto_fixture import NativeFixture
from .native_key_carrier import KeyCarrierFixture
from .native_oem_material import MaterialFixture
from .packaged_oem_identity import APK, packaged_registration


def derive_candidate():
    app_id, app_secret = packaged_registration()  # Pins full APK hash first.
    certificate = signing_certificate(APK.read_bytes())
    fingerprint = native_certificate_fingerprint(certificate)
    with zipfile.ZipFile(APK) as archive:
        content = archive.read('assets/t_s.bmp')
    parser = KeyCarrierFixture()
    status, values = parser.read_keys(app_id.encode('ascii'), content)
    if status or len(values) != 1 or re.fullmatch(b'[0-9A-Fa-f]{64}', values[0]) is None:
        raise ValueError('unexpected_carrier_result')
    decoded_key = bytes.fromhex(values[0].decode('ascii'))
    package = b'es.cecotec.forceclima'  # Identity of this exact pinned artifact.
    components = [package, fingerprint, decoded_key, app_secret.encode('ascii')]
    material = b'_'.join(components)
    native = MaterialFixture()
    native.constructors()
    if native.join_segment(*components) != material:
        raise ValueError('native_material_join_mismatch')
    # Returned privately to callers, not serialized. Not a local_key.
    return app_id, material


def validate_candidate():
    app_id, material = derive_candidate()
    fixture = NativeFixture()
    request = b'00000000-0000-4000-8000-000000000000'
    cases = 0
    for ecode in [None, b'', b'synthetic-session-ecode']:
        message = material if ecode is None else material + b'_' + ecode
        expected = hmac.new(request, message, hashlib.sha256).hexdigest()[:16].encode()
        if fixture.native_request_key(request, material, ecode) != expected:
            raise ValueError('candidate_native_request_key_mismatch')
        cases += 1
    canonical = b'a=synthetic.action||v=1.0'
    native_mac = fixture.native_hmac(material, canonical)
    if native_mac != hmac.new(material, canonical, hashlib.sha256).digest():
        raise ValueError('candidate_native_hmac_mismatch')
    return {'execution': 'bounded_offline_arm64', 'source': 'pinned_supplied_apk',
            'packaged_app_id_length': len(app_id), 'candidate_material_length': len(material),
            'carrier_returned_one_hex_key': True, 'native_join_segment_matches': True,
            'candidate_native_request_key_cases_match': cases,
            'candidate_native_hmac_matches': True, 'whole_command_zero_verified': False,
            'effective_account_namespace_verified': False, 'cloud_login_verified': False,
            'robot_local_key_recovered': False, 'network_or_phone_access': False,
            'registration_material_or_derived_values_saved': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', help='Optional NEW redacted evidence JSON')
    args = parser.parse_args()
    result = validate_candidate()
    if args.evidence:
        with open(args.evidence, 'x') as handle:
            json.dump(result, handle, indent=2)
            handle.write('\n')
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never include arbitrary exception messages carrying native values.
        print(json.dumps({'status': 'not_validated', 'error_type': type(exc).__name__,
                          'details_suppressed': True}))
        raise SystemExit(1)
