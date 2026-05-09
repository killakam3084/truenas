.PHONY: init pull nginx-reload help

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

## Show available targets
help:
	@grep -E '^##' Makefile | sed 's/## //'
