.PHONY: init pull nginx-reload infisical-up infisical-down \
        certrenew-run certrenew-dry-run \
        rss-curator-up rss-curator-down \
        rarclean-up rarclean-down \
        dotfiles help

REPO_DIR      := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
INFISICAL_DIR := $(REPO_DIR)infisical
INFISICAL_URL := https://infisical.iillmaticc.link
APPS_DIR      := /mnt/cell_block_d/apps

# Helper: run a command with secrets injected from an app's .env
# Usage: $(call infisical-run,<app>,<projectId>,<cmd...>)
define infisical-run
	set -a && . $(APPS_DIR)/$(1)/.env && set +a && \
	infisical run \
	  --domain=$(INFISICAL_URL) \
	  --projectId=$(2) \
	  --env=$${INFISICAL_ENV:-prod} \
	  --token=$${INFISICAL_TOKEN} \
	  -- $(3)
endef

## Initialize submodules after a fresh clone
init:
	git submodule update --init --recursive

## Pull latest commits for all submodules (advances pinned commits)
pull:
	git submodule foreach git pull origin main
	git add .
	git commit -m "chore: advance submodule pins" || true

## Reload nginx-proxy config (pull submodules then signal nginx)
## Requires docker CLI access — run from provisioning container or host
nginx-reload: pull
	docker kill --signal=HUP nginx-proxy

## Start Infisical (run from host or provisioner — requires .env to exist)
infisical-up:
	docker compose -f $(INFISICAL_DIR)/docker-compose.yml --env-file $(INFISICAL_DIR)/.env up -d

## Stop Infisical
infisical-down:
	docker compose -f $(INFISICAL_DIR)/docker-compose.yml --env-file $(INFISICAL_DIR)/.env down

## Run certrenew (dry-run — prints plan, executes nothing)
certrenew-dry-run:
	docker compose -f $(REPO_DIR)certrenew/docker-compose.yaml run --rm certrenew --dry-run

## Run certrenew (live cert renewal)
certrenew-run:
	docker compose -f $(REPO_DIR)certrenew/docker-compose.yaml run --rm certrenew

## Deploy rss-curator stack with secrets from Infisical
rss-curator-up:
	$(call infisical-run,rss-curator,$$(. $(APPS_DIR)/rss-curator/.env && echo $$INFISICAL_PROJECT_ID),\
	  docker compose -f $(REPO_DIR)rss-curator/docker-compose.truenas.yml up -d)

## Stop rss-curator stack
rss-curator-down:
	docker compose -f $(REPO_DIR)rss-curator/docker-compose.truenas.yml down

## Deploy rarclean with secrets from Infisical
rarclean-up:
	$(call infisical-run,rarclean,$$(. $(APPS_DIR)/rarclean/.env && echo $$INFISICAL_PROJECT_ID),\
	  docker compose -f $(REPO_DIR)rarclean/docker-compose.truenas.yml up -d)

## Stop rarclean
rarclean-down:
	docker compose -f $(REPO_DIR)rarclean/docker-compose.truenas.yml down

## Apply dotfiles for truenas_admin (run as truenas_admin on host, not inside provisioner)
dotfiles:
	bash $(REPO_DIR)dotfiles/bootstrap.sh

## Show available targets
help:
	@grep -E '^##' Makefile | sed 's/## //'
