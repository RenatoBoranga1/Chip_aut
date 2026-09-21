import json
from dataclasses import asdict
from datetime import datetime, timezone

from database.repository import SQLiteRepository, encode
from partners.models import CollectionResult, PartnerMotorcycle


class PartnerRepository(SQLiteRepository):
    def save_collection(self, result):
        status = (
            "CACHED"
            if result.cached
            else "COMPLETE"
            if result.complete
            else "PARTIAL"
            if result.advertisements
            else "FAILED"
        )
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            cursor = self.connection.execute(
                "INSERT INTO partner_collections(partner,created_at,status,summary_json) VALUES (?,?,?,?)",
                (
                    result.partner,
                    datetime.now(timezone.utc).isoformat(),
                    status,
                    encode({k: v for k, v in asdict(result).items() if k != "advertisements" or result.cached}),
                ),
            )
            collection_id = cursor.lastrowid
            if result.cached:
                return collection_id
            if result.complete:
                self.connection.execute(
                    "UPDATE partner_advertisements SET not_seen_in_latest_collection=1 WHERE partner=?",
                    (result.partner,),
                )
            for ad in result.advertisements:
                self.connection.execute(
                    "INSERT INTO partner_advertisements VALUES (?,?,?,?,1,0,?,?) "
                    "ON CONFLICT(partner,external_id) DO UPDATE SET "
                    "last_seen_at=MAX(partner_advertisements.last_seen_at,excluded.last_seen_at),"
                    "verification_count=partner_advertisements.verification_count+1,"
                    "not_seen_in_latest_collection=0,latest_collection_id=excluded.latest_collection_id,"
                    "payload_json=excluded.payload_json",
                    (ad.partner, ad.external_id, ad.collected_at, ad.collected_at, collection_id, encode(asdict(ad))),
                )
                self.connection.execute(
                    "INSERT INTO partner_observations VALUES (?,?,?,?)",
                    (collection_id, ad.partner, ad.external_id, encode(asdict(ad))),
                )
        return collection_id

    def get_collection(self, collection_id):
        row = self.connection.execute(
            "SELECT summary_json FROM partner_collections WHERE id=?", (collection_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Coleta não encontrada")
        payload = json.loads(row[0])
        ads = payload.pop("advertisements", None)
        if ads is None:
            ads = [
                json.loads(r[0])
                for r in self.connection.execute(
                    "SELECT payload_json FROM partner_observations WHERE collection_id=? ORDER BY external_id",
                    (collection_id,),
                )
            ]
        return CollectionResult(**payload, advertisements=[PartnerMotorcycle(**a) for a in ads])

    def save_coverage(self, collection_id, import_id, report):
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO coverage_runs(collection_id,import_id,created_at,report_json) VALUES (?,?,?,?)",
                (collection_id, import_id, datetime.now(timezone.utc).isoformat(), encode(report)),
            )
        return cursor.lastrowid
