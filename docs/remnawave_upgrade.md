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
