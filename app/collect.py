import argparse
import json
import logging
from pathlib import Path

from partners.registry import create_collector
from partners.wr_browser import WRBrowserSource
from partners.wr_http import WRHTTPSource
from services.collection_report import write_collection_report
from services.collection_service import collect_partners


def main():
    parser = argparse.ArgumentParser(description="Coletar catálogo de parceiro sem comparar suporte")
    parser.add_argument("--partner", default="wr_motos")
    parser.add_argument("--db", type=Path, default=Path("data/coverage.sqlite3"))
    parser.add_argument("--reports", type=Path, default=Path("reports/collections"))
    parser.add_argument("--channel", choices=["msedge", "chrome"], default=None)
    parser.add_argument("--transport", choices=["http", "browser"], default="http")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=int, default=30000)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--fresh", action="store_true", help="Ignorar cache local; mantém limites de acesso")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        options = dict(
            delay=args.delay, timeout_ms=args.timeout, max_pages=args.max_pages, evidence_dir=args.reports / "evidence"
        )
        source = (
            WRHTTPSource(**options) if args.transport == "http" else WRBrowserSource(channel=args.channel, **options)
        )
        collector = create_collector(
            args.partner, source=source, cache_file=args.db.parent / "wr-cache.json", cache_ttl=0 if args.fresh else 300
        )
        for collection_id, result in collect_partners({args.partner: collector}, args.db):
            summary = write_collection_report(collection_id, result, args.reports / f"collection-{collection_id:04d}")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            if not result.complete:
                raise SystemExit(2)
    except Exception:
        logging.getLogger(__name__).exception("collection_command_failed")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
