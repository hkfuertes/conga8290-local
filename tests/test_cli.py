"""The packaged CLI has visible email, masked password and no phrase gate."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch

import recover_key


class CliTests(unittest.TestCase):
    def client(self, auth=2, reads=2):
        client = Mock(auth_attempts=auth, read_attempts=reads)
        client.list_homes.return_value = [{'gid': '123', 'name': 'Test home'}]
        client.list_robots.return_value = [{'id': 'synthetic-robot', 'name': 'Test robot'}]
        client.select_robot.return_value = {'id': 'synthetic-robot', 'local_key': '0123456789abcdef'}
        return client

    def test_default_recovery_needs_only_country_email_password_and_saves_id_key(self):
        client = self.client()
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'private'
            with patch('conga8290.oem_rootless_client.RootlessClient.from_package', return_value=client) as bootstrap, patch('recover_key.visible_input', side_effect=['34', 'synthetic@example.invalid']) as visible, patch('recover_key.masked_password', return_value='synthetic-password') as masked, redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(recover_key.main(['--output-dir', str(output)]), 0)
            bootstrap.assert_called_once_with('EU', auth_flow='oem-ui')
            self.assertEqual(visible.call_count, 2)
            masked.assert_called_once_with('Cecotec password: ')
            client.login.assert_called_once_with('synthetic-password', allow_new_session=True)
            value = json.loads(out.getvalue())
            path = Path(value['private_file'])
            self.assertEqual(json.loads(path.read_text()), {'id': 'synthetic-robot', 'local_key': '0123456789abcdef'})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            self.assertEqual(value['status'], 'robot_key_recovered')
        client.close.assert_called_once()
        self.assertIn('"id": "synthetic-robot"', err.getvalue())
        self.assertIn('Tuya Local credentials (do not share this output):', err.getvalue())
        self.assertIn('"local_key": "0123456789abcdef"', err.getvalue())
        self.assertNotIn('0123456789abcdef', out.getvalue())
        # The old Spanish confirmation phrases must remain absent.
        for secret in ['synthetic-password', 'NUEVA SESION', 'NUEVA_SESION']:
            self.assertNotIn(secret, out.getvalue() + err.getvalue())

    def test_check_never_prompts_or_authenticates(self):
        client = self.client(0, 0)
        out = io.StringIO()
        with patch('conga8290.oem_rootless_client.RootlessClient.from_package', return_value=client), patch('recover_key.visible_input') as visible, patch('recover_key.masked_password') as masked, redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(recover_key.main(['--check']), 0)
        visible.assert_not_called()
        masked.assert_not_called()
        client.email_token.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())['status'], 'offline_ready')

    def test_token_only_never_prompts_for_password(self):
        client = self.client(1, 0)
        with patch('conga8290.oem_rootless_client.RootlessClient.from_package', return_value=client), patch('recover_key.visible_input', side_effect=['', 'synthetic@example.invalid']), patch('recover_key.masked_password') as masked, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(recover_key.main(['--token-only']), 0)
        client.email_token.assert_called_once_with('34', 'synthetic@example.invalid')
        masked.assert_not_called()
        client.login.assert_not_called()

    def test_failure_never_echoes_arbitrary_details_or_retries_login(self):
        from conga8290.oem_readonly_api import OemReadError
        client = self.client(2, 0)
        client.login.side_effect = OemReadError('credentials_rejected', safe_diagnostics={'msg': 'synthetic-private-secret'})
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch('conga8290.oem_rootless_client.RootlessClient.from_package', return_value=client), patch('recover_key.visible_input', side_effect=['34', 'synthetic@example.invalid']), patch('recover_key.masked_password', return_value='synthetic-password'), redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(recover_key.main(['--output-dir', str(Path(directory) / 'private')]), 1)
        self.assertEqual(json.loads(out.getvalue())['failure_category'], 'credentials_rejected')
        client.login.assert_called_once()
        client.list_homes.assert_not_called()
        client.close.assert_called_once()
        self.assertNotIn('synthetic-private-secret', out.getvalue() + err.getvalue())
        self.assertNotIn('synthetic-password', out.getvalue() + err.getvalue())

    def test_accidental_password_arguments_are_not_echoed(self):
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit):
            recover_key.main(['--unknown-credential', 'synthetic-argument-secret'])
        self.assertNotIn('synthetic-argument-secret', err.getvalue())

    def test_all_account_arguments_skip_prompts_without_printing_account_secrets(self):
        client = self.client()
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch('conga8290.oem_rootless_client.RootlessClient.from_package', return_value=client), patch('recover_key.visible_input') as visible, patch('recover_key.masked_password') as masked, redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(recover_key.main(['-c', '34', '-u', 'synthetic@example.invalid', '-p', 'synthetic-password', '--output-dir', directory]), 0)
        visible.assert_not_called()
        masked.assert_not_called()
        client.email_token.assert_called_once_with('34', 'synthetic@example.invalid')
        client.login.assert_called_once_with('synthetic-password', allow_new_session=True)
        self.assertIn('Warning: -p', err.getvalue())
        self.assertNotIn('synthetic-password', out.getvalue() + err.getvalue())
        self.assertNotIn('synthetic@example.invalid', out.getvalue() + err.getvalue())

    def test_console_credentials_escape_controls_and_exclude_other_fields(self):
        client = self.client()
        client.select_robot.return_value = {'id': 'synthetic-robot\x1b[31m', 'local_key': '0123456789abcdef',
                                           'sid': 'synthetic-session-secret', 'token': 'synthetic-token-secret'}
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch('conga8290.oem_rootless_client.RootlessClient.from_package', return_value=client), patch('recover_key.visible_input', side_effect=['34', 'synthetic@example.invalid']), patch('recover_key.masked_password', return_value='synthetic-password'), redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(recover_key.main(['--output-dir', directory]), 0)
        self.assertIn('synthetic-robot\\u001b[31m', err.getvalue())
        self.assertIn('0123456789abcdef', err.getvalue())
        self.assertNotIn('\x1b', err.getvalue())
        for secret in ['synthetic-session-secret', 'synthetic-token-secret', 'synthetic-password']:
            self.assertNotIn(secret, out.getvalue() + err.getvalue())

    def test_failed_private_save_does_not_display_robot_credentials(self):
        client = self.client()
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch('conga8290.oem_rootless_client.RootlessClient.from_package', return_value=client), patch('recover_key.visible_input', side_effect=['34', 'synthetic@example.invalid']), patch('recover_key.masked_password', return_value='synthetic-password'), patch('recover_key.save_robot', side_effect=OSError('synthetic-disk-secret')), redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(recover_key.main(['--output-dir', directory]), 1)
        for secret in ['0123456789abcdef', 'synthetic-disk-secret', 'synthetic-password']:
            self.assertNotIn(secret, out.getvalue() + err.getvalue())
        client.close.assert_called_once()

    def test_user_country_arguments_still_prompt_for_password(self):
        client = self.client()
        with tempfile.TemporaryDirectory() as directory, patch('conga8290.oem_rootless_client.RootlessClient.from_package', return_value=client), patch('recover_key.visible_input') as visible, patch('recover_key.masked_password', return_value='synthetic-password') as masked, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(recover_key.main(['--user', 'synthetic@example.invalid', '--country', '34', '--output-dir', directory]), 0)
        visible.assert_not_called()
        masked.assert_called_once()

    def test_credentials_in_offline_or_password_in_token_mode_are_rejected_privately(self):
        for argv in [['--check', '-u', 'synthetic@example.invalid'], ['--check', '-p', 'synthetic-secret'], ['--check', '-c', '34'], ['--token-only', '--password', 'synthetic-secret']]:
            err = io.StringIO()
            with patch('conga8290.oem_rootless_client.RootlessClient.from_package') as bootstrap, redirect_stderr(err), self.assertRaises(SystemExit):
                recover_key.main(argv)
            bootstrap.assert_not_called()
            self.assertNotIn('synthetic-secret', err.getvalue())
            self.assertNotIn('synthetic@example.invalid', err.getvalue())

    def test_invalid_country_argument_stops_before_network_without_echo(self):
        client = self.client(0, 0)
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch('conga8290.oem_rootless_client.RootlessClient.from_package', return_value=client), patch('recover_key.visible_input') as visible, redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(recover_key.main(['-c', '+invalid-country', '-u', 'synthetic@example.invalid', '--output-dir', directory]), 1)
        visible.assert_not_called()
        client.email_token.assert_not_called()
        self.assertIn('Invalid country calling code', err.getvalue())
        self.assertNotIn('+invalid-country', out.getvalue() + err.getvalue())

    def test_private_capture_never_overwrites_existing_file(self):
        robot = {'id': 'synthetic', 'local_key': '0123456789abcdef'}
        with tempfile.TemporaryDirectory() as directory, patch('recover_key.time.time_ns', return_value=123):
            path = recover_key.save_robot(Path(directory), robot)
            with self.assertRaises(FileExistsError):
                recover_key.save_robot(Path(directory), robot)
            self.assertEqual(json.loads(path.read_text()), robot)

    def test_unowned_or_permissive_output_stops_before_account_access(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'unsafe'
            output.mkdir(mode=0o755)
            output.chmod(0o755)
            with patch('conga8290.oem_rootless_client.RootlessClient.from_package') as bootstrap, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(recover_key.main(['--output-dir', str(output)]), 1)
            bootstrap.assert_not_called()

    def test_selection_sanitizes_terminal_control_sequences(self):
        err = io.StringIO()
        with redirect_stderr(err), patch('recover_key.visible_input', return_value='2'):
            chosen = recover_key.choose([{'name': '\x1b[31mFirst\n'}, {'name': 'Second'}], 'Robots')
        self.assertEqual(chosen['name'], 'Second')
        self.assertNotIn('\x1b', err.getvalue())
