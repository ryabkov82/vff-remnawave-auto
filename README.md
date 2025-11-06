# 🚀 VFF Remnawave Auto Deployment

Полностью автоматизированное развертывание **Remnawave Panel** и **Remnawave Nodes** с поддержкой:
- SNI-маршрутизации на одном IP (панель + Reality node)
- Автоматического деплоя и обновления нод
- Автоматической регистрации нод в панели
- Smoke-тестов и health-check таймеров

---

## ⚙️ Основные команды

### Развернуть панель
```bash
make panel
```
При необходимости:
```bash
make panel LIMIT=panel
make panel TAGS=haproxy
make panel TAGS=nginx
```

### Настроить DNS через Cloudflare
```bash
make dns LIMIT=panel TAGS=cf_dns
```

### Развернуть ноду (контейнер + SECRET_KEY)
```bash
make nodes LIMIT=node-name TAGS=node
```

### Зарегистрировать ноду в панели через API
```bash
make nodes LIMIT=node-name TAGS=register_node
```

### Smoke-тесты
```bash
make nodes LIMIT=node-name TAGS=smoke_node
```

---

## 📚 Документация

### 1) Панель и прокси
| Документ | Описание |
|---|---|
| **[docs/remnawave_panel.md](docs/remnawave_panel.md)** | Установка панели, Postgres/Redis, health-check |
| **[docs/haproxy_tls_sni.md](docs/haproxy_tls_sni.md)** | Как панель и Xray делят один 443 порт |

### 2) Ноды
| Документ | Описание |
|---|---|
| **[docs/remnawave_node.md](docs/remnawave_node.md)** | Запуск контейнера ноды с SECRET_KEY |
| **[docs/remnawave_register_node.md](docs/remnawave_register_node.md)** | API регистрация ноды + UUID inbound'а |

### 3) Проверки
| Документ | Описание |
|---|---|
| **docs/smoke_tests.md** *(будет добавлен)* | Проверка панели, нод и TCP портов |

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

## 🔒 Vault

Чувствительные данные хранятся в:
```
inventory/group_vars/panel/vault.yml
inventory/host_vars/<node>/vault.yml
```
**Не коммитим секреты в git.**

---

## ✅ Проверка после развёртывания

### Панель
```bash
curl -vk https://panel.example.com/health
```

### Нода
```bash
docker logs remnanode --tail=50
```

### Проверка маршрутизации SNI
```bash
echo | openssl s_client -connect IP:443 -servername panel.example.com
echo | openssl s_client -connect IP:443 -servername www.cloudflare.com
```

---
