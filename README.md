# 🚀 VFF Remnawave Auto Deployment

<p align="center">
  <img src="https://img.shields.io/badge/Remnawave-Panel-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/Nodes-purple?style=flat-square" />
  <img src="https://img.shields.io/badge/Subscription_Page-gray?style=flat-square" />
  <img src="https://img.shields.io/badge/Migration_Marzban→Remnawave-orange?style=flat-square" />
  <img src="https://img.shields.io/badge/VLESS-Reality-0A7?style=flat-square" />
  <img src="https://img.shields.io/badge/Ansible-Automation-yellow?style=flat-square" />
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square" />
</p>

Полностью автоматизированное развертывание **Remnawave Panel**, **Remnawave Nodes**, **Subscription Page**  
и полная миграция данных **Marzban → Remnawave** (inbounds, hosts, users).

---

## ⚙️ Основные возможности

- Автодеплой **панели Remnawave**
- Автодеплой **нод** + автоматическая регистрация в панели
- Автодеплой **страницы подписки** (bundled / separate)
- **Subscription Page v7 (blue-green)**:
  - параллельный next-контур на отдельном порту;
  - декларативная конфигурация через Remnawave API;
  - безопасный cutover/rollback production upstream;
  - TLS и health checks
- Управление сертификатами (HTTP‑01 / DNS‑01)
- Интеграция с HAProxy (TLS passthrough, SNI‑routing)
- Полная **миграция данных Marzban → Remnawave**
  - inbound VLESS Reality
  - hosts (node-host configs)
  - users (включая uuid, трафик, статус, срок действия)
- Legacy Router: поддержка старых ссылок формата  
  `https://<domain>/sub/<marzban_token>`
- Smoke‑тесты панели, нод и страницы подписки
- Полный decommission нод

---

## ⚙️ Основные команды

### Развернуть панель
```bash
make panel
```

После успешного развёртывания панели:
1. Зайдите в веб-интерфейс панели под `admin`.
2. Перейдите в **Settings → API Tokens → Create Token**.
3. Скопируйте значение токена (`ey...`) и сохраните в:
   ```bash
   inventory/group_vars/panel/vault.yml
   ```
   пример:
   ```yaml
   vault_remnawave_panel_api_token: "eyJhbGciO..."
   ```

   > Этот токен используется для API-вызовов и автоматического добавления inbound’ов.

---

### Настроить DNS через Cloudflare
```bash
make dns LIMIT=panel TAGS=cf_dns
```

---

### ➕ Добавить inbound (после панели, до нод)
После того как панель развернута и токен добавлен в vault, можно автоматически добавить Reality-inbound в профиль панели:

```bash
make inbounds
```

Примеры:
```bash
# ограничить по хосту
make inbounds LIMIT=panel

# явно указать UUID профиля
make inbounds EXTRA='-e remnawave_profile_uuid=7988e3a1-5a32-461a-9136-c9475e92f19a'
```

Inbound будет создан или обновлён идемпотентно (по `tag`), а затем автоматически зарегистрирован во **внутреннем скваде** `Default-Squad`.

> Подробности см. в [docs/remnawave_inbounds.md](docs/remnawave_inbounds.md)

---

### Развернуть страницу подписки
Разворачивает production-контейнер **Remnawave Subscription Page** (legacy, порт 3010) и Nginx-vhost.

```bash
make sub LIMIT=subscription
```

Примеры:
```bash
# bundled: страница подписки на том же хосте, что и панель
make sub LIMIT=panel

# separate: отдельный subscription-хост
make sub LIMIT=subscription
```

**Subscription Page v7** — next-контур, API-конфигурация и cutover:

```bash
make sub-next-check LIMIT=subscription
make sub-next-full LIMIT=subscription

make sub-next-config-check
make sub-next-config-plan LIMIT=subscription
make sub-next-config-apply LIMIT=subscription

make sub-cutover-check LIMIT=subscription
make sub-cutover LIMIT=subscription

make sub-rollback-check LIMIT=subscription
make sub-rollback LIMIT=subscription
```

