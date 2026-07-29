# Remnawave Subscription Page branding (multi-brand)

Архитектура управления двумя брендами Subscription Page через Remnawave Backend **2.7.4**.

## Модель конфигурации

```
roles/remnawave_subscription_page_config/files/base.json
roles/remnawave_subscription_page_config/files/brands/vpn-for-friends.patch.json
roles/remnawave_subscription_page_config/files/brands/friends-connect.patch.json
        │
        ▼
scripts/build_subpage_config.py   (deep merge + validate)
        │
        ▼
Subpage Config "VPN for friends"
Subpage Config "Friends Connect"
        │
        ▼
External Squad "VPN-for-Friends"  →  Subpage Config "VPN for friends"
External Squad "Friends-Connect"  →  Subpage Config "Friends Connect"
```

Общая структура страницы (платформы, приложения, инструкции, svgLibrary, baseTranslations)
живёт в `base.json`. Brand patch содержит **только** брендовые различия.

### Семантика merge

Реализована в `scripts/subpage_branding.py` (`deep_merge`):

- объекты сливаются рекурсивно по ключам;
- `null` в patch удаляет ключ (как JSON Merge Patch);
- списки словарей сливаются **по индексу** (частичный объект мержится в элемент base; `{}` — no-op);
- прочие списки и скаляры полностью заменяются patch-значением;
- порядок ключей не влияет на сравнение (canonical JSON / Remnawave canonicalize).

Общий нейтральный логотип `https://remna.st/img/logo.svg` задаётся в `base.json`
(`brandingSettings.logoUrl`) и не переопределяется брендовыми patch-файлами.

### Брендовые JSON-path

| Path | VFF (production) | Friends Connect |
|------|------------------|-----------------|
| `$.brandingSettings.title` | `VPN for friends` | `Friends Connect` |
| `$.brandingSettings.logoUrl` | `https://remna.st/img/logo.svg` (общий, в `base.json`) | то же |
| `$.brandingSettings.supportUrl` | `https://t.me/friends_connect_support` | `https://t.me/friends_connect_support` |
| `$.baseSettings.metaTitle` | `VPN for friends` | `Friends Connect` |
| `$.platforms.windows.apps[0].blocks[1].buttons[0].link` | `https://vff.portalbase.link/redirect.html?...` | `https://fc.portalbase.link/redirect.html?...` |

Инструкции приложений, списки клиентов и общие тексты **не** считаются брендовыми.

Golden-эталон VFF: `tests/fixtures/vpn-for-friends.golden.json`  
(`base + vff patch` должен быть канонически эквивалентен).

## Subpage Config (Ansible)

Роль: `roles/remnawave_subscription_page_config`

Inventory (`inventory/group_vars/subscription/main.yml`):

```yaml
remnawave_subpage_configs:
  - key: vff
    name: "VPN for friends"
    uuid: "…"   # существующий UUID
    base_file: base.json
    patch_file: brands/vpn-for-friends.patch.json
  - key: fc
    name: "Friends Connect"
    uuid: ""    # создать по имени, если отсутствует
    base_file: base.json
    patch_file: brands/friends-connect.patch.json
```

Для каждой записи роль:

1. собирает JSON через `scripts/build_subpage_config.py`;
2. валидирует локально;
3. `GET /api/subscription-page-configs` — поиск по UUID или точному имени;
4. при отсутствии — `POST /api/subscription-page-configs` с телом `{ "name": "…" }` (контракт 2.7.4: только name);
5. при отличии конфигурации — backup + `PATCH /api/subscription-page-configs` `{ uuid, config[, name] }`;
6. сохраняет resolved UUID в `remnawave_subpage_config_resolved`;
7. в check mode не делает POST/PATCH.

Legacy single-config (`remnawave_subpage_config_uuid` + `source_file`) работает, если `remnawave_subpage_configs` пуст.

### Подтверждённые API endpoints (Backend 2.7.4)

| Method | Path | Назначение |
|--------|------|------------|
| GET | `/api/subscription-page-configs` | список |
| GET | `/api/subscription-page-configs/{uuid}` | один объект |
| POST | `/api/subscription-page-configs` | create `{name}` |
| PATCH | `/api/subscription-page-configs` | update `{uuid, name?, config?}` |

Scopes: `subscription-page-configs: get, create, update`.

