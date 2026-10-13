#!/usr/bin/env python3
"""Recupera ID/local_key del Conga 8290 y guárdalos privadamente para Tuya Local.

Sin Android/root. País/email visibles; contraseña con *. Un token, un login y dos
listados como máximo. Invocar este script autoriza ese login: puede alertar como
dispositivo nuevo o sustituir una sesión. Sin confirmación escrita adicional.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from conga8290.terminal import masked_password, visible_input

ROOT = Path(__file__).resolve().parent


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Argumentos no válidos. Usa --help.\n')


def label(value, fallback):
    if not isinstance(value, str):
        return fallback
    cleaned = ''.join(c for c in value if c.isprintable())[:80]
    return cleaned or fallback


def choose(items, title):
    if not items:
        raise ValueError('no_matching_items')
    if len(items) == 1:
        print(f'{title}: {label(items[0].get("name"), "1")}', file=sys.stderr)
        return items[0]
    print(title, file=sys.stderr)
    for index, item in enumerate(items, 1):
        suffix = label(item.get('id'), '')[-6:]
        identity = f' (…{suffix})' if suffix else ''
        print(f'  {index}. {label(item.get("name"), str(index))}{identity}', file=sys.stderr)
    answer = visible_input('Número: ').strip()
    if not answer.isascii() or not answer.isdigit() or not 1 <= int(answer) <= len(items):
        raise ValueError('invalid_local_selection')
    return items[int(answer) - 1]


def save_robot(directory, robot):
    from conga8290.assets import owned_directory
    dev_id, key = robot.get('id'), robot.get('local_key')
    if (not isinstance(dev_id, str) or not dev_id or not isinstance(key, str) or
            not key.isascii() or len(key) != 16):
        raise ValueError('invalid_selected_robot_credentials')
    owned_directory(directory)
    output = directory / f'robot-connection-{time.time_ns()}.json'
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump({'id': dev_id, 'local_key': key}, handle, indent=2)
        handle.write('\n')
    return output


def main(argv=None):
    parser = PrivateParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', action='store_true', help='Solo bootstrap offline; sin cuenta ni red')
    modes.add_argument('--token-only', action='store_true', help='Solo token/RSA; no contraseña ni login')
    parser.add_argument('-u', '--user', help='Email Cecotec; si se omite, se pregunta localmente')
    parser.add_argument('-p', '--password', help='Contraseña (visible en historial/argumentos); preferir prompt')
    parser.add_argument('-c', '--country', help='Prefijo de país, sin + ni 00 (España: 34); si se omite, se pregunta')
    parser.add_argument('--xapk', type=Path, help='Importar XAPK compatible local, sin subirlo a ningún sitio')
    parser.add_argument('--region', choices=['EU', 'AZ', 'IN', 'RU'], default='EU')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'private')
    args = parser.parse_args(argv)
    if (args.check and any(value is not None for value in [args.user, args.password, args.country]) or
            args.token_only and args.password is not None):
        parser.error('credentials_not_used_by_selected_mode')
    password_argument = args.password
    args.password = None
    previous_umask = os.umask(0o077)
    client, stage = None, 'assets'
    result = {'android_or_root_used': False, 'session_saved': False,
              'robot_commands_sent': False, 'auth_attempts': 0, 'read_attempts': 0}
    try:
        if args.xapk:
            from conga8290.assets import prepare_xapk
            prepare_xapk(args.xapk.expanduser())
        from conga8290.assets import owned_directory
        from conga8290.oem_login_payload import email_token_payload
        from conga8290.oem_rootless_client import RootlessClient
        if not args.check and not args.token_only:
            owned_directory(args.output_dir.expanduser())
        stage = 'offline_bootstrap'
        print('Preparando cliente Cecotec…', file=sys.stderr)
        client = RootlessClient.from_package(args.region, auth_flow='oem-ui')
        if args.check:
            result['status'] = 'offline_ready'
        else:
            if password_argument is not None:
                print('Aviso: -p expone la contraseña en historial/argumentos del proceso y metadatos Docker; se recomienda el prompt.', file=sys.stderr)
            if not args.token_only:
                print('Aviso: este login puede generar una alerta de dispositivo nuevo o afectar la sesión de la app.', file=sys.stderr)
            stage = 'account_input'
            country = args.country.strip() if args.country is not None else visible_input('Prefijo de país [34]: ').strip() or '34'
            email = (args.user if args.user is not None else visible_input('Email Cecotec: ')).strip()
            args.user = None
            email_token_payload(country, email)
            stage = 'username_token'
            print('Obteniendo token/RSA…', file=sys.stderr)
            client.email_token(country, email)
            del email, country
            if args.token_only:
                result['status'] = 'token_validated_no_login'
            else:
                stage = 'password_input'
                password = password_argument if password_argument is not None else masked_password('Contraseña Cecotec: ')
                password_argument = None
                stage = 'login'
                print('Iniciando sesión…', file=sys.stderr)
                try:
                    client.login(password, allow_new_session=True)
                finally:
                    del password
                stage = 'homes'
                home = choose(client.list_homes(), 'Casa')
                stage = 'robots'
                robots = client.list_robots(home['gid'])
                if not robots:
                    raise ValueError('conga_8290_not_found')
                robot = choose(robots, 'Conga 8290')
                stage = 'private_output'
                output = save_robot(args.output_dir.expanduser(), client.select_robot(robot['id']))
                result.update(status='robot_key_recovered', private_file=str(output), lan_protocol='3.3')
                print(f'ID y clave guardados en {output}. No se ha modificado Home Assistant.', file=sys.stderr)
    except (Exception, KeyboardInterrupt) as exc:
        result.update(status='not_completed', safe_stage=stage, error_type=type(exc).__name__)
        category = getattr(exc, 'category', None)
        categories = {'session_rejected', 'signature_rejected', 'human_verification_required',
                      'application_integrity_rejected', 'application_identity_rejected',
                      'request_parameters_rejected', 'api_permission_rejected',
                      'unclassified_server_rejection', 'http_read_rejected', 'credentials_rejected',
                      'account_rejected', 'account_or_rate_limited', 'auth_token_rejected', 'service_unavailable'}
        if category in categories:
            result['failure_category'] = category
        hints = {
            'explicit_country_code_required': 'País no válido: solo dígitos, sin + ni 00.',
            'local_email_required': 'Email no válido: completo y sin espacios.',
            'conga_8290_not_found': 'No hay un Conga 8290 compatible en la casa seleccionada.',
            'interactive_terminal_required': 'Ejecuta el script en un terminal interactivo.',
            'unsupported_cecotec_artifact': 'El XAPK no corresponde a la versión exacta compatible.',
            'private_directory_must_be_owned_mode_0700': 'La carpeta privada debe ser tuya, sin symlinks y con permisos 0700.',
        }
        hint = hints.get(str(exc)) if type(exc) is ValueError else None
        if hint:
            print(hint, file=sys.stderr)
        elif isinstance(exc, FileNotFoundError) and stage in ['assets', 'offline_bootstrap']:
            print('Faltan recursos locales. Importa el XAPK compatible con --xapk (ver README).', file=sys.stderr)
        elif isinstance(exc, ImportError):
            print('Instala las dependencias con pip install -r requirements.txt.', file=sys.stderr)
        else:
            print('Proceso detenido, sin reintentos. No se muestran detalles privados.', file=sys.stderr)
    finally:
        password_argument = None
        args.user = None
        if client is not None:
            result.update(auth_attempts=client.auth_attempts, read_attempts=client.read_attempts)
            client.close()
        os.umask(previous_umask)
    print(json.dumps(result))
    return 1 if result['status'] == 'not_completed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
