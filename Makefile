# === Общие переменные ===
VENV ?= .venv
BIN  := $(VENV)/bin

ANSIBLE        ?= $(BIN)/ansible-playbook
ANSIBLE_ADHOC  ?= $(BIN)/ansible
ANSIBLE_LINT   ?= $(BIN)/ansible-lint
ANSIBLE_GALAXY ?= $(BIN)/ansible-galaxy

# Если venv не создан — подскажем
ifeq (,$(wildcard $(BIN)/ansible-playbook))
$(info [hint] venv не найден. Создай: make venv)
endif

INVENTORY ?= inventory/hosts.ini

# Плейбуки
PLAY_BOOTSTRAP ?= playbooks/bootstrap.yml
PLAY_PANEL     ?= playbooks/panel.yml
PLAY_NODES     ?= playbooks/nodes.yml
PLAY_HAPROXY   ?= playbooks/haproxy.yml
PLAY_SMOKE     ?= playbooks/smoke.yml
PLAY_SITE      ?= playbooks/site.yml
PLAY_DNS       ?= playbooks/dns.yml
PLAY_INBOUNDS  ?= playbooks/inbounds.yml

# Доп. флаги для ansible/ansible-playbook (например: --ask-vault-pass, -e var=val)
ANSIBLE_FLAGS ?=
# Ограничение по хосту/группе (например: LIMIT=panel или LIMIT=node-nl-1)
LIMIT         ?= all
# Теги плейбуков (например: TAGS=upgrade,panel)
TAGS          ?=
# Свободные доп. аргументы к playbook (оставлено для совместимости)
EXTRA         ?=

# Вспомогательные флаги
LIMIT_FLAG     = $(if $(strip $(LIMIT)),--limit $(LIMIT),)
TAGS_FLAG      = $(if $(strip $(TAGS)),--tags $(TAGS),)

# --- Load .env into environment (if present) ---
ifneq (,$(wildcard .env))
include .env
export $(shell sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' .env)
endif

.PHONY: help bootstrap dns dns-plan dns-absent panel nodes haproxy up smoke smoke-docker site lint vault ping facts destroy

help: ## Показать справку по целям
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*##/: /' | sort

# --- Основные цели ---

bootstrap: ## Базовая подготовка хостов (common, docker)
	@# Примеры:
	@#   make bootstrap
	@#   make bootstrap LIMIT=all
	@#   make bootstrap LIMIT=panel ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_BOOTSTRAP) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

dns: ## Зарегистрировать/обновить DNS-записи панели (отдельный плей)
	@# Примеры:
	@#   make dns
	@#   make dns LIMIT=panel
	@#   CF_DNS_API_TOKEN=xxx CF_DNS_ZONE=example.com make dns LIMIT=panel
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_DNS) $(LIMIT_FLAG) --tags cf_dns $(ANSIBLE_FLAGS) $(EXTRA)

dns-plan: ## Прогнать DNS в check/diff режиме (dry-run)
	@# Примеры:
	@#   make dns-plan LIMIT=panel
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_DNS) $(LIMIT_FLAG) --tags cf_dns --check --diff $(ANSIBLE_FLAGS) $(EXTRA)

dns-absent: ## Удалить DNS-записи панели (cf_dns_state=absent)
	@# Примеры:
	@#   make dns-absent LIMIT=panel
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_DNS) $(LIMIT_FLAG) --tags cf_dns -e cf_dns_state=absent $(ANSIBLE_FLAGS) $(EXTRA)

panel: ## Деплой Remnawave Panel (и health-checks)
	@# Примеры:
	@#   make panel
	@#   make panel LIMIT=panel
	@#   make panel TAGS=panel
	@#   make panel TAGS=nginx
	@#   make panel TAGS=haproxy
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_PANEL) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

## Добавить/обновить inbound'ы в профиле (через API панели)
inbounds:  ## make inbounds [LIMIT=panel] [TAGS=inbounds] [EXTRA='-e remnawave_profile_uuid=...']
	@# Примеры:
	@#  make inbounds
	@# 	ограничить конкретным хостом/группой
	@#	make inbounds LIMIT=panel
	@# 	выполнить только тэг inbounds (указан на роли)
	@#	make inbounds TAGS=inbounds
	@# 	разово переопределить профиль по UUID (пример)
	@#	make inbounds EXTRA='-e remnawave_profile_uuid=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
	@# 	разово подменить базовый URL API (если нужно)
	@#	make inbounds EXTRA='-e remnawave_api_base_url=https://remna.vpn-for-friends.com/api'	
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_INBOUNDS) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

