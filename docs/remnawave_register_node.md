# Remnawave Register Node (API)

## TL;DR
Эта роль:
1) Берёт **SECRET_KEY** из `.env` ноды (мы его заранее получили из панели)
2) Поднимает контейнер ноды (уже сделано ролью `remnawave_node`)
3) Находит **UUID inbound'а** по тегу `VLESS TCP REALITY`
4) Создаёт запись ноды в панели через API
5) Проверяет, что нода подключилась

---

## Поток

```
Ansible → Remnawave API → создаёт Node → панель присваивает UUID
   │
   └→ Нода с SECRET_KEY подключается к панели по WebSocket
```

Если SECRET_KEY совпал — панель автоматически отметит ноду как **Online**.

---

## Переменные

| Переменная | Где задаётся | Описание |
|---|---|---|
| `remnawave_panel_url` | `group_vars/panel` | URL панели |
| `vault_remnawave_panel_api_token` | `group_vars/panel/vault.yml` | API ключ (Bearer) |
| `remnawave_inbound_tag` | `group_vars/all.yml` | Тег инбаунда в профиле: `VLESS TCP REALITY` |
| `remnawave_node_env_content` | `host_vars/<node>/main.yml` | Содержит `SECRET_KEY` и `NODE_PORT` |
| `remnawave_node_country_code` | `default: XX` | ISO-код страны |
| `remnawave_node_notify_percent` | default: 0 | Уведомления о лимите |
| `remnawave_node_traffic_limit_bytes` | default: 0 | Лимит трафика |
| `remnawave_node_consumption_multiplier` | default: 0.1 | Коэффициент тарификации |

---

## Пример вызова

```bash
make nodes LIMIT=de-fra-1 TAGS=register_node
```

---

## Проверка

### В панели → Nodes
Ищем ноду → статус должен быть **Online**.

### На ноде
```
docker logs remnanode --tail=50 | grep -i connected
```

Ожидаем:
```
connected to panel
```

---

## Troubleshooting

| Проблема | Решение |
|---|---|
| Нода видна, но `isConnected=false` | SECRET_KEY не совпадает — проверь `.env` |
| Панель не может достучаться до ноды | Проверь firewall: `NODE_PORT` |
| В панели нет инбаунда с тегом | Проверь тег в `remnawave_inbound_tag` |

