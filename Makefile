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
PLAY_UPGRADE_REMNAWAVE ?= playbooks/upgrade-remnawave.yml
PLAY_HAPROXY   ?= playbooks/haproxy.yml
PLAY_SMOKE     ?= playbooks/smoke.yml
PLAY_SITE      ?= playbooks/site.yml
PLAY_DNS       ?= playbooks/dns.yml
PLAY_INBOUNDS  ?= playbooks/inbounds.yml
PLAY_ANTIBLOCK_CDN ?= playbooks/antiblock_cdn.yml
PLAY_ANTIBLOCK_CDN_BOOTSTRAP ?= playbooks/antiblock_cdn_bootstrap.yml
PLAY_ANTIBLOCK_CDN_YANDEX ?= playbooks/antiblock_cdn_yandex.yml
# === Плейбуки для отключения/удаления нод ===
PLAY_DISABLE_NODE ?= playbooks/disable_node.yml
PLAY_DELETE_NODE  ?= playbooks/delete_node.yml
# === Subscription Page (единый entry point: playbooks/subscription.yml) ===
# Make target → tag: sub=subpage; subpage-config=sub_config; sub-next=sub_next;
# sub-next-nginx=sub_next_nginx; sub-next-config-*=sub_next_config;
# sub-next-full=sub_next_full; sub-cutover=sub_cutover; sub-rollback=sub_rollback;
# sub-portalbase=sub_portalbase (sub.portalbase.link -> 127.0.0.1:3011)
# subpage-brands-*=sub_next_config; external-squads-*=external_squads;
# subscription-branding-*=subscription_branding
# sub TAGS=nginx → production Nginx-only (never, nginx wrapper in play 1)
PLAY_SUB ?= playbooks/subscription.yml

# === Плейбуки миграции Marzban -> Remnawave
PLAY_MIGRATE_INBOUND ?= playbooks/migrate_inbound.yml
PLAY_MIGRATE_HOSTS ?= playbooks/migrate_hosts.yml
PLAY_MIGRATE_USERS ?= playbooks/migrate_users.yml
PLAY_AUDIT_HOSTS ?= playbooks/audit_hosts.yml
PLAY_API_PREFLIGHT ?= playbooks/remnawave_api_preflight.yml

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

.PHONY: help bootstrap dns dns-plan dns-absent panel nodes hosts-audit hosts-plan remnawave-api-preflight haproxy up smoke smoke-docker site lint vault ping facts destroy upgrade upgrade-remnawave sub-next sub-next-check sub-next-nginx sub-next-nginx-check sub-next-config-check sub-next-config-plan sub-next-config-apply sub-next-full sub-portalbase sub-portalbase-check sub-cutover-check sub-cutover sub-rollback-check sub-rollback subpage-brands-check subpage-brands external-squads-check external-squads subscription-branding-check subscription-branding antiblock-cdn-plan antiblock-cdn antiblock-cdn-bootstrap-plan antiblock-cdn-bootstrap antiblock-cdn-node antiblock-cdn-node-plan

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

antiblock-cdn-plan: ## Local AntiBlock CDN validation (syntax-check only; no API writes)
	@# Ansible --check is NOT used: remnawave uri roles skip or still GET, and
	@# writes are not reliably blocked. This target never contacts panel/nodes.
	@# Примеры:
	@#   make antiblock-cdn-plan
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_ANTIBLOCK_CDN) --syntax-check

antiblock-cdn: ## Apply AntiBlock inbound, origin, HAProxy, Yandex CDN, public CNAME, Hosts
	@# Hosts default allow_writes=false; this apply playbook sets true.
	@# Prune/DELETE stays off unless EXTRA='-e antiblock_cdn_hosts_prune=true'.
	@# Does not change make inbounds / make nodes / remnawave_add_host.
	@# Примеры:
	@#   make antiblock-cdn
	@#   make antiblock-cdn TAGS=antiblock_cdn_inbound
	@#   make antiblock-cdn TAGS=antiblock_cdn_nodes
	@#   make antiblock-cdn TAGS=antiblock_cdn_hosts EXTRA='-e antiblock_cdn_hosts_allow_writes=false'
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_ANTIBLOCK_CDN) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

