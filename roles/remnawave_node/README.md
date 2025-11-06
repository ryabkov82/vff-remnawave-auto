# roles/remnawave_node

Роль устанавливает и запускает **Remnawave Node** (контейнер `remnawave/node`) в соответствии с официальными инструкциями.

## Как это работает

1. В панели Remnawave: **Nodes → Management → + → заполнить форму → Copy docker-compose.yml**. Обрати внимание на *Node Port* — это порт, на котором **нода** слушает внутренний API вызов панели.  
2. Передай YAML в переменную `remnawave_node_compose_raw` **или** используй Jinja-шаблон `templates/docker-compose.yml.j2` (когда удобнее управлять параметрами из Ansible).  
3. Роль создаст проект в `{{ remnawave_node_dir }}` и поднимет контейнер через `docker compose`.

> Документация: см. “Remnawave Node” (install), где описаны network_mode=host, env_file=.env, точечные монтирования geo-*.dat и рекомендации по логам/логротейту.

## Переменные (главные)

- `remnawave_node_compose_raw` — *сырой* docker-compose из панели (приоритетнее шаблона).
- `remnawave_node_write_env` + `remnawave_node_env_content` — если хочешь, чтобы роль записала `.env`.
- `remnawave_node_enable_host_logs` (bool), `remnawave_node_log_dir`, `remnawave_node_manage_logrotate` — логи Xray на хосте.
- `remnawave_node_geo_files` — список файлов `{src, dest_name}` для монтирования в `/usr/local/share/xray/…` (точечно).

## Быстрый пример (сырой compose из панели)

```yaml
- hosts: node
  roles:
    - role: remnawave_node
      vars:
        remnawave_node_compose_raw: "{{ lookup('file', 'files/docker-compose-node-from-panel.yml') }}"
        remnawave_node_enable_host_logs: true
        remnawave_node_manage_logrotate: true
