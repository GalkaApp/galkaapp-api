SWIFT_OUT = ../TodoAp/Galka/Api/ApiTypes.swift
PY = .venv/bin/python

.PHONY: run test swift-types openapi-json

run:
	.venv/bin/uvicorn app.main:app --reload --port 8600

test:
	.venv/bin/pytest

# Regenerate Swift Codable types in the app from the FastAPI OpenAPI schema.
swift-types:
	$(PY) scripts/generate_swift_types.py $(SWIFT_OUT)

# Dump the raw OpenAPI spec (for other tooling).
openapi-json:
	$(PY) -c "import json; from app.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > openapi.json
