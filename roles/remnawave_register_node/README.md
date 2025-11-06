# remnawave_register_node

Создаёт (или обновляет) запись ноды в панели Remnawave и гарантирует,
что указанный inbound (по тегу) активирован у ноды. Профиль берётся из inbound.profileUuid
или задаётся явно.

## Vars
- remnawave_panel_url (str) — https://panel.example.com
- remnawave_panel_api_token (str, secret) — Bearer токен (хранить в Vault)
- remnawave_inbound_tag (str) — тег инбаунда, который активируем, по умолчанию "VLESS TCP REALITY"
- remnawave_profile_uuid (str) — UUID профиля; если пусто, используем profileUuid инбаунда
- remnawave_node_name / remnawave_node_address / remnawave_node_port — атрибуты ноды
- прочие поля: countryCode, consumptionMultiplier, и т.д.

## Tags
- register_node — выполнение регистрации

## Outputs (facts)
- remnawave_node_uuid — UUID созданной/найденной ноды