antiblock-cdn-node: ## Provision one CDN node: panel + origin + HAProxy + Yandex CDN + CNAME + Hosts
	@# HOST is required and must be in [antiblock_cdn_nodes]. Limit is panel:HOST so
	@# the panel play is not skipped. Yandex CDN uses delegate_to localhost (limit-safe).
	@# TAGS=antiblock_cdn_hosts skips Yandex / Cloudflare / HAProxy / inbound/squads.
	@# Hosts plan: EXTRA='-e antiblock_cdn_hosts_allow_writes=false' (GET + diff only).
	@# Read-only prune plan: also pass -e antiblock_cdn_hosts_prune=true (no DELETE).
	@# Actual prune: apply already sets allow_writes=true; add prune=true EXTRA.
	@# Примеры:
	@#   make antiblock-cdn-node HOST=de-fra-2
	@#   make antiblock-cdn-node HOST=de-fra-2 TAGS=antiblock_cdn_hosts EXTRA='-e antiblock_cdn_hosts_allow_writes=false'
	@#   make antiblock-cdn-node HOST=de-fra-2 TAGS=antiblock_cdn_hosts EXTRA='-e antiblock_cdn_hosts_allow_writes=false -e antiblock_cdn_hosts_prune=true'
	@#   make antiblock-cdn-node HOST=de-fra-2 TAGS=antiblock_cdn_hosts EXTRA='-e antiblock_cdn_hosts_prune=true'
	@#   make antiblock-cdn-node HOST=de-fra-2 TAGS=antiblock_cdn_hosts
	@test -n "$(HOST)" || { echo "HOST is required, e.g. make antiblock-cdn-node HOST=de-fra-2"; exit 1; }
	@awk '/^\[antiblock_cdn_nodes\]/{p=1;next} /^\[/{p=0} p && $$1=="$(HOST)"{found=1} END{if(!found){print "$(HOST) is not in group antiblock_cdn_nodes" > "/dev/stderr"; exit 1}}' $(INVENTORY)
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_ANTIBLOCK_CDN) --limit panel:$(HOST) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

antiblock-cdn-node-plan: ## Read-only Yandex CDN plan for one HOST (no cloud/HAProxy/Remnawave writes)
	@# Syntax-check + Yandex GET compare. Does not use Ansible --check.
	@# yandex_cdn_allow_writes stays false. No Cloudflare / HAProxy / Remnawave writes.
	@# Примеры:
	@#   make antiblock-cdn-node-plan HOST=de-fra-2
	@test -n "$(HOST)" || { echo "HOST is required, e.g. make antiblock-cdn-node-plan HOST=de-fra-2"; exit 1; }
	@awk '/^\[antiblock_cdn_nodes\]/{p=1;next} /^\[/{p=0} p && $$1=="$(HOST)"{found=1} END{if(!found){print "$(HOST) is not in group antiblock_cdn_nodes" > "/dev/stderr"; exit 1}}' $(INVENTORY)
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_ANTIBLOCK_CDN) --syntax-check
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_ANTIBLOCK_CDN_YANDEX) --limit $(HOST) $(ANSIBLE_FLAGS) $(EXTRA)

antiblock-cdn-bootstrap-plan: ## Local wildcard-cert bootstrap validation (no cloud writes)
	@# Syntax-check + desired-state dump only. Does not call Yandex or Cloudflare.
	@# Ansible --check is NOT used: shell/API helpers can still write under check mode.
	@# Примеры:
	@#   make antiblock-cdn-bootstrap-plan
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_ANTIBLOCK_CDN_BOOTSTRAP) --syntax-check
	$(BIN)/python scripts/yandex_certificate_manager.py print-desired --vars-file inventory/group_vars/all/antiblock_cdn.yml

antiblock-cdn-bootstrap: ## Apply global wildcard cert + DNS challenge (Yandex + Cloudflare writes)
	@# Global resources only. Does not create CDN Resource / Origin Group / HAProxy / Hosts.
	@# Does not change make inbounds / make nodes / make antiblock-cdn.
	@# Примеры:
	@#   make antiblock-cdn-bootstrap
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_ANTIBLOCK_CDN_BOOTSTRAP) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