> Подробности v7: [docs/remnawave_subscription_page_next.md](docs/remnawave_subscription_page_next.md)
> Legacy deploy: [docs/remnawave_subscription_deploy.md](docs/remnawave_subscription_deploy.md)
>
> Declarative JSON v7: `roles/remnawave_subscription_page_config/files/vpn-for-friends.json`

### Развернуть ноду
Перед развёртыванием ноды необходимо:

1. В панели на вкладке **Nodes → Add Node** создать ноду и скопировать её `SECRET_KEY` (строку вида `eyJu...`).
2. Сохранить этот ключ в vault конкретной ноды:
   ```bash
   inventory/host_vars/de-fra-1/vault.yml
   ```
   пример:
   ```yaml
   remnawave_secret_key: "eyJu..."
   ```

После этого можно запускать ноду:
```bash
make nodes LIMIT=de-fra-1 TAGS=node
```

---

### Зарегистрировать ноду в панели
```bash
make nodes LIMIT=node-name TAGS=register_node
```

### Зарегистрировать Host для ноды
```bash
make nodes LIMIT=node-name TAGS=register_host
```

### Smoke-тесты
```bash
make nodes LIMIT=node-name TAGS=smoke_node
```

---

## 🧹 Вывод ноды из эксплуатации (Decommission)

Когда ноду нужно **корректно вывести из работы** (например, при обновлении или замене), процесс выполняется в три шага:

1. **Отключить ноду и её хосты**
   ```bash
   make disable-node EXTRA='-e remnawave_node_name=de-fra-1 -e remnawave_enable_state=false -e remnawave_disable_hosts_of_node=true'
   ```
   Роль: [docs/remnawave_disable_node.md](docs/remnawave_disable_node.md)

2. **Дождаться завершения активных сессий**
   - Убедитесь через панель или Grafana, что активных соединений нет.
   - При необходимости можно запустить smoke-тесты:
     ```bash
     make nodes LIMIT=de-fra-1 TAGS=smoke_node
     ```

3. **Удалить ноду (и связанные хосты)**
   ```bash
   make delete-node EXTRA='-e remnawave_node_name=de-fra-1 -e remnawave_delete_hosts=true'
   ```
   Роль: [docs/remnawave_delete_node.md](docs/remnawave_delete_node.md)

> 🔒 Обе операции безопасны и идемпотентны — повторный запуск не приведёт к ошибкам.

---

## 🔄 Миграция данных Marzban → Remnawave

В репозитории присутствуют три специализированные роли, позволяющие **полностью перенести конфигурацию** из существующего Marzban-кластера в Remnawave:

- **Inbound VLESS TCP Reality**  
  `roles/remnawave_migrate_inbound`

- **Hosts (пулы адресов / Domain Bindings)**  
  `roles/remnawave_migrate_hosts`

- **Users (статусы, лимиты, UUID, squads, expireAt)**  
  `roles/remnawave_migrate_users`

Все роли поддерживают **DRY-RUN**, работают идемпотентно и допускают повторный запуск без побочных эффектов.

---

### ▶️ Миграция inbound (VLESS TCP REALITY)

Переносит профиль Reality из Marzban в Remnawave, маппируя:

- публичный ключ сервера,
- shortId,
- serverName,
- поток реальности,
- параметры VLESS,
- теги,
- слушающие адреса.

```bash
make migrate-inbound
```

Примеры:

```bash
# Только посмотреть, что будет создано/обновлено
make migrate-inbound EXTRA='-e remnawave_migrate_inbound_dry_run=true'
```

Подробности:  
👉 `docs/remnawave_migrate_inbound.md`

---

### ▶️ Миграция Hosts

