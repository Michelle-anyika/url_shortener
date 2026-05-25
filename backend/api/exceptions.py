"""
Custom DRF exception handler.
Logs all 500-level errors in structured JSON format before returning the
standard DRF error response.
"""

import logging
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        # Unhandled exception — this is a 500
        logger.error(
            '500 Internal Server Error',
            extra={
                'exception': str(exc),
                'exception_type': type(exc).__name__,
                'view': str(context.get('view')),
            },
            exc_info=True,
        )
        return response

    if response.status_code >= 500:
        logger.error(
            'Server error in API view',
            extra={
                'status_code': response.status_code,
                'detail': str(response.data),
                'view': str(context.get('view')),
            },
        )
    elif response.status_code in (401, 403):
        logger.warning(
            'Security event: unauthorized/forbidden request',
            extra={
                'status_code': response.status_code,
                'path': context['request'].path,
                'user': str(context['request'].user),
            },
        )

    return response
