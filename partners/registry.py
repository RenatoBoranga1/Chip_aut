"""Explicit adapter allowlist. Configuration never imports executable code."""

from partners.base_partner import PartnerAdapter
from partners.config import load_settings, validate_key
from partners.wr_motos import WRMotosCollector


class PartnerRegistry:
    def __init__(self, settings=None, factories=None):
        self._settings = {}
        self._factories = dict(factories if factories is not None else {"wr_motos": WRMotosCollector})
        for entry in load_settings() if settings is None else settings:
            self.register(entry)

    def register(self, entry):
        key = validate_key(entry.partner_key)
        if key in self._settings:
            raise ValueError(f"Parceiro duplicado: {key}")
        factory = self._factories.get(entry.collector)
        if not isinstance(factory, type) or not issubclass(factory, PartnerAdapter):
            raise ValueError(f"Adapter desconhecido: {entry.collector}")
        if factory.partner_key != key or entry.limits.concurrency > factory.max_concurrency:
            raise ValueError("Adapter incompatível com a configuração do parceiro")
        self._settings[key] = entry

    def list(self, *, enabled_only=False):
        return [p for p in self._settings.values() if p.enabled or not enabled_only]

    def get(self, key, *, require_enabled=False):
        validate_key(key)
        if key not in self._settings:
            raise ValueError(f"Parceiro desconhecido: {key}")
        entry = self._settings[key]
        if require_enabled and not entry.enabled:
            raise ValueError(f"Parceiro desabilitado: {key}")
        return entry

    def create(self, key, **kwargs):
        entry = self.get(key, require_enabled=True)
        adapter = self._factories[entry.collector](**kwargs)
        adapter.display_name, adapter.enabled = entry.display_name, entry.enabled
        adapter.detail_lookup, adapter.image_fetch = entry.detail_lookup, entry.image_fetch
        return adapter

    def for_pipeline(self, key, config, folder):
        entry = self.get(key, require_enabled=True)
        factory = self._factories[entry.collector]
        return factory.for_pipeline(entry, config, folder)


def create_collector(name, **kwargs):
    return PartnerRegistry().create(name, **kwargs)