Переносит host-binding’и (доменные имена, режимы, привязку к inbound'ам).

```bash
make migrate-hosts
```

Примеры:

```bash
# DRY-RUN без внесения изменений
make migrate-hosts EXTRA='-e remnawave_migrate_hosts_dry_run=true'
```

Документация:  
👉 `docs/remnawave_migrate_hosts.md`

---

### ▶️ Миграция пользователей

Самая сложная часть миграции — перенести всех пользователей Marzban:

- username / note  
- статус (active / disabled / limited / expired)  
- trafficLimit + стратегия  
- expireAt → перевод unix-timestamp → ISO8601  
- VLESS UUID — перенос 1:1  
- squads (опционально)  
- описание  
- фильтрация по `usernames=[...]`  

Команда:

```bash
make migrate-users LIMIT=panel
```

Примеры:

```bash
# Полный DRY-RUN всех пользователей
make migrate-users LIMIT=panel EXTRA='-e remnawave_migrate_users_dry_run=true'

# DRY-RUN только одного пользователя
make migrate-users LIMIT=panel EXTRA='-e remnawave_migrate_users_dry_run=true -e remnawave_migrate_users_usernames=["us_67"]'

# Применить реальные изменения для конкретного пользователя
make migrate-users LIMIT=panel EXTRA='-e remnawave_migrate_users_dry_run=false -e remnawave_migrate_users_usernames=["us_67"]'
```

Роль гарантирует:

- идемпотентность: существующий пользователь → PATCH, нового → POST  
- никакого «добавления _ в конце» (строгая нормализация)  
- уведомления в выходном логе о `create` или `update`  

Документация:  
👉 `docs/remnawave_migrate_users.md`

---

## 📚 Документация

| Раздел | Файл | Описание |
|--------|------|----------|
| Панель | [docs/remnawave_panel.md](docs/remnawave_panel.md) | Установка панели и сервисов |
| **Обновление (Upgrade)** | **[docs/remnawave_upgrade.md](docs/remnawave_upgrade.md)** | **Безопасное обновление панели и нод (upgrade flow)** |
| Inbounds | [roles/remnawave_inbounds/README.md](roles-remnawave_inbounds-README.md) | Добавление и регистрация inbound’ов |
| HAProxy | [docs/haproxy_tls_sni.md](docs/haproxy_tls_sni.md) | Совместная работа панели и Xray |
| Ноды | [docs/remnawave_node.md](docs/remnawave_node.md) | Запуск контейнера с SECRET_KEY |
| Регистрация ноды | [docs/remnawave_register_node.md](docs/remnawave_register_node.md) | API-регистрация ноды |
| Регистрация Host | [docs/remnawave_add_host.md](docs/remnawave_add_host.md) | Добавление Host через API |
| Subscription Deploy | [docs/remnawave_subscription_deploy.md](docs/remnawave_subscription_deploy.md) | Развёртывание страницы подписки |
| Subscription Page | [docs/remnawave_subscription_page.md](docs/remnawave_subscription_page.md) | Конфигурация Nginx и Docker контейнера |
| Subscription Page v7 | [docs/remnawave_subscription_page_next.md](docs/remnawave_subscription_page_next.md) | Blue-green deploy, API-конфигурация, cutover и rollback |
| Проверки | [docs/smoke_tests.md](docs/smoke_tests.md) | Smoke-тесты панели и нод |
| Отключение ноды | [docs/remnawave_disable_node.md](docs/remnawave_disable_node.md) | Временное отключение ноды и хостов |
| Удаление ноды | [docs/remnawave_delete_node.md](docs/remnawave_delete_node.md) | Полное удаление ноды и связанных хостов |
| **Миграция Inbound** | **[docs/remnawave_migrate_inbound.md](docs/remnawave_migrate_inbound.md)** | Перенос Reality-inbound |
| **Миграция Hosts** | **[docs/remnawave_migrate_hosts.md](docs/remnawave_migrate_hosts.md)** | Перенос Host-binding’ов |
| **Миграция Users** | **[docs/remnawave_migrate_users.md](docs/remnawave_migrate_users.md)** | Полная миграция пользователей |

---

## 🧱 Архитектура развертывания

### Вариант 1 — Панель и страница подписки на одном хосте

```mermaid
flowchart TB
  User[Пользователь] -->|запрос к remna.vpn-for-friends.com или sub.vpn-for-friends.com| CloudflareDNS[Cloudflare DNS]
  CloudflareDNS --> PublicIP_One[Публичный IP Host1]

  PublicIP_One --> HAProxy443

  subgraph Host1 [Host1: panel + subpage + node]
    HAProxy443[HAProxy 443 TCP SNI]
    Nginx4443[Nginx 4443 loopback]
    Xray8444[Xray 8444 loopback]
    Panel3000[Panel app port 3000]
    Sub3010[Subscription page port 3010 docker]
    Certbot[Certbot ACME]

    HAProxy443 -->|SNI remna.* , sub.*| Nginx4443
    HAProxy443 -->|non-TLS/иное SNI| Xray8444

    Sub3010 -->|HTTP /api| Nginx4443
    Nginx4443 -->|proxy /api| Panel3000

    Nginx4443 -->|proxy| Panel3000
    Nginx4443 -->|proxy| Sub3010

    Nginx4443 -. validation .-> Certbot
  end

  Certbot -. DNS-01 или HTTP-01 .-> CloudflareDNS
```

---

### Вариант 2 — Панель и страница подписки на разных хостах

```mermaid
flowchart TB
  User[Пользователь] -->|remna-domain| CloudflareDNS[Cloudflare DNS]
  User -->|sub-domain| CloudflareDNS
  CloudflareDNS -->|A remna-domain| PublicIP_Panel[Публичный IP Host1]
  CloudflareDNS -->|A sub-domain| PublicIP_Sub[Публичный IP Host2]

  PublicIP_Panel --> HAProxy1

  subgraph Host1 [Host1: panel + node]
    HAProxy1[HAProxy 443 TCP SNI]
    Nginx1[Nginx 4443 loopback]
    Xray1[Xray 8444 loopback]
    Panel3000[Panel app port 3000]
    Certbot1[Certbot ACME]

    HAProxy1 -->|SNI remna-domain| Nginx1
    HAProxy1 -->|non-TLS/иное SNI| Xray1
    Nginx1 -->|proxy /api| Panel3000
    Nginx1 -. validation .-> Certbot1
  end

  PublicIP_Sub --> Nginx2

  subgraph Host2 [Host2: subscription]
    Nginx2[Nginx 443 upstream legacy/next]
    Sub3010[Legacy Subscription Page :3010]
    Sub3011[Subscription Page v7 :3011]
    Certbot2[Certbot ACME]
    Nginx2 -->|production upstream| Sub3010
    Nginx2 -->|production upstream| Sub3011
  end

  Sub3010 -->|HTTPS remna-domain /api| PublicIP_Panel
  Sub3011 -->|HTTPS remna-domain /api| PublicIP_Panel

  Certbot1 -. DNS-01 или HTTP-01 .-> CloudflareDNS
  Certbot2 -. DNS-01 или HTTP-01 .-> CloudflareDNS
```

---

## 🔒 Vault и секреты

```
inventory/group_vars/all/vault.yml
inventory/group_vars/panel/vault.yml
inventory/host_vars/<node>/vault.yml
```

> **Не коммитим** содержимое Vault в git.  
> Используйте `ansible-vault edit` для безопасного редактирования файлов.

---

## ✅ Проверка после развёртывания

```bash
curl -vk https://panel.example.com/health
docker logs remnanode --tail=50
echo | openssl s_client -connect IP:443 -servername panel.example.com
echo | openssl s_client -connect IP:443 -servername www.cloudflare.com
```

---

## Поддержка и вклад

PR приветствуются: дополнения к ролям, новые дашборды и правила, улучшения документации. Старайтесь сопровождать изменения коротким описанием и примерами проверки.

---

© [VPN for Friends](https://t.me/vpn_for_myfriends_bot)
