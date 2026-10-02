# SayyaraDMS developer commands (Linux/macOS/CI). On Windows use scripts/dev.ps1.
API := apps/api
WEB := apps/web
PY  := $(API)/.venv/bin/python

.PHONY: setup env db-start db-reset db-test api web dev test test-api test-web e2e lint

setup:            ## Install API and web dependencies
	python3.12 -m venv $(API)/.venv && $(PY) -m pip install -e "$(API)[dev]"
	cd $(WEB) && npm ci && npx playwright install chromium

db-start:         ## Start local Supabase (Postgres, Auth, REST, Storage, Mailpit) and write apps/api/.env
	npx supabase start -x studio,imgproxy,vector,logflare,edge-runtime,realtime,supavisor,postgres-meta
	$(MAKE) env

env:              ## apps/api/.env from the template + local secret key from the running stack
	test -f $(API)/.env || cp $(API)/.env.example $(API)/.env
	key=$$(npx supabase status -o env | grep '^SECRET_KEY=' | cut -d= -f2- | tr -d '"'); \
	test -n "$$key" || { echo "Local Supabase is not running; run make db-start"; exit 1; }; \
	sed -i.bak "s|^SUPABASE_SERVICE_ROLE_KEY=.*|SUPABASE_SERVICE_ROLE_KEY=$$key|" $(API)/.env && rm -f $(API)/.env.bak

db-reset:         ## Re-apply all migrations and the local seed
	npx supabase db reset

db-test:          ## pgTAP: RLS, tenant isolation, permissions, audit
	npx supabase test db

api:              ## Run the API on :8000
	cd $(API) && .venv/bin/python -m uvicorn app.main:create_app --factory --reload --port 8000

web:              ## Run Angular on :4200
	cd $(WEB) && npm start

dev:              ## Supabase + API + web (API and web in the background)
	$(MAKE) db-start
	$(MAKE) api & $(MAKE) web

test-api:
	cd $(API) && .venv/bin/python -m pytest

test-web:
	cd $(WEB) && npm test

e2e:
	cd $(WEB) && npx playwright test

test: db-test test-api test-web e2e

lint:
	cd $(API) && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy
	cd $(WEB) && npm run lint && npm run lint:styles
