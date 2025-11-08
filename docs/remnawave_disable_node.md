# remnawave_disable_node

Временное **отключение (disable)** или **включение (enable)** ноды Remnawave. При желании — пакетное отключение/включение всех хостов, привязанных к ноде.

## Кратко
- Находит ноду по UUID/имени, читает текущий статус.
- Вызывает action-эндпоинт: `POST /api/nodes/{uuid}/actions/disable|enable`.
- Дожидается целевого состояния (`isDisabled`).
- При `remnawave_disable_hosts_of_node=true` выполняет **bulk** `enable|disable` для всех связанных хостов.

## Переменные

### Доступ к панели
- `remnawave_panel_url` — базовый URL панели (пример: `https://panel.example.com`)
- `remnawave_panel_api_base` — вычисляется автоматически как `<url>/api`
- `remnawave_panel_api_token` — Bearer-токен (**хранить в Vault**)

### Цель
- `remnawave_node_uuid` — UUID ноды (приоритетнее имени)
- `remnawave_node_name` — имя ноды (если UUID не указан)

### Состояние
- `remnawave_enable_state` — `false` для отключения (disable), `true` для включения (enable)

### Дополнительно
- `remnawave_disable_hosts_of_node` — `true/false` (по умолчанию `false`): переключить состояние всех хостов ноды.
- `remnawave_dry_run` — только показать план действий
- `remnawave_timeout` — таймаут HTTP-запросов (сек)

## Используемые эндпоинты API
- Получение ноды: `GET /api/nodes`, `GET /api/nodes/{uuid}`
- Действие над нодой: `POST /api/nodes/{uuid}/actions/disable` или `.../enable`
- Каталог хостов: `GET /api/hosts`
- Массовое изменение статуса хостов: `POST /api/hosts/bulk/disable` или `.../enable`

## Идемпотентность и проверки
- Роль читает текущее состояние; если целевое уже достигнуто — изменений нет.
- После action — ожидает подтверждения статуса `isDisabled`.
- Для хостов — выполняет bulk и может работать как enable, так и disable.

## Примеры

### 1) Отключить ноду по UUID
```bash
ansible-playbook -i inventory/hosts.ini playbooks/disable_node.yml   -e remnawave_node_uuid=UUID   -e remnawave_enable_state=false
```

### 2) Отключить ноду и все её хосты
```bash
ansible-playbook -i inventory/hosts.ini playbooks/disable_node.yml   -e remnawave_node_name=de-fra-1   -e remnawave_enable_state=false   -e remnawave_disable_hosts_of_node=true
```

### 3) Включить обратно
```bash
ansible-playbook -i inventory/hosts.ini playbooks/disable_node.yml   -e remnawave_node_name=de-fra-1   -e remnawave_enable_state=true
```

### 4) Сухой прогон
```bash
ansible-playbook -i inventory/hosts.ini playbooks/disable_node.yml   -e remnawave_node_name=de-fra-1   -e remnawave_enable_state=false   -e remnawave_dry_run=true
```

## Makefile (пример цели)
```makefile
disable-node: ## Отключить/включить ноду (опц.: отключить её хосты)
	$(ANSIBLE) -i $(INVENTORY) playbooks/disable_node.yml \
		$(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)
# Примеры:
# make disable-node EXTRA='-e remnawave_node_uuid=UUID -e remnawave_enable_state=false'
# make disable-node EXTRA='-e remnawave_node_name=de-fra-1 -e remnawave_enable_state=false -e remnawave_disable_hosts_of_node=true'
# make disable-node EXTRA='-e remnawave_node_name=de-fra-1 -e remnawave_enable_state=false -e remnawave_dry_run=true'
```
