HOST ?= localhost
export VOICE_PIPELINE_HOST=$(HOST)

.PHONY: smoke test test-integration test-unit

smoke:
	pytest tests/integration/test_health.py -v --timeout=10

test-integration:
	pytest tests/integration/ -v

test-unit:
	cd frontend && npx vitest run
	cd agent && pytest tests/ -v

test: test-unit test-integration
