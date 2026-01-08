# Remnawave Register Node (API)

## Назначение

Роль `remnawave_register_node` отвечает за **декларативную регистрацию ноды в панели Remnawave через API** и синхронизацию её inbound-конфигурации.

Роль **не поднимает контейнер ноды** и **не управляет SECRET_KEY** — этим занимается `remnawave_node`.
Задача роли — привести состояние панели в соответствие с описанием в Ansible.

---

## TL;DR

Роль делает следующее:

1) Проверяет доступ к панели Remnawave (URL + API token)
2) Определяет список inbound-тегов (поддержка single и multi-tag)
3) Разрешает соответствие **`inbound_tag → inbound_uuid + profile_uuid`**
   - сначала из уже известного mapping (`remnawave_inbounds_by_tag`)
   - при необходимости — через API панели
4) Создаёт ноду в панели **или** обновляет существующую (idempotent)
5) Гарантирует корректную привязку профиля и инбаундов
6) Экспортирует факты для последующих ролей

---

## Архитектурный поток

```
Ansible
  │
  ├─ remnawave_node
  │      └─ старт контейнера ноды с SECRET_KEY
  │
  └─ remnawave_register_node
         │
         ├─ GET /api/config-profiles/inbounds
         │      └─ resolve inbound_tag → inbound_uuid/profile_uuid
         │
         ├─ GET /api/nodes
         │      └─ find node by name
         │
         ├─ POST /api/nodes        (если ноды нет)
         │   или
         └─ PATCH /api/nodes       (если нода уже есть)
```

---

## Ключевые особенности

### Декларативная модель
Роль описывает желаемое состояние панели и приводит её к нему без лишних PATCH.

### Глобально уникальные inbound-теги
Один `inbound.tag` допускается только в одном профиле.
Дубликаты приводят к ошибке выполнения роли.

### Mapping-first стратегия
Если `remnawave_inbounds_by_tag` уже задан — API не вызывается.

### Безопасная работа с activeInbounds
Формат проверяется явно, чтобы избежать неидемпотентности.

---

## Переменные

### Обязательные

| Переменная | Описание |
|-----------|----------|
| `remnawave_panel_url` | URL панели |
| `remnawave_panel_api_token` | API token |
| `remnawave_register_enabled` | Включение роли |

### Inbound

| Переменная | Описание |
|-----------|----------|
| `remnawave_inbound_tags` | Список inbound-тегов |
| `remnawave_inbound_tag` | Legacy single-tag |
| `remnawave_profile_uuid` | UUID профиля (опционально) |

### Node

| Переменная | Описание |
|-----------|----------|
| `remnawave_node_name` | Имя ноды |
| `remnawave_node_address` | Адрес |
| `remnawave_node_port` | Порт |
| `remnawave_node_country_code` | ISO код |
| `remnawave_node_notify_percent` | Notify % |
| `remnawave_node_traffic_limit_bytes` | Traffic limit |
| `remnawave_node_consumption_multiplier` | Multiplier |

---

## Экспортируемые факты

```yaml
remnawave_node_uuid
remnawave_profile_uuid
remnawave_inbounds_by_tag
remnawave_inbound_uuid
```

---

## Пример запуска

```bash
make nodes LIMIT=de-fra-1 TAGS=register_node
```

---

## Проверка

В панели: **Nodes → Status = Online**

На ноде:
```bash
docker logs remnanode --tail=50 | grep -i connected
```

---

## Troubleshooting

| Симптом | Решение |
|-------|---------|
| Offline | Проверить SECRET_KEY |
| Дубликаты inbound tag | Исправить конфигурацию |
| PATCH каждый запуск | Проверить merge/replace |
