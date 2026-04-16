#!/bin/bash
# Run PulseEdit direttamente da sorgente (sviluppo)
cd "$(dirname "$0")"
source venv/bin/activate
python main.py
