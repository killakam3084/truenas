.PHONY: init pull nginx-reload infisical-up infisical-down \
        certrenew-run certrenew-dry-run \
        rss-curator-up rss-curator-down \
        rarclean-up rarclean-down \
        qbittorrent-up qbittorrent-down \
        vuetorrent-install \
        dotfiles help

REPO_DIR           := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
INFISICAL_DIR      := $(REPO_DIR)infisical
INFISICAL_URL      := https://infisical.iillmaticc.link
APPS_DIR           := /mnt/cell_block_d/apps
VUETORRENT_VERSION := $(shell cat $(REPO_DIR)themes/vuetorrent.version)
QBIT_THEMES_DIR    := $(APPS_DIR)/qbittorrent-vpn/config/themes

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

## Deploy qbittorrent-vpn stack (gluetun + qbittorrent + port-sync) with secrets from Infisical
qbittorrent-up: vuetorrent-install
	$(call infisical-run,qbittorrent-vpn,$$(. $(APPS_DIR)/qbittorrent-vpn/.env && echo $$INFISICAL_PROJECT_ID),\
	  docker compose -f $(REPO_DIR)port-sync/docker-compose.truenas.yml up -d)

## Stop qbittorrent-vpn stack
qbittorrent-down:
	docker compose -f $(REPO_DIR)port-sync/docker-compose.truenas.yml down

## Install (or upgrade) VueTorrent theme — no-op if already at pinned version
## To upgrade: edit themes/vuetorrent.version; no container restart needed
vuetorrent-install:
	@installed=$$(cat $(QBIT_THEMES_DIR)/vuetorrent/version.txt 2>/dev/null); \
	if [ "$$installed" = "$(VUETORRENT_VERSION)" ]; then \
	  echo "VueTorrent $(VUETORRENT_VERSION) already installed, skipping"; \
	else \
	  echo "Installing VueTorrent $(VUETORRENT_VERSION)..."; \
	  mkdir -p $(QBIT_THEMES_DIR); \
	  rm -rf $(QBIT_THEMES_DIR)/vuetorrent; \
	  curl -fsSL https://github.com/VueTorrent/VueTorrent/releases/download/v$(VUETORRENT_VERSION)/vuetorrent.zip \
	    -o /tmp/vuetorrent.zip; \
	  unzip -q /tmp/vuetorrent.zip -d $(QBIT_THEMES_DIR); \
	  rm /tmp/vuetorrent.zip; \
	  echo "VueTorrent $(VUETORRENT_VERSION) installed to $(QBIT_THEMES_DIR)/vuetorrent"; \
	fi

## Apply dotfiles for truenas_admin (run as truenas_admin on host, not inside provisioner)
dotfiles:
	bash $(REPO_DIR)dotfiles/bootstrap.sh

## Show available targets
help:
	@grep -E '^##' Makefile | sed 's/## //'
