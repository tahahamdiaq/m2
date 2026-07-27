#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def _strip_user_site() -> None:
    """Inside the venv, drop user site-packages injected via PYTHONPATH.

    Certaines machines exportent PYTHONPATH=~/.local/... ce qui fait passer
    un Django global avant celui du venv. On force la priorité au venv.
    """
    if sys.prefix != sys.base_prefix:
        home_site = os.path.expanduser("~/.local/lib")
        sys.path[:] = [p for p in sys.path if not p.startswith(home_site)]


def main():
    """Run administrative tasks."""
    _strip_user_site()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
