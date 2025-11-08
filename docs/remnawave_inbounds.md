# remnawave_inbounds — автоматическое добавление/обновление inbound'ов в Remnawave

Идемпотентная Ansible‑роль, которая через **Remnawave API** обновляет *Config Profile* (поле `config.inbounds`):
- добавляет или обновляет inbound’ы **по тегу** (`tag`);
- обрабатывает конфликт глобальной уникальности тегов (409) с **автопрефиксом**;
- (опционально) регистрирует добавленные inbound’ы во **внутреннем скваде** (*Internal Squad*, по умолчанию `Default-Squad`).

> Роль рассчитана на префикс переменных **`remnawave_*`** и токен из `remnawave_panel_api_token` (например, в `inventory/group_vars/all.yml`).


## Быстрый старт

1) **Переменные инвентаря** (пример `inventory/group_vars/panel/main.yml`):
```yaml
remnawave_api_base_url: "https://{{ remnawave_panel_frontend_domain }}/api"

# Что обновляем
remnawave_profile_uuid: "7988e3a1-5a32-461a-9136-c9475e92f19a"   # ← предпочтительно
# remnawave_profile_name: "Default-Profile"                       # альтернативно

# Политики роли
remnawave_tag_collision_mode: "auto_prefix"  # [fail|auto_prefix]
remnawave_update_mode: "upsert"              # [upsert|replace]
remnawave_validate_config: true

# Reality (секреты в vault)
remnawave_reality_private_key: "{{ vault_reality_private_key }}"
remnawave_reality_short_id:    "{{ vault_reality_short_id }}"

# Inbounds, которые нужно добавить/обновить (идемпотентно по tag)
remnawave_inbounds:
  - tag: "vless_reality_tcp_443"
    listen: "0.0.0.0"
    port: 443
    type: "vless"
    sniffing:
      enabled: true
      destOverride: ["http","tls"]
    settings:
      clients: []
    streamSettings:
      network: "tcp"
      security: "reality"
      realitySettings:
        dest: "www.cloudflare.com:443"
        serverNames: ["www.cloudflare.com"]
        privateKey: "{{ remnawave_reality_private_key }}"
        shortIds: ["{{ remnawave_reality_short_id }}"]
        xver: 0
        show: false
```

2) **Токен API** (пример `inventory/group_vars/all.yml`):
```yaml
remnawave_panel_api_token: "{{ vault_remnawave_panel_api_token }}"
```

3) **Плейбук** `playbooks/inbounds.yml`:
```yaml
---
- name: Remnawave | Ensure/update inbounds in config profile
  hosts: panel
  gather_facts: false
  roles:
    - role: remnawave_inbounds
      tags: [inbounds]
```

4) **Makefile** (фрагмент):
```makefile
PLAY_INBOUNDS := playbooks/inbounds.yml

inbounds:  ## Добавить/обновить inbound'ы (API панели)
	$(ANSIBLE) -i $(INVENTORY) $(PLAY_INBOUNDS) $(LIMIT_FLAG) $(TAGS_FLAG) $(ANSIBLE_FLAGS) $(EXTRA)
```
Примеры:
```bash
make inbounds
make inbounds LIMIT=panel
make inbounds TAGS=inbounds
make inbounds EXTRA='-e remnawave_profile_uuid=7988e3a1-5a32-461a-9136-c9475e92f19a'
```


## Доступные переменные роли (defaults)

```yaml
# API и целевой профиль
remnawave_api_base_url: ""                       # если пусто — соберётся от remnawave_panel_frontend_domain
remnawave_profile_name: "default"
remnawave_profile_uuid: ""                       # лучше указывать UUID

# Поведение
remnawave_tag_collision_mode: "auto_prefix"      # [fail|auto_prefix]
remnawave_update_mode: "upsert"                  # [upsert|replace]
remnawave_validate_config: true
remnawave_tag_prefix_template: "{profile_name}__{tag}"  # для автопрефикса при 409

# Reality
remnawave_reality_private_key: ""
remnawave_reality_short_id: ""

# Список описаний inbound'ов (идемпотентный upsert по tag)
remnawave_inbounds: []

# Регистрация в Internal Squad
remnawave_register_inbounds_in_squad: true
remnawave_internal_squad_name: "Default-Squad"
remnawave_internal_squad_uuid: ""                # можно указать явно
```

### Замечания
- **`tag` должен быть глобально уникален** в Remnawave. При 409 роль применит автопрефикс (или упадёт — в зависимости от `remnawave_tag_collision_mode`).
- Режим `upsert`: объединяет существующий объект по `tag` с вашим (глубокий merge).  
  Режим `replace`: перезаписывает объект по `tag` целиком значением из `remnawave_inbounds`.
- `publicKey` для Reality хранить в профиле **не нужно** — панель подставляет его клиентам автоматически по `privateKey`. Но удобно сохранить `publicKey` в vault для внешних сценариев (бот/инструкции).


## Регистрация в Internal Squad

Если включено (`remnawave_register_inbounds_in_squad: true`), роль:
1) перечитывает профиль и находит **UUID** добавленных inbound’ов по их `tag`;
2) находит **Internal Squad** по UUID или имени (`Default-Squad` по умолчанию);
3) объединяет списки inbound’ов (без удаления существующих) и делает `PATCH /api/internal-squads`.

> Можно указать `remnawave_internal_squad_uuid` для точного попадания в нужный сквад.


## Генерация Reality‑ключей (подсказка)

Через Docker (не требует установки на хосте):
```bash
# Reality keypair
docker run --rm ghcr.io/sagernet/sing-box:latest generate reality-keypair

# Short ID (16 hex)
docker run --rm alpine:3 sh -c 'apk add --no-cache openssl >/dev/null && openssl rand -hex 8'
```

Через xray:
```bash
docker run --rm ghcr.io/xtls/xray-core:latest x25519        # выдаст private; можно derive public:
docker run --rm ghcr.io/xtls/xray-core:latest x25519 -i <PRIVATE>
```

Сохраните значения в vault:
```bash
ansible-vault edit inventory/group_vars/panel/vault.yml
# vault_reality_private_key, vault_reality_short_id, (опц.) vault_reality_public_key
```


## Диагностика

Посмотреть, какие профили вернулись из API:
```yaml
- debug: var=_cp_list
  run_once: true
  tags: [diag]
```
Запуск:
```bash
ansible-playbook -i inventory/hosts.ini playbooks/inbounds.yml -t diag --limit panel
```

---

**Лицензия:** MIT  
**Поддержка:** issues/PR в репозитории проекта.
