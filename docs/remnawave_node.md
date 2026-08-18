# Remnawave Node Deployment

## Кратко
Нода — это просто **контейнер с Xray**, который подключается к панели по **SECRET_KEY**.

Для **новых** нод ключ больше не нужно копировать вручную и класть в
per-node `vault.yml`. `make nodes LIMIT=<new-node>` получает его через
`GET /api/keygen` (`response.secretKey`) и пишет в `/opt/remnanode/.env`.
Повторный запуск читает уже существующий `.env`, **не** вызывает keygen
и **не** перезаписывает файл.

Существующие Vault-секреты (`remnawave_secret_key`) поддерживаются и имеют
высший приоритет: старые ноды не перегенерируются.

## Источники SECRET_KEY

1. Явный `remnawave_secret_key` (inventory / per-node Vault) — без `/api/keygen`
2. Непустой `SECRET_KEY=` в `{{ remnawave_node_dir }}/.env` на ноде
   (файл — источник истины, роль его не переписывает)
3. Только если обоих нет: `GET {{ remnawave_panel_url }}/api/keygen`
   (нужен API token со scope `keygen:get`)

Ключ из API **не** пишется в inventory и **не** создаёт `vault.yml`.
`--check` не вызывает keygen: если ключа нет, play падает с
`SECRET_KEY is absent and cannot be generated in check mode`.

## Последовательность (новая нода)

1) `host_vars` с `remnawave_node_write_env: true` и
   `SECRET_KEY={{ remnawave_secret_key }}` в `remnawave_node_env_content`
   (сам ключ в Vault для новой ноды не обязателен)
2) Деплой:
```
make nodes LIMIT=de-fra-3 TAGS=node
```

## Последовательность (существующая нода с Vault)

Vault по-прежнему работает и перекрывает `.env` / keygen:

```yaml
# inventory/host_vars/de-fra-1/vault.yml
remnawave_secret_key: "eyJu..."
```

```
make nodes LIMIT=de-fra-1 TAGS=node
```

## Что делает роль `remnawave_node`

| Компонент | Действие |
|---|---|
| `.env` | Создаётся из шаблона только если `SECRET_KEY` ещё нет; существующий файл не трогается |
| `docker-compose.yml` | Рендерится из `templates/` |
| Контейнер `remnanode` | Запускается / перезапускается |
| Health | Проверка порта ноды |

Проверка:
```
docker logs remnanode --tail=50
```

Ожидаем сообщение о подключении к панели.
