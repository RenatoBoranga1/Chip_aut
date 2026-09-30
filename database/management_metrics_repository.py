"""Consistent, read-only analytics evidence. No migrations, refreshes or commands."""

import json
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

from database.development_repository import read_connection
from database.review_repository import ReviewRepository
from matching.review_policy import signature


def stamp(value):
    try:
        result = datetime.fromisoformat(value)
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def before(value, cutoff):
    parsed = stamp(value)
    return parsed is not None and parsed < cutoff


def unpack(row):
    result = dict(row)
    for key in list(result):
        if key.endswith("_json"):
            result[key[:-5]] = json.loads(result.pop(key) or "{}")
    return result


class HistoricalReview(ReviewRepository):
    """Use the existing validity rules with historical evidence, never today's projection."""

    def __init__(self, connection, cutoff, ads):
        self.connection, self.cutoff, self.ads = connection, cutoff, ads

    def _decisions(self, item):
        return [d for d in super()._decisions(item) if before(d["created_at"], self.cutoff)]

    def observation(self, item):
        ad = self.ads.get(item["external_id"])
        return (None, signature(ad) if ad else None)


class ManagementMetricsRepository:
    def __init__(self, path):
        self.path = path

    def versions(self):
        with read_connection(self.path) as db:
            return [dict(r) for r in db.execute("SELECT id,created_at FROM imports ORDER BY id DESC")]

    def pair(self, partner, cutoff, previous_cutoff, version=None):
        with read_connection(self.path) as db:
            return (self.snapshot(partner, cutoff, version, db), self.snapshot(partner, previous_cutoff, version, db))

    def snapshot(self, partner, cutoff, version=None, connection=None):
        with nullcontext(connection) if connection is not None else read_connection(self.path) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

            def rows(table, columns="*", where="1", params=()):
                if table not in tables:
                    return []
                return [unpack(r) for r in db.execute(f"SELECT {columns} FROM {table} WHERE {where}", params)]

            def past(items, field="created_at"):
                return [r for r in items if before(r.get(field), cutoff)]

            versions = past(rows("imports", "id,created_at,report_json,diff_json"))
            selected = (
                next((r for r in versions if r["id"] == version), None)
                if version
                else max(versions, key=lambda r: r["id"], default=None)
            )
            base_id = selected["id"] if selected else None
            if selected:
                published = rows("scanner_versions", "id,report_json", "import_id=?", (base_id,))
                selected["publication"] = published[0]["report"] if published else {}
                selected["revalidation_required"] = selected["publication"].get("review_affected")
                selected["revalidation_events"] = len(
                    past(rows("review_events", "id,created_at", "import_id=?", (base_id,)))
                )
            base_rows = rows("motorcycle_snapshots", "payload_json", "import_id=?", (base_id,))
            base = {r["payload"]["key"]: SimpleNamespace(**r["payload"]) for r in base_rows}
            applications = [
                dict(r)
                for r in db.execute(
                    "SELECT m.normalized_key AS key,json_extract(r.payload_json,'$.system_key') AS system,json_extract(r.payload_json,'$.duplicate_of') AS duplicate_of FROM system_records r JOIN motorcycles m ON m.id=r.motorcycle_id WHERE r.import_id=?",
                    (base_id,),
                )
            ]

            previous_id = max((r["id"] for r in versions if base_id and r["id"] < base_id), default=None)
            previous_base = rows("motorcycle_snapshots", "payload_json", "import_id=?", (previous_id,))

            collections = past(rows("partner_collections", "id,created_at,status", "partner=?", (partner,)))
            collections = {r["id"]: r for r in collections if r["status"] in {"COMPLETE", "PARTIAL"}}
            observations = rows(
                "partner_observations",
                "collection_id,external_id,json_remove(payload_json,'$.raw_data','$.raw_text') AS payload_json",
                "partner=?",
                (partner,),
            )
            observations = [r for r in observations if r["collection_id"] in collections]
            observations.sort(key=lambda r: (stamp(collections[r["collection_id"]]["created_at"]), r["collection_id"]))
            latest = {
                r["external_id"]: {
                    **r["payload"],
                    "observed_at": collections[r["collection_id"]]["created_at"],
                    "collection_id": r["collection_id"],
                }
                for r in observations
            }
            complete = max((r["id"] for r in collections.values() if r["status"] == "COMPLETE"), default=0)
            ads = {k: a for k, a in latest.items() if a["collection_id"] >= complete}
            first_seen = {
                r["external_id"]: r["first_seen_at"]
                for r in rows("partner_advertisements", "external_id,first_seen_at", "partner=?", (partner,))
            }
            for key, ad in latest.items():
                ad["first_seen"] = first_seen.get(key)
                ad["active_at_end"] = key in ads
            coverage = past(
                rows(
                    "coverage_runs",
                    "id,collection_id,import_id,created_at,report_json",
                    "collection_id IN (SELECT id FROM partner_collections WHERE partner=?)",
                    (partner,),
                )
            )
            coverage_entries = []
            for run in sorted(coverage, key=lambda r: (stamp(r["created_at"]), r["id"])):
                for group in run["report"].get("groups", {}).values():
                    for entry in group:
                        coverage_entries.append(
                            {
                                **entry,
                                "evaluated_at": run["created_at"],
                                "import_id": run["import_id"],
                                "coverage_id": run["id"],
                                "collection_id": run["collection_id"],
                            }
                        )
            occurrences = past(
                rows(
                    "review_occurrences",
                    "id,review_item_id,collection_id,run_id,import_id,advertisement_json,automatic_json,created_at",
                    "review_item_id IN (SELECT id FROM review_items WHERE partner=?)",
                    (partner,),
                )
            )
            by_item = {
                r["review_item_id"]: r for r in sorted(occurrences, key=lambda r: (stamp(r["created_at"]), r["id"]))
            }
            items = past(
                rows(
                    "review_items", "id,partner,external_id,signature,identity_json,created_at", "partner=?", (partner,)
                )
            )
            evaluator = HistoricalReview(db, cutoff, latest)
            reviews = []
            for item in items:
                occurrence = by_item.get(item["id"])
                if not occurrence:
                    continue
                item.update({k: occurrence[k] for k in ("run_id", "automatic", "advertisement", "collection_id")})
                item["automatic_import_id"] = occurrence["import_id"]
                item["active"] = (
                    signature(latest[item["external_id"]]) == item["signature"]
                    if item["external_id"] in latest
                    else False
                )
                effective, state, decision, stale = evaluator._evaluate(item, base_id, base)
                reviews.append(
                    {**item, "effective": effective, "state": state, "human_decision": decision, "stale_reason": stale}
                )
            decisions = past(
                rows(
                    "review_decisions",
                    "id,review_item_id,created_at,action,previous_decision_id",
                    "review_item_id IN (SELECT id FROM review_items WHERE partner=?)",
                    (partner,),
                )
            )
            review_events = past(
                rows(
                    "review_events",
                    "id,review_item_id,created_at,reason",
                    "review_item_id IN (SELECT id FROM review_items WHERE partner=?)",
                    (partner,),
                )
            )
            dev_items = past(
                rows(
                    "development_items",
                    "id,manufacturer,model,version,year,scanner_key,created_at",
                    "id IN (SELECT item_id FROM development_origins WHERE partner=?)",
                    (partner,),
                )
            )
            dev_ids = {r["id"] for r in dev_items}
            dev_events = [
                r
                for r in past(rows("development_events", "id,item_id,created_at,action,after_json"))
                if r["item_id"] in dev_ids
            ]
            origins = [
                r
                for r in rows("development_origins", "item_id,partner,external_id")
                if r["item_id"] in dev_ids and r["partner"] == partner
            ]
            cases = rows("priority_cases", "id,entity_id,identity_key", "partner=?", (partner,))
            case_ids = {r["id"] for r in cases}
            assessments = [
                r
                for r in past(
                    rows("priority_assessments", "id,case_id,calculated_at,suggested_priority"), "calculated_at"
                )
                if r["case_id"] in case_ids
            ]
            overrides = [
                r
                for r in past(rows("priority_overrides", "id,case_id,created_at,after_priority"))
                if r["case_id"] in case_ids
            ]
            priorities = []
            for case in cases:
                assessment = max(
                    (a for a in assessments if a["case_id"] == case["id"]), key=lambda r: r["id"], default=None
                )
                override = max(
                    (a for a in overrides if a["case_id"] == case["id"]), key=lambda r: r["id"], default=None
                )
                if assessment:
                    priorities.append(
                        {
                            **case,
                            **assessment,
                            "manual": bool(override and override["after_priority"]),
                            "priority": (override or {}).get("after_priority") or assessment["suggested_priority"],
                        }
                    )
            alerts = []
            for table, history in (
                ("alerts", "alert_history"),
                ("development_alerts", "development_alert_history"),
                ("priority_alerts", "priority_alert_history"),
                ("scanner_alerts", "scanner_alert_history"),
            ):
                columns = "id,alert_type,created_at"
                columns += (
                    ",partner,external_id,severity"
                    if table == "alerts"
                    else ",item_id,severity"
                    if table == "development_alerts"
                    else ",case_id"
                    if table == "priority_alerts"
                    else ",partner"
                )
                histories = past(rows(history, "id,alert_id,created_at,after_status"))
                statuses = {r["alert_id"]: r["after_status"] for r in sorted(histories, key=lambda r: r["id"])}
                for alert in past(rows(table, columns)):
                    if table in {"alerts", "scanner_alerts"} and alert["partner"] != partner:
                        continue
                    if table == "development_alerts" and alert["item_id"] not in dev_ids:
                        continue
                    if table == "priority_alerts":
                        case = next((c for c in cases if c["id"] == alert["case_id"]), None)
                        if not case:
                            continue
                        alert["external_id"] = case["entity_id"]
                    if table == "priority_alerts":
                        alert["severity"] = "ATENCAO" if "OUTDATED" in alert["alert_type"] else "ALTA"
                    if table == "scanner_alerts":
                        alert["severity"] = "INFO" if alert["alert_type"] == "SCANNER_PUBLISHED" else "ATENCAO"
                    alerts.append(
                        {
                            **alert,
                            "key": f"{table}:{alert['id']}",
                            "status": statuses.get(alert["id"], "NOVO"),
                            "severity": alert.get("severity", "ATENCAO"),
                        }
                    )
            return {
                "applications": applications,
                "base_id": base_id,
                "version": selected,
                "base": [r["payload"] for r in base_rows],
                "previous_base": [r["payload"] for r in previous_base],
                "ads": list(latest.values()),
                "reviews": reviews,
                "decisions": decisions,
                "review_events": review_events,
                "development": dev_items,
                "development_events": dev_events,
                "origins": origins,
                "priorities": priorities,
                "alerts": alerts,
                "coverage": coverage_entries,
                "observations": observations,
                "tables": sorted(tables),
                "versions": versions,
            }
