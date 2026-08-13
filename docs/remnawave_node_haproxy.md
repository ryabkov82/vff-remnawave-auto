# remnawave_node_haproxy

Автогенерация конфигурации **HAProxy** на основе актуального состояния *Remnawave Node*, полученного через API панели Remnawave.

Роль автоматически:

- получает UUID ноды (или ищет её по имени `inventory_hostname`);
- запрашивает активный профиль ноды;
- получает список inbound’ов из профиля;
- получает список хостов, привязанных к этой ноде;
- вычисляет список SNI-доменов, которые должны быть направлены на Reality inbound;
- формирует корректный `haproxy.cfg`;
- проверяет candidate config (`haproxy -c`) до замены production файла;
- делает graceful reload HAProxy (без blind restart).

Дополнительно роль принимает generic `haproxy_node_extra_sni_routes`
(по умолчанию пустой список) для static SNI, которые **не** берутся из
Remnawave Hosts — например origin SNI Yandex CDN. Конфликт extra SNI с
dynamic map останавливает роль до записи конфига.

---

## 🧠 Логика определения SNI

Для каждого inbound:

1. Собираются `serverNames` из inbound (whitelist).
2. Собираются SNI домены из всех host, привязанных к ноде.
3. Логика объединения:

- если host.sni указан у хоста → используется **пересечение** host.sni ∩ serverNames
- если host.sni отсутствует → используется **serverNames** из inbound

Такой подход всегда корректен, так как:

- не пропускает лишние домены;
- не требует ручного ведения списка доменов в переменных;
- автоматически подхватывает обновления host и inbound.

---

## 🏗 Структура роли

```
roles/
  remnawave_node_haproxy/
    defaults/
      main.yml
    tasks/
      main.yml
    templates/
      haproxy_node.cfg.j2
    README.md   ← этот файл
```

---

## ⚙️ Что генерируется

HAProxy получает:

- один фронтенд на `:443`
- несколько ACL по SNI → нужный Reality inbound port
- backend'ы для каждого inbound, например:

```
backend xray_8444
backend xray_8445
backend xray_9001
```

Домены сайта (`website_domains`) продолжают маршрутизироваться в nginx.

---

## 🔌 Пример итогового haproxy.cfg

```
frontend https_in
    bind :443
    mode tcp
    option tcplog
    tcp-request inspect-delay 5s
    tcp-request content accept if { req_ssl_hello_type 1 }
    tcp-request content capture req.ssl_sni len 256

    acl is_site req.ssl_sni -i digitalstreamers.xyz
    use_backend nginx_https if is_site

    acl sni_8444 req.ssl_sni -i edge-fra-01.digitalstreamers.xyz cache-fra-01.digitalstreamers.xyz
    acl sni_8445 req.ssl_sni -i ds-node1.digitalstreamers.xyz
    acl sni_9001 req.ssl_sni -i special.domain.com

    use_backend xray_8444 if sni_8444
    use_backend xray_8445 if sni_8445
    use_backend xray_9001 if sni_9001

    default_backend xray_8444
```

---

## 🛠 Требования роли

- HAProxy должен быть установлен
- Remnawave Panel API должен быть доступен
- Переменные для доступа:

```
remnawave_panel_api_token: "..."
remnawave_panel_url: "https://panel.example.com"
```

---

## 📡 Что делает роль при запуске

1. Определяет UUID ноды:
   - если `remnawave_node_uuid` задан → использует его
   - если нет → ищет по `inventory_hostname`

2. Загружает:
   - `/api/nodes/<uuid>` → activeProfile / activeInbounds / hosts
   - `/api/config-profiles/<uuid>` → inbound definitions
   - `/api/hosts` → host SNI

3. Строит карту:
   ```
   SNI → inbound port
   ```

4. Генерирует `haproxy.cfg`

5. Проверяет `haproxy.cfg` через `haproxy -c` и делает reload.

---

## ✔️ Статус

Роль полностью автоматизирована, идемпотентна и не требует ручной поддержки.  
Достаточно изменить хосты или inbound — и HAProxy сам перестроится при следующем запуске ansible.
