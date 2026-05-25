"""
Saga Pattern — URL Creation Distributed Transaction.

What is a Saga?
---------------
A Saga is a sequence of local transactions where each step publishes an
event or calls the next step. If a step fails, compensating transactions
undo the completed steps.

URLCreationSaga
---------------
Step 1: Create URL record (local DB write) ← can be compensated by deleting
Step 2: Fetch preview metadata (call external Preview Service) ← async
Step 3: Update URL with preview data ← only if step 2 succeeded

Compensation:
  If Step 2 fails, we do NOT roll back Step 1.
  Instead, we apply eventual consistency: the URL is still created (usable),
  and preview data is left as null. A retry can fill it in later.

  This is the "Forward Recovery" variant of the Saga pattern:
  we never leave the system in an inconsistent state — a URL without
  preview data is still a valid, functional URL.

Why not a 2-Phase Commit?
  2PC requires distributed locks and a coordinator. For an eventually
  consistent metadata field (title/description/favicon), this is overkill.
  The Saga is simpler, more resilient, and appropriate here.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from shortener.commands import CreateURLCommand, handle_create_url, CommandError
from shortener.models import URL

logger = logging.getLogger(__name__)


@dataclass
class URLCreationSagaResult:
    url: URL
    preview_fetched: bool
    preview_error: Optional[str] = None


class URLCreationSaga:
    """
    Orchestrates the two-step URL creation process.

    Usage:
        saga = URLCreationSaga()
        result = saga.execute(command)
        # result.url is always set
        # result.preview_fetched tells you if metadata was populated
    """

    def execute(self, cmd: CreateURLCommand) -> URLCreationSagaResult:
        # ---------------------------------------------------------------
        # Step 1: Create the URL (local transaction)
        # This is the critical step — if it fails, nothing else happens.
        # ---------------------------------------------------------------
        url = handle_create_url(cmd)
        logger.info(
            'Saga Step 1 complete: URL created',
            extra={'short_code': url.short_code, 'url_id': url.pk},
        )

        # ---------------------------------------------------------------
        # Step 2: Trigger async preview fetch (non-blocking)
        # We fire the Celery task and return immediately.
        # If Celery is unavailable, we log and continue — the URL is
        # still fully functional without preview data.
        # ---------------------------------------------------------------
        preview_fetched = False
        preview_error = None

        try:
            from shortener.tasks import fetch_url_preview_task
            fetch_url_preview_task.delay(url.pk, url.original_url)
            preview_fetched = True
            logger.info(
                'Saga Step 2 queued: preview fetch task dispatched',
                extra={'url_id': url.pk},
            )
        except Exception as exc:
            # Compensating action: do nothing — the URL is still valid.
            # Preview data will simply be null until a retry fills it in.
            preview_error = str(exc)
            logger.warning(
                'Saga Step 2 skipped: could not dispatch preview task (non-fatal)',
                extra={'url_id': url.pk, 'error': preview_error},
            )

        return URLCreationSagaResult(
            url=url,
            preview_fetched=preview_fetched,
            preview_error=preview_error,
        )
