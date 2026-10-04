#!/bin/bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
else
  source .venv/bin/activate
  python3 -c 'import PySide6.QtWebSockets, PySide6.QtMultimedia, msgpack, numpy' || pip install -r requirements.txt
fi
python3 whale_pet.py "$@"
