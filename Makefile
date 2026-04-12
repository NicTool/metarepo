.PHONY: help init install env up up-ui up-legacy up-all down clean test test-v2 test-v2-xt logs sync fork

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

init: ## Clone submodules and install deps
	git submodule update --init --recursive
	$(MAKE) install

install: ## Install all Node.js dependencies via pnpm
	pnpm install

env: ## Generate docker/.env with random passwords
	./docker/generate-env.sh

up: env ## Start db + api (v3 core)
	docker compose --env-file docker/.env up --build -d --wait

up-ui: env ## Start db + api + server (v3 full stack)
	docker compose --env-file docker/.env --profile ui up --build -d --wait

up-legacy: env ## Start db + legacy Perl NicTool
	docker compose --env-file docker/.env --profile legacy up --build -d --wait

up-all: env ## Start everything
	docker compose --env-file docker/.env --profile all up --build -d --wait

down: ## Stop all services
	docker compose --profile all down

clean: ## Stop all and remove volumes
	docker compose --profile all down -v

test: ## Run all Node.js tests
	pnpm test

test-v2-xt: ## Run NicTool v2 permission & delegation tests (requires up-legacy)
	docker compose --env-file docker/.env --profile legacy exec -T nictool-legacy bash -c 'cd /usr/local/nictool/server && prove -v xt/*.t'

test-v2: ## Run all NicTool v2 tests (requires up-legacy)
	docker compose --env-file docker/.env --profile legacy exec -T nictool-legacy make -C /usr/local/nictool/server test
	docker compose --env-file docker/.env --profile legacy exec -T nictool-legacy make -C /usr/local/nictool/client test
	$(MAKE) test-v2-xt

logs: ## Tail all service logs
	docker compose --profile all logs -f

sync: ## Update all submodules to latest from their tracked branch
	git submodule update --remote --merge

fork: ## Fork all upstream repos into your GitHub account and repoint submodules
	@user=$$(gh api user --jq .login) || { echo "Run 'gh auth login' first"; exit 1; }; \
	echo "Forking repos into $$user's account..."; \
	git config -f .gitmodules --get-regexp '\.url$$' | while read key url; do \
		name=$$(echo "$$key" | sed 's/submodule\.\(.*\)\.url/\1/'); \
		upstream=$$(echo "$$url" | sed 's|.*github.com/||; s|\.git$$||'); \
		echo "==> $$upstream"; \
		gh repo fork "$$upstream" --clone=false 2>/dev/null || true; \
		fork_url="https://github.com/$$user/$$(basename $$upstream).git"; \
		git submodule set-url "$$name" "$$fork_url"; \
		(cd "$$name" && \
			git remote set-url origin "$$fork_url" && \
			git remote add upstream "$$url" 2>/dev/null || \
			git remote set-url upstream "$$url"); \
	done; \
	echo "Done. 'origin' is your fork, 'upstream' is NicTool."
