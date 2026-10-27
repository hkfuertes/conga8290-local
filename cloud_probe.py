#!/usr/bin/env python3
"""OEM cloud probe: login, persist session, then arbitrary read-only API calls.

Usage:
  python3 cloud_probe.py <email>              # login + save private/session.json + probes
  python3 cloud_probe.py --reuse              # reuse saved session (no password)

Session is a bearer token: keep private/session.json as secret as the password.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

XAPK = Path('/tmp/xapk/cecotec.xapk')
PW_FILE = Path('/tmp/pw.txt')
SESSION_FILE = Path(__file__).parent / 'private' / 'session.json'

PROBES = [
    ('m.life.device.upgrade.list', '1.1', lambda ctx: {'gid': str(ctx['gid'])}),
    ('thing.m.dev.storage.config.get', '1.0', lambda ctx: {'type': 'Common', 'devId': ctx['devId']}),
    # expediente completo del robot (uiId/panelId para el bundle RN)
    ('m.life.my.group.device.list', '2.2', lambda ctx: {'gid': ctx['gid']}),
    ('m.life.app.server.list', '1.0', lambda ctx: {'gid': str(ctx['gid'])}),
    ('m.life.app.server.list', '2.0', lambda ctx: {'gid': str(ctx['gid'])}),
]


def raw_call(client, method, version, payload):
    """Generic ET3-signed m.life.* call (mirrors build_candidate_request)."""
    from conga8290.oem_candidate_request import base_request_body, normalize_endpoint
    from conga8290.cloud_protocol import derive_request_key, encrypt_et3, sign_request
    body = base_request_body(client.context, client.ch_key)
    body.update(a=method, v=version, sid=client.session['sid'])
    key = derive_request_key(body['requestId'], client.material, client.session['ecode'])
    data = json.dumps(payload, separators=(',', ':')).encode()
    body['postData'] = encrypt_et3(data, key)
    body['sign'] = sign_request(body, client.material)
    # transport mirrors oem_readonly_api._https_exchange
    from urllib.parse import urlencode
    from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler
    import ssl
    req = Request(normalize_endpoint(client.session['mobile_api_url']), data=urlencode(body).encode(), method='POST',
                  headers={'Content-Type': 'application/x-www-form-urlencoded',
                           'Accept-Encoding': 'gzip'})
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(req, timeout=25) as r:
        raw = r.read(4 * 1048576)
    envelope = json.loads(raw)
    if envelope.get('success') is not True:
        print('   server says:', envelope.get('errorCode'), '|', envelope.get('errorMsg'))
    from conga8290.oem_readonly_api import decode_result
    return decode_result(envelope, key)


def show(tag, fn):
    try:
        result = fn()
        text = json.dumps(result, ensure_ascii=False, indent=1)
        open('/tmp/probe_last.json', 'w').write(text)
        print(f'--- {tag}: OK (full → /tmp/probe_last.json) ---\n{text[:3000]}\n')
    except Exception as exc:
        detail = getattr(exc, 'category', None) or type(exc).__name__
        status = getattr(exc, 'http_status', '')
        diag = getattr(exc, 'safe_diagnostics', '')
        print(f'--- {tag}: {detail} {status} {diag} ---\n')


def main():
    from conga8290.assets import prepare_xapk
    from conga8290.oem_rootless_client import RootlessClient

    prepare_xapk(XAPK)
    client = RootlessClient.from_package('EU', auth_flow='oem-ui')

    if '--reuse' in sys.argv or '--call' in sys.argv:
        saved = json.loads(SESSION_FILE.read_text())
        client.session = {'sid': saved['sid'], 'ecode': saved['ecode'],
                          'mobile_api_url': saved['mobile_api_url']}
        ctx = saved
        print(f'session reused (saved {saved["ts"]}) robot={ctx["devId"]}')
    else:
        email = sys.argv[1]
        password = PW_FILE.read_text().strip()
        print('[1] token…'); client.email_token('34', email)
        print('[2] login…'); client.login(password, allow_new_session=True)
        print('[3] homes…')
        homes = client.list_homes()
        print('    homes:', [h.get('name') for h in homes])
        robots = client.list_robots(homes[0]['gid'])
        print('    robots:', [(r['id'], r.get('name')) for r in robots])
        sel = client.select_robot(robots[0]['id'])
        print('    local_key matches tuya_local:', sel['local_key'] == 'REDACTED_LOCAL_KEY')
        ctx = {'devId': sel['id'], 'gid': homes[0]['gid']}
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SESSION_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps({'sid': client.session['sid'],
                                   'ecode': client.session['ecode'],
                                   'mobile_api_url': client.session['mobile_api_url'],
                                   'devId': ctx['devId'], 'gid': ctx['gid'],
                                   'ts': __import__('time').strftime('%F %T')}))
        os.chmod(tmp, 0o600); tmp.rename(SESSION_FILE)
        print(f'    session saved → {SESSION_FILE}')

    if '--export-native' in sys.argv:
        # dump everything the Go binary (native/conga) needs: no XAPK/unicorn there
        out = {'lan': {'device_id': ctx['devId'], 'ip': '192.168.0.239',
                       'local_key': 'REDACTED_LOCAL_KEY'},
               'cloud': {'sid': client.session['sid'], 'ecode': client.session['ecode'],
                         'api_url': client.session['mobile_api_url'],
                         'gid': int(ctx['gid']), 'dev_id': ctx['devId'],
                         'ch_key': client.ch_key, 'material_hex': client.material.hex(),
                         'client_id': client.context['mAppId'],
                         'app_version': client.context['mAppVersion'],
                         'ttid': client.context['mTtid'],
                         'phone_device_id': client.context['mDeviceId']}}
        target = SESSION_FILE.parent / 'native.json'
        tmp = target.with_suffix('.tmp')
        tmp.write_text(json.dumps(out))
        os.chmod(tmp, 0o600); tmp.rename(target)
        print(f'native config exported → {target}')
        return

    if '--call' in sys.argv:
        i = sys.argv.index('--call')
        method, ver = sys.argv[i + 1], sys.argv[i + 2]
        payload = json.loads(sys.argv[i + 3])
        show(f'{method} v{ver}', lambda: raw_call(client, method, ver, payload))
        return
    for method, version, build in PROBES:
        show(f'{method} v{version} {build.__name__}',
             lambda m=method, v=version, b=build: raw_call(client, m, v, b(ctx)))


if __name__ == '__main__':
    main()
