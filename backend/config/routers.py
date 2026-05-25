"""
Database router for the URL Shortener project.

Strategy
--------
- All writes always go to the 'default' (primary) database.
- Read operations for the Click model — the highest-volume analytics table —
  are routed to the 'analytics_replica' database when it is configured.
  All other reads fall back to 'default'.

This lets you point 'analytics_replica' at a PostgreSQL read-replica or a
separate analytics database (e.g. read-optimised warehouse) without changing
any application code.

Configuration (settings.py / .env)
-----------------------------------
Set ANALYTICS_REPLICA_URL in your environment to enable the replica:

    ANALYTICS_REPLICA_URL=postgres://user:pass@replica-host:5432/urlshortener

Leave it unset in development and the router transparently uses 'default'.
"""


ANALYTICS_MODELS = {'click'}      # lowercase model names routed to replica
ANALYTICS_APP    = 'shortener'


class AnalyticsReplicaRouter:
    """
    Routes Click model reads to 'analytics_replica' if configured,
    and sends all writes to 'default'.
    """

    def _is_analytics(self, model):
        return (
            model._meta.app_label == ANALYTICS_APP
            and model._meta.model_name in ANALYTICS_MODELS
        )

    def db_for_read(self, model, **hints):
        """
        Direct heavy analytics reads (Click) to the replica.
        Everything else uses the default DB.
        """
        if self._is_analytics(model):
            return 'analytics_replica'
        return 'default'

    def db_for_write(self, model, **hints):
        """All writes go to the primary database."""
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations if both objects are in the same database family
        (default or analytics_replica both reference the same schema).
        """
        allowed = {'default', 'analytics_replica'}
        return (
            obj1._state.db in allowed
            and obj2._state.db in allowed
        )

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Migrations only run on the primary database."""
        return db == 'default'
