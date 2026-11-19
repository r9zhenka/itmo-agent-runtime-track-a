PYTHON ?= python3
DOCKER ?= docker
PAIR ?= custom+replay
.PHONY: init up down client test-ci check-all test-ui test-infra test-docker test-b6-docker test-hardening measure-sandbox baf-smoke baf contracts
init:
	$(PYTHON) -m scripts.init
up:
	$(DOCKER) compose up --build -d --wait
down:
	$(DOCKER) compose down -v
client:
	$(PYTHON) -m client gui
test-ci:
	$(PYTHON) -m scripts.validate
check-all:
	$(PYTHON) -m scripts.check_all $(CHECK_ARGS)
test-ui:
	$(PYTHON) -m unittest tests.test_client -v
test-infra:
	$(PYTHON) -m unittest tests.test_protocol tests.test_runtime tests.test_engine -v
test-docker:
	$(PYTHON) -m scripts.docker_check
test-b6-docker:
	$(PYTHON) -m scripts.check_b6
test-hardening:
	$(PYTHON) -m scripts.hardening_check
measure-sandbox:
	$(PYTHON) -m scripts.measure_sandbox
baf-smoke:
	$(PYTHON) -m scripts.benchmark --smoke --pair $(PAIR)
baf:
	$(PYTHON) -m scripts.benchmark --pair $(PAIR) --repeats 1
contracts:
	$(PYTHON) -m scripts.export_contracts
