.PHONY: help init env up up-ui up-legacy up-all down clean test test-api test-api-backends test-server test-libs test-v2 test-v2-unit test-v2-soap test-v2-rest test-v2-e2e-rest test-v2-xt test-v2-xt-soap test-v2-xt-rest logs sync status update train fork

V2_EXEC = docker compose --env-file docker/.env --profile legacy exec -T
V2_E2E_EXEC = docker compose --env-file docker/.env --profile legacy --profile test run --rm --no-deps -T
V2_SOAP_ENV = -e NICTOOL_DATA_PROTOCOL=soap -e NICTOOL_SERVER_HOST=localhost -e NICTOOL_SERVER_PORT=8082 -e NICTOOL_SERVER_PROTOCOL=http -e NICTOOL_TEST_CFG=t/test.cfg
V2_REST_ENV = -e NICTOOL_DATA_PROTOCOL=rest -e NICTOOL_SERVER_HOST=api -e NICTOOL_SERVER_PORT=3000 -e NICTOOL_SERVER_PROTOCOL=http -e NICTOOL_TEST_CFG=t/test-rest.cfg

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

down: env ## Stop all services
	docker compose --env-file docker/.env --profile all down

clean: env ## Stop all and remove volumes
	docker compose --env-file docker/.env --profile all down -v

test: test-api test-libs ## Run v3 API + library tests (requires make up)

test-api: ## Run API tests (requires make up)
	docker compose --env-file docker/.env exec -T api npm test

test-api-backends: ## Run API tests against every data store backend (requires make up)
	@for backend in mysql json toml; do \
		echo "==> api tests, $$backend store"; \
		docker compose --env-file docker/.env exec -T -e NICTOOL_DATA_STORE=$$backend api sh test/run.sh || exit 1; \
	done

test-server: ## Run server tests (requires make up-ui)
	docker compose --env-file docker/.env --profile ui exec -T server npm test

test-libs: ## Run library tests (no running services needed)
	@for lib in validate dns-zone dns-nameserver dns-resource-record; do \
		echo "==> libs/$$lib"; \
		docker run --rm -v $$(pwd)/libs/$$lib:/app -w /app node:22-slim sh -c "npm install --ignore-scripts 2>&1 | tail -1 && npm test"; \
	done

test-v2-unit: ## Run NicTool v2 unit tests with SOAP defaults (requires up-legacy)
	$(V2_EXEC) $(V2_SOAP_ENV) nictool-legacy bash -c 'cd /usr/local/nictool/server && perl Makefile.PL && make test'
	$(V2_EXEC) $(V2_SOAP_ENV) nictool-legacy bash -c 'cd /usr/local/nictool/client && perl Makefile.PL && make test'

test-v2-xt-soap: ## Run all NicTool v2 extended tests through SOAP (requires up-legacy)
	$(V2_EXEC) $(V2_SOAP_ENV) nictool-legacy bash -c 'cd /usr/local/nictool/server && prove -v xt/*.t'

test-v2-xt-rest: ## Run the supported NicTool v2 extended tests through REST (requires up-legacy)
	$(V2_EXEC) $(V2_REST_ENV) nictool-legacy bash -c 'cd /usr/local/nictool/server && prove -v xt/14_permissions.t xt/16_delegation.t xt/20_permission.t'

test-v2-soap: ## Run all NicTool v2 SOAP tests (requires up-legacy)
	$(MAKE) test-v2-unit
	$(MAKE) test-v2-xt-soap

test-v2-rest: ## Run the NicTool v2 REST bridge tests (requires up-legacy)
	$(MAKE) test-v2-xt-rest

test-v2-e2e-rest: ## Run the v2 browser suite through REST (requires up-legacy)
	@user=$$(sed -n "s/^[[:space:]]*username[[:space:]]*=>[[:space:]]*'\([^']*\)'.*/\1/p" NicTool/server/t/test-rest.cfg); \
	password=$$(sed -n "s/^[[:space:]]*password[[:space:]]*=>[[:space:]]*'\([^']*\)'.*/\1/p" NicTool/server/t/test-rest.cfg); \
	test_gid=$$(sed -n "s/^[[:space:]]*test_gid[[:space:]]*=>[[:space:]]*\([0-9][0-9]*\).*/\1/p" NicTool/server/t/test-rest.cfg); \
	if [ -z "$$user" ] || [ -z "$$password" ] || [ -z "$$test_gid" ]; then \
		echo "REST browser test settings are missing; recreate nictool-legacy" >&2; exit 1; \
	fi; \
	$(V2_E2E_EXEC) \
		-e NICTOOL_TEST_USER="$$user" \
		-e NICTOOL_TEST_PASSWORD="$$password" \
		-e NICTOOL_TEST_GID="$$test_gid" \
		v2-e2e

test-v2-xt: ## Run all NicTool v2 extended tests through SOAP (requires up-legacy)
	$(MAKE) test-v2-xt-soap

test-v2: ## Run all NicTool v2 SOAP tests (requires up-legacy)
	$(MAKE) test-v2-soap

logs: env ## Tail all service logs
	docker compose --env-file docker/.env --profile all logs -f

sync: ## Fetch all repos, move clean ones to their manifest pins
	./nt.py sync

status: ## Drift report: pin vs HEAD, dirty files, claimed branches
	./nt.py status

update: ## Check upstream for newer release tags (make update W=1 to write)
	./nt.py update $(if $(W),--write)

train: ## Assemble PR integration branches declared in mani.yaml
	./nt.py train

fork: ## Create GitHub forks and wire 'fork' remotes (optional PART=<name> OWNER=<user|org>)
	./nt.py fork $(OWNER) $(if $(PART),--part $(PART))