nodes: ## Деплой Remnawave Nodes (+ регистрация, health-checks)
	@# Примеры:
	@#   make nodes
	@#   make nodes LIMIT=nodes
	@#   make nodes LIMIT=node-nl-1
	@#   make nodes LIMIT=de-fra-1 TAGS=node
	@#   make nodes LIMIT=de-fra-1 TAGS=register_node
	@#   make nodes LIMIT=de-fra-1 TAGS=register_host
	@#   make nodes LIMIT=de-fra-1 TAGS=register_host EXTRA='-e rw_host_force_recreate=true'
	@#   make nodes LIMIT=de-fra-1 TAGS=register_host --check --diff
	@#   make nodes LIMIT=de-fra-1 TAGS=cf_dns
	@#   make nodes LIMIT=de-fra-1 TAGS=cert_enroll
	@#   make nodes LIMIT=de-fra-1 TAGS=tls_sync
	@#   make nodes LIMIT=de-fra-1 TAGS=haproxy
	@#   make nodes LIMIT=de-fra-1 TAGS=nginx
	@#   make nodes LIMIT=de-fra-1 TAGS=qos
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_NODES) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

hosts-audit: ## Read-only аудит API Host (только GET; отчёты в build/)
	@# Примеры:
	@#   make hosts-audit LIMIT=panel
	@#   make hosts-audit LIMIT=panel ANSIBLE_FLAGS="--vault-password-file ~/.ansible/vault.pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_AUDIT_HOSTS) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

remnawave-api-preflight: ## Read-only Remnawave 3.2.3 API token/scope preflight (GET only)
	@# После upgrade Panel до 3.2.3 и выдачи scopes — ДО mutating automation.
	@#   make remnawave-api-preflight LIMIT=panel
	@#   make remnawave-api-preflight LIMIT=panel ANSIBLE_FLAGS="--vault-password-file ~/.ansible/vault.pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_API_PREFLIGHT) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

hosts-plan: ## Dry-run register_host (Ansible --check --diff; без production update)
	@# Примеры:
	@#   make hosts-plan LIMIT=de-fra-1
	@#   make hosts-plan LIMIT=de-fra-1 EXTRA='-e rw_host_match_by=endpoint_inbound'
	@# Не выполняет массовый rename: нужен явный LIMIT и rw_host_set_remark_if_exists=true
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_NODES) $(LIMIT_FLAG) --tags register_host --check --diff $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

disable-node: ## Отключить/включить ноду (опц.: отключить её хосты)
	@# Примеры:
	@#   make disable-node LIMIT=de-fra-1
	@#   make disable-node EXTRA='-e remnawave_node_uuid=UUID -e remnawave_enable_state=false'
	@#   make disable-node EXTRA='-e remnawave_node_name=de-fra-1 -e remnawave_enable_state=false -e remnawave_disable_hosts_of_node=true'
	@#   # DRY-RUN:
	@#   make disable-node EXTRA='-e remnawave_node_name=de-fra-1 -e remnawave_enable_state=false -e remnawave_dry_run=true'
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_DISABLE_NODE) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

delete-node: ## Удалить ноду (опц.: каскадно удалить связанные хосты)
	@# Примеры:
	@#   make delete-node LIMIT=de-fra-1
	@#   make delete-node EXTRA='-e remnawave_node_uuid=UUID -e remnawave_delete_hosts=true'
	@#   make delete-node EXTRA='-e remnawave_node_name=de-fra-1 -e remnawave_delete_hosts=false'
	@#   # DRY-RUN:
	@#   make delete-node EXTRA='-e remnawave_node_name=de-fra-1 -e remnawave_dry_run=true'
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_DELETE_NODE) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

upgrade-remnawave: ## Обновление Remnawave panel + nodes (prepull -> panel -> rolling nodes -> verify)
	@# Примеры:
	@#   make upgrade-remnawave
	@#   make upgrade-remnawave ANSIBLE_FLAGS="--ask-vault-pass"
	@#   make upgrade-remnawave EXTRA='-e remnawave_upgrade_verify_api=true -e remnawave_api_base_url=https://remna.example.com -e remnawave_panel_api_token=...'
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_UPGRADE_REMNAWAVE) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

upgrade: upgrade-remnawave ## Alias для upgrade-remnawave

verify-remnawave: ## Verify Remnawave via panel API (LIMIT=panel)
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_UPGRADE_REMNAWAVE) --limit panel \
		-e remnawave_upgrade_do_prepull=false \
		-e remnawave_upgrade_do_panel=false \
		-e remnawave_upgrade_do_nodes=false \
		-e remnawave_upgrade_verify=true \
		-e remnawave_upgrade_verify_api=true \
		$(ANSIBLE_FLAGS) $(EXTRA)

sub: ## Deploy subscription page (auto detect bundled/separate)
	@# Примеры:
	@# Separate (два хоста: panel + subscription):
	@# make sub
	@# Bundled (на панельном хосте):
	@# make sub LIMIT=panel
	@# Только DNS для sub-домена:
	@# make sub TAGS=cf_dns
	@# Только выпуск сертификата:
	@# make sub TAGS=cert
	@# Только перегенерация vhost-а и reload Nginx:
	@# make sub TAGS=nginx
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

