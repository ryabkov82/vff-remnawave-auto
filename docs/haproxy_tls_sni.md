# HAProxy TLS SNI Router

## Задача
Разделить входящий TLS-трафик на **443**:
- если SNI = домен панели → отправить в nginx → панель
- иначе → Xray Reality inbound

## Схема
```
Client --> 443/Haproxy
    ├── SNI=panel.example.com → nginx:4443 → Remnawave Panel
    └── SNI=www.cloudflare.com → node:8444 → Xray Reality
```

## Почему TCP passthrough?
- Xray Reality должен видеть TLS ClientHello → значит **нельзя** терминировать TLS в nginx.
- HAProxy просто маршрутизирует по SNI без расшифровки.

## Где настраивается?
Роль: `roles/haproxy_tls_sni`

Основные переменные:
```yaml
haproxy_front_port: 443
haproxy_panel_port: 4443
haproxy_reality_port: 8444
```

Проверка:
```
echo | openssl s_client -connect node_ip:443 -servername panel.example.com
echo | openssl s_client -connect node_ip:443 -servername www.cloudflare.com
```
Ожидаем разные backend’ы.
