#!/usr/bin/env bash
set -euo pipefail
exec livekit-server --dev --bind 0.0.0.0
