"""Real POSIX PTY with synthetic input only; no account, network or password log."""
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import time
import unittest


class RealTerminalTests(unittest.TestCase):
    def test_visible_email_masked_unicode_password_and_echo_restoration(self):
        master, slave = pty.openpty()
        code = '''import json,sys,termios
from conga8290.terminal import visible_input,masked_password
email=visible_input('EMAIL: ')
password=masked_password('PASSWORD: ')
print(json.dumps({'email_matched':email=='synthetic@example.invalid',
                 'password_matched':password=='synthétic-😀',
                 'echo_restored':bool(termios.tcgetattr(sys.stdin.fileno())[3]&termios.ECHO)}),flush=True)
'''
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        child = subprocess.Popen([sys.executable, '-u', '-c', code],
                                 cwd=Path(__file__).resolve().parents[1],
                                 stdin=slave, stdout=slave, stderr=slave, env=env)
        os.close(slave)
        captured = bytearray()
        deadline = time.monotonic() + 8
        def until(marker):
            while marker not in captured:
                if time.monotonic() >= deadline:
                    self.fail('synthetic_pty_timeout')
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    captured.extend(os.read(master, 4096))
        try:
            until(b'EMAIL: ')
            os.write(master, b'synthetic@example.invalid\n')
            until(b'PASSWORD: ')
            os.write(master, 'synthétic-😀\n'.encode())
            until(b'echo_restored')
            child.wait(timeout=2)
            text = captured.decode('utf8')
            self.assertIn('synthetic@example.invalid', text)
            self.assertIn('*', text)
            self.assertNotIn('synthétic-😀', text)
            line = next(line for line in text.splitlines() if line.startswith('{'))
            self.assertEqual(json.loads(line), {'email_matched': True, 'password_matched': True, 'echo_restored': True})
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            os.close(master)
