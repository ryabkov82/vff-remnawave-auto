# remnawave_upgrade

Роль `remnawave_upgrade` предназначена для **безопасного и воспроизводимого обновления**
Remnawave Panel и Remnawave Nodes с учётом архитектурной особенности проекта:
**новые версии панели не являются backward-compatible со старыми нодами**.

Документ описывает:
- логику upgrade flow;
- используемые переменные роли;
- корректные способы запуска;
- типовые ошибки и способы их избежать.

---

## Ключевая особенность Remnawave

⚠️ **Важно**

После обновления панели:
- все ноды временно переходят в состояние `offline`;
- ноды начинают работать только после обновления до совместимой версии.

Это **ожидаемое и корректное поведение**.

---

## Cutover 2.7.4 → 3.2.3 (API tokens / scopes)

Remnawave 3.x вводит `ScopesGuard`. Токен без нужных resource scopes получит **403**
на ACTIVE automation (`make nodes`, inbounds, hosts, squads, subpage configs).

`make upgrade-remnawave` **не** выдаёт scopes и **не** запускает scope preflight.
`roles/remnawave_upgrade/tasks/preflight.yml` — это docker/compose проверка **до** upgrade;
на панели 2.7.4 она не может доказать 3.2.3 scopes.
`make verify-remnawave` проверяет только `GET /system/health`, `GET /nodes`,
`GET /system/nodes/metrics` — этого недостаточно для hosts / config-profiles / squads / subpage.

### Обязательный порядок

1. Backup DB / compose / env / snapshot.
2. Upgrade Panel → 3.2.3 (`make upgrade-remnawave`).
3. Убедиться, что DB migrations панели завершились.
4. В Remnawave выдать **используемым API token** необходимые scopes (см. ниже).
5. Выполнить `make remnawave-api-preflight`.
6. Только после успешного preflight запускать новую automation (`make nodes`, inbounds, …).
7. Затем smoke tests.

**DO NOT run new vff-remnawave-auto mutations before token scopes are configured.**

### Required production scopes

Официальные имена: `remnawave/backend` tag 3.2.3
`libs/contract/api/controllers-info.ts` + `buildResourceScope()` → `<resource>:*`.

`resource:*` выбран сознательно: automation делает несколько read/write endpoint
внутри ресурса. Успешный GET доказывает только read/list доступ
(например `hosts:read` / `hosts:list` достаточно для `GET /hosts`).
Write scope математически не доказывается без mutation — поэтому checklist обязателен.

| token variable | required scopes |
|---|---|
| `remnawave_panel_api_token` | `hosts:*` `nodes:*` `config-profiles:*` `internal-squads:*` `system:read` `keygen:get` |
| `remnawave_inbounds_cache_api_token` | `config-profiles:*` |
| `remnawave_external_squads_api_token` | `external-squads:*` `subscription-page-configs:*` |
| `remnawave_subpage_config_api_token` | `subscription-page-configs:*` |

`keygen:get` проверяется только вручную: `GET /api/keygen` preflight **не**
вызывает, потому что этот HTTP GET генерирует новый Node SECRET_KEY.

`remnawave_external_squads` использует **один** token для `GET /external-squads`
и `GET /subscription-page-configs`. `remnawave_subpage_config_api_token` — другая
ACTIVE role/variable; её тоже нужно проверять отдельно.

`remnawave_inbounds_cache_api_token` по умолчанию наследует panel token, но может
быть переопределена — preflight делает отдельный `GET /config-profiles/inbounds`.

Не предполагать, что разные variables содержат один и тот же secret.
Если inventory мапит несколько vars на один physical token, этому token нужно
**объединение scopes всех этих vars**. Preflight всё равно проверяет каждую
variable отдельным GET.

`system:read` покрывает `GET /system/health` (endpoint slug `system:remnawave-health`)
и `GET /system/nodes/metrics` в upgrade verify.

```bash
make remnawave-api-preflight LIMIT=panel
```

