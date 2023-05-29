SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
# .DELETE_ON_ERROR:
MAKEFLAGS = --warn-undefined-variables
MAKEFLAGS += --no-builtin-rules


# Override PWD so that it's always based on the location of the file and **NOT**
# based on where the shell is when calling `make`. This is useful if `make`
# is called like `make -C <some path>`
PWD := $(realpath $(dir $(abspath $(firstword $(MAKEFILE_LIST)))))

WORKTREE_ROOT := $(shell git rev-parse --show-toplevel 2> /dev/null)


# Using $$() instead of $(shell) to run evaluation only when it's accessed
# https://unix.stackexchange.com/a/687206
pytest = pytest
py = $$(if [ -d $(PWD)/'venv' ]; then echo $(PWD)/"venv/bin/python3"; else echo "python3"; fi)
pip = $(py) -m pip

PY_PATHS := $(PWD)
pypath := python3 -c 'import sys, pathlib as p; print(":".join([str(p.Path(x).resolve()) for x in sys.argv[1:]]))'
export PYTHONPATH=$(shell $(pypath) $(PY_PATHS))
export DJANGO_SETTINGS_MODULE=tests.settings

.PHONY: test-pypath
test-pypath: export PYTHONPATH = $(shell $(pypath) $(PY_PATHS))
test-pypath:
	@python3 -c 'import sys; print(sys.path)'



.DEFAULT_GOAL := help
.PHONY: help
help: ## Display this help section
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z]+.*:.*?##[a-zA-Z0-9 ]*/ {printf "\033[36m%-38s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

venv: requirements.txt  ## Build the virtual environment
	$(py) -m venv venv
	$(pip) install -U pip setuptools wheel build
	$(pip) install -U -r requirements.txt
	touch venv

test: tests  ## Run the test suite
	$(pytest) tests

release: VERSION
	@cp VERSION VERSION-
	@awk 'BEGIN {FS="." } { print "$$1.$$2.$$3+1" }' VERSION- > xxx
	@git add .
	@git commit -m "Version bump"
