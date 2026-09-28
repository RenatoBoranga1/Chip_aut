"""Post-commit projection hooks; failures cannot undo a human command."""

from functools import wraps


def after_change(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        result = method(self, *args, **kwargs)
        from services.prioritization_service import safe_refresh

        safe_refresh(self.config.database, self.config.partner, method.__name__)
        return result

    return wrapped
