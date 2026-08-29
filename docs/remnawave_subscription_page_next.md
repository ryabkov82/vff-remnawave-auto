# Remnawave Subscription Page Next (7.2.1)

Параллельный **тестовый** контур страницы подписки Remnawave. Production-контур не затрагивается.

## Отличие старого и нового контейнера

| Параметр | Production (старый) | Next (тестовый) |
|----------|---------------------|-----------------|
| Роль Ansible | `remnawave_subscription_page` | `remnawave_subscription_page_next` |
| Каталог | `/opt/remnasub` | `/opt/remnasub-next` |
| Образ | pinned SHA / `latest` (см. inventory) | `remnawave/subscription-page:7.2.1` |
| Контейнер | `remnawave-subscription-page` | `remnawave-subscription-page-next` |
| Порт (localhost) | `127.0.0.1:3010` | `127.0.0.1:3011` |
| Публичный HTTPS | `https://sub.vpn-for-friends.com` → 3010 (Nginx :4443) | `https://sub-next.vpn-for-friends.com` → 3011 (Nginx :443) |
| `app-config.json` | монтируется из роли | не используется (конфиг в Remnawave) |
| META_TITLE / META_DESCRIPTION | в `.env` старой версии | не используются в 7.2.1 |

Production Nginx (`roles/remnawave_subscription_page`) продолжает проксировать `sub.vpn-for-friends.com` на порт **3010**. Переключение production upstream на 3011 **запрещено**.

## DNS

A-запись для тестового контура:

```
sub-next.vpn-for-friends.com -> 91.184.245.69
```

Production DNS не меняется:

```
sub.vpn-for-friends.com -> 91.184.245.69
```

## HTTPS reverse proxy (Nginx)

Отдельный vhost в роли `remnawave_subscription_page_next` (`tasks/nginx.yml`), по образцу
`roles/remnawave_subscription_page/templates/nginx-subscription.conf.j2` и webroot/certbot из `roles/nginx`.

| Параметр | Значение |
|----------|----------|
| Домен | `sub-next.vpn-for-friends.com` |
| Upstream | `http://127.0.0.1:3011` |
| HTTP :80 | ACME `/.well-known/acme-challenge/` + redirect на HTTPS |
| HTTPS :443 | Let's Encrypt (`/etc/letsencrypt/live/sub-next.vpn-for-friends.com/`) |
| Webroot | `/var/www/letsencrypt` (общий с production HTTP-01) |

Обязательные proxy-заголовки (без basic auth):

- `Host $host`
- `X-Real-IP $remote_addr`
- `X-Forwarded-For $proxy_add_x_forwarded_for`
- `X-Forwarded-Proto https`
- `X-Forwarded-Host $host`

Remnawave Subscription Page закрывает соединение без `X-Forwarded-For` и `X-Forwarded-Proto=https`.

### Bootstrap сертификата

Первый `make sub-next-nginx` без существующего сертификата выполняет **два reload**:

