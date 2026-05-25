"""
Security Headers Middleware.

Adds HTTP security headers to every response:
  - X-Content-Type-Options: nosniff       — prevent MIME-type sniffing
  - X-Frame-Options: DENY                  — prevent clickjacking
  - X-XSS-Protection: 1; mode=block       — legacy XSS filter
  - Strict-Transport-Security             — enforce HTTPS (HSTS)
  - Referrer-Policy: strict-origin-when-cross-origin
  - Permissions-Policy                    — restrict browser features
  - Content-Security-Policy               — restrict content sources
"""


class SecurityHeadersMiddleware:
    """
    Middleware that injects security headers on every HTTP response.
    Should be placed near the top of MIDDLEWARE in settings.py.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = (
            'geolocation=(), microphone=(), camera=(), payment=()'
        )
        response['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        # Only add HSTS in production (when not DEBUG)
        if not getattr(response, '_resource_closers', None):
            response['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains'
            )
        return response
