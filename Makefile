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

# --- containers --------------------------------------------------------------

IMAGE := git.home.fanyagin.ru/galka/galka-api:main
# Set CTX=prod to drive the production daemon over SSH instead of the local one.
CTX ?= default
COMPOSE := docker --context $(CTX) compose

image:
	docker build -t $(IMAGE) .

# Bring the whole stack up against the tag compose pulls. Locally this is the
# rehearsal for a deploy; with CTX=prod it is the deploy.
up: image
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail 100

ps:
	$(COMPOSE) ps

# What CI runs between build and deploy: the tests inside the built image.
image-test: image
	docker run --rm $(IMAGE) pytest -q

# Deploy by hand, when you would rather not push. Same commands as the CI job.
deploy:
	docker --context prod compose pull
	docker --context prod compose up -d --remove-orphans
	docker --context prod compose ps

.PHONY: image up down logs ps image-test deploy