1. stat `fullchain.pem` + `privkey.pem` (`follow: true` — пути Certbot в `/etc/letsencrypt/live/` являются symlink) → `remnawave_sub_next_ssl_ready=false`, `certificate_was_missing=true`
2. HTTP-only vhost (ACME доступен, HTTPS block отсутствует, ссылок на сертификат нет)
3. symlink + **reload #1** (`nginx -t`, затем reload) — HTTP bootstrap загружен до certbot
4. `certbot certonly --webroot` (пропускается в check mode и если оба файла сертификата уже есть)
5. повторный stat обоих файлов → пересчёт `remnawave_sub_next_ssl_ready`
6. assert, что сертификат появился
7. повторный render vhost с HTTPS block + **reload #2**
8. публичный HTTPS health check (только после reload #2)

Повторный deploy при действующем сертификате:

- certbot пропускается;
- template/symlink проверяются идемпотентно;
- reload выполняется только при реальном изменении конфигурации (handler после notify);
- публичный HTTPS health check выполняется.

Check mode (`make sub-next-nginx-check`):

- stat и template diff выполняются;
- certbot, handlers/reload и health check пропускаются;
- отсутствие сертификата не считается ошибкой.

Production vhost `sub.vpn-for-friends.com` и upstream `:3010` не затрагиваются.

### Переменные Nginx

```yaml
remnawave_sub_next_domain: "sub-next.vpn-for-friends.com"
remnawave_sub_next_upstream_host: "127.0.0.1"
remnawave_sub_next_upstream_port: 3011
remnawave_sub_next_nginx_enabled: true
remnawave_sub_next_healthcheck_short_uuid: "VZLHkrKwsj0Qs82e"
```

## Переменные контейнера

### Несекретные (defaults роли)

```yaml
remnawave_sub_next_root_dir: /opt/remnasub-next
remnawave_sub_next_image: remnawave/subscription-page:7.2.1
remnawave_sub_next_service_name: remnawave-subscription-page-next
remnawave_sub_next_container_name: remnawave-subscription-page-next
remnawave_sub_next_bind_address: 127.0.0.1
remnawave_sub_next_external_port: 3011
remnawave_sub_next_internal_port: 3010
remnawave_sub_next_restart_policy: unless-stopped
remnawave_sub_next_panel_url: https://remna.vpn-for-friends.com
remnawave_sub_next_custom_sub_prefix: ""
remnawave_sub_next_marzban_legacy_enabled: true
remnawave_sub_next_config_uuid: ""   # в .env → SUBPAGE_CONFIG_UUID
remnawave_sub_next_healthcheck_short_uuid: ""
remnawave_sub_next_restart_stabilize_seconds: 5
```

Локальный HTTP health-check (`HTTP check subscription-next page URL`) ходит на
`http://127.0.0.1:3011/<shortUuid>`, но передаёт reverse-proxy headers
(`Host` / `X-Forwarded-Host` = `remnawave_sub_portalbase_domain`,
`X-Forwarded-Proto=https`, `X-Forwarded-Port=443`, `X-Real-IP`, `X-Forwarded-For`).
Subscription Page требует HTTPS proxy context (`ProxyCheckMiddleware`) и иначе
закрывает соединение без ответа.

### Секретные (Ansible Vault / inventory secrets)

```yaml
remnawave_sub_next_api_token: "{{ vault_remnawave_api_token }}"
remnawave_sub_next_marzban_legacy_secret_key: "{{ vault_marzban_secret_key }}"
```

## Деплой

Контейнер:

```bash
make sub-next LIMIT=subscription
```

Nginx + сертификат + публичный HTTPS health check:

```bash
make sub-next-nginx LIMIT=subscription
```

С vault:

```bash
make sub-next-nginx LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
```

Прямой вызов (эквивалент `make sub-next-nginx`):

```bash
ansible-playbook -i inventory/hosts.ini playbooks/subscription.yml \
  --limit subscription --tags sub_next_nginx
```

## Dedicated domain: sub.portalbase.link

Отдельный Nginx-vhost для существующего runtime на `127.0.0.1:3011`.
Это **не** alias-механизм и не список доменов — фиксированный vhost для одного домена.

| Параметр | Значение |
|----------|----------|
| Домен | `sub.portalbase.link` |
| Upstream | `http://127.0.0.1:3011` |
| Site file | `/etc/nginx/sites-available/subscription-portalbase.conf` |
| Certificate | `/etc/letsencrypt/live/sub.portalbase.link/` |
| Health check | TCP `127.0.0.1:3011` + `GET https://sub.portalbase.link/healthz` → `200` / `ok` |

Не изменяет `sub.vpn-for-friends.com`, `sub-next.vpn-for-friends.com`, `SUB_PUBLIC_DOMAIN`,
контейнеры Subscription Page и production cutover.

Deploy health-check **не** зависит от пользовательской подписки: TCP на configured
upstream (`remnawave_sub_portalbase_upstream_host`:`remnawave_sub_portalbase_upstream_port`)
и публичный `GET /healthz` (Nginx `return 200`, без proxy в Subscription Page).

```bash
make sub-portalbase-check LIMIT=subscription
make sub-portalbase LIMIT=subscription
```

Первый apply без сертификата: HTTP bootstrap → `nginx -t` + reload → certbot webroot →
HTTPS vhost → `nginx -t` + reload → public health check.

### INCY protected subscription endpoint

Отдельный HTTPS location только на `sub.portalbase.link` для клиентов INCY.
Обычные subscription URL не меняются.

| | |
|--|--|
| Public | `https://sub.portalbase.link/incy/<shortUuid>` |
| Upstream | `http://127.0.0.1:3011/<shortUuid>` |
| Отличие ответа | заголовок `hide-url: 1` |

Nginx **не** модифицирует body Subscription Page: prefix только снимается перед
`proxy_pass` (trailing slash у `proxy_pass`). Заголовок `hide-url` — client-side
protection hint для INCY, а не cryptographic secret protection.

Endpoint предназначен для дальнейшего использования с `incy://crypt1/...` в vpnbot.

Обычные URL (`https://sub.portalbase.link/<shortUuid>`) остаются без `hide-url`
и без изменения path.

Переменные (только portalbase vhost; default — выключено):

```yaml
remnawave_sub_portalbase_incy_enabled: false
remnawave_sub_portalbase_incy_prefix: "/incy/"
```

Production inventory включает feature (`true` / `/incy/`). Другие домены
(`sub.vpn-for-friends.com`, `sub-next.vpn-for-friends.com`) не затрагиваются.

## API-конфигурация (роль `remnawave_subscription_page_config`)

Идемпотентная загрузка JSON-конфигурации страницы подписки v7 из Git в Remnawave Panel через API.

Роль **не** управляет Docker-установкой контейнера — для этого используйте `remnawave_subscription_page_next`.
Production-контур (порт 3010, default UUID) не затрагивается.

### Назначение

- читает declarative JSON с Ansible controller;
- сравнивает с текущей конфигурацией в панели (`GET /api/subscription-page-configs/{uuid}`);
- при отличии создаёт backup на subscription-хосте и выполняет `PATCH /api/subscription-page-configs`;
- опционально перезапускает только тестовый контейнер `remnawave-subscription-page-next`.

Контейнер `remnawave-subscription-page-next` можно закрепить за той же конфигурацией через
`remnawave_sub_next_config_uuid` (в `.env` → `SUBPAGE_CONFIG_UUID`).

### Источник declarative JSON

| Параметр | Значение |
|----------|----------|
| Git-источник | `roles/remnawave_subscription_page_config/files/base.json` + `files/brands/*.patch.json` (см. [remnawave_subscription_branding.md](remnawave_subscription_branding.md)) |
| Базовый шаблон upstream | `roles/remnawave_subscription_page_config/files/source/default-7.2.1.json` |
| Сборка кастомного JSON | `scripts/build_vpn_for_friends_subpage_config.py` |

Состав платформ и приложений наследуется из upstream-шаблона соответствующей версии
(`files/source/default-7.2.1.json`); локальные настройки существующих платформ и приложений
имеют приоритет; итоговый desired JSON формируется build script через merge.

Переменная `remnawave_subpage_configs` задаёт список брендовых конфигураций
(`base_file` + `patch_file`). Legacy fallback: если список пуст, используется
`remnawave_subpage_config_uuid` / `remnawave_subpage_config_source_file`.
Подробности multi-brand: [remnawave_subscription_branding.md](remnawave_subscription_branding.md).

### Config check

Локальная валидация JSON **без** Ansible и API:

```bash
make sub-next-config-check
```

Собирает и валидирует VFF и Friends Connect через `scripts/build_subpage_config.py`.
`sub-next-config-plan` и `sub-next-config-apply` всегда выполняют config check первым шагом.

### Config plan

Dry-run: GET из панели, сравнение, diff в stdout — **без** PATCH, backup, restart или HTML health check.

```bash
make sub-next-config-plan LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
```

Эквивалент: `playbooks/subscription.yml --tags sub_next_config --check --diff`.

Если raw JSON отличается, но канонические объекты совпадают, plan сообщает:

`Subscription Page config is already up to date after Remnawave normalization.`

### Config apply

Полный apply через API и опциональный restart next-контейнера:

```bash
make sub-next-config-apply LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
```

Входит в полный деплой тестового контура:

```bash
make sub-next-full LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
```

Force restart без PATCH (если PATCH уже сохранён, но контейнер не перезапускался):

```bash
make sub-next-config-apply LIMIT=subscription \
  EXTRA='-e remnawave_subpage_config_force_restart_next=true'
```

### Каноническое сравнение

Remnawave backend перед сохранением нормализует локализованные строки в `platforms` и
`baseTranslations` (`cleanLocalizedTexts`: только активные `locales`, `strip()`, удаление пустых
значений). Raw JSON из Git и сохранённый config могут отличаться символически, но быть
семантически одинаковыми.

Роль использует filter `remnawave_subpage_config_canonicalize` и сравнивает канонические объекты:

- `needs_update` — только если канонические current и desired различаются;
- verification GET после PATCH — `updated_canonical == desired_canonical`;
- в PATCH по-прежнему отправляется исходный desired config (не канонический).

При ошибке verification в `fail_msg` выводятся только JSON paths (`remnawave_subpage_config_diff_paths`), без значений полей.

### Backup

Перед PATCH текущая конфигурация сохраняется на subscription-хосте:

```
/opt/remnasub-next/config-backups/<uuid>-YYYYMMDD-HHMMSS.json
```

Каталог задаётся переменной `remnawave_subpage_config_backup_dir` (default `/opt/remnasub-next/config-backups`).

Откат вручную:

1. восстановить JSON из backup через PATCH с тем же UUID;
2. `docker compose restart remnawave-subscription-page-next` в `/opt/remnasub-next`.

### PATCH

- выполняется только при `remnawave_subpage_config_needs_update=true`;
- endpoint: `PATCH /api/subscription-page-configs` с UUID из inventory;
- API token должен иметь scopes `subscription-page-configs: get, update`;
- в check mode (`config plan`) PATCH не выполняется.

### Verification

После успешного PATCH роль выполняет повторный `GET /api/subscription-page-configs/{uuid}` и сравнивает
канонический ответ с desired config. Несовпадение — fail с перечислением diff paths (без значений полей).

### Restart и health check

- **Restart** — при `remnawave_subpage_config_restart_next=true` (default) и (`needs_update` или `force_restart_next`);
- **Force restart** не выполняет PATCH; нужен для перечитывания уже сохранённой конфигурации контейнером;
- сервис: `remnawave-subscription-page-next` в `/opt/remnasub-next` (`remnawave_subpage_config_compose_dir`);
- **HTML health check** выполняется при каждом обычном apply (не в check mode), если задан
  `remnawave_subpage_config_healthcheck_short_uuid` — даже когда PATCH не требуется.

### Переменные

| Переменная | Default | Описание |
|------------|---------|----------|
| `remnawave_subpage_config_panel_url` | `https://{{ remnawave_panel_frontend_domain }}` | Base URL панели |
| `remnawave_subpage_config_uuid` | `""` | UUID конфигурации в Remnawave |
| `remnawave_subpage_config_source_file` | `""` | Пользовательский override пути к desired JSON |
| `remnawave_subpage_configs` | `[]` | Declarative multi-brand list (`key`, `name`, `uuid`, `base_file`, `patch_file`) |
| `remnawave_subpage_config_api_token` | `""` | Bearer token (vault) |
| `remnawave_subpage_config_backup_dir` | `/opt/remnasub-next/config-backups` | Каталог backup |
| `remnawave_subpage_config_restart_next` | `true` | Restart next-контейнера после PATCH или force restart |
| `remnawave_subpage_config_force_restart_next` | `false` | Restart без PATCH |
| `remnawave_subpage_config_compose_dir` | `/opt/remnasub-next` | Каталог docker compose |
| `remnawave_subpage_config_compose_service` | `remnawave-subscription-page-next` | Имя сервиса |
| `remnawave_subpage_config_healthcheck_short_uuid` | `""` | shortUuid для HTML health check |
| `remnawave_subpage_config_healthcheck_host` | `sub.vpn-for-friends.com` | Host header |

### Inventory (subscription)

```yaml
remnawave_subpage_config_uuid: "f24bc0b1-2386-4473-9bde-9cd7b384641c"
remnawave_subpage_config_api_token: "{{ remnawave_panel_api_token }}"
remnawave_subpage_config_healthcheck_short_uuid: "VZLHkrKwsj0Qs82e"
remnawave_sub_next_config_uuid: "{{ remnawave_subpage_config_uuid }}"
```

### Безопасные команды Make

| Команда | Режим | PATCH | Backup | Restart | Health check |
|---------|-------|-------|--------|---------|--------------|
| `make sub-next-config-check` | локальная валидация JSON | — | — | — | — |
| `make sub-next-config-plan` | Ansible `--check` | нет | нет | нет | нет |
| `make sub-next-config-apply` | apply | при `needs_update` | при PATCH | опционально | при apply |
| `make sub-next-full` | apply (container + nginx + config) | при `needs_update` | при PATCH | опционально | при apply |

С vault:

```bash
make sub-next-config-plan LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
make sub-next-config-apply LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
```

## Make targets и tags

Все операции Subscription Page используют один playbook: `playbooks/subscription.yml`.

| Make target | Ansible tag | Назначение |
|-------------|-------------|------------|
| `make sub` | *(без tag; deploy role `subpage`)* | Штатный deploy production subscription |
| `make subpage-config` | `sub_config` | Legacy app-config update |
| `make sub-next` | `sub_next` | Next container (3011) |
| `make sub-next-nginx` | `sub_next_nginx` | Next HTTPS reverse proxy |
| `make sub-portalbase` | `sub_portalbase` | `sub.portalbase.link` → 3011 |
| `make sub-next-config-check` | *(локальный скрипт)* | Validate declarative JSON |
| `make sub-next-config-plan` | `sub_next_config` + `--check` | Plan API config upload |
| `make sub-next-config-apply` | `sub_next_config` | Apply API config upload |
| `make sub-next-full` | `sub_next_full` | Next container + Nginx + API config apply |
| `make sub-cutover` | `sub_cutover` | Production cutover → upstream 3011 |
| `make sub-rollback` | `sub_rollback` | Production rollback → upstream 3010 |

Специальные операции помечены tag `never` и не запускаются при обычном `make sub`.

## Проверка (dry-run)

Контейнер:

```bash
make sub-next-check LIMIT=subscription
```

Nginx (syntax-check + Ansible check, без certbot/reload):

```bash
make sub-next-nginx-check LIMIT=subscription
```

Portalbase Nginx (syntax-check + Ansible check, без certbot/reload):

```bash
make sub-portalbase-check LIMIT=subscription
```

API config (GET + сравнение, без PATCH/backup/restart):

```bash
make sub-next-config-plan LIMIT=subscription ANSIBLE_FLAGS="--ask-vault-pass"
```

## Ручная проверка на сервере

```bash
docker compose -f /opt/remnasub-next/docker-compose.yml ps
ss -tlnp | grep -E ':443|:3011'
curl -v https://sub.portalbase.link/healthz
nginx -t
```

Проверка, что production не затронут:

```bash
curl -v https://sub.vpn-for-friends.com/
curl -v http://127.0.0.1:3010/
docker compose -f /opt/remnasub/docker-compose.yml ps
```

## Production cutover (blue-green)

### Architecture

| | Before cutover | After cutover |
|---|----------------|---------------|
| Production domain | `https://sub.vpn-for-friends.com` | unchanged |
| Production TLS | `/etc/letsencrypt/live/sub.vpn-for-friends.com/` | unchanged |
| Nginx listen | `0.0.0.0:4443` (via HAProxy :443) | unchanged |
| Production upstream | `http://127.0.0.1:3010` (legacy container) | `http://127.0.0.1:3011` (next container) |
| Test domain | `https://sub-next.vpn-for-friends.com` → 3011 | unchanged |
| Legacy container | running on 3010 | **still running** (rollback target) |

Production vhost использует selector `remnawave_subscription_upstream_target`:

- `legacy` (default) — обычный `make sub` / `playbooks/subscription.yml` → `127.0.0.1:3010`
- `next` — только `make sub-cutover` / `playbooks/subscription.yml --tags sub_cutover` → `127.0.0.1:3011`

Наличие next-endpoint переменных в inventory **не** переключает обычный deploy.

Stable legacy backup создаётся только если текущий vhost подтверждённо содержит marker `server 127.0.0.1:3010;`.

### Preflight и cutover

1. Preflight GET `http://127.0.0.1:3011/<shortUuid>` с `Host: sub.vpn-for-friends.com` и `X-Forwarded-*`
2. Backup текущего vhost в `/etc/nginx/vff-backups/subscription-prod-before-v7-*.conf`
3. Stable legacy backup `/etc/nginx/vff-backups/subscription-prod-legacy.conf` (создаётся один раз)
4. Render production vhost с upstream 3011
5. `nginx -t` → reload
6. Public HTTPS health check `https://sub.vpn-for-friends.com/<shortUuid>`
7. При ошибке — automatic rescue rollback из backup

```bash
make sub-cutover-check LIMIT=subscription   # plan + preflight, без backup/reload
make sub-cutover LIMIT=subscription         # полный cutover
make sub-rollback-check LIMIT=subscription  # проверить legacy backup
make sub-rollback LIMIT=subscription        # ручной rollback на 3010
```

Cutover **не** включён в `make sub`, `make sub-next`, `make sub-next-full` или `site.yml`.

Повторный `sub-cutover` после успешного переключения идемпотентен: backup/reload пропускаются, выполняется только production health check.

Legacy backup `subscription-prod-legacy.conf` никогда не перезаписывается автоматически.

### Критерии удаления legacy-контейнера

Удалять контейнер на `:3010` только после стабильной работы production на 3011 и явного решения; rollback должен оставаться возможным через `make sub-rollback`.

## Откат

### Test contour

Остановить только тестовый контейнер:

```bash
docker compose -f /opt/remnasub-next/docker-compose.yml down
```

Отключить только next-vhost (production Nginx не трогать):

```bash
rm -f /etc/nginx/sites-enabled/subscription-next.conf
nginx -t && systemctl reload nginx
```

### Production cutover rollback

```bash
make sub-rollback LIMIT=subscription
```

Восстанавливает `/etc/nginx/vff-backups/subscription-prod-legacy.conf` → `subscription.conf`. Новый контейнер на 3011 и test vhost не останавливаются.

## Ограничения

- cutover только через явную команду `make sub-cutover`;
- не останавливать legacy-контейнер автоматически;
- DNS и production certificate не меняются;
- `sub-next.vpn-for-friends.com` не затрагивается cutover playbook.

