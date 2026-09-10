SHELL := /bin/bash
CONFIG ?= config/local.yml
VENV := .venv
PY := $(VENV)/bin/python
ANSIBLE := $(VENV)/bin/ansible-playbook

.PHONY: bootstrap syntax validate provision prepare-tls configure benchmark report campaign-report destroy clean

bootstrap:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -U pip
	$(VENV)/bin/pip install -r requirements.txt
	$(VENV)/bin/ansible-galaxy collection install -r collections/requirements.yml

syntax:
	$(ANSIBLE) playbooks/configure.yml --syntax-check -e @$(CONFIG)

validate: syntax
	$(PY) scripts/validate_config.py $(CONFIG)
	$(ANSIBLE) playbooks/validate.yml -e @$(CONFIG)

provision: validate
	$(ANSIBLE) playbooks/provision.yml -e @$(CONFIG)
	$(ANSIBLE) playbooks/prepare_tls.yml -e @$(CONFIG)
	$(ANSIBLE) playbooks/configure.yml -e @$(CONFIG)

prepare-tls:
	$(ANSIBLE) playbooks/prepare_tls.yml -e @$(CONFIG)

configure: prepare-tls
	$(ANSIBLE) playbooks/configure.yml -e @$(CONFIG)

benchmark:
	$(PY) scripts/benchmark.py --config $(CONFIG)

report:
	$(PY) scripts/compare.py results

campaign-report:
	$(PY) scripts/compare_campaigns.py results $(CAMPAIGN_REPORT_ARGS)

destroy:
	$(ANSIBLE) playbooks/destroy.yml -e @$(CONFIG)

clean:
	rm -rf state/* results/*
	touch state/.gitkeep results/.gitkeep

