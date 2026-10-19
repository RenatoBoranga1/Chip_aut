"""Official token transport. No login, token persistence, redirects or secret-bearing errors."""

import csv
import io
import os

import requests

from database.inventory_repository import alert, event
from database.partner_repository import PartnerRepository
from services.partner_inventory_import import PartnerInventoryImportService, writable

ENDPOINT = "https://integracao.autocerto.com/api/Veiculo/ObterEstoque"


class SourceError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(
            {
                "AUTH_REQUIRED": "Aguardando credencial autorizada",
                "AUTH_FAILED": "Credencial inválida ou expirada",
                "SOURCE_UNAVAILABLE": "Fonte temporariamente indisponível",
                "SOURCE_STRUCTURE_CHANGED": "Fonte sem estrutura ou classificação validada",
            }.get(code, code)
        )


class AuthenticatedSource:
    def __init__(self, *, environ=None, transport=None):
        self.environ = os.environ if environ is None else environ
        self.transport = transport

    def read(self):
        env = self.environ
        token = env.get("THOMAS_API_TOKEN", "")
        motorcycle_type = env.get("THOMAS_MOTORCYCLE_TYPE", "")
        if not token or env.get("THOMAS_AUTHORIZED") != "true" or not motorcycle_type:
            return {"status": "AGUARDANDO_CONFIGURACAO", "code": "AUTH_REQUIRED", "rows": []}
        try:
            if self.transport:
                status, records = self.transport(token)
            else:
                with requests.get(
                    ENDPOINT,
                    headers={
                        "Authorization": "Bearer " + token,
                        "Accept": "application/json",
                        "User-Agent": "MotoCoverageMonitor/0.4",
                    },
                    timeout=20,
                    allow_redirects=False,
                    stream=True,
                ) as response:
                    status = response.status_code
                    if status in {401, 403}:
                        raise SourceError("AUTH_FAILED")
                    if status != 200:
                        raise SourceError("SOURCE_UNAVAILABLE")
                    body = bytearray()
                    for chunk in response.iter_content(65536):
                        body.extend(chunk)
                        if len(body) > 5_000_000:
                            raise SourceError("SOURCE_STRUCTURE_CHANGED")
                    import json

                    records = json.loads(body)
            if status in {401, 403}:
                raise SourceError("AUTH_FAILED")
            if status != 200:
                raise SourceError("SOURCE_UNAVAILABLE")
            if not isinstance(records, list) or not records or len(records) > 5000:
                raise SourceError("SOURCE_STRUCTURE_CHANGED")
            rows = []
            for item in records:
                if not isinstance(item, dict) or not isinstance(item.get("TipoVeiculo"), str):
                    raise SourceError("SOURCE_STRUCTURE_CHANGED")
                if item["TipoVeiculo"] != motorcycle_type:
                    continue
                if (
                    not item.get("Codigo")
                    or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ("Marca", "Modelo"))
                    or type(item.get("AnoModelo")) is not int
                ):
                    raise SourceError("SOURCE_STRUCTURE_CHANGED")
                rows.append(
                    {
                        "external_id": str(item["Codigo"]),
                        "manufacturer": item.get("Marca"),
                        "model": item.get("Modelo"),
                        "version": item.get("Versao"),
                        "year": item.get("AnoModelo"),
                        "price": item.get("Preco"),
                        "mileage": item.get("Km"),
                    }
                )
            if not rows:
                raise SourceError("SOURCE_STRUCTURE_CHANGED")
            return {"status": "READY", "rows": rows, "excluded": len(records) - len(rows)}
        except SourceError:
            raise
        except requests.RequestException:
            raise SourceError("SOURCE_UNAVAILABLE") from None
        except Exception:
            raise SourceError("SOURCE_STRUCTURE_CHANGED") from None


class FakeAuthenticatedSource(AuthenticatedSource):
    """Explicit injection fixture, never selected from production environment."""

    def __init__(self, records=None, *, status=200, missing=False, error=None):
        def transport(_token):
            if error:
                raise error
            return status, records

        super().__init__(
            environ={}
            if missing
            else {"THOMAS_API_TOKEN": "fixture-only", "THOMAS_AUTHORIZED": "true", "THOMAS_MOTORCYCLE_TYPE": "Moto"},
            transport=transport,
        )


def collect_authenticated(database, *, source=None, confirmed=False, reviewer="", read_only=False, reports=None):
    writable(database, read_only)
    source = source or AuthenticatedSource()
    try:
        result = source.read()
        if result["status"] != "READY":
            with PartnerRepository(database) as repo, repo.connection:
                alert(repo.connection, "thomas_motos", "AUTH_REQUIRED")
            return result
        from services.partner_inventory_import import FIELDS

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(result["rows"])
        content = buffer.getvalue().encode("utf-8")
        service = PartnerInventoryImportService(database, read_only=read_only, reports=reports)
        if not confirmed:
            return service.preview("thomas_motos", content, "autocerto.csv")
        output = service.confirm(
            "thomas_motos",
            content,
            "autocerto.csv",
            reviewer=reviewer,
            confirmed=True,
            authorized=True,
            motorcycles_confirmed=True,
        )
        with PartnerRepository(database) as repo, repo.connection:
            event(repo.connection, "thomas_motos", "AUTHENTICATED_COLLECTION", reviewer, {"import_id": output["id"]})
            alert(repo.connection, "thomas_motos", "AUTH_REQUIRED", False)
            alert(repo.connection, "thomas_motos", "AUTH_FAILED", False)
        return output
    except SourceError as exc:
        with PartnerRepository(database) as repo, repo.connection:
            alert(repo.connection, "thomas_motos", exc.code)
            event(repo.connection, "thomas_motos", exc.code, reviewer or "sistema", {"status": "FAILED"})
        raise
