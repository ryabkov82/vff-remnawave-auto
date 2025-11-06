# Remnawave Panel — deployment + reverse proxy

## Кратко (TL;DR)
Панель поднимается в Docker, публикуется наружу через **nginx**, а TLS-порт **443** обслуживается **HAProxy** в режиме TCP passthrough с **SNI-роутингом**:
```
Client → 443 (HAProxy) → SNI=panel.example.com → nginx:4443 → Remnawave Panel
Client → 443 (HAProxy) → SNI=www.cloudflare.com → remnanode:8444 → Xray Reality
```
Таким образом панель и нода могут работать **на одном публичном IP**.

---
## Установка

Запуск:
```
make panel
```
Фактически выполняется playbook `playbooks/panel.yml`:

```yaml
- name: Deploy Remnawave Panel
  hosts: panel
  become: true
  roles:
    - common
    - docker_engine
    - remnawave_panel
    - nginx
    - haproxy_tls_sni
    - health_checks
```

---
## Что делает роль `remnawave_panel`

| Компонент | Действие |
|---|---|
| Postgres / Redis | Разворачиваются в контейнерах |
| Backend панели | Стартует на internal-порту |
| External URL | Устанавливается на домен панели |
| Здоровье | Ждёт `/health` перед завершением |

Переменные:
```
remnawave_panel_url: "https://panel.example.com"
```

---
## Reverse Proxy Architecture

### nginx (TLS termination **не происходит**)
nginx работает «за» HAProxy и обслуживает **только панель**:
```
listen 4443 ssl;
proxy_pass http://panel_backend;
```

### haproxy_tls_sni
```
frontend main
  bind :443
  tcp-request inspect-delay 5s
  tcp-request content accept if { req.ssl_hello_type 1 }

  use_backend panel if { req.ssl_sni -i panel.example.com }
  use_backend reality if { req.ssl_sni -i www.cloudflare.com }

backend panel
  server panel 127.0.0.1:4443

backend reality
  server node 127.0.0.1:8444
```

---
## Smoke-тест панели

```
curl -vk https://panel.example.com/health
```

Ожидаем `{"status":"ok"}`.
