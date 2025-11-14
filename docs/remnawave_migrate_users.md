# 🧩 Роль `remnawave_migrate_users`

Миграция пользователей из **Marzban** в **Remnawave** с сохранением:
- логина (`username`);
- статуса и лимитов трафика;
- даты истечения (`expireAt`), рассчитанной из unix‑timestamp Marzban;
- заметки (`description`);
- VLESS UUID (боевой идентификатор клиента);
- привязки к **Internal Squad** (для доступа к нодам/хостам).

Роль *ничего не трогает* в Marzban и работает только через его API.  
На стороне Remnawave пользователи создаются/обновляются через REST API панели.

---

## 🔧 Основная логика

Для каждого пользователя Marzban (`/api/users`):

1. **Чтение данных Marzban**
   - Берётся объект пользователя из `users[]`:
     - `username`
     - `status`
     - `expire` (unix‑timestamp, сек)
     - `data_limit`
     - `data_limit_reset_strategy`
     - `note`
     - `proxies.vless.id` (VLESS UUID)
   - При задании `remnawave_migrate_users_usernames` список пользователей фильтруется по указанным логинам.

2. **Преобразование полей**
   - `status` маппится в enum Remnawave:
     - `active` → `ACTIVE`
     - `disabled` → `DISABLED`
     - `limited` → `LIMITED`
     - `expired` → `EXPIRED`
     - `on_hold` → `DISABLED`
   - `expire` (unix‑timestamp) → `expireAt` (ISO‑строка) через `date -u -d @<ts> +%Y-%m-%dT%H:%M:%SZ`.
     - Если `expire` отсутствует или `0` → используется `remnawave_migrate_users_default_expire_at`.
   - `data_limit` → `trafficLimitBytes` (если `null` → `0`).
   - `data_limit_reset_strategy` → `trafficLimitStrategy`:
     - `no_reset` → `NO_RESET`
     - `day` → `DAY`
     - `week` → `WEEK`
     - `month` → `MONTH`
     - `year` → `MONTH` (по аналогии с официальным мигратором).
   - `note` → `description`.
   - `proxies.vless.id` → `vlessUuid` (боевой VLESS UUID).

3. **Привязка к Internal Squad**
   - Через `/internal-squads` выбирается сквад:
     - по `remnawave_internal_squad_uuid`, если задан;
     - иначе по `remnawave_internal_squad_name` (по умолчанию `Default-Squad`).
   - В тело create/update кладётся:
     - `activeInternalSquads: ["<uuid выбранного сквада>"]`,
       если `remnawave_migrate_users_assign_squad=true`.

4. **Создание или обновление пользователя в Remnawave**
   - Сначала выполняется `GET /users/by-username/{username}`.
   - Если пользователь **не найден** (404):
     - выполняется `POST /users` с полями:
       - `username`
       - `status`
       - `expireAt`
       - `trafficLimitBytes`
       - `trafficLimitStrategy`
       - `description`
       - `activeInternalSquads`
       - `vlessUuid` (если не пустой)
   - Если пользователь **уже есть** (200):
     - выполняется `PATCH /users` с полями:
       - `username`
       - `uuid` (как вернула панель)
       - `status`
       - `expireAt`
       - `trafficLimitBytes`
       - `trafficLimitStrategy`
       - `description`
       - `activeInternalSquads`
     - `vlessUuid` при обновлении **не меняется** (как и в официальном миграторе).

5. **Dry‑run**
   - При `remnawave_migrate_users_dry_run=true` запросы `POST`/`PATCH` **не отправляются**.
   - Роль выводит planned `create_body` / `update_body` для каждого пользователя.

---

## ⚙️ Входные переменные

### Базовые параметры Remnawave

```yaml
# Базовый URL API Remnawave (если не задан — собирается из домена панели)
remnawave_api_base_url: ""
remnawave_panel_frontend_domain: "remna.vpn-for-friends.com"

# Токен API панели Remnawave
remnawave_panel_api_token: ""
```

