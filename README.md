Module 5 – Fundamentals, Architecture & Containerization
Overview

This module establishes the foundation of the URL Shortener microservice. It focuses on building a clean Django architecture, implementing core URL shortening logic, and setting up Docker for consistent deployment.

Features
Django project with modular structure (core, shortener, api)
URL shortening (generate short codes)
URL redirection (HTTP 302)
REST API with validation
Dockerized environment (PostgreSQL + Django)
Auto-generated API documentation (Swagger/OpenAPI)
Core Implementation
Model
original_url
short_code (unique)
Short Code Generator
Random 6-character alphanumeric string
Endpoints
POST /api/urls/ → Create short URL
GET /<short_code>/ → Redirect to original URL
DevOps Setup
Dockerfile (multi-stage build)
docker-compose (web + db)
Environment variables using django-environ
Outcome

A working MVP that can shorten URLs and redirect users reliably in a containerized environment.