nodes: ## Деплой Remnawave Nodes (+ регистрация, health-checks)
	@# Примеры:
	@#   make nodes
	@#   make nodes LIMIT=nodes
	@#   make nodes LIMIT=node-nl-1
	@#   make nodes LIMIT=de-fra-1 TAGS=node
	@#   make nodes LIMIT=de-fra-1 TAGS=register_node
	@#   make nodes LIMIT=de-fra-1 TAGS=register_host
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_NODES) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

haproxy: ## Настройка HAProxy TCP SNI-перекидки
	@# Примеры:
	@#   make haproxy
	@#   make haproxy LIMIT=panel
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_HAPROXY) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

smoke: ## Smoke-тесты панели и нод
	@# Примеры:
	@#   make smoke
	@#   make smoke LIMIT=panel TAGS=smoke_panel
	@#   make smoke LIMIT=nodes TAGS=smoke_node
	@#   make smoke LIMIT=de-fra-1 TAGS=smoke_node
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SMOKE) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

# --- Smoke tests (Docker only) ---
smoke-docker: ## Запуск только Docker smoke-тестов
	@# Примеры:
	@#   make smoke-docker
	@#   make smoke-docker LIMIT=de-fra-1
	@#   make smoke-docker LIMIT=de-fra-1 ANSIBLE_FLAGS='-e smoke_run_hello=false'
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SMOKE) $(LIMIT_FLAG) --tags docker $(ANSIBLE_FLAGS) $(EXTRA)

site: ## Полный сценарий (site.yml)
	@# Примеры:
	@#   make site
	@#   make site LIMIT=all
	@#   make site TAGS=upgrade
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SITE) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

up: ## Быстрый деплой: bootstrap → panel → nodes → smoke
	@# Примеры:
	@#   make up
	@#   make up LIMIT=all
	@#   make up LIMIT=panel
	$(MAKE) bootstrap LIMIT="$(LIMIT)" TAGS="$(TAGS)" ANSIBLE_FLAGS="$(ANSIBLE_FLAGS)" EXTRA="$(EXTRA)"
	$(MAKE) panel     LIMIT="$(LIMIT)" TAGS="$(TAGS)" ANSIBLE_FLAGS="$(ANSIBLE_FLAGS)" EXTRA="$(EXTRA)"
	$(MAKE) nodes     LIMIT="$(LIMIT)" TAGS="$(TAGS)" ANSIBLE_FLAGS="$(ANSIBLE_FLAGS)" EXTRA="$(EXTRA)"
	$(MAKE) smoke     LIMIT="$(LIMIT)" TAGS="$(TAGS)" ANSIBLE_FLAGS="$(ANSIBLE_FLAGS)" EXTRA="$(EXTRA)"

# --- Диагностика ---

ping: ## Ansible ping целевых хостов (LIMIT=...)
	@# Примеры:
	@#   make ping
	@#   make ping LIMIT=panel
	@#   make ping LIMIT=node-nl-1
	$(ANSIBLE_ADHOC) -i $(INVENTORY) $(LIMIT) -m ping $(ANSIBLE_FLAGS) || true

facts: ## Показать ansible_facts для LIMIT
	@# Примеры:
	@#   make facts
	@#   make facts LIMIT=nodes
	@#   make facts LIMIT=node-nl-1
	$(ANSIBLE_ADHOC) -i $(INVENTORY) $(LIMIT) -m setup -a 'gather_subset=network,virtual,hardware' $(ANSIBLE_FLAGS) || true

lint: ## ansible-lint (офлайн, локальный конфиг)
	@# Примеры:
	@#   make lint
	@#   make lint ANSIBLE_FLAGS="--exclude roles/some_role/tmp/"
	$(ANSIBLE_LINT) -c .ansible-lint playbooks roles

vault: ## Подсказка по редактированию vault
	@# Примеры:
	@#   make vault
	@echo "Пример: ansible-vault edit inventory/group_vars/panel.yml"

destroy: ## Удалить стек (state=absent) на LIMIT (осторожно!)
	@# Примеры:
	@#   make destroy
	@#   make destroy LIMIT=nodes
	@#   make destroy LIMIT=node-nl-1
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_NODES) -e 'state=absent' $(LIMIT_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_PANEL) -e 'state=absent' $(LIMIT_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

.PHONY: venv
venv: ## Создать локальное venv с ansible-core 2.17
	python3 -m venv .venv
	. .venv/bin/activate && pip install -U pip wheel
	. .venv/bin/activate && pip install "ansible-core==2.17.*" ansible-lint
	. .venv/bin/activate && ansible-galaxy collection install -r collections/requirements.yml --force

.PHONY: collections
collections: ## Установить Ansible collections из requirements.yml
	$(ANSIBLE) --version >/dev/null
	$(ANSIBLE_GALAXY) collection install -r collections/requirements.yml --force