### Доступ к Marzban

```yaml
# Базовый URL панели Marzban
remnawave_migrate_users_marzban_base_url: "https://marzban-s2.vpn-for-friends.com:4443"

# Либо готовый токен, либо логин/пароль администратора
remnawave_migrate_users_marzban_token: ""
remnawave_migrate_users_marzban_username: "admin"
remnawave_migrate_users_marzban_password: ""
```

Если `remnawave_migrate_users_marzban_token` пуст, роль сама получит токен через
`POST /api/admin/token` по логину/паролю.

### Internal Squad

```yaml
# Имя / UUID внутреннего сквада, к которому будут привязаны пользователи
remnawave_internal_squad_name: "Default-Squad"
remnawave_internal_squad_uuid: ""

# Включать ли привязку пользователей к скваду
remnawave_migrate_users_assign_squad: true
```

### Поведение миграции

```yaml
# По умолчанию роль работает в dry-run режиме (ничего не меняет в панели)
remnawave_migrate_users_dry_run: true

# Какие пользователи Marzban мигрируются (если список пуст — все)
remnawave_migrate_users_usernames: []
#   - "us_67"
#   - "test_user"

# Значение expireAt, если в Marzban нет expire
remnawave_migrate_users_default_expire_at: "2099-12-31T23:59:59Z"
```

---

## ▶️ Пример playbook `playbooks/migrate_users.yml`

```yaml
---
- name: Migrate Marzban users to Remnawave
  hosts: panel
  gather_facts: false

  vars:
    # Примеры, обычно задаются в inventory или .env → group_vars
    # remnawave_panel_frontend_domain: "remna.vpn-for-friends.com"
    # remnawave_panel_api_token: "RW_API_TOKEN"

    # remnawave_migrate_users_marzban_base_url: "https://marzban-s2.vpn-for-friends.com:4443"
    # remnawave_migrate_users_marzban_token: "MARZBAN_API_TOKEN"
    # remnawave_migrate_users_marzban_username: "admin"
    # remnawave_migrate_users_marzban_password: "secret"

    # remnawave_internal_squad_name: "Default-Squad"
    # remnawave_internal_squad_uuid: ""

    # remnawave_migrate_users_dry_run: true

  roles:
    - role: remnawave_migrate_users
      tags: [remnawave_migrate_users, migrate_users]
```

---

## 🛠 Пример команд `make`

В `Makefile`:

```make
migrate-users: ## Миграция пользователей из Marzban в Remnawave
	$(ANSIBLE) -i $(INVENTORY) playbooks/migrate_users.yml $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)
```

Примеры использования:

### 1) Dry‑run для всех пользователей

```bash
make migrate-users LIMIT=panel
```

(по умолчанию `remnawave_migrate_users_dry_run=true`)

### 2) Dry‑run только для одного пользователя

```bash
make migrate-users LIMIT=panel EXTRA='-e remnawave_migrate_users_usernames=["us_67"]'
```

### 3) Реальная миграция конкретного пользователя

```bash
make migrate-users LIMIT=panel EXTRA='-e remnawave_migrate_users_dry_run=false -e remnawave_migrate_users_usernames=["us_67"]'
```

---

## 🧪 Что проверить после миграции

Для выбранного пользователя (например, `us_67`):

1. В панели Remnawave:
   - Пользователь существует.
   - `status`, `expireAt`, лимиты трафика и описание выглядят корректно.
   - У пользователя установлен `vlessUuid` совпадающий с Marzban (`proxies.vless.id`).
   - Пользователь состоит в выбранном Internal Squad.

2. В подписке Remnawave (после обновления ссылки в клиенте):
   - Пользователь получает список хостов (мигрированных `hosts`).
   - Подключение к нодам продолжает работать (сначала под управлением Marzban, затем — после миграции нод — через Remnawave).

Эта роль рассчитана на поэтапную миграцию: сначала inbound/hosts, затем пользователи, затем — переключение управления нодами с Marzban на Remnawave.