sub-next: ## Deploy parallel test subscription page 7.2.1 (port 3011)
	@# Примеры:
	@#   make sub-next LIMIT=subscription
	@#   make sub-next LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_next $(TAGS_FLAG) \
	  $(ANSIBLE_FLAGS) $(EXTRA)

sub-next-check: ## Dry-run subscription-next (Ansible --check --diff only; no Docker/runtime checks)
	@# Примеры:
	@#   make sub-next-check LIMIT=subscription
	@#   make sub-next-check LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_next $(TAGS_FLAG) --check --diff \
	  $(ANSIBLE_FLAGS) $(EXTRA)

sub-next-nginx-check: ## Dry-run subscription-next nginx (syntax-check + Ansible check; no certbot/reload)
	@# Примеры:
	@#   make sub-next-nginx-check LIMIT=subscription
	@#   make sub-next-nginx-check LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) --syntax-check
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_next_nginx $(TAGS_FLAG) --check --diff \
	  $(ANSIBLE_FLAGS) $(EXTRA)

sub-next-nginx: ## Deploy subscription-next HTTPS reverse proxy (cert + nginx + public health check)
	@# Примеры:
	@#   make sub-next-nginx LIMIT=subscription
	@#   make sub-next-nginx LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_next_nginx $(TAGS_FLAG) \
	  $(ANSIBLE_FLAGS) $(EXTRA)

sub-portalbase-check: ## Dry-run sub.portalbase.link nginx (syntax-check + Ansible check; no certbot/reload)
	@# Примеры:
	@#   make sub-portalbase-check LIMIT=subscription
	@#   make sub-portalbase-check LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) --syntax-check
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_portalbase $(TAGS_FLAG) --check --diff \
	  $(ANSIBLE_FLAGS) $(EXTRA)

sub-portalbase: ## Deploy sub.portalbase.link HTTPS reverse proxy to 127.0.0.1:3011
	@# Примеры:
	@#   make sub-portalbase LIMIT=subscription
	@#   make sub-portalbase LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_portalbase $(TAGS_FLAG) \
	  $(ANSIBLE_FLAGS) $(EXTRA)

sub-next-config-check: ## Validate brand Subpage Configs (base + VFF/FC patches)
	@# Пример:
	@#   make sub-next-config-check
	.venv/bin/python scripts/build_subpage_config.py --brand vff --output /tmp/subpage-vff.json
	.venv/bin/python scripts/build_subpage_config.py --brand fc --output /tmp/subpage-fc.json
	.venv/bin/python scripts/validate_subpage_config.py /tmp/subpage-vff.json
	.venv/bin/python scripts/validate_subpage_config.py /tmp/subpage-fc.json

sub-next-config-plan: ## Plan subscription page config upload (validate + Ansible check)
	@# Пример:
	@#   make sub-next-config-plan LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(MAKE) sub-next-config-check
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_next_config $(TAGS_FLAG) --check --diff \
	  $(ANSIBLE_FLAGS) $(EXTRA)

sub-next-config-apply: ## Apply subscription page config upload via Remnawave API
	@# Пример:
	@#   make sub-next-config-apply LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(MAKE) sub-next-config-check
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_next_config $(TAGS_FLAG) \
	  $(ANSIBLE_FLAGS) $(EXTRA)

subpage-brands-check: ## Alias: plan multi-brand Subpage Configs (check mode)
	@# Пример:
	@#   make subpage-brands-check LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(MAKE) sub-next-config-plan

subpage-brands: ## Alias: apply multi-brand Subpage Configs
	@# Пример:
	@#   make subpage-brands LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(MAKE) sub-next-config-apply

external-squads-check: ## Plan External Squad ↔ Subpage Config bindings (check mode)
	@# Пример:
	@#   make external-squads-check LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) --syntax-check
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags external_squads $(TAGS_FLAG) --check --diff \
	  $(ANSIBLE_FLAGS) $(EXTRA)

external-squads: ## Apply External Squad ↔ Subpage Config bindings
	@# Пример:
	@#   make external-squads LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags external_squads $(TAGS_FLAG) \
	  $(ANSIBLE_FLAGS) $(EXTRA)

