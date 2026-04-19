.PHONY: help install install-dev install-hook test test-live eval lint clean uninstall

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Install
install:       ## bootstrap (no Stop hook, system-friendly)
	./bootstrap.sh

install-hook:  ## bootstrap + install Claude Code Stop hook
	./bootstrap.sh --hook

install-dev:   ## editable install with dev deps + run tests
	./bootstrap.sh --dev

##@ Tests
test:          ## offline stub tests (no API key needed) — 21 cases
	cd packages/ringwood && python3 -m pytest tests/ -v

test-live:     ## LIVE Claude API calls — requires ANTHROPIC_API_KEY
	cd packages/ringwood && python3 -m pytest tests_live/ -v -s

eval:          ## golden scenario suite (compounding, contradiction, retrieval)
	python3 scripts/eval.py

##@ Quality
lint:          ## ruff + pyright if available
	ruff check packages/ringwood/src packages/ringwood-mcp/src || true

##@ Cleanup
clean:         ## remove build artifacts
	rm -rf packages/*/build packages/*/dist packages/*/*.egg-info
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name .pytest_cache -type d -exec rm -rf {} + 2>/dev/null || true

uninstall:     ## remove local installs (preserves wiki data)
	python3 -m pip uninstall -y ringwood ringwood-mcp || true
	rm -rf .venv
	@echo "✓ uninstalled. Your wiki data at ~/ringwood is untouched."
