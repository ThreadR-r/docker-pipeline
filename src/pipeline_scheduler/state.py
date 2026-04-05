from typing import Dict, Any

# Shared in-memory state for scheduler and API
running = {"job": False}
jobs: Dict[str, Dict[str, Any]] = {}
