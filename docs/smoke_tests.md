# Smoke Tests

## Цель
Проверить корректность:
- доступности панели
- статуса ноды
- маршрутизации HAProxy по SNI
- открытости портов

---

## Вызов тестов

```bash
make nodes LIMIT=node-name TAGS=smoke_node
```

```bash
make panel TAGS=smoke_panel
```

---

## Что проверяется

### Панель
```
curl -sk https://panel.example.com/health
```
Ожидаем:
```
{"status":"ok"}
```

### Нода (локальный health)
```
nc -z 127.0.0.1 $NODE_PORT
```

### SNI-маршрутизация
```
echo | openssl s_client -connect IP:443 -servername panel.example.com
echo | openssl s_client -connect IP:443 -servername www.cloudflare.com
```

### Docker состояние
```
docker ps --format "table {{.Names}}	{{.Status}}"
```

---

## Ошибки и решения

| Симптом | Причина | Решение |
|---|---|---|
| Панель не отвечает | Nginx не поднят | `make panel TAGS=nginx` |
| Нода в панели Offline | SECRET_KEY неверный | проверить `.env` |
| Reality inbound не работает | SNI роутинг не совпадает | проверить `haproxy_tls_sni` |
| TCP порт ноды недоступен | Firewall / UFW | открыть порт или убрать фильтры |

