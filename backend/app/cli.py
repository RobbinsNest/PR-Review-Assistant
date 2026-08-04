"""Command-line interface for LLM API key management.

Usage: ``python -m app.cli key set|status|clear``

The key is read via ``getpass`` (hidden input) and stored through
``CredentialStore`` (keyring first, ``.env`` fallback). Only masked forms
are ever printed - the plaintext key is never echoed.
"""

import argparse
import getpass
import sys

from app.services.credentials import CredentialStore


def cmd_key_set(_args: argparse.Namespace) -> int:
    """``key set``: prompt for the key, store it, print the masked result."""
    key = getpass.getpass("Enter LLM API key: ")
    if not key:
        print("No key entered; nothing stored.", file=sys.stderr)
        return 1
    CredentialStore.set_llm_api_key(key)
    print(f"已保存（掩码：{CredentialStore.mask(key)}）")
    return 0


def cmd_key_status(_args: argparse.Namespace) -> int:
    """``key status``: print configured/unconfigured plus the masked key."""
    key = CredentialStore.get_llm_api_key()
    if key:
        print(f"已配置（掩码：{CredentialStore.mask(key)}）")
    else:
        print("未配置")
    return 0


def cmd_key_clear(_args: argparse.Namespace) -> int:
    """``key clear``: remove the stored LLM API key."""
    CredentialStore.clear_llm_api_key()
    print("已清除")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the ``key set|status|clear`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Manage the LLM API key (keyring first, .env fallback).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    key = sub.add_parser("key", help="manage the LLM API key")
    key_actions = key.add_subparsers(dest="action", required=True)
    key_actions.add_parser("set", help="store the LLM API key (hidden input)")
    key_actions.add_parser("status", help="show configured status and masked key")
    key_actions.add_parser("clear", help="remove the LLM API key")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "key":
        if args.action == "set":
            return cmd_key_set(args)
        if args.action == "status":
            return cmd_key_status(args)
        if args.action == "clear":
            return cmd_key_clear(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
