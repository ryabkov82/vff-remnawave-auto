# ✅ Role: `remnawave_subscription_deploy`

Автодеплой страницы подписки Remnawave: выпуск сертификата (HTTP‑01/DNS‑01), конфиг Nginx, DNS-записи (Cloudflare), запуск приложения и интеграция с HAProxy (если нужно).

---

## Режимы развертывания

- **Bundled** — страница подписки на том же сервере, что и панель.
- **Separate** — страница подписки на отдельном сервере.

Выбор — через переменную `remnawave_sub_deploy_mode: bundled|separate`.

---

## Инвентори (исправлено)

Выберите один режим.

**A. Bundled (подписка и панель на одном сервере)** — **группу `[subscription]` НЕ создаём**.
```ini
[panel]
de-fra-1 ansible_user=root ...
```
Переменные подписки кладём в `inventory/group_vars/panel/` (например, `subscription.yml`).

**B. Separate (подписка на отдельном сервере)** — создаём `[subscription]`.
```ini
[panel]
de-fra-1 ansible_user=root ...

[subscription]
de-fra-2 ansible_user=root ...
```
Переменные подписки кладём в `inventory/group_vars/subscription/`.

---

## Минимальные переменные

Общие (папка зависит от режима, см. выше):

```yaml
remnawave_sub_public_domain: sub.vpn-for-friends.com
remnawave_sub_app_port: 3005
remnawave_sub_deploy_mode: bundled   # или separate

# Выпуск сертификата (выберите один режим)
nginx_tls_mode: "letsencrypt"        # http-01
nginx_letsencrypt_email: admin@vpn-for-friends.com

# или DNS‑01 (Cloudflare)
# nginx_tls_mode: "letsencrypt_dns01"
# cf_dns_api_token: "{{ vault_cf_dns_api_token }}"
# cf_dns_zone: "vpn-for-friends.com"
# cf_dns_target_ip: "77.239.127.199"
```

Если используете HAProxy (TLS passthrough на 443 → локальный Nginx:4443):
```yaml
nginx_bind_address: "127.0.0.1"
nginx_external_https_port: 4443
```

---

## Плейбук и Makefile

**Bundled:**
```bash
make sub            # или: ansible-playbook -i inventory/hosts.ini playbooks/subscription.yml --limit panel
```

**Separate:**
```bash
make sub-separate   # или: ansible-playbook -i inventory/hosts.ini playbooks/subscription.yml --limit subscription
```

Теги:
- `--tags dns` — только DNS
- `--tags cert` — только выпуск сертификата
- `--tags nginx` — только конфиг Nginx
- `--tags subpage` — только приложение
- `--tags haproxy` — только HAProxy часть

---

## Что делает роль

1. **DNS** (опц.) — создаёт/обновляет A/CNAME в Cloudflare.
2. **Cert** — выпускает сертификат через `roles/nginx`:
   - `letsencrypt` (HTTP‑01): временный `*.challenge.conf` → после выдачи удаляется автоматически.
   - `letsencrypt_dns01` (Cloudflare API token).
3. **Nginx** — рендерит сайт подписки, слушает `127.0.0.1:4443` (если используется HAProxy).
4. **App** — поднимает контейнер подписки.
5. **HAProxy** (опц.) — добавляет SNI домен подписки в ACL и прокидывает на Nginx:4443.

---

## Полезные проверки

```bash
# Сертификат на Nginx (локально)
echo | openssl s_client -connect 127.0.0.1:4443 -servername sub.vpn-for-friends.com -brief

# Сквозной путь через HAProxy (снаружи)
echo | openssl s_client -connect <PUBLIC_IP>:443 -servername sub.vpn-for-friends.com -brief

# HAProxy статистика по backend’ам
echo "show stat" | socat stdio /run/haproxy/admin.sock | grep -E 'be_panel|be_xray'
```

---

## Частые проблемы

- **502 Bad Gateway**: приложение не запущено/порт не совпадает/не тот `REMNAWAVE_PANEL_URL`.
- **Cloudflare “Edge IP Restricted”**: выключите оранжевое облако для A‑записи (используйте «серое»).
- **HTTP‑01 challenge остался включён**: в новой версии временный `*.challenge.conf` удаляется автоматически.
