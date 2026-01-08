from __future__ import annotations
from statistics import median
from typing import Dict, List, Optional

def median_aggregate(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return median(vals) if vals else None

def aggregate_cluster_metrics(node_metrics: Dict[str, dict], excluded: set[str]) -> dict:
    z_vals = []
    for node_id, m in node_metrics.items():
        if node_id in excluded:
            continue
        z = m.get("Z") or m.get("z")
        if isinstance(z, (int, float)):
            z_vals.append(float(z))
    return {
        "z_median": median_aggregate(z_vals),
        "z_min": min(z_vals) if z_vals else None,
        "z_max": max(z_vals) if z_vals else None,
        "count": len(z_vals),
    }