## External Squads

Роль: `roles/remnawave_external_squads`

```yaml
remnawave_external_squads:
  - name: "VPN-for-Friends"
    subpage_config_name: "VPN for friends"
  - name: "Friends-Connect"
    subpage_config_name: "Friends Connect"

remnawave_external_squads_protected_names:
  - AntiBlock-Premium
```

Роль:

- получает список External Squads;
- находит по **точному** имени;
- создаёт отсутствующий (`POST {name}`);
- назначает `subpageConfigUuid` только при расхождении (`PATCH {uuid, subpageConfigUuid}`);
- **не** меняет members / templates / hosts / headers / HWID / customRemarks;
- **не** трогает `AntiBlock-Premium`;
- неизвестное имя Subpage Config → понятная ошибка;
- в **check mode**, если Subpage Config декларативно объявлен в `remnawave_subpage_configs`,
  но ещё не существует в API: не требует UUID и печатает deferred-план
  («would be created after Subpage Config … is created, then linked…»);
- check mode без POST/PATCH.

### Подтверждённые API endpoints (Backend 2.7.4)

| Method | Path | Назначение |
|--------|------|------------|
| GET | `/api/external-squads` | список |
| POST | `/api/external-squads` | create `{name}` |
| PATCH | `/api/external-squads` | update, в т.ч. `subpageConfigUuid` |

Scopes: `external-squads: get, create, update` (+ `subscription-page-configs: get` для резолва имени).

## Команды

```bash
# локальная сборка/валидация брендов
make sub-next-config-check
# или:
.venv/bin/python scripts/build_subpage_config.py --brand vff -o /tmp/vff.json
.venv/bin/python scripts/build_subpage_config.py --brand fc -o /tmp/fc.json

# только Subpage Configs
make subpage-brands-check LIMIT=subscription
make subpage-brands LIMIT=subscription

# только External Squads
make external-squads-check LIMIT=subscription
make external-squads LIMIT=subscription

# оба шага
make subscription-branding-check LIMIT=subscription
make subscription-branding LIMIT=subscription

# тесты
.venv/bin/python -m unittest tests.test_subpage_branding -v
```

Обратная совместимость: `make sub-next-config-{check,plan,apply}` сохранены и работают с multi-brand inventory.

## Rollback

1. Backup JSON пишется на subscription-хост в `remnawave_subpage_config_backup_dir`
   (`/opt/remnasub-next/config-backups/<uuid>-<timestamp>.json`) перед PATCH.
2. Откат Subpage Config: `PATCH` с содержимым backup (вручную или временно подставив файл как `source_file`).
3. Откат связи External Squad: `PATCH` с прежним `subpageConfigUuid` (или `null`, если нужно отвязать).
4. AntiBlock-Premium и пользователи ролью не изменяются.

## Добавление третьего бренда

1. Создать `roles/.../files/brands/<brand>.patch.json` только с брендовыми path.
2. Добавить preset в `scripts/build_subpage_config.py` (`BRAND_PRESETS`), при необходимости.
3. Добавить запись в `remnawave_subpage_configs`.
4. Добавить External Squad в `remnawave_external_squads` с `subpage_config_name`.
5. Расширить `ALLOWED_BRAND_DIFF_PATHS` / тесты, если появились новые брендовые path.
6. `make sub-next-config-check` и check-mode plan до apply.

## Ограничения Remnawave API 2.7.4

- Create Subpage Config принимает **только** `name` (не полный config) — config заливается отдельным PATCH.
- Create External Squad принимает **только** `name` — привязка Subpage через PATCH `subpageConfigUuid`.
- Поиска «по имени» отдельным endpoint нет — используется list + exact match.
- Имена: 2–30 символов, `^[A-Za-z0-9_\s-]+$`.
- Роль **не** назначает пользователей External Squads и не вызывает bulk-actions add/remove users.
- `SUB_PUBLIC_DOMAIN`, старый домен `sub.vpn-for-friends.com`, SHM и remnawave-shm-template этой задачей не меняются.

## Локальный генератор

```bash
scripts/build_subpage_config.py --base ... --patch ... [--output FILE] [--stdout]
scripts/build_subpage_config.py --brand vff|fc ...
```

Только стандартная библиотека Python. Ненулевой exit code при ошибке JSON/валидации.
