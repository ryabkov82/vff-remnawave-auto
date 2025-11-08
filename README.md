# 🚀 VFF Remnawave Auto Deployment

Полностью автоматизированное развертывание **Remnawave Panel** и **Remnawave Nodes** с поддержкой:
- SNI-маршрутизации на одном IP (панель + Reality node)
- Автоматического деплоя и обновления нод
- Автоматической регистрации нод и хостов в панели
- Smoke-тестов и health-check таймеров

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
   vault_remnawave_panel_api_token: "eyJhbGciOi..."
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

> Подробности см. в [roles/remnawave_inbounds/README.md](roles-remnawave_inbounds-README.md)

---

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

## 📚 Документация

| Раздел | Файл | Описание |
|--------|------|----------|
| Панель | [docs/remnawave_panel.md](docs/remnawave_panel.md) | Установка панели и сервисов |
| Inbounds | [roles/remnawave_inbounds/README.md](roles-remnawave_inbounds-README.md) | Добавление и регистрация inbound’ов |
| HAProxy | [docs/haproxy_tls_sni.md](docs/haproxy_tls_sni.md) | Совместная работа панели и Xray |
| Ноды | [docs/remnawave_node.md](docs/remnawave_node.md) | Запуск контейнера с SECRET_KEY |
| Регистрация ноды | [docs/remnawave_register_node.md](docs/remnawave_register_node.md) | API-регистрация ноды |
| Регистрация Host | [docs/remnawave_add_host.md](docs/remnawave_add_host.md) | Добавление Host через API |
| Проверки | [docs/smoke_tests.md](docs/smoke_tests.md) | Smoke-тесты панели и нод |

---

## 🧱 Архитектура развертывания

```
Client
   │ HTTPS :443
   ▼
┌───────────────┐     ┌───────────────┐
│   HAProxy     │────▶│               │──▶ Remnawave Panel
│  (TCP SNI)    │     │   4443 TLS    │
└───────────────┘     └───────────────┘
        │
        │ SNI=www.cloudflare.com
        ▼
      Xray Reality 8444 (remnanode)
```

---

## 🔒 Vault и секреты

```
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
