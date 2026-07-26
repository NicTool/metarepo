.PHONY: help init env up up-ui up-legacy up-all down clean test test-api test-server test-libs test-v2 test-v2-xt logs sync status update train fork

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

init: ## Clone all repos and check out manifest pins
	./nt.py sync

env: ## Generate docker/.env with random passwords
	./docker/generate-env.sh

# Stop containers from any compose project that hold ports we need.
# Parses docker-compose.yml defaults + docker/.env overrides, then
# checks each host port.  Containers belonging to THIS project are
# skipped (compose up will manage them).
check-ports:
	@PROJECT=$$(basename "$$PWD"); \
	PORTS=""; \
	if [ -f docker/.env ]; then . docker/.env; fi; \
	PORTS="$${DB_PORT:-3307} $${API_PORT:-3000} $${SERVER_PORT:-8080} $${LEGACY_HTTP_PORT:-8082} $${LEGACY_HTTPS_PORT:-8443}"; \
	for port in $$PORTS; do \
		cid=$$(docker ps -q --filter "publish=$$port" 2>/dev/null | head -1); \
		[ -z "$$cid" ] && continue; \
		name=$$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$$cid" 2>/dev/null); \
		[ "$$name" = "$$PROJECT" ] && continue; \
		echo "Port $$port is held by container $$cid (project: $${name:-unknown}), stopping it..."; \
		docker stop "$$cid" >/dev/null; \
	done

up: env check-ports ## Start db + api (v3 core)
	docker compose --env-file docker/.env up --build -d --wait

up-ui: env check-ports ## Start db + api + server (v3 full stack)
	docker compose --env-file docker/.env --profile ui up --build -d --wait

up-legacy: env check-ports ## Start db + legacy Perl NicTool
	docker compose --env-file docker/.env --profile legacy up --build -d --wait

up-all: env check-ports ## Start everything
	docker compose --env-file docker/.env --profile all up --build -d --wait

down: ## Stop all services
	docker compose --profile all down

clean: ## Stop all and remove volumes
	docker compose --profile all down -v

test: test-api test-libs ## Run v3 API + library tests (requires make up)

test-api: ## Run API tests (requires make up)
	docker compose --env-file docker/.env exec -T api npm test

test-server: ## Run server tests (requires make up-ui)
	docker compose --env-file docker/.env --profile ui exec -T server npm test

test-libs: ## Run library tests (no running services needed)
	@for lib in validate dns-zone dns-nameserver dns-resource-record; do \
		echo "==> libs/$$lib"; \
		docker run --rm -v $$(pwd)/libs/$$lib:/app -w /app node:22-slim sh -c "npm install --ignore-scripts 2>&1 | tail -1 && npm test"; \
	done

test-v2-xt: ## Run NicTool v2 permission & delegation tests (requires up-legacy)
	docker compose --env-file docker/.env --profile legacy exec -T nictool-legacy bash -c 'cd /usr/local/nictool/server && prove -v xt/*.t'

test-v2: ## Run all NicTool v2 tests (requires up-legacy)
	docker compose --env-file docker/.env --profile legacy exec -T nictool-legacy bash -c 'cd /usr/local/nictool/server && perl Makefile.PL && make test'
	docker compose --env-file docker/.env --profile legacy exec -T nictool-legacy bash -c 'cd /usr/local/nictool/client && perl Makefile.PL && make test'
	$(MAKE) test-v2-xt

logs: ## Tail all service logs
	docker compose --profile all logs -f

sync: ## Fetch all repos, move clean ones to their manifest pins
	./nt.py sync

status: ## Drift report: pin vs HEAD, dirty files, claimed branches
	./nt.py status

update: ## Check upstream for newer release tags (make update W=1 to write)
	./nt.py update $(if $(W),--write)

train: ## Assemble PR integration branches declared in mani.yaml
	./nt.py train

fork: ## Create GitHub forks and wire 'fork' remotes (make fork OWNER=<user|org>)
	./nt.py fork $(OWNER)
