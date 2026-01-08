# 🧩 Role: remnawave_add_host

Роль автоматически добавляет и приводит в соответствие (**reconcile**) **Host** в Remnawave Panel
и привязывает его к ранее созданной ноде.

Роль является **идемпотентной** и предназначена для декларативного управления Host-ами.

---

## 🔍 Назначение

Роль выполняет полный цикл управления Host через API панели Remnawave:

1. Определяет **Node UUID**:
   - использует `remnawave_node_uuid` (из роли `remnawave_register_node`), либо
   - ищет ноду по имени (`rw_node_name`).

2. Определяет **Inbound / Profile UUID**:
   - из явных UUID в описании host,
   - либо из кэша `remnawave_inbounds_by_tag`,
   - либо через API панели (`/config-profiles/inbounds`).

3. Создаёт Host (`POST /api/hosts`), если он отсутствует.

4. Для существующего Host:
   - при необходимости обновляет inbound (bulk set-inbound),
   - при необходимости обновляет порт (bulk set-port).

5. Опционально:
   - обновляет `REALITY.serverNames` для inbound-а,
   - удаляет устаревшие managed-host’ы (prune, только для текущей ноды).

---

## ⚙️ Основные переменные

### Обязательные

| Переменная | Описание |
|-----------|----------|
| `remnawave_panel_api_token` | Bearer-токен API панели |
| `remnawave_panel_api_base` | Базовый URL API (например `https://panel.example.com/api`) |

---

### Описание Host-ов (рекомендуемый способ)

```yaml
remnawave_hosts:
  - remark: "🇳🇱 2 vpn-for-friends"
    address: "ams-02.example.com"
    port: 443
    inbound_tag: "VLESS TCP REALITY"
    sni:
      - example.com
      - www.example.com

  - remark: "🇳🇱 2 vpn-for-friends (xHTTP)"
    address: "api-ams-02.example.com"
    port: 443
    inbound_tag: "VLESS xHTTP (behind nginx)"
    path: "/api/v1/sync/"
    patch_reality_servernames: false
    include_in_sni_map: false
```

---

### Ключевые поля Host

| Поле | Описание | По умолчанию |
|-----|----------|--------------|
| `remark` | Отображаемое имя Host | — |
| `address` | Адрес Host | — |
| `port` | Порт подключения | `443` |
| `inbound_tag` | Тег inbound-а | — |
| `sni` | SNI (string или list) | `address` |
| `path` | Path (например для xHTTP) | `""` |
| `patch_reality_servernames` | Обновлять REALITY.serverNames | `true` |
| `serverDescription` | Описание | `""` |

---

## 🧠 Поведение и логика

### Inbound и порт

- Inbound и порт **приводятся к желаемому состоянию**, если Host уже существует.
- Управляется флагами:
  ```yaml
  rw_host_set_inbound_if_exists: true
  rw_host_set_port_if_exists: true
  ```

### REALITY serverNames

- Вызывается роль `remnawave_reality_servernames` **только если**
  ```yaml
  patch_reality_servernames: true
  ```

### Managed hosts и prune

- Все Host-ы, созданные ролью, помечаются:
  ```yaml
  tag: "{{ rw_host_managed_tag }}"   # по умолчанию: VFF:MANAGED
  ```

- Поддерживается очистка устаревших Host-ов:
  ```yaml
  rw_host_prune: true
  rw_host_prune_scope: per_node
  ```

- В режиме `per_node` удаляются **только managed-host’ы**, привязанные к текущей ноде.

---

## 🚀 Пример запуска

```bash
make nodes LIMIT=nl-ams-2 TAGS=register_host
```

или напрямую:

```bash
ansible-playbook -i inventory/hosts.ini playbooks/nodes.yml   --limit nl-ams-2   --tags register_host
```

---

## 📤 Возвращаемые факты

| Факт | Описание |
|------|----------|
| `remnawave_node_uuid` | UUID ноды |
| `remnawave_inbounds_by_tag` | Mapping `{ tag → {inbound_uuid, profile_uuid} }` |

---

## 🔧 Примечания

- Роль безопасна для повторного запуска.
- Не использует `serverDescription` как managed-marker.
- Корректно обрабатывает несколько Host-ов и разные inbound-ы.
- Предназначена для совместного использования с:
  - `remnawave_register_node`
  - `remnawave_reality_servernames`
