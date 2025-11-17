# 📘 Role: `remnawave_subscription_page`
**Развертывание страницы подписки Remnawave (контейнер + системный Nginx)**

Роль отвечает за:

- создание каталога (`/opt/remnasub` по умолчанию),
- генерацию `docker-compose.yml` и `.env`,
- запуск/обновление контейнера `remnawave/subscription-page`,
- развертывание **основного Nginx-vhost** для домена подписки,
- (опционально) развертывание **legacy-vhost** для поддержки старых Marzban-ссылок,
- корректный reverse-proxy с `X-Forwarded-*` для работы ProxyCheckMiddleware,
- минимальный `/healthz`, не ходящий в upstream,
- обновление `.env` панели (SUB_PUBLIC_DOMAIN),
- взаимодействие с внешней ролью `remnawave_subscription_deploy`, которая выдает сертификаты и создает DNS-записи.

---

# 🔧 Переменные роли

## 🟦 Основные переменные

```yaml
# Где развернуть приложение
remnawave_sub_dir: "/opt/remnasub"

# Домен страницы подписки
remnawave_sub_public_domain: "sub.example.com"

# Порт, на котором работает контейнер
remnawave_sub_app_port: 3010

# Путь к панели
remnawave_panel_frontend_domain: "panel.example.com"
```

---

## 🟩 Как контейнер обращается к панели

### Вариант 1: через публичный домен панели (обычный случай)

```yaml
remnawave_sub_use_local_docker_dns: false
```

### Вариант 2: через docker-alias `remnawave` (только bundled-режим!)

```yaml
remnawave_sub_use_local_docker_dns: true
```

Будет использовано:

```
REMNAWAVE_PANEL_URL=http://remnawave:3000
```

> Роль делает `assert`: `*_use_local_docker_dns: true` допустимо только при `bundled`-режиме.

---

## 🔒 TLS и системный Nginx

Сертификаты **не выпускает эта роль** — их выдает `roles/nginx`, но она ожидает:

```yaml
remnawave_nginx_ssl_fullchain: "/etc/letsencrypt/live/{{ remnawave_sub_public_domain }}/fullchain.pem"
remnawave_nginx_ssl_privkey:   "/etc/letsencrypt/live/{{ remnawave_sub_public_domain }}/privkey.pem"
```

И Nginx слушает локально:

```yaml
remnawave_nginx_bind_address: "127.0.0.1"
remnawave_nginx_external_https_port: 4443
```

---

## ⚠️ Marzban Legacy Mode — поддержка старых ссылок

Роль может автоматически обслуживать старые ссылки:

```
https://marzban-s2.example.com:4443/sub/<token>
```

### Включение:

```yaml
remnawave_sub_marzban_legacy_enabled: true
remnawave_sub_marzban_secret_key: "{{ vault_marzban_jwt_secret }}"
remnawave_sub_marzban_custom_sub_prefix: "sub"   # старый префикс
remnawave_sub_legacy_domain: "marzban-s2.example.com"
```

Что делает роль:

- генерирует **дополнительный legacy-vhost**  
- добавляет rewrite:  
  - если `CUSTOM_SUB_PREFIX` указан — `/sub/<token> → /myprefix/<token>`
  - иначе — `/sub/<token> → /<token>`
- проксирует запросы к контейнеру subscription-page,
- обновляет `CUSTOM_SUB_PREFIX`, `MARZBAN_LEGACY_*` в `.env`.

### Выключение:

```yaml
remnawave_sub_marzban_legacy_enabled: false
```

Роль автоматически:

- удаляет `nginx-legacy-marzban.conf`
- удаляет symlink в sites-enabled
- делает `nginx -t && reload`

---

# 📄 Переменные для legacy

| Переменная | Значение |
|-----------|----------|
| `remnawave_sub_marzban_legacy_enabled` | включение/выключение |
| `remnawave_sub_marzban_secret_key` | secret_key из JWT таблицы Marzban |
| `remnawave_sub_marzban_custom_sub_prefix` | старый префикс: почти всегда `sub` |
| `remnawave_sub_legacy_domain` | домен вида `marzban-s2.example.com` |
| `remnawave_sub_remnawave_api_token` | токен для запросов к панели |

В `.env` формируется:

```
MARZBAN_LEGACY_LINK_ENABLED=true
MARZBAN_LEGACY_SECRET_KEY=...
CUSTOM_SUB_PREFIX=<runtime prefix>
REMNAWAVE_API_TOKEN=...
```

---

# ⚙️ Автоматически собираемый `.env`

```yaml
remnawave_sub_env:
  APP_PORT: "{{ remnawave_sub_app_port }}"
  REMNAWAVE_PANEL_URL: >-
    {{
      'http://remnawave:3000'
      if remnawave_sub_use_local_docker_dns | bool
      else 'https://' ~ remnawave_panel_frontend_domain
    }}
  META_TITLE: "Subscription page"
  META_DESCRIPTION: "Subscription page for Friends Connect"
  CUSTOM_SUB_PREFIX: ""
  MARZBAN_LEGACY_LINK_ENABLED: "false"
```

---

# 🧱 Что делает роль — подробно

1. **Создаёт каталог установки**
2. **Рендерит**:
   - `docker-compose.yml`
   - `.env`
   - `app-config.json`
3. **Запускает контейнер**, используя `community.docker.docker_compose_v2`
4. **Разворачивает Nginx-vhost** для `sub.example.com`
5. **При включённом legacy**:
   - рендерит второй vhost `nginx-legacy-marzban.conf.j2`
   - делает rewrite + proxy_pass
   - включает сертификат legacy-домена
6. **При выключении legacy**:
   - удаляет legacy-конфиг
   - удаляет include
   - перезагружает Nginx
7. **Опционально обновляет .env панели: SUB_PUBLIC_DOMAIN**
8. **Уведомляет handlers**:
   - reload Nginx
   - restart container
   - restart panel (если нужно)

---

# 🏗 Примеры запуска роли

## В составе deploy-роли:

```yaml
- name: SUBPAGE | Deploy bundled subscription page
  ansible.builtin.include_role:
    name: remnawave_subscription_page
  vars:
    remnawave_sub_deploy_mode: "bundled"
```

## Самостоятельно:

```yaml
- hosts: subscription
  become: true
  roles:
    - role: remnawave_subscription_page
```

Теги: `subpage`, `nginx`, `legacy`

---

# 🧪 Отладка

### Проверка Nginx:

```
nginx -t && systemctl reload nginx
```

### Проверка сертификата:

```
echo | openssl s_client -connect 127.0.0.1:4443 -servername sub.example.com -brief
```

### Проверка legacy:

```
curl -vk https://marzban-s2.example.com:4443/sub/<token>
```

### Логи контейнера:

```
docker compose -f /opt/remnasub/docker-compose.yml logs --tail=200
```

### Health:

```
curl -k https://127.0.0.1:4443/healthz
```

---

# 🟩 Итог

Роль полностью закрывает развертывание subscription-service:

```
.env → контейнер → основной vhost → legacy vhost → прокси → X-Forwarded → health
```

Она изолирована от DNS и сертификатов, но совместно с `remnawave_subscription_deploy` обеспечивает полный pipeline подписки.

