# remnawave_subscription_page — страница подписки (контейнер + системный Nginx)

Роль выполняет:
- создание каталога установки (по умолчанию `/opt/remnawave/subscription`),
- рендер `docker-compose.yml` и `.env`,
- старт/обновление контейнера `remnawave/subscription-page:latest`,
- рендер Nginx‑vhost (`subscription.conf`) с HTTPS на локальном порту `:4443`,
- health‑endpoint `/healthz` (не трогает upstream).

> Сертификат выпускается **внешней** ролью `nginx` (tls‑блоки), эта роль использует уже готовые `ssl_certificate`/`ssl_certificate_key`.

---

## Переменные (минимум)

```yaml
# Домены
remnawave_sub_public_domain: "sub.example.com"
remnawave_panel_frontend_domain: "panel.example.com"

# Пути/порты
remnawave_sub_dir: "/opt/remnawave/subscription"
remnawave_sub_app_port: 3005

# Как обращаться к панели из контейнера:
# 1) Через публичный домен панели (default):
remnawave_sub_use_local_docker_dns: false

# 2) Через docker‑alias 'remnawave' (только bundled, если контейнеры в одной сети):
# remnawave_sub_use_local_docker_dns: true

# Системный Nginx и TLS
remnawave_nginx_ssl_fullchain: "/etc/letsencrypt/live/{{ remnawave_sub_public_domain }}/fullchain.pem"
remnawave_nginx_ssl_privkey:   "/etc/letsencrypt/live/{{ remnawave_sub_public_domain }}/privkey.pem"
nginx_bind_address: "127.0.0.1"
nginx_external_https_port: 4443

# (опц.) Обновление SUB_PUBLIC_DOMAIN в .env панели и рестарт стека
remnawave_sub_update_panel_env: true
remnawave_panel_root_dir: "/opt/remnawave/panel"
```

Автосборка `.env` для контейнера:
```yaml
remnawave_sub_env:
  APP_PORT: "{{ remnawave_sub_app_port }}"
  REMNAWAVE_PANEL_URL: >-
    {{ 
      ('http://remnawave:3000/api' if remnawave_sub_use_local_docker_dns | bool 
       else 'https://' ~ remnawave_panel_frontend_domain ~ '/api') 
    }}
```

> Роль делает `assert`, что `remnawave_sub_use_local_docker_dns: true` допустим **только** в bundled‑сценарии.

---

## Примеры запуска

В составе orchestration роли:
```yaml
- name: SUBPAGE | Deploy bundled subscription page
  ansible.builtin.include_role:
    name: remnawave_subscription_page
  vars:
    remnawave_sub_deploy_mode: "bundled"
```

Как отдельная роль в плейбуке:
```yaml
- hosts: subscription
  become: true
  roles:
    - role: remnawave_subscription_page
```

Теги: `subpage`, `nginx`

---

## Что получает Nginx‑vhost

- HTTPS‑vhost на `listen {{ nginx_bind_address }}:{{ nginx_external_https_port }}`
- upstream на `127.0.0.1:{{ remnawave_sub_app_port }}`
- `/healthz` -> 200, не ходит в upstream
- gzip/headers и sane proxy‑timeouts
- сертификаты из путей `remnawave_nginx_ssl_fullchain`/`privkey`

> HTTP‑редирект/челлендж‑сайт для HTTP‑01 ACME — часть роли `nginx` и удаляется после выпуска сертификата.

---

## Отладка

- Проверить Nginx: `nginx -t && systemctl reload nginx`
- Проверить TLS локально: `echo | openssl s_client -connect 127.0.0.1:4443 -servername sub.example.com -brief`
- Логи контейнера: `docker compose -f /opt/remnawave/subscription/docker-compose.yml logs --tail=200`
- Health: `curl -k https://127.0.0.1:4443/healthz`
