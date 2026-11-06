PYTHON ?= python3
DOCKER ?= docker
PAIR ?= custom+replay
.PHONY: init up down client test-ci test-ui test-infra test-docker baf-smoke baf contracts
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
test-ui:
	$(PYTHON) -m unittest tests.test_client -v
test-infra:
	$(PYTHON) -m unittest tests.test_protocol tests.test_runtime tests.test_engine -v
test-docker:
	$(PYTHON) -m scripts.docker_check
baf-smoke:
	$(PYTHON) -m scripts.benchmark --smoke --pair $(PAIR)
baf:
	$(PYTHON) -m scripts.benchmark --pair $(PAIR) --repeats 1
contracts:
	$(PYTHON) -m scripts.export_contracts
