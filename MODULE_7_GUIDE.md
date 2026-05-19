# Module 7: Authentication & Authorization Guide

This guide documents the step-by-step process of implementing Module 7 for our Enterprise-Grade URL Shortener Microservice. It explains what we did, how we did it, and the exact commands used so you can review and demonstrate the implementation.

## Overview
Module 7 focuses on securing our API endpoints using JSON Web Tokens (JWT) and implementing Role-Based Access Control (RBAC). The key requirements are:
1. **JWT Authentication**: Secure user login and registration.
2. **Rate Limiting**: Throttling login requests to prevent brute force attacks (e.g., 5 attempts per minute).
3. **RBAC (Role-Based Access Control)**: Restricting actions based on the user's tier (Free vs Premium) and ownership.

---

## Step 1: Branch Creation
We started by creating and switching to a new branch for Module 7.
**Command used:**
```bash
git checkout -b module_7
```

---

## Step 2: Install JWT Library
We need to install the `djangorestframework-simplejwt` package, which is the industry standard for handling JWT authentication with Django REST Framework.

**Commands used:**
```bash
# Install the package using pip in the active virtual environment
venv\Scripts\python -m pip install djangorestframework-simplejwt

# Update the requirements.txt to freeze the dependency
venv\Scripts\python -m pip freeze > backend\requirements.txt
```

### Configuration
We then opened `backend/config/settings.py` and updated `INSTALLED_APPS` and `REST_FRAMEWORK` to enforce JWT and Throttling logic.

**What we did:**
1. Added `'rest_framework_simplejwt'` to `INSTALLED_APPS`.
2. Added `REST_FRAMEWORK` block:
   - Configured `DEFAULT_AUTHENTICATION_CLASSES` to use `JWTAuthentication` validating every JWT token automatically.
   - Configured `DEFAULT_THROTTLE_CLASSES` to throttle requests based on User or Anon IPs.
   - Configured `DEFAULT_THROTTLE_RATES` to allow 5 login attempts per minute (`login: 5/minute`).

---

## Step 3: JWT Validation & ORM Organization
We configured the JWT settings and optimized our ORM models for better organization and performance.

### JWT Validation & Secret Key
We added the `SIMPLE_JWT` configuration in `settings.py`. 
*   **Validation**: Every incoming request with a `Bearer` token is automatically validated against its expiration and signature.
*   **Secret Key**: We explicitly set `'SIGNING_KEY': SECRET_KEY`. This ensures that the system uses your project's unique secret key to decode and verify the tokens.

### ORM Meta Classes
To reduce boilerplate and improve code organization, we added `Meta` classes to our models (`User`, `URL`, `Click`, `Tag`). 
*   **Organization**: Defined `verbose_name` and `ordering` to ensure consistent behavior across the application and Django Admin.
*   **Performance**: Added database indexes via the `Meta` class to the `URL` model for faster lookups on `short_code`.

---

## Step 4: Implement Permissions (RBAC)
We created custom permission classes in `api/permissions.py`.
*   `IsOwnerOrReadOnly`: Ensures only the creator of a short link can update or delete it.
*   `IsPremiumUser`: Restricts access to advanced features and analytics to users in the 'Premium' tier.

---

## Step 5: Implement Views & URLs
We implemented the endpoints for registration and secured our existing URL creation logic.

### Registration & Login
*   **Registration**: Created `UserRegisterView` which uses the `UserRegistrationSerializer` to create new user accounts.
*   **Login**: Utilized `TokenObtainPairView` from `simplejwt` to exchange credentials for Access/Refresh tokens.

### URL Operations (Secured)
*   **Ownership**: The `URLCreateView` now automatically assigns the `owner` to the logged-in user.
*   **Access Control**: Used `permissions.IsAuthenticated` to ensure only logged-in users can create links.
*   **Versioning**: Updated the project URLs to use the `/api/v1/` prefix.

**Key Endpoints Added:**
*   `POST /api/v1/auth/register/`
*   `POST /api/v1/auth/login/` (Token Obtain)
*   `POST /api/v1/auth/refresh/` (Token Refresh)
*   `GET /api/v1/urls/list/` (List only your own URLs)
*   `GET /api/v1/urls/<short_code>/` (Retrieve/Update/Delete your own URLs)
*   `GET /api/v1/analytics/<short_code>/` (Detailed stats - **Premium Only**)

---

## Step 6: Apply Rate Limiting (Security)
To prevent brute-force attacks, we applied the `login: 5/minute` throttle rate to the authentication endpoint.
*   **Implementation**: Subclassed `TokenObtainPairView` as `ThrottledTokenObtainPairView` and set `throttle_scope = 'login'`.
*   **Verification**: If a user attempts to login more than 5 times in 60 seconds, the API will return `429 Too Many Requests`.

---

## Final Review
Module 7 is now complete. The API is secured with industry-standard JWT authentication, and business rules for Free vs Premium users are enforced at the serializer level.

**What to demonstrate:**
1.  **Unauthorized Access**: Try creating a URL without a token (should return 401).
2.  **Tier Limits**: Try creating more than 10 URLs as a 'Free' user (should return a validation error).
3.  **Custom Aliases**: Try setting a `custom_alias` as a 'Free' user (should return a validation error).
4.  **Ownership**: Create a link with User A and try to update it with User B (should return 403 Forbidden).
