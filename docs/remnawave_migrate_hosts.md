# remnawave_migrate_hosts

> **LEGACY:** validated only for historical Remnawave 2.7.4 migration flow.
> Do not run against 3.2.3.

Роль `remnawave_migrate_hosts` выполняет автоматическую миграцию **Host‑конфигураций** из Marzban в Remnawave, строго соблюдая идемпотентность (повторный запуск не создаёт дубликатов).

Это второй ключевой этап миграции после переноса Reality‑inbound’a.

---

## 🎯 Цель роли

В Marzban хосты (`hosts`) — это список доменов и маршрутов, которые клиенты используют для подключения.

Роль:

1. Получает список хостов из Marzban.
2. Нормализует их параметры (remark, path, host, sni, fingerprint, alpn, securityLayer и т.д.).
3. Создаёт их в Remnawave, привязывая к выбранному inbound’у.
4. Гарантирует **идеальную идемпотентность**:
   - повторный запуск не создаёт дубликатов;
   - каждый host мигрируется ровно один раз.

---

## 📌 Идемпотентность

Для определения уникальности хоста используется строгий и стабильный ключ:

```
address|port
```

Почему так:

- `address` уникален (например: *edge-ams-01.digitalstreamers.xyz*)
- `port` почти всегда 443
- `remark` плохо подходит — он может быть обрезан Remnawave или слегка отличаться между системами

Поэтому при повторном запуске роли:

- все уже созданные `address|port` попадают в `_mh_existing_host_keys`
- каждый новый Marzban‑хост проверяется по ключу
- если host уже есть — он **пропускается**

---

## 📦 Что делает роль

### 1. Читает хосты из Marzban

Через:

```
GET /api/hosts
```

> ⚠️ Поля в Marzban могут быть null, пустыми или отсутствовать — роль их нормализует.

### 2. Читает текущие хосты Remnawave

Через:

```
GET /api/hosts
```

Important: API возвращает строго:

```json
{ "response": [ {...}, {...} ] }
```

Поэтому список извлекается как:

```yaml
_mh_rw_hosts_list: "{{ _mh_rw_hosts_raw.json.response | default([]) }}"
```

### 3. Нормализует входящие значения

Роль приводит к корректному виду:

- `remark` (не более 40 символов)
- `sni` → address, если пусто
- `host` → host → sni → address
- `path` → "/" если null
- `alpn` → omit, если пусто
- `fingerprint` → omit, если пусто
- `allowInsecure` → boolean
- `securityLayer` → STRICT enum: `DEFAULT`, `TLS`, `NONE`

### 4. Собирает CreateHostRequestDto

С полями:

```yaml
inbound:
  configProfileUuid: ...
  configProfileInboundUuid: ...

address: ...
port: ...
remark: ...
host: ...
sni: ...
path: ...
alpn: <omit>
fingerprint: <omit>
securityLayer: DEFAULT
allowInsecure: false
```

### 5. Создаёт хост в Remnawave (если его нет)

```
POST /api/hosts
```

---

## 🧪 Режим Dry‑Run

В переменной:

```yaml
remnawave_migrate_hosts_dry_run: true
```

Роль:

- не делает PATCH/POST
- только выводит:
  - пропуски: `Skip existing host: ...`
  - будущие создания: `DRY-RUN: show host body to create`

---

## 🔧 Входные переменные

Обычно задаются в `group_vars/panel.yml`.

### Основные

```yaml
# Marzban API
marzban_api_base_url: "https://marzban-s2.vpn-for-friends.com:4443"
marzban_api_token: ""
marzban_admin_username: "admin"
marzban_admin_password: "changeme"

# Remnawave API
remnawave_api_base_url: "https://{{ remnawave_panel_frontend_domain }}/api"
remnawave_panel_api_token: "rw_xxx"

# Какой inbound привязывать к хостам
remnawave_migrate_hosts_target_inbound_tag: "VLESS TCP REALITY"

# Dry‑run
remnawave_migrate_hosts_dry_run: true
```

---

## ▶️ Как запустить

### Один раз мигрировать:

```bash
make migrate-hosts
```

или:

```bash
make migrate-hosts EXTRA='-e remnawave_migrate_hosts_dry_run=false'
```

### Dry‑run:

```bash
make migrate-hosts EXTRA='-e remnawave_migrate_hosts_dry_run=true'
```

---

## 🧱 Как устроена роль внутри

### Шаги:

1. Получение и авторизация Marzban (если токена нет)
2. Получение списка хостов из Marzban
3. Получение списка хостов из Remnawave
4. Построение `_mh_existing_host_keys` (`address|port`)
5. Для каждого Marzban‑host:
   - нормализация
   - проверка idempotency
   - dry‑run / create host
6. Лог-сводка

---

## 🛡️ Ограничения роли

- Роль **не удаляет** хосты в Remnawave
- Роль **не обновляет существующие** хосты (только создаёт новые)
- Роль не мигрирует пользователей — это отдельная роль
- Роль не переносит ноды — будет отдельный этап

---

## 📘 Пример Playbook

`playbooks/migrate_hosts.yml`:

```yaml
---
- name: Migrate Marzban hosts to Remnawave
  hosts: panel
  gather_facts: false
  roles:
    - role: remnawave_migrate_hosts
```

---

## 📄 Связанные роли

- `remnawave_migrate_inbound`
- `remnawave_migrate_users` (будет следующим шагом)
- `remnawave_node` (развёртывание нод)
- `remnawave_add_host` (ручное добавление одного хоста)
