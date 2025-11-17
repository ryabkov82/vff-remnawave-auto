# 🚀 Role: `remnawave_subscription_deploy`

Полностью автоматизированное развертывание **Remnawave Subscription Page**, включая:

- выпуск сертификатов (HTTP-01 или DNS-01)
- конфигурацию Nginx (основной домен + Marzban-legacy домен)
- развертывание контейнера subscription-page
- DNS-записи в Cloudflare
- интеграцию с HAProxy (TLS passthrough + SNI routing)
- автоматическое включение/отключение режима Marzban-legacy

---

# 🔧 Режимы развертывания

Роль поддерживает два варианта:

### **1) `bundled`** — subscription-page и панель на одном сервере  
→ сервер работает как HAProxy TLS-SNI router → локальный Nginx → контейнер.

### **2) `separate`** — subscription-page на отдельной машине  
→ HAProxy только на панели  
→ отдельный Nginx + контейнер на subscription-сервере.

Выбор режима:

```yaml
remnawave_sub_deploy_mode: bundled     # или: separate
```

---

# 📁 Инвентори

## ✔ Режим A: Bundled  
**Группу `[subscription]` создавать НЕ нужно.**

```
[panel]
de-fra-1 ansible_host=77.239.xxx.xxx ansible_user=root
```

Variables → `inventory/group_vars/panel/subscription.yml`

---

## ✔ Режим B: Separate  
Создаём две группы:

```
[panel]
de-fra-1 ansible_user=root

[subscription]
de-fra-2 ansible_user=root
```

Variables → `inventory/group_vars/subscription/subpage.yml`

---

# ⚙ Минимальные переменные

```yaml
remnawave_sub_public_domain: sub.vpn-for-friends.com
remnawave_sub_app_port: 3010
remnawave_sub_deploy_mode: bundled   # или: separate
```

### Сертификат HTTP-01

```yaml
nginx_tls_mode: "letsencrypt"
nginx_letsencrypt_email: admin@example.com
```

### или DNS-01 (Cloudflare)

```yaml
nginx_tls_mode: "letsencrypt_dns01"
cf_dns_zone: "vpn-for-friends.com"
cf_dns_api_token: "{{ vault_cf_dns_api_token }}"
cf_dns_target_ip: "77.239.xxx.xxx"
```

### Если используется HAProxy → Nginx (4443)

```yaml
nginx_bind_address: "127.0.0.1"
nginx_external_https_port: 4443
```

---

# 🟦 Marzban Legacy Mode

Позволяет обслуживать **старые ссылки вида**

```
https://marzban-s2.example.com:4443/sub/<token>
```

через новую subscription-page.

Включение:

```yaml
remnawave_sub_marzban_legacy_enabled: true
remnawave_sub_marzban_secret_key: "{{ vault_marzban_jwt_secret }}"
remnawave_sub_marzban_custom_sub_prefix: "sub"     # старый префикс
remnawave_sub_legacy_domain: "marzban-s2.example.com"
```

После включения роль автоматически:

✔ создаёт отдельный **Nginx-vhost legacy-домена**  
✔ выпускает для него сертификат  
✔ проксирует `/sub/<token>` внутрь subscription-page  
✔ корректно переписывает пути `/sub/...` → `/<CUSTOM_SUB_PREFIX>/...`  
✔ **удаляет legacy-конфиг**, если флаг выключить

---

# 🧱 Что делает роль

При выполнении:

### **1. DNS**
Создаёт/обновляет A-записи:

- домен subscription-page
- домен Marzban-legacy (если включён режим)

### **2. Сертификаты**
Через роль `roles/nginx`, полностью автоматизировано:

- HTTP-01 → создаёт временный `.challenge.conf`, затем удаляет
- DNS-01 → создаёт TXT через Cloudflare API

Выпускаются сертификаты:

- `sub.example.com`
- `marzban-s2.example.com` (если включён legacy)

### **3. HAProxy (в bundled)**
Добавляет SNI-домены в TLS-маршрутизацию:

- панель
- subscription-page
- legacy-домен (если включён)

### **4. Deployment**
Разворачивает:

- `docker-compose.yml`
- `.env`
- app-config.json
- контейнер `remnawave-subscription-page`

### **5. Nginx**
Рендерит:

- subscription-vhost  
- legacy-vhost (если включён)

Отключает/удаляет legacy-vhost если флаг выключен.

---

# 🏗 Плейбук и Makefile

### Bundled:

```
make sub
```

или:

```
ansible-playbook -i inventory/hosts.ini playbooks/subscription.yml --limit panel
```

### Separate:

```
make sub-separate
```

или:

```
ansible-playbook -i inventory/hosts.ini playbooks/subscription.yml --limit panel,subscription
```

---

# 🏷 Полезные теги

| Тег        | Что делает |
|-----------|------------|
| `dns`     | только DNS-записи |
| `cert`    | только выпуск сертификата |
| `nginx`   | конфиг Nginx |
| `legacy`  | только legacy-режим |
| `haproxy` | конфиг SNI в HAProxy |
| `subpage` | обновление контейнера |
| `sub_config` | обновление app-config |

---

# 🧪 Проверки

```
# Проверить локальный сертификат
echo | openssl s_client -connect 127.0.0.1:4443 -servername sub.example.com -brief

# Проверить путь через HAProxy
echo | openssl s_client -connect <PUBLIC_IP>:443 -servername sub.example.com -brief

# Проверить legacy
curl -vk https://marzban-s2.example.com:4443/sub/<token>
```

---

# ❗ Частые проблемы

### 1. **Ответ 502**
- контейнер не поднят
- неверный `REMNAWAVE_PANEL_URL`
- Nginx слушает не тот порт (`nginx_external_https_port`)

### 2. **Legacy не работает**
- не указан `remnawave_sub_legacy_domain`
- забыл обновить DNS
- забыта установка сертификата для legacy-домена

### 3. **Cloudflare ошибка Edge IP Restricted**
— A-запись должна быть **серой**, не «проксированной».

---

# 🟩 Итого

Эта роль является “верхнеуровневой” orchestration-надстройкой над:

- `roles/nginx`
- `roles/haproxy_tls_sni`
- `roles/cf_dns`
- `roles/remnawave_subscription_page`

и обеспечивает полный lifecycle:

```
DNS → TLS → Nginx → App → HAProxy → Marzban Legacy Support
```

Всё в одном месте, полностью автоматизировано.
