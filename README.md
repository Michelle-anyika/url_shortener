# Enterprise-Grade URL Shortener - Module 5

This repository contains a production-ready, highly scalable microservice for shortening URLs. The current branch focuses on **Module 5: Fundamentals, Architecture & Containerization**, establishing a solid architectural foundation, a clean dependency-injected design, and containerization.

---

## 1. Architecture & Design Patterns

To meet enterprise requirements, this project decouples business logic, API presentation, and database persistence using the following design principles:

### A. Dependency Injection (DI)
The application views depend on an abstract service interface rather than concrete model queries.
* **Interface**: `BaseURLService` in `shortener/services.py` defines the business contract.
* **Implementation**: `URLService` in `shortener/services.py` implements the DB actions and unique key generation.
* **Injection**: Dependencies are injected into the Django Class-Based Views (`URLCreateView`, `URLRedirectView`) using the `as_view()` initialization property in `urls.py`. This ensures full testability and mockability of views.

### B. Factory Pattern
We isolate object creation logic into a dedicated Factory layer to ensure flexibility:
* **`ShortCodeGeneratorFactory`**: Standardizes how unique short keys are generated, allowing easy transition to alternate hash/random algorithms.
* **`URLServiceFactory`**: Orchestrates instantiating the service layer and injecting the default generator function.

---

## 2. API Endpoint Specifications

The microservice exposes a RESTful API with automated OpenAPI specifications:

| Method | Endpoint | Description | Status Codes |
| :--- | :--- | :--- | :--- |
| **POST** | `/api/urls/` | Create a shortened URL from a long URL. | `201 Created`, `400 Bad Request` |
| **GET** | `/<short_code>/` | Redirection endpoint to redirect client to target URL. | `302 Found`, `404 Not Found` |

### Swagger / OpenAPI UI
Interactive documentation is available at:
* **Swagger UI**: `/api/docs/`
* **Raw Schema**: `/api/schema/`

---

## 3. DevOps & Containerization

### A. Multi-Stage Dockerfile
To maximize security and reduce image footprint, the `backend/Dockerfile` is structured as a two-stage build:
1. **Builder Stage**: Installs compiler tools (`gcc`, `libpq-dev`), builds dependencies, and packages them into Python wheels.
2. **Runner Stage**: Installs the runtime library `libpq5`, extracts compiled wheels, registers a non-root system user (`app`), and executes the Django runtime securely.

### B. Startup Synchronization (`wait_for_db.py`)
To prevent container startup race conditions (where Django attempts to connect before PostgreSQL has fully booted up), we created a custom, platform-independent synchronization script. It continuously checks for a successful PostgreSQL port response before allowing the Django migration runner to run.

---

## 4. How to Run the Project

### Environment Variables
First, copy the environment variable template:
```bash
cp .env.example .env
```

### Docker Compose
Run the entire service stack with:
```bash
docker-compose up --build
```
This command will:
1. Initialize the PostgreSQL 15 database service.
2. Build the Django web runtime container.
3. Automatically wait for PostgreSQL to be ready.
4. Run Django migrations.
5. Launch the Gunicorn/Django server at `http://localhost:8000/`.

### Run Tests Locally
To run the automated suite locally:
```bash
cd backend
venv\Scripts\python -m pytest
```
