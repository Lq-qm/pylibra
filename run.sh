#!/usr/bin/env bash
# pylibra — sobe a interface desktop usando o venv do pyvox
cd "$(dirname "$0")"
exec pyvox/.venv/bin/python main.py "$@"
