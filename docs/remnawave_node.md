# Remnawave Node Deployment

## Кратко
Нода — это просто **контейнер с Xray**, который подключается к панели по **SECRET_KEY**.
Ключ **не генерируется** Ansible — его копируем из панели.

## Последовательность
1) В панели → Nodes → Add Node → Show docker-compose → копируем `SECRET_KEY`
2) Добавляем в `host_vars`:
```
inventory/host_vars/de-fra-1/main.yml
```
```yaml
remnawave_node_write_env: true
remnawave_node_env_content: |
  NODE_PORT=2222
  SECRET_KEY=eyJ...
```
3) Деплой контейнера:
```
make nodes LIMIT=de-fra-1 TAGS=node
```

## Что делает роль `remnawave_node`

| Компонент | Действие |
|---|---|
| `.env` | Создаётся из шаблона |
| `docker-compose.yml` | Рендерится из `templates/` |
| Контейнер `remnanode` | Запускается / перезапускается |
| Health | Проверка порта ноды |

Проверка:
```
docker logs remnanode --tail=50
```

Ожидаем сообщение о подключении к панели.
