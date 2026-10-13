"""POSIX terminal prompts: visible account input, password stars; no echo fallback."""
import copy
import sys


def require_terminal():
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError('interactive_terminal_required')


def visible_input(message):
    require_terminal()
    sys.stderr.write(message)
    sys.stderr.flush()
    return input()


def masked_password(message):
    require_terminal()
    import termios
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    masked = copy.deepcopy(original)
    masked[3] &= ~(termios.ECHO | termios.ICANON)
    masked[6][termios.VMIN] = 1
    masked[6][termios.VTIME] = 0
    characters = []
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, masked)
        # Disable echo BEFORE showing the prompt, even for an immediate paste.
        sys.stderr.write(message)
        sys.stderr.flush()
        while True:
            char = sys.stdin.read(1)
            if char in ['', '\x04']:
                raise EOFError()
            if char in ['\r', '\n']:
                return ''.join(characters)
            if char == '\x03':
                raise KeyboardInterrupt()
            if char in ['\b', '\x7f']:
                if characters:
                    characters.pop()
                    sys.stderr.write('\b \b')
                    sys.stderr.flush()
            elif char.isprintable():
                characters.append(char)
                sys.stderr.write('*')
                sys.stderr.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)
        sys.stderr.write('\n')
        sys.stderr.flush()
