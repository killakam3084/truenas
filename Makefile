.PHONY: init pull nginx-up nginx-down nginx-reload infisical-up infisical-down \
        roon-up roon-down roon-restart \
        certrenew-run certrenew-dry-run \
        rss-curator-up rss-curator-down \
        rarclean-up rarclean-down \
        qbittorrent-up qbittorrent-down \
        vuetorrent-install \
        logging-up logging-down \
        dotfiles help

REPO_DIR           := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
INFISICAL_DIR      := $(REPO_DIR)infisical
NGINX_DIR          := $(REPO_DIR)truenas-nginx-config
ROON_DIR           := $(REPO_DIR)roon
LOGGING_DIR        := $(REPO_DIR)logging
INFISICAL_URL      := https://infisical.iillmaticc.link
APPS_DIR           := /mnt/cell_block_d/apps
VUETORRENT_VERSION := $(shell cat $(REPO_DIR)themes/vuetorrent.version)
QBIT_THEMES_DIR    := $(APPS_DIR)/qbittorrent-vpn/config/themes
GIT_USER_NAME      := killakam3084
GIT_USER_EMAIL     := cameron.rison@gmail.com

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

## Pull latest commits for parent repo and all submodules (advances pinned commits)
pull:
	@set -e; \
	rebase_merge=$$(git rev-parse --git-path rebase-merge); \
	rebase_apply=$$(git rev-parse --git-path rebase-apply); \
	if [ -d "$$rebase_merge" ] || [ -d "$$rebase_apply" ]; then \
	  echo "Detected unfinished rebase in parent repo; aborting stale state"; \
	  git rebase --abort || true; \
	  if [ -d "$$rebase_merge" ] || [ -d "$$rebase_apply" ]; then \
	    echo "Parent rebase metadata still present; removing stale rebase state"; \
	    rm -rf "$$rebase_merge" "$$rebase_apply"; \
	  fi; \
	fi
	git pull --rebase origin main
	@set -e; \
	for module in certrenew port-sync rarclean rss-curator truenas-nginx-config truenas-provisioning-image; do \
	  rebase_merge=$$(git -C $$module rev-parse --git-path rebase-merge); \
	  rebase_apply=$$(git -C $$module rev-parse --git-path rebase-apply); \
	  if [ -d "$$rebase_merge" ] || [ -d "$$rebase_apply" ]; then \
	    echo "Detected unfinished rebase in $$module; aborting stale state"; \
	    git -C $$module rebase --abort || true; \
	    if [ -d "$$rebase_merge" ] || [ -d "$$rebase_apply" ]; then \
	      echo "$$module rebase metadata still present; removing stale rebase state"; \
	      rm -rf "$$rebase_merge" "$$rebase_apply"; \
	    fi; \
	  fi; \
	  git -C $$module pull --rebase origin main; \
	done
	git add .gitmodules certrenew port-sync rarclean rss-curator truenas-nginx-config truenas-provisioning-image
	git -c user.name=$(GIT_USER_NAME) -c user.email=$(GIT_USER_EMAIL) commit -m "chore: advance submodule pins" || true

## Start nginx-proxy stack (host-network reverse proxy)
nginx-up:
	docker compose -f $(NGINX_DIR)/docker-compose.yml up -d

## Stop nginx-proxy stack
nginx-down:
	docker compose -f $(NGINX_DIR)/docker-compose.yml down

## Reload nginx-proxy config (pull submodules then signal nginx; requires docker CLI access)
nginx-reload: pull
	docker kill --signal=HUP nginx-proxy

## Start Infisical (run from host or provisioner — requires .env to exist)
infisical-up:
	docker compose -f $(INFISICAL_DIR)/docker-compose.yml --env-file $(INFISICAL_DIR)/.env up -d

## Stop Infisical
infisical-down:
	docker compose -f $(INFISICAL_DIR)/docker-compose.yml --env-file $(INFISICAL_DIR)/.env down

## Start RoonServer stack
roon-up:
	docker compose -f $(ROON_DIR)/docker-compose.yml up -d

## Stop RoonServer stack
roon-down:
	docker compose -f $(ROON_DIR)/docker-compose.yml down

## Restart RoonServer (stop then start; use when Roon glitches out)
roon-restart:
	docker compose -f $(ROON_DIR)/docker-compose.yml down
	docker compose -f $(ROON_DIR)/docker-compose.yml up -d

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

## Start Loki + Promtail logging stack
logging-up:
	mkdir -p /mnt/cell_block_d/apps/loki/data
	docker compose -f $(LOGGING_DIR)/docker-compose.truenas.yml up -d

## Stop Loki + Promtail logging stack
logging-down:
	docker compose -f $(LOGGING_DIR)/docker-compose.truenas.yml down

## Apply dotfiles for truenas_admin (run as truenas_admin on host, not inside provisioner)
dotfiles:
	@if [ "$(shell id -un)" = "truenas_admin" ]; then \
	  DOTFILES_USER=truenas_admin bash $(REPO_DIR)dotfiles/bootstrap.sh; \
	else \
	  sudo -u truenas_admin -H DOTFILES_USER=truenas_admin bash $(REPO_DIR)dotfiles/bootstrap.sh; \
	fi

## Show available targets
help:
	@echo "Available make targets:"
	@echo ""
	@awk '/^##/ { desc=substr($$0, 4); getline; if (match($$0, /^[a-zA-Z_][a-zA-Z0-9_-]*:/)) { target=substr($$0, 1, RLENGTH-1); printf "  %-25s %s\n", target, desc } }' Makefile | sort
	@echo ""
