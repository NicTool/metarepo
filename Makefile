.PHONY: help init install env up up-ui up-legacy up-all down clean test logs sync

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
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

logs: ## Tail all service logs
	docker compose --profile all logs -f

sync: ## Fetch upstream changes for all submodules
	@for dir in NicTool api server libs/dns-zone libs/validate libs/dns-nameserver libs/dns-resource-record; do \
		echo "==> Syncing $$dir"; \
		(cd $$dir && git fetch upstream && git merge upstream/main --no-edit); \
	done
