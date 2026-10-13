"""Masked password input restores terminal settings even after cancellation."""
import io
import unittest
from unittest.mock import patch, Mock

from conga8290.terminal import masked_password, visible_input


class TerminalTests(unittest.TestCase):
    def terminal(self, text):
        stream = Mock()
        stream.isatty.return_value = True
        stream.fileno.return_value = 12
        stream.read.side_effect = list(text)
        return stream

    def test_only_password_gets_stars_and_backspace_never_echoes_it(self):
        import termios
        attrs = [0, 0, 0, termios.ECHO | termios.ICANON, 0, 0, [0] * 32]
        out = io.StringIO()
        with patch('conga8290.terminal.sys.stdin', self.terminal('ab\x7fc\n')), patch('conga8290.terminal.sys.stderr', out), patch.object(out, 'isatty', return_value=True), patch('termios.tcgetattr', return_value=attrs), patch('termios.tcsetattr') as restore:
            self.assertEqual(masked_password('Password: '), 'ac')
        self.assertIn('**', out.getvalue())
        self.assertNotIn('ac', out.getvalue())
        self.assertEqual(restore.call_args.args[2], attrs)
        self.assertFalse(restore.call_args_list[0].args[2][3] & termios.ECHO)

    def test_eof_and_keyboard_interrupt_restore_echo(self):
        import termios
        attrs = [0, 0, 0, termios.ECHO | termios.ICANON, 0, 0, [0] * 32]
        for trigger in ['\x04', KeyboardInterrupt()]:
            stream = self.terminal('')
            stream.read.side_effect = [trigger] if isinstance(trigger, str) else trigger
            out = io.StringIO()
            with patch('conga8290.terminal.sys.stdin', stream), patch('conga8290.terminal.sys.stderr', out), patch.object(out, 'isatty', return_value=True), patch('termios.tcgetattr', return_value=attrs), patch('termios.tcsetattr') as restore:
                with self.assertRaises((EOFError, KeyboardInterrupt)):
                    masked_password('Password: ')
            self.assertEqual(restore.call_args.args[2], attrs)

    def test_noninteractive_password_never_falls_back_to_echo(self):
        with patch('conga8290.terminal.sys.stdin.isatty', return_value=False):
            with self.assertRaises(ValueError):
                masked_password('Password: ')

    def test_email_uses_visible_input_not_password_reader(self):
        out = io.StringIO()
        with patch('conga8290.terminal.sys.stdin.isatty', return_value=True), patch('conga8290.terminal.sys.stderr', out), patch.object(out, 'isatty', return_value=True), patch('builtins.input', return_value='synthetic@example.invalid') as read:
            self.assertEqual(visible_input('Email: '), 'synthetic@example.invalid')
        read.assert_called_once_with()
        self.assertEqual(out.getvalue(), 'Email: ')
