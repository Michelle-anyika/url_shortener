"""
Module 7 tests: Authentication, RBAC, Security.

Coverage:
  1. User registration
  2. JWT login & token refresh
  3. Token logout (blacklisting)
  4. Social auth (Google)
  5. RBAC — free-tier quota
  6. RBAC — custom alias gate
  7. RBAC — premium analytics access
  8. Ownership — owner can edit, others get 403
  9. Security headers on every response
  10. Unauthenticated access correctly denied
  11. Rate limit scope is configured (login)
"""

from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import User, TIER_FREE, TIER_PREMIUM
from shortener.models import URL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username='user', email=None, tier=TIER_FREE, **kwargs):
    email = email or f"{username}@test.com"
    return User.objects.create_user(
        username=username, email=email, password='StrongPass123!',
        tier=tier, **kwargs
    )


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def make_url(owner, short_code='abc123', **kwargs):
    return URL.objects.create(
        short_code=short_code,
        original_url='https://example.com',
        owner=owner,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. Registration
# ---------------------------------------------------------------------------

class RegistrationTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('register')

    def test_register_success(self):
        data = {'username': 'alice', 'email': 'alice@test.com', 'password': 'StrongPass123!'}
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertTrue(User.objects.filter(username='alice').exists())

    def test_register_duplicate_email_fails(self):
        make_user('alice', email='alice@test.com')
        data = {'username': 'alice2', 'email': 'alice@test.com', 'password': 'StrongPass123!'}
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_weak_password_fails(self):
        data = {'username': 'bob', 'email': 'bob@test.com', 'password': '123'}
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_missing_email_fails(self):
        data = {'username': 'charlie', 'password': 'StrongPass123!'}
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 2. JWT Login & Token Refresh
# ---------------------------------------------------------------------------

class JWTAuthTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = make_user('testuser', email='test@test.com')

    def test_login_returns_tokens(self):
        response = self.client.post(reverse('token_obtain_pair'), {
            'username': 'testuser', 'password': 'StrongPass123!'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_login_wrong_password_denied(self):
        response = self.client.post(reverse('token_obtain_pair'), {
            'username': 'testuser', 'password': 'wrongpassword'
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_refresh(self):
        refresh = RefreshToken.for_user(self.user)
        response = self.client.post(reverse('token_refresh'), {'refresh': str(refresh)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_invalid_token_denied(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer invalidtoken')
        response = self.client.get(reverse('url-list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# 3. Logout (token blacklisting)
# ---------------------------------------------------------------------------

class LogoutTest(TestCase):

    def setUp(self):
        self.user = make_user('logoutuser', email='logout@test.com')
        self.client = auth_client(self.user)

    def test_logout_blacklists_token(self):
        refresh = RefreshToken.for_user(self.user)
        response = self.client.post(reverse('logout'), {'refresh': str(refresh)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Refreshing with the blacklisted token should now fail
        anon = APIClient()
        response2 = anon.post(reverse('token_refresh'), {'refresh': str(refresh)})
        self.assertEqual(response2.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_without_token_returns_400(self):
        response = self.client.post(reverse('logout'), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 4. Social Auth (Google)
# ---------------------------------------------------------------------------

class SocialAuthTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('social_auth')

    @patch('api.views.http_requests.get')
    def test_google_social_auth_creates_user(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'email': 'googleuser@gmail.com',
            'email_verified': True,
        }
        mock_get.return_value = mock_response

        response = self.client.post(self.url, {'provider': 'google', 'token': 'valid-google-token'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertTrue(User.objects.filter(email='googleuser@gmail.com').exists())

    @patch('api.views.http_requests.get')
    def test_google_social_auth_returns_existing_user(self, mock_get):
        existing = make_user('existing', email='existing@gmail.com')
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'email': 'existing@gmail.com', 'email_verified': True}
        mock_get.return_value = mock_response

        response = self.client.post(self.url, {'provider': 'google', 'token': 'valid-token'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(User.objects.filter(email='existing@gmail.com').count(), 1)

    @patch('api.views.http_requests.get')
    def test_invalid_google_token_denied(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_get.return_value = mock_response

        response = self.client.post(self.url, {'provider': 'google', 'token': 'bad-token'})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unsupported_provider_rejected(self):
        response = self.client.post(self.url, {'provider': 'facebook', 'token': 'some-token'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 5. RBAC — Free tier quota
# ---------------------------------------------------------------------------

class FreeTierQuotaTest(TestCase):

    def setUp(self):
        self.user = make_user('freeuser', email='free@test.com', tier=TIER_FREE)
        self.client = auth_client(self.user)

    def test_free_user_can_create_up_to_limit(self):
        for i in range(10):
            make_url(self.user, short_code=f'code{i}')
        response = self.client.post(reverse('url-create'), {
            'original_url': 'https://eleventh.com'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('10', str(response.data))

    def test_free_user_below_limit_succeeds(self):
        response = self.client.post(reverse('url-create'), {
            'original_url': 'https://first.com'
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# 6. RBAC — Custom alias gate
# ---------------------------------------------------------------------------

class CustomAliasGateTest(TestCase):

    def setUp(self):
        self.free_user = make_user('freeuser2', email='free2@test.com', tier=TIER_FREE)
        self.premium_user = make_user('premuser', email='prem@test.com', tier=TIER_PREMIUM)

    def test_free_user_cannot_use_custom_alias(self):
        client = auth_client(self.free_user)
        response = client.post(reverse('url-create'), {
            'original_url': 'https://google.com',
            'custom_alias': 'my-google',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Premium', str(response.data))

    def test_premium_user_can_use_custom_alias(self):
        client = auth_client(self.premium_user)
        response = client.post(reverse('url-create'), {
            'original_url': 'https://google.com',
            'custom_alias': 'my-special-link',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['short_code'], 'my-special-link')


# ---------------------------------------------------------------------------
# 7. RBAC — Premium analytics access
# ---------------------------------------------------------------------------

class AnalyticsAccessTest(TestCase):

    def setUp(self):
        self.free_user = make_user('freeana', email='freeana@test.com', tier=TIER_FREE)
        self.premium_user = make_user('premana', email='premana@test.com', tier=TIER_PREMIUM)
        self.url_obj = make_url(self.premium_user, short_code='statsurl')

    def test_free_user_cannot_access_analytics(self):
        client = auth_client(self.free_user)
        response = client.get(reverse('url-analytics', kwargs={'short_code': 'statsurl'}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_premium_owner_can_access_analytics(self):
        client = auth_client(self.premium_user)
        response = client.get(reverse('url-analytics', kwargs={'short_code': 'statsurl'}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('click_count', response.data)


# ---------------------------------------------------------------------------
# 8. Ownership (IsOwnerOrReadOnly)
# ---------------------------------------------------------------------------

class OwnershipTest(TestCase):

    def setUp(self):
        self.owner = make_user('owner', email='owner@test.com')
        self.other = make_user('other', email='other@test.com')
        self.url_obj = make_url(self.owner, short_code='ownerurl')

    def test_owner_can_update(self):
        client = auth_client(self.owner)
        response = client.patch(
            reverse('url-detail', kwargs={'short_code': 'ownerurl'}),
            {'original_url': 'https://updated.com'},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_owner_can_delete(self):
        client = auth_client(self.owner)
        response = client.delete(reverse('url-detail', kwargs={'short_code': 'ownerurl'}))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_other_user_cannot_update(self):
        client = auth_client(self.other)
        response = client.patch(
            reverse('url-detail', kwargs={'short_code': 'ownerurl'}),
            {'original_url': 'https://evil.com'},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_user_cannot_delete(self):
        client = auth_client(self.other)
        response = client.delete(reverse('url-detail', kwargs={'short_code': 'ownerurl'}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_can_read_but_not_write(self):
        anon = APIClient()
        # Read is allowed
        get_resp = anon.get(reverse('url-detail', kwargs={'short_code': 'ownerurl'}))
        self.assertNotEqual(get_resp.status_code, status.HTTP_403_FORBIDDEN)
        # Write is denied
        patch_resp = anon.patch(
            reverse('url-detail', kwargs={'short_code': 'ownerurl'}),
            {'original_url': 'https://evil.com'},
        )
        self.assertIn(patch_resp.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])


# ---------------------------------------------------------------------------
# 9. Security headers
# ---------------------------------------------------------------------------

class SecurityHeadersTest(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_x_content_type_options_header(self):
        response = self.client.get('/api/schema/')
        self.assertEqual(response.get('X-Content-Type-Options'), 'nosniff')

    def test_x_frame_options_header(self):
        response = self.client.get('/api/schema/')
        self.assertEqual(response.get('X-Frame-Options'), 'DENY')

    def test_referrer_policy_header(self):
        response = self.client.get('/api/schema/')
        self.assertEqual(response.get('Referrer-Policy'), 'strict-origin-when-cross-origin')

    def test_content_security_policy_header(self):
        response = self.client.get('/api/schema/')
        self.assertIn("default-src 'self'", response.get('Content-Security-Policy', ''))


# ---------------------------------------------------------------------------
# 10. Unauthorized access correctly denied
# ---------------------------------------------------------------------------

class UnauthorizedAccessTest(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_url_create_requires_auth(self):
        response = self.client.post(reverse('url-create'), {
            'original_url': 'https://google.com'
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_url_list_requires_auth(self):
        response = self.client.get(reverse('url-list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_analytics_requires_auth(self):
        owner = make_user('owner3', email='owner3@test.com')
        make_url(owner, short_code='sectest')
        response = self.client.get(reverse('url-analytics', kwargs={'short_code': 'sectest'}))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# 11. Throttle scope is configured
# ---------------------------------------------------------------------------

class ThrottleConfigTest(TestCase):

    def test_login_view_has_throttle_scope(self):
        from api.views import ThrottledTokenObtainPairView
        view = ThrottledTokenObtainPairView()
        self.assertEqual(view.throttle_scope, 'login')

    def test_login_rate_is_configured(self):
        from django.conf import settings
        rates = settings.REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {})
        self.assertIn('login', rates)
        self.assertEqual(rates['login'], '5/minute')
