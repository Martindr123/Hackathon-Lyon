# Codex Agent Instructions for This Repository

This file provides instructions for you, the Codex agent, on how to work with this codebase.

## Project Architecture

This project follows **Clean Architecture** with **CQRS** (Command Query Responsibility Segregation). A fundamental rule is that **dependencies only point inwards**, from outer layers to inner layers.

- **`domain`**: The core. Contains business entities and logic. It has no dependencies on other layers.
- **`application`**: Orchestrates domain logic using commands and queries. Depends only on `domain`.
- **`api`**: The entry point for external requests (FastAPI). Depends on `application` and `domain`.
- **`infrastructure`**: Implements external concerns like databases and services. Depends on `application` and `domain` (via interfaces).

The main entry point is `main.py`. For more specific guidance on each layer, refer to the `AGENTS.md` file within that layer's directory (e.g., `src/api/AGENTS.md`).

## Core Technologies

This project uses the following technologies:
- **FastAPI** with **Uvicorn** for the web layer.
- **Pydantic** for data validation and models.
- **MediatR** to implement the mediator pattern for CQRS.
- **SQLAlchemy** (`asyncio`) and **aioodbc** for database access.
- **python-jose** and **MSAL** for authentication.
- **Pytest** (with `pytest-asyncio`) for testing.
- **Ruff** for linting and formatting.
- **azure-identity** for Azure integrations.

Dependencies are defined in `requirements.txt`. Configuration for `ruff` and `pytest` is in `pyproject.toml`.

## Code Quality: Programmatic Checks

You MUST run these checks after making any changes to ensure code quality.

### Linting & Formatting

This project uses **Ruff**. To format and lint the code, run the following commands from the project root:

```bash
ruff format .
ruff check . --fix
```

Alternatively, you can use the provided PowerShell script:

```powershell
.\\scripts\\format.ps1
```

### Testing

This project uses **Pytest**. You MUST run the full test suite after making any changes. Execute the following command from the project root:

```bash
pytest tests/
``` 