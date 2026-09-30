"""Deterministic application differences; never fuzzy-merge systems or cables."""

import json
from collections import defaultdict
from dataclasses import asdict

from scanner_base.models import SystemRecord
from scanner_base.normalizer import normalize_text


def applications(records):
    grouped = defaultdict(dict)
    for item in records:
        r = asdict(item) if isinstance(item, SystemRecord) else item
        key = (r["key"], r["system_key"], normalize_text(r.get("cable", "")))
        attributes = {
            k: v for k, v in r["raw_fields"].items() if k not in {"manufacturer", "model", "year", "system", "cable"}
        }
        encoded = json.dumps(attributes, ensure_ascii=False, sort_keys=True)
        grouped[key][encoded] = {
            "system": r["system"],
            "cable": r.get("cable", ""),
            "attributes": attributes,
            "source_format": r.get("source_format", "LEGACY"),
        }
    return {key: [values[k] for k in sorted(values)] for key, values in grouped.items()}


def application_differences(old_records, new_records):
    old, new = applications(old_records), applications(new_records)
    old_keys, new_keys = set(old), set(new)
    added, removed = new_keys - old_keys, old_keys - new_keys
    cable_pairs = []
    old_groups, new_groups = defaultdict(list), defaultdict(list)
    for key in removed:
        old_groups[key[:2]].append(key)
    for key in added:
        new_groups[key[:2]].append(key)
    for group in old_groups.keys() & new_groups.keys():
        # A one-to-one replacement is deterministic. Multiple cable options stay separate.
        if len(old_groups[group]) == len(new_groups[group]) == 1:
            a, b = old_groups[group][0], new_groups[group][0]
            cable_pairs.append((a, b))
            removed.remove(a)
            added.remove(b)
    changed = {key for key in old_keys & new_keys if old[key] != new[key]}
    unchanged = old_keys & new_keys - changed
    details = []
    for kind, keys in (
        ("APPLICATION_ADDED", added),
        ("APPLICATION_REMOVED", removed),
        ("APPLICATION_CHANGED", changed),
    ):
        for key in sorted(keys):
            details.append(
                (
                    kind,
                    key[0],
                    {
                        "vehicle_key": key[0],
                        "system_key": key[1],
                        "cable_key": key[2],
                        "before_applications": old.get(key, []),
                        "after_applications": new.get(key, []),
                    },
                )
            )
    for a, b in sorted(cable_pairs):
        details.append(
            (
                "APPLICATION_CABLE_CHANGED",
                a[0],
                {"vehicle_key": a[0], "system_key": a[1], "before_applications": old[a], "after_applications": new[b]},
            )
        )
    before_systems, after_systems = {k[1] for k in old}, {k[1] for k in new}
    return {
        "applications": {
            "previous": len(old),
            "new": len(new),
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed) + len(cable_pairs),
            "cable_changed": len(cable_pairs),
            "attributes_changed": len(changed),
            "unchanged": len(unchanged),
            "unit": "vehicle_system_cable_key",
        },
        "systems": {
            "previous": len(before_systems),
            "new": len(after_systems),
            "added": sorted(after_systems - before_systems),
            "removed": sorted(before_systems - after_systems),
        },
    }, details
