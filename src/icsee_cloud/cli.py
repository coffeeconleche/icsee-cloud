"""Command dispatch; importing the package never logs in or starts an emulator."""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(prog='icsee-cloud')
    parser.add_argument('command', choices=['watch', 'record', 'stop'])
    commands = ['watch', 'record', 'stop']
    if len(sys.argv) > 1 and sys.argv[1] in commands:
        command, rest = sys.argv[1], sys.argv[2:]
    else:
        args, rest = parser.parse_known_args()
        command = args.command
    sys.argv = [f'icsee-cloud {command}', *rest]
    if command == 'watch':
        from .viewer import main as run
    elif command == 'record':
        from .recorder import main as run
    else:
        from .stop import main as run
    return run()
