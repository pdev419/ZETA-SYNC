from __future__ import annotations

import json
from typing import Optional, Dict, Any


def parse_metrics_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Accepts either:
    1) JSON line: {"type":"metrics","z":..., "drift":..., "stability":..., ...}
    2) Key=Value line: "Z=0.9998 drift=12.3 stability=0.98 ppm_offset=1.2"
    Returns a dict of numeric metrics, or None if not a metrics line.
    """

    s = line.strip()
    if not s:
        return None

    # ---- JSON line support (mock zeta-sync) ----
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = json.loads(s)
        except Exception:
            obj = None

        if isinstance(obj, dict):
            # Only accept metrics-ish messages
            if obj.get("type") not in (None, "metrics"):
                return None

            out: Dict[str, Any] = {}
            # whitelist keys commonly used
            for k in ("z", "Z", "drift", "stability", "ppm_offset", "rate_hz", "peer_rate_hz", "sequence"):
                if k in obj:
                    v = obj[k]
                    if isinstance(v, (int, float)):
                        # normalize "Z" -> "z"
                        out["z" if k == "Z" else k] = float(v)
            return out or None

    # ---- Key=Value support ----
    out2: Dict[str, Any] = {}
    if "Z=" not in s and "z=" not in s:
        return None

    for part in s.replace(",", " ").split():
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        try:
            out2[k] = float(v)
        except ValueError:
            continue

    # normalize common variants
    if "Z" in out2 and "z" not in out2:
        out2["z"] = out2.pop("Z")

    return out2 or None
