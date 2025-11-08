# remnawave_delete_node

Удаляет ноду Remnawave и (опционально) каскадно удаляет все связанные с ней Hosts через API.

## Кратко
- Находит ноду по `remnawave_node_uuid` или по имени `remnawave_node_name`.
- Собирает связанные хосты (те, у кого `nodes[]` содержит UUID ноды).
- При `remnawave_delete_hosts=true` удаляет хосты **bulk**-запросом.
- Удаляет ноду `DELETE /api/nodes/{uuid}` и **дожидается 404**.
- Безопасность: по умолчанию запрещает оставлять сиротские хосты (см. `remnawave_allow_orphan_hosts`).

## Переменные

### Доступ к панели
- `remnawave_panel_url` — базовый URL панели (пример: `https://panel.example.com`)
- `remnawave_panel_api_base` — вычисляется автоматически как `<url>/api`
- `remnawave_panel_api_token` — Bearer-токен (**хранить в Vault**)

### Цель
- `remnawave_node_uuid` — UUID ноды (приоритетнее имени)
- `remnawave_node_name` — имя ноды (если UUID не указан)

### Поведение
- `remnawave_delete_hosts` — `true/false` каскадно удалить все привязанные к ноде хосты (по умолчанию `true` в ваших сценариях)
- `remnawave_allow_orphan_hosts` — `false` (по умолчанию). Если `true`, разрешает удалять ноду, оставляя за ней привязанные хосты (не рекомендуется).
- `remnawave_dry_run` — только показать план действий
- `remnawave_timeout` — таймаут HTTP-запросов (сек)

## Используемые эндпоинты API
- Получение ноды: `GET /api/nodes`, `GET /api/nodes/{uuid}`
- Удаление ноды: `DELETE /api/nodes/{uuid}`
- Каталог хостов: `GET /api/hosts`
- Удаление хостов **bulk**: `POST /api/hosts/bulk/delete`

## Идемпотентность и проверки
- Перед удалением хостов делается запрос каталога и фильтрация `nodes[]`.
- После **bulk delete** — проверка, что хосты исчезли из каталога.
- После `DELETE` — ожидание состояния 404 для ноды (повторные запуски безопасны).

## Примеры

### 1) Удалить ноду по UUID и каскадно удалить её хосты
```bash
ansible-playbook -i inventory/hosts.ini playbooks/delete_node.yml   -e remnawave_node_uuid=UUID   -e remnawave_delete_hosts=true
```

### 2) Удалить ноду по имени, оставить хосты (явно подтвердив риск)
```bash
ansible-playbook -i inventory/hosts.ini playbooks/delete_node.yml   -e remnawave_node_name=de-fra-1   -e remnawave_delete_hosts=false   -e remnawave_allow_orphan_hosts=true
```

### 3) Сухой прогон (ничего не удаляет)
```bash
ansible-playbook -i inventory/hosts.ini playbooks/delete_node.yml   -e remnawave_node_name=de-fra-1   -e remnawave_dry_run=true
```

## Makefile (пример цели)
```makefile
delete-node: ## Удалить ноду (опц.: каскадно удалить связанные хосты)
	$(ANSIBLE) -i $(INVENTORY) playbooks/delete_node.yml \
		$(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)
# Примеры:
# make delete-node EXTRA='-e remnawave_node_uuid=UUID -e remnawave_delete_hosts=true'
# make delete-node EXTRA='-e remnawave_node_name=de-fra-1 -e remnawave_delete_hosts=false -e remnawave_allow_orphan_hosts=true'
# make delete-node EXTRA='-e remnawave_node_name=de-fra-1 -e remnawave_dry_run=true'
```