subscription-branding-check: ## Plan Subpage Configs + External Squads (check mode)
	@# Пример:
	@#   make subscription-branding-check LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(MAKE) sub-next-config-check
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) --syntax-check
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags subscription_branding $(TAGS_FLAG) --check --diff \
	  $(ANSIBLE_FLAGS) $(EXTRA)

subscription-branding: ## Apply Subpage Configs + External Squads
	@# Пример:
	@#   make subscription-branding LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(MAKE) sub-next-config-check
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags subscription_branding $(TAGS_FLAG) \
	  $(ANSIBLE_FLAGS) $(EXTRA)

sub-next-full: ## Deploy next container, nginx and apply subscription page config
	@# Пример:
	@#   make sub-next-full LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_next_full $(TAGS_FLAG) \
	  $(ANSIBLE_FLAGS) $(EXTRA)

sub-cutover-check: ## Plan production cutover to subscription page v7 (preflight + check mode)
	@# Примеры:
	@#   make sub-cutover-check LIMIT=subscription
	@#   make sub-cutover-check LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) --syntax-check
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_cutover $(TAGS_FLAG) --check --diff \
	  $(ANSIBLE_FLAGS) $(EXTRA)

sub-cutover: ## Cutover production sub.vpn-for-friends.com to upstream 3011 with auto-rollback
	@# Примеры:
	@#   make sub-cutover LIMIT=subscription
	@#   make sub-cutover LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_cutover $(TAGS_FLAG) \
	  $(ANSIBLE_FLAGS) $(EXTRA)

sub-rollback-check: ## Verify legacy production vhost backup exists (check mode)
	@# Примеры:
	@#   make sub-rollback-check LIMIT=subscription
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) --syntax-check
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_rollback $(TAGS_FLAG) --check --diff \
	  $(ANSIBLE_FLAGS) $(EXTRA)

sub-rollback: ## Restore production subscription vhost from legacy backup
	@# Примеры:
	@#   make sub-rollback LIMIT=subscription
	@#   make sub-rollback LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
	  $(LIMIT_FLAG) --tags sub_rollback $(TAGS_FLAG) \
	  $(ANSIBLE_FLAGS) $(EXTRA)

subpage-config: ## Update subscription app-config.json and restart container
	@# Примеры:
	@## Только на хосте панели (по умолчанию сабстраница bundled)
	@# make subpage-config LIMIT=panel
	@## Или, если у тебя отдельная группа/хосты для сабстраницы:
	@# make subpage-config LIMIT=subscription	
	@echo ">>> Update subscription app-config.json and restart container"
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SUB) \
		$(LIMIT_FLAG) \
		--tags sub_config \
		$(ANSIBLE_FLAGS) $(EXTRA)

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

# --- Smoke tests (Subscription only) ---
smoke-sub: ## Запуск только Subscription smoke-тестов
	@# Примеры:
	@#   make smoke-sub
	@#   make smoke-sub LIMIT=de-fra-1
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_SMOKE) $(LIMIT_FLAG) --tags smoke_subscription $(ANSIBLE_FLAGS) $(EXTRA)

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

.PHONY: roles
roles: ## Установить Ansible roles из .ansible/requirements.yml
	$(ANSIBLE) --version >/dev/null
	$(ANSIBLE_GALAXY) role install -r .ansible/requirements.yml -p .ansible/roles --force

.PHONY: deps
deps: collections roles ## Установить все Ansible зависимости (collections + roles)

migrate-inbound: ## Миграция inbound VLESS TCP REALITY из Marzban в Remnawave
	@# Примеры:
	@#   make migrate-inbound EXTRA='-e remnawave_migrate_inbound_dry_run=true'
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_MIGRATE_INBOUND) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

migrate-hosts: ## Миграция hosts из Marzban в Remnawave
	@# Примеры:
	@#   make migrate-hosts EXTRA='-e remnawave_migrate_hosts_dry_run=true'
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_MIGRATE_HOSTS) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)

migrate-users: ## Миграция пользователей из Marzban в Remnawave
	@# Примеры:
	@#   make migrate-users LIMIT=panel EXTRA='-e remnawave_migrate_users_dry_run=true'
	@#   make migrate-users LIMIT=panel EXTRA='-e remnawave_migrate_users_dry_run=true -e remnawave_migrate_users_usernames=["us_67"]'
	@#   make migrate-users LIMIT=panel EXTRA='-e remnawave_migrate_users_dry_run=false -e remnawave_migrate_users_usernames=["us_67"]'
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_MIGRATE_USERS) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)
