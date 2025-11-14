# remnawave_migrate_inbound

Роль `remnawave_migrate_inbound` синхронизирует **Reality-настройки inbound’a** в Remnawave
с исходным inbound’ом из Marzban.  
Цель роли — сделать миграцию максимально прозрачной для клиентов: чтобы
`privateKey`, `shortIds`, `serverNames` и прочие поля Reality совпадали в обеих панелях.

Роль **ничего не меняет в пользователях, нодах и hosts** – только в одном inbound’e
внутри выбранного config profile.

---

## Что именно делает роль

1. Подключается к **Marzban API** и запрашивает core-config:
   - `GET /api/core/config`;
   - находит inbound с тегом `marzban_inbound_tag` (по умолчанию `"VLESS TCP REALITY"`);
   - извлекает блок `streamSettings.realitySettings` (dest, privateKey, serverNames, shortIds, xver, show и т.д.).

2. Подключается к **Remnawave API** и:
   - запрашивает список config profiles: `GET /api/config-profiles`;
   - находит профиль, у которого есть inbound с тем же тегом `marzban_inbound_tag`;
   - по `uuid` профиля запрашивает полный профиль: `GET /api/config-profiles/{uuid}`;
   - берёт `config.inbounds` и находит inbound с нужным тегом.

3. Строит новый inbound:
   - берётся **текущий inbound из Remnawave**;
   - у него **заменяется только** `streamSettings.realitySettings` на marzban-овский;
   - все остальные поля inbound’a (tag, listen, port, protocol, sniffing и т.п.) остаются как есть.

4. Собирает новый `config` с обновлённым inbound’ом и, при наличии изменений,
   отправляет PATCH:
   - `PATCH /api/config-profiles`
   - body: `{ uuid, config }` с обновлённым `config.inbounds`.

Если после замены `realitySettings` итоговый список inbounds не меняется
(по сравнению с текущим) – PATCH не выполняется.

---

## Важные ограничения и гарантии

- Роль **не добавляет и не удаляет** inbounds в профиле — она только
  **заменяет Reality-настройки у одного inbound’a по тегу**.
- Роль **не трогает**:
  - пользователей,
  - hosts,
  - internal squads,
  - nodes.
- Роль не работает с Marzban users/hosts — только с core-config (inbounds).
- Ожидается, что:
  - в Marzban есть inbound с тегом `marzban_inbound_tag` в `core.config.inbounds`;
  - в Remnawave есть config profile, у которого в `config.inbounds` есть inbound с тем же тегом.

---

## Переменные роли

Рекомендуется задавать переменные в `group_vars/panel.yml`.

### Основные

```yaml
# Какой inbound мигрируем
marzban_inbound_tag: "VLESS TCP REALITY"

# Marzban API
marzban_api_base_url: "https://marzban-s2.vpn-for-friends.com:4443"
marzban_admin_username: "admin"
marzban_admin_password: "changeme"
# Либо готовый токен, тогда логин не выполняется
marzban_api_token: ""

# Remnawave API
remnawave_api_base_url: "https://{{ remnawave_panel_frontend_domain }}/api"
remnawave_panel_api_token: "rw_xxx"  # Bearer-токен панели
```

### Режим dry-run

```yaml
# Если true — роль НИЧЕГО не меняет в профиле,
# только выводит старые/новые realitySettings для проверки.
remnawave_migrate_inbound_dry_run: true
```

---

## Как это работает пошагово

1. Роль получает admin-токен Marzban (если `marzban_api_token` не задан).
2. Запрашивает Marzban core-config и находит inbound с тегом `marzban_inbound_tag`.
3. Получает список config profiles в Remnawave, находит профиль,
   в котором есть inbound с таким же тегом.
4. По `uuid` профиля запрашивает `GET /config-profiles/{uuid}` и извлекает:
   - `config`,
   - `config.inbounds`.
5. Находит inbound с нужным тегом внутри `config.inbounds` и:
   - заменяет у него `streamSettings.realitySettings` значениями из Marzban;
   - собирает новый список inbounds с заменой только одного элемента.
6. Формирует новый `config` с обновлённым inbound’ом и:
   - если изменений нет — выводит сообщение и ничего не патчит;
   - если изменения есть и `remnawave_migrate_inbound_dry_run=false` —
     вызывает `PATCH /config-profiles` с новым `config`.

---

## Пример playbook’а

`playbooks/migrate_inbound.yml`:

```yaml
---
- name: Migrate Marzban inbound to Remnawave config profile
  hosts: panel
  gather_facts: false
  roles:
    - role: remnawave_migrate_inbound
```

Ожидается, что группа `panel` в инвентаре содержит хост панели Remnawave
(например, `de-fra-1`).

---

## Пример запуска через Makefile

Таргет (пример):

```makefile
migrate-inbound: ## Миграция inbound VLESS TCP REALITY из Marzban в Remnawave
	$(ANSIBLE) -i $(INVENTORY) playbooks/migrate_inbound.yml $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)
```

### Dry-run (только показать old/new realitySettings):

```bash
make migrate-inbound EXTRA='-e remnawave_migrate_inbound_dry_run=true'
```

### Применить изменения:

```bash
make migrate-inbound EXTRA='-e remnawave_migrate_inbound_dry_run=false'
```

---

## Когда и зачем запускать эту роль

Роль имеет смысл запускать, когда:

- ты мигрируешь инфраструктуру с Marzban на Remnawave;
- хочешь, чтобы Reality-параметры (privateKey, shortIds, serverNames и т.д.)
  в Remnawave **точно совпадали** с теми, что были в Marzban;
- важно максимально сохранить совместимость со старыми конфигами клиентов
  (особенно там, где они кэшируют public key / shortIds и не сразу обновляют подписку).

Обычно это первый шаг в цепочке миграции:

1. `remnawave_migrate_inbound` — выравниваем Reality-конфиг inbound’а.
2. Роль миграции hosts из Marzban → Remnawave.
3. Роль миграции пользователей (UUID/лимиты).
4. Пошаговый перенос нод под управление Remnawave.