Только GET. Не создаёт токены и не меняет Vault.

---

## Общий сценарий обновления (upgrade flow)

Обновление выполняется строго в следующем порядке:

```
1. Pre-pull образов нод (без рестартов)
2. Обновление панели
3. Rolling update нод (serial=1)
4. Отдельная API-проверка панели (verify)
```

### Почему verify вынесен в отдельный шаг

- API-проверка относится **только к панели**
- `extra-vars` Ansible применяются **ко всем plays**
- запуск API-verify вместе с нодами приводит к ложным ошибкам

Поэтому verify выполняется **отдельной командой и только на панели**.

---

## Управление версиями

Версии панели и нод задаются централизованно:

```yaml
remnawave_release:
  panel: "2.3.2"
  node:  "2.3.1"
```

Если `remnawave_release` не задан:
- используются версии по умолчанию из ролей `remnawave_panel` и `remnawave_node`.

---

## Переменные роли

### Основные флаги стадий обновления

| Переменная | Описание | По умолчанию |
|-----------|---------|-------------|
| remnawave_upgrade_do_prepull | Pre-pull Docker-образов нод | true |
| remnawave_upgrade_do_panel | Обновление панели | true |
| remnawave_upgrade_do_nodes | Обновление нод | true |
| remnawave_upgrade_verify | Включить verify-стадию | true |
| remnawave_upgrade_verify_api | Проверка панели через API | false |

---

### Переменные API verify

```yaml
remnawave_api_base_url: "https://remna.example.com/api"
remnawave_panel_api_token: "..."
remnawave_validate_certs: true
remnawave_health_retries: 30
remnawave_health_delay: 2
```

⚠️ `remnawave_api_base_url` **должен содержать `/api`**  
(пример: `https://host/api`).

---

## Что проверяется на verify-стадии

1. `GET /system/health`
2. `GET /nodes`
3. `GET /system/nodes/metrics`

Для `/nodes` и `/system/nodes/metrics` используется ожидание (`retries/delay`),
чтобы дождаться появления всех нод после rolling-апдейта.

---

## Makefile targets

В проекте предусмотрены основные цели:

### Обновление панели и нод

```bash
make upgrade-remnawave
```

Выполняет:
- pre-pull образов;
- обновление панели;
- rolling update нод.

❗ API-verify **не выполняется**.

---

### Проверка состояния панели через API

```bash
make verify-remnawave
```

Особенности:
- выполняется **только на панели** (`--limit panel`);
- безопасно повторяется;
- рекомендуется запускать после каждого апдейта.

---

## Типовые сценарии использования

### Полный рекомендуемый сценарий

```bash
make upgrade-remnawave
make verify-remnawave
```

---

### Повторная проверка состояния

```bash
make verify-remnawave
```

---

### Апдейт без verify

```bash
make upgrade-remnawave EXTRA='-e remnawave_upgrade_verify=false'
```

---

## ❌ Неправильные сценарии (НЕ ДЕЛАТЬ)

### Включение verify через EXTRA без ограничения хоста

```bash
make upgrade-remnawave EXTRA='-e remnawave_upgrade_verify_api=true'
```

Причина:
- `extra-vars` применяются ко всем plays;
- verify попадает на ноды;
- роль падает из-за отсутствия API-переменных.

---

## Известные подводные камни

- ❗ Ноды offline сразу после апдейта панели — **нормально**
- ❗ API verify нельзя включать глобально
- ❗ `/api/api/...` означает неверный `remnawave_api_base_url`
- ❗ Verify всегда выполняется отдельным шагом

---

## Рекомендации по эксплуатации

- Всегда использовать `make verify-remnawave`
- Не включать `remnawave_upgrade_verify_api` в `group_vars/all.yml`
- Хранить API token панели в vault
- Использовать verify как read-only проверку

---

## Назначение роли

`remnawave_upgrade` — orchestration-роль,
реализующая корректный upgrade flow Remnawave
с учётом отсутствия backward compatibility между версиями.
