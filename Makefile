.PHONY: help init env up up-ui up-legacy up-all down clean test test-all test-api test-api-backends stress-api test-server test-libs test-v2 test-v2-unit test-v2-soap test-v2-rest test-v2-e2e-rest test-v2-xt test-v2-xt-soap test-v2-xt-rest logs sync status update train fork

SHELL := bash

# node exits zero for skipped and cancelled tests, so preserve the pipeline
# status and inspect its summary before calling a suite successful.
define node_suite
out=$$(mktemp); $(1) 2>&1 | tee $$out; rc=$${PIPESTATUS[0]}; \
awk '/^(ℹ|\#) (fail|skipped|cancelled) [1-9]/ { bad = 1 } END { exit bad }' $$out || rc=1; \
rm -f $$out; [ $$rc -eq 0 ]
endef

define node_suite_warn_skips
out=$$(mktemp); $(1) 2>&1 | tee $$out; rc=$${PIPESTATUS[0]}; \
awk '/^(ℹ|\#) (fail|cancelled) [1-9]/ { bad = 1 } /^(ℹ|\#) skipped [1-9]/ { print "WARNING: " $$0 > "/dev/stderr" } END { exit bad }' $$out || rc=1; \
rm -f $$out; [ $$rc -eq 0 ]
endef

V2_EXEC = docker compose --env-file docker/.env --profile legacy exec -T
V2_E2E_EXEC = docker compose --env-file docker/.env --profile legacy --profile test run --rm --no-deps -T
V2_SOAP_ENV = -e NICTOOL_DATA_PROTOCOL=soap -e NICTOOL_SERVER_HOST=localhost -e NICTOOL_SERVER_PORT=8082 -e NICTOOL_SERVER_PROTOCOL=http -e NICTOOL_TEST_CFG=t/test.cfg
V2_REST_ENV = -e NICTOOL_DATA_PROTOCOL=rest -e NICTOOL_SERVER_HOST=api -e NICTOOL_SERVER_PORT=3000 -e NICTOOL_SERVER_PROTOCOL=http -e NICTOOL_TEST_CFG=t/test-rest.cfg
NICTOOL_LIBS_SOURCE ?= $(CURDIR)/libs
NICTOOL_VALIDATE_SOURCE ?= $(NICTOOL_LIBS_SOURCE)/validate
NICTOOL_DNS_ZONE_SOURCE ?= $(NICTOOL_LIBS_SOURCE)/dns-zone
NICTOOL_DNS_NAMESERVER_SOURCE ?= $(NICTOOL_LIBS_SOURCE)/dns-nameserver
NICTOOL_DNS_RESOURCE_RECORD_SOURCE ?= $(NICTOOL_LIBS_SOURCE)/dns-resource-record
LIB_TEST_MOUNTS = -v "$(NICTOOL_LIBS_SOURCE):/libs" -v "$(NICTOOL_VALIDATE_SOURCE):/libs/validate" -v "$(NICTOOL_DNS_ZONE_SOURCE):/libs/dns-zone" -v "$(NICTOOL_DNS_NAMESERVER_SOURCE):/libs/dns-nameserver" -v "$(NICTOOL_DNS_RESOURCE_RECORD_SOURCE):/libs/dns-resource-record"

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

# The one-off v2 browser runner lives outside the all profile so up-all
# never starts it; down and clean still have to cover it.
down: env ## Stop all services
	docker compose --env-file docker/.env --profile all --profile test down

clean: env ## Stop all and remove volumes
	docker compose --env-file docker/.env --profile all --profile test down -v

test: test-api test-libs ## Run v3 API + library tests (requires make up)

test-all: test test-api-backends test-v2-rest test-v2-xt test-v2-e2e-rest ## Every suite, v3 and v2, in order (requires make up-legacy)

test-api: ## Run API tests (requires make up)
	@$(call node_suite,docker compose --env-file docker/.env exec -T api npm test)

test-api-backends: ## Run API tests against every data store backend (requires make up)
	@for backend in mysql json toml; do \
		echo "==> api tests, $$backend store"; \
		( $(call node_suite,docker compose --env-file docker/.env exec -T -e NICTOOL_DATA_STORE=$$backend api sh test/run.sh) ) || exit 1; \
	done

stress-api: env ## Repeat API tests under a runtime image (RUNTIME=node:24 N=25; requires make up)
	@RUNTIME="$(or $(RUNTIME),node:24)" N="$(or $(N),25)" ./docker/stress-api.sh

test-server: ## Run server tests (requires make up-ui)
	docker compose --env-file docker/.env --profile ui exec -T server npm test

test-libs: ## Run library tests (no running services needed)
	@for lib in validate dns-zone dns-resource-record; do \
		echo "==> libs/$$lib"; \
		( $(call node_suite,docker run --rm $(LIB_TEST_MOUNTS) -w /libs/$$lib node:22-slim sh -c "npm install --ignore-scripts 2>&1 | tail -1 && npm test") ) || exit 1; \
	done
	@echo "==> libs/dns-nameserver"
	@$(call node_suite_warn_skips,docker run --rm $(LIB_TEST_MOUNTS) -w /libs/dns-nameserver node:22-slim sh -c "npm install --ignore-scripts 2>&1 | tail -1 && npm test")

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
