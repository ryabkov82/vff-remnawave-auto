# AntiBlock / Yandex Cloud CDN (xHTTP packet-up)

Автоматизация AntiBlock CDN. `antiblock_cdn_enabled` в
`inventory/group_vars/all/antiblock_cdn.yml` только **описывает** feature:
сам по себе он ничего не применяет. Изменения идут только через dedicated
playbook `playbooks/antiblock_cdn.yml` (`make antiblock-cdn`).

Обычные `make inbounds` **не** получают AntiBlock squad memberships.
Обычный `make nodes` **не** активирует AntiBlock на нодах вне группы
`antiblock_cdn_nodes`. На нодах этой группы AntiBlock inbound сохраняется
через `remnawave_inbound_tags_extra` (см. ниже).

## Architecture (текущий этап)

```
GLOBAL
  shared xHTTP packet-up inbound :8447
  AntiBlock-Squad / absent Default-Squad
  wildcard cert  *.cdn.digitalstreamers.xyz  (make antiblock-cdn-bootstrap)
  Cloudflare authoritative DNS

PER NODE  (one node = one Origin Group = one origin = one CDN Resource)
  origin hostname  →  A record  →  HAProxy SNI  →  127.0.0.1:8447
  Yandex Origin Group (exactly one origin, no backup, no round-robin)
  Yandex CDN Resource (cname = public hostname)
  public Cloudflare CNAME  →  resource.provider_cname
  Remnawave Hosts (VFF:ANTIBLOCK, current Host API)
```

Никакого общего origin pool. Никакого backup origin. Никакого round-robin между VPN nodes.

Origin SNI (de-fra-2: `origin-cdn.digitalstreamers.xyz`) → `127.0.0.1:8447` без
send-proxy-v2 задаётся generic extra SNI route на группе
`antiblock_cdn_nodes`. de-fra-2 сохраняет legacy names
`cdn-lab` / `origin-cdn` / origin group `common-origin-cdn-digitalstreamers-xyz`.

## Orchestration

```
make antiblock-cdn
  |
  +-- ensure inbound          (panel, remnawave_inbounds)
  +-- ensure AntiBlock-Squad membership
  +-- ensure absence from Default-Squad
  +-- activate inbound on antiblock_cdn_nodes
  +-- wait 127.0.0.1:antiblock_cdn_inbound_port
  +-- origin A DNS via roles/cf_dns
  +-- HAProxy extra SNI route (validate + reload)
  +-- Yandex Origin Group + CDN Resource (delegate_to localhost)
  +-- public Cloudflare CNAME → provider_cname
  +-- Remnawave Hosts adopt/reconcile (VFF:ANTIBLOCK)
```

Порядок plays обязателен: inbound должен существовать, прежде чем
`remnawave_register_node` резолвит его по tag на ноде. UUID между plays
не передаются.

### Play 1 — panel

Роль `remnawave_inbounds` с role params (не group_vars):

- `remnawave_inbounds: [antiblock_cdn_inbound]` — рабочий объект из inventory,
  без новой decryption-строки;
- `remnawave_inbounds_managed: [antiblock_cdn_inbound_tag]` — не трогает
  остальные panel inbounds;
- `remnawave_update_mode: replace` — per-tag replace; остальные tag в профиле
  сохраняются (роль копирует current map и меняет только desired tags);
- `remnawave_tag_collision_mode: "{{ antiblock_cdn_tag_collision_mode }}"`
  (`fail`) — 409 не автопрефиксуется;
- `remnawave_register_inbounds_in_squad: false` — старый additive Default-Squad
  путь выключен;
- `remnawave_inbound_squad_memberships` — present `AntiBlock-Squad`,
  absent `Default-Squad`; unrelated members сохраняются; PATCH только при drift.

### Play 2 — antiblock_cdn_nodes

Роль `remnawave_register_node` без override `replace`/`inbound_tags`.
Desired inbounds ноды:

```
effective = remnawave_inbound_tags + remnawave_inbound_tags_extra | unique
```

`inventory/group_vars/antiblock_cdn_nodes.yml` задаёт extra только для этой
группы:

```yaml
remnawave_inbound_tags_extra:
  - "{{ antiblock_cdn_inbound_tag }}"
```

host_vars ноды по-прежнему `remnawave_node_inbounds_mode: replace` и строгий
список обычных inbound’ов. Replace снимает чужие UUID, но **не** AntiBlock,
потому что он в extra.

Поэтому после `make antiblock-cdn`:

```bash
make nodes LIMIT=de-fra-2 TAGS=register_node
```

не снимает `VLESS xHTTP packet-up test`. Ноды вне группы extra не получают.

## Make targets

| Target | Что делает |
|--------|------------|
| `make antiblock-cdn-plan` | Только `ansible-playbook --syntax-check`. Без API. Ansible `--check` **не** используется: `uri` в Remnawave-ролях не является безопасным check-mode. |
| `make antiblock-cdn` | Apply inbound + squads + origin DNS + HAProxy + Yandex CDN + public CNAME + Hosts. |
| `make antiblock-cdn-node HOST=…` | То же для одной ноды: `--limit panel:HOST`. HOST обязан быть в `[antiblock_cdn_nodes]`. Yandex CDN идёт через `delegate_to: localhost`, поэтому limit не пропускает cloud provisioning. `TAGS=antiblock_cdn_yandex` гоняет Yandex reconcile **и** public CNAME (`include_role apply.tags`); origin A / HAProxy / Remnawave Hosts не входят. `TAGS=antiblock_cdn_hosts` — только Hosts (GET + plan; apply playbook ставит `allow_writes=true`). Plan: `EXTRA='-e antiblock_cdn_hosts_allow_writes=false'`. |
| `make antiblock-cdn-node-plan HOST=…` | Membership check + syntax-check + **read-only** Yandex GET plan (`yandex_cdn_allow_writes=false`). Нет Cloudflare / HAProxy / Remnawave writes. Ansible `--check` не используется. |
| `make antiblock-cdn-bootstrap-plan` | Syntax-check + dump desired certificate state. Без Yandex/Cloudflare writes. `--check` не используется. |
| `make antiblock-cdn-bootstrap` | Apply: managed wildcard cert + Cloudflare DNS challenge. |

## Global wildcard certificate bootstrap

Один managed certificate в Yandex Certificate Manager на все будущие
per-node CDN Resources (`de-fra-3.cdn.digitalstreamers.xyz`,
`nl-ams-2.cdn.digitalstreamers.xyz`, …). Не `*.digitalstreamers.xyz`:
этот namespace занят Certbot (`_acme-challenge.digitalstreamers.xyz` TXT).

```
name:      edge-cert-01
domains:   *.cdn.digitalstreamers.xyz
challenge: DNS
dns_zone:  digitalstreamers.xyz
```

Lookup **по name**, UUID сертификата в inventory не кладётся.

```
make antiblock-cdn-bootstrap-plan
  |
  +-- ansible-playbook --syntax-check
  +-- print desired state (без Yandex/Cloudflare API)

make antiblock-cdn-bootstrap
  |
  +-- найти/запросить managed certificate (Yandex CM)
  +-- взять DNS challenge из FULL view (VALIDATING)
  +-- после certificate ID: canonical renewal CNAME
  +-- создать/держать CNAME в Cloudflare через roles/cf_dns (proxied=false)
```

`playbooks/antiblock_cdn.yml` сертификаты **не** выпускает. Обычные
`make inbounds` / `make nodes` не меняются.

### Auth (non-interactive)

Автоматизация **не** использует `yc init`. Нужен service account в folder:

1. Создать SA в Yandex Cloud folder, где будет сертификат и CDN.
2. Выдать роли уровня folder:
   - Certificate Manager: например `certificate-manager.editor` (bootstrap);
   - Cloud CDN: `cdn.editor` (этап 5, Origin Group + Resource).
     Не расширять до primitive `editor`/`admin` без необходимости.
3. Создать authorized key и положить JSON в Ansible Vault:

   `inventory/group_vars/all/vault.yml` → `vault_yandex_cloud_sa_authorized_key`

4. Заполнить `antiblock_cdn_yc_folder_id` (это folder ID, не UUID сертификата).
5. На контроллере для JWT PS256 нужен пакет `cryptography`
   (`$(VENV)/bin/pip install cryptography`).
6. Cloudflare token (`vault_cf_dns_api_token`) должен уметь править зону
   `digitalstreamers.xyz`. После ISSUED automation продолжает reconcile
   канонического renewal CNAME
   `_acme-challenge.cdn.digitalstreamers.xyz → <certificate_id>.cm.yandexcloud.net`,
   чтобы случайно удалённый challenge восстановился до следующего Renewing.
   Apex `_acme-challenge.digitalstreamers.xyz` (Certbot TXT) **не** трогается.

OAuth / IAM tokens в git не класть. Короткий IAM token
(`vault_yandex_cloud_iam_token`) допустим только для ручного теста.

SA bootstrap (создание SA, роли, ключа) — **prerequisite**, не часть этого
playbook.

### Certificate lifecycle

```
absent → request → VALIDATING → Cloudflare CNAME → PROCESSING → ISSUED
```

- `ISSUED` — успех; канонический renewal CNAME
  `_acme-challenge.cdn.digitalstreamers.xyz → <certificate_id>.cm.yandexcloud.net`
  продолжает reconcile (не удаляется и восстанавливается, если его стёрли).
  Certificate ID берётся из API как runtime fact, в inventory не хардкодится.
- `VALIDATING` / challenge `PROCESSING` — сертификат ещё выпускается;
  новый certificate с тем же name **не** создаётся; DNS challenge
  name/type/value берутся строго из FULL view Yandex.
- `INVALID` / `RENEWAL_FAILED` / `REVOKED` — fail с диагностикой.

HTTP challenge для wildcard не используется. TXT рядом с CNAME на том же
имени не создаётся (`solo: true` на CNAME).

## Per-node origin bootstrap

Каждая CDN-enabled node получает свои hostname. de-fra-2 — legacy/reference
и **не** переименовывается:

| Node | public | origin |
|------|--------|--------|
| de-fra-2 | `cdn-lab.digitalstreamers.xyz` | `origin-cdn.digitalstreamers.xyz` |
| будущая de-fra-3 (ещё не в группе) | `de-fra-3.cdn.digitalstreamers.xyz` | `origin-de-fra-3.digitalstreamers.xyz` |

Origin hostname остаётся в namespace `*.digitalstreamers.xyz`
(`origin-<node>.digitalstreamers.xyz`), не под `*.cdn`. de-fra-2 не
использует shared wildcard (`certificate_mode: legacy_existing`).

`inventory/group_vars/antiblock_cdn_nodes.yml` задаёт derived names и
`haproxy_node_extra_sni_routes`. Override de-fra-2:
`inventory/host_vars/de-fra-2/antiblock_cdn.yml`.

Origin DNS — существующий `roles/cf_dns`: A-запись relative name, IP из
`ansible_host`, `proxied: false`, `solo: true` (только другие A того же
имени, например stale IP; другие имена зоны и другие типы не трогаются).
Список `antiblock_cdn_origin_dns_records` передаётся в `cf_dns` только
dedicated playbook’ом. Group vars **не** задаёт `cf_dns_records`, поэтому
`make nodes` продолжает использовать host_vars DNS ноды.

HAProxy extra route — generic `haproxy_node_extra_sni_routes` (роль
`remnawave_node_haproxy`, default `[]`):

- SNI → `127.0.0.1:{{ antiblock_cdn_inbound_port }}`
- `send_proxy_v2: false`
- `timeout connect 5s` / `timeout server 5m`
- конфликт SNI с dynamic Host map или два разных backend на один SNI →
  fail **до** записи `haproxy.cfg`
- `validate: /usr/sbin/haproxy -c -f %s`; при ошибке production config
  не меняется, reload не вызывается
- handler: `systemctl reload haproxy` (имя `Restart HAProxy` оставлено
  как listen alias)
- перед HAProxy: read-only `wait_for` `127.0.0.1:{{ antiblock_cdn_inbound_port }}`
  (`antiblock_cdn_origin_listen_timeout`, default 90s). `register_node` сам
  порт не проверяет.

`make antiblock-cdn-node HOST=de-fra-2` гоняет `playbooks/antiblock_cdn.yml`
с `--limit panel:de-fra-2`, чтобы panel play не пропускался. Yandex CDN
вызывается `delegate_to: localhost` внутри node play — localhost не должен
быть в `--limit`.

## Per-node Yandex CDN

`one node = one CDN Resource`. `one node = one Origin Group`.
`one Origin Group = one origin`. No backup. No round-robin between nodes.

IDs (Origin Group, Origin, Resource, certificate, `provider_cname`) **не**
кладутся в inventory. Lookup:

- Origin Group — exact stable `antiblock_cdn_node.origin_group_name`
- CDN Resource — exact `antiblock_cdn_node.public_hostname` (cname)
- wildcard cert — name `edge-cert-01`, только если
  `certificate_mode: shared_wildcard`

Новые ноды (group default):

```yaml
antiblock_cdn_node:
  public_hostname: "{{ inventory_hostname }}.cdn.digitalstreamers.xyz"
  origin_hostname: "origin-{{ inventory_hostname }}.digitalstreamers.xyz"
  origin_group_name: "edge-{{ inventory_hostname }}"
  origin_group_use_next: false
  certificate_mode: shared_wildcard
```

`use_next: false`, потому что второго origin нет.

Writes выключены по умолчанию (`yandex_cdn_allow_writes: false`). Dedicated
apply передаёт `true`. POST/PATCH без этого флага не выполняются. DELETE
на этом этапе не реализован (нет prune).

### Legacy DE-FRA-2 adoption

de-fra-2 уже есть в production. Automation **не** переименовывает group,
не пересоздаёт resource, не меняет public hostname / provider cname.

```yaml
# inventory/host_vars/de-fra-2/antiblock_cdn.yml
certificate_mode: legacy_existing
origin_group_name: common-origin-cdn-digitalstreamers-xyz
origin_group_use_next: true
```

`legacy_existing` значит: **не** переводить cdn-lab на shared wildcard
certificate при первом adoption. Миграция сертификата — отдельное решение.

Перед destructive reconcile legacy group automation FAIL, если:

- в группе больше одного origin;
- `resourcesMetadata` содержит >1 resource или unrelated cname.

Идеал после adoption: `changed=0`.

Новая managed group с extra origin → UPDATE к ровно одному origin.
Дубликаты имени group или cname resource → FAIL, без случайного выбора.

### CDN Resource managed fields

Воспроизводится рабочий cdn-lab template (без «улучшения» cache/compression):

- `origin_protocol: HTTPS`, `active: true`, `provider_type: ourcdn`
- `tls.profile: PROFILE_COMPATIBLE`
- `ignore_query_string`, `host` = origin hostname, `custom_server_name` =
  origin hostname, `allowed_http_methods: GET/HEAD/OPTIONS`, `ignore_cookie`
- `secure_key.type: DISABLE_IP_SIGNING`

Пустые default objects (`edge_cache_settings: {}` и т.п.) **не** считаются
drift. Unmanaged options сохраняются: PATCH шлёт merge current+managed.
CNAME resource — identity; rename через delete/recreate запрещён.

`provider_cname` берётся только из GET resource (не deprecated
GetProviderCName). Если operation done, а cname ещё пуст — poll GET.

Public DNS — отдельный runtime-список `yandex_cdn_public_dns_records`
(не generic `cf_dns_records` в group_vars): CNAME, `proxied: false`,
`solo: true`. Origin A не затрагивается. Конфликт с чужим A/AAAA на том же
имени → fail модуля Cloudflare, без удаления arbitrary types.

Wildcard certificate для новых нод должен быть `ISSUED`. Absent →
«Run make antiblock-cdn-bootstrap». VALIDATING/RENEWING → fail/pending,
новый cert не создаётся.

## Stage 6A — Remnawave AntiBlock Hosts

Dedicated role `roles/remnawave_antiblock_hosts`. Обычный `remnawave_add_host`
/ `make nodes` не меняется (`VFF:MANAGED` остаётся обычным ownership).

- Ownership: `antiblock_cdn_host_owner_tag: VFF:ANTIBLOCK` (не `VFF:MANAGED`).
- Safe identity: `address + port + configProfileUuid + configProfileInboundUuid`.
- Write guard: `antiblock_cdn_hosts_allow_writes` default `false`. Apply
  playbook передаёт `true`. Plan = GET + diff, без POST/PATCH/DELETE.
- Unmanaged exact transport → PATCH только `tags` (adoption).
- Unmanaged transport drift → hard fail, без mutate.
- `antiblock_cdn_hosts_prune: false`. DELETE в Stage 6A не реализован.
- Desired addresses: `public_hostname` + global
  `antiblock_cdn_trusted_ingress_ips`.
- Shared `antiblock_cdn_host_xhttp_extra_params` (`xhttpExtraParams`,
  `uplinkHTTPMethod`). Legacy `tag` / `xHttpExtraParams` / `allowInsecure`
  не отправляются.
- Узкий запуск: `make antiblock-cdn-node HOST=de-fra-2 TAGS=antiblock_cdn_hosts`.
  `include_role apply.tags` обязателен. Node/inbound UUID резолвятся read-only
  внутри роли, если tagged run пропустил `register_node`.

### Trusted CDN edge IP pool

`antiblock_cdn_trusted_ingress_ips` в
`inventory/group_vars/all/antiblock_cdn.yml` — **curated/manual** пул CDN
edge IP, общий для всех `antiblock_cdn_nodes`. Это не автоматически
обнаруженные Yandex CDN IP: роль **не** резолвит `providerCname` и **не**
делает DNS lookup этих адресов.

Чтобы централизованно заменить или добавить trusted CDN edge IP,
редактируем только этот список. После этого desired Remnawave IP Hosts
на каждой AntiBlock CDN node становятся:

```
<antiblock_cdn_node.public_hostname>
+ antiblock_cdn_trusted_ingress_ips
```

de-fra-2: `cdn-lab.digitalstreamers.xyz` + тот же global pool.
Будущая de-fra-3: `de-fra-3.cdn.digitalstreamers.xyz` + тот же pool.
Список в host_vars не копируется. Per-node extra/exclude пока нет.

Удаление IP из пула **не** удаляет старый Host. Stage 6B.1 только
классифицирует stale / prune eligibility. DELETE ещё нет.

### Stage 6B.1 — stale detection (no DELETE)

После desired reconcile роль смотрит global GET `/api/hosts`, но stale
считается **только** для текущего scope:

- tag `VFF:ANTIBLOCK`
- текущие profile + inbound UUID
- Host привязан к текущему node UUID
- safe identity `(address, port, profile, inbound)` нет в desired

`VFF:MANAGED` и `tags=[]` не являются AntiBlock ownership.

prune_eligible (будущий DELETE) только если одновременно:

- tags ровно `["VFF:ANTIBLOCK"]` (extra tags, включая `VFF:MANAGED`, блокируют)
- nodes ровно `[current_node_uuid]` (multi-node → `multiple_nodes`)
- address IPv4 и не равен `public_hostname`
- UUID есть

Public hostname Host **никогда** не prune_eligible. Чужие node/inbound/profile
вне scope и не попадают в `stale` / `prune_blocked`.

`antiblock_cdn_hosts_prune` остаётся `false`. `plan.delete` всегда 0.
Writes только POST/PATCH desired Hosts.

Будущий Stage 6B.2 (не реализован):

1. calculate desired
2. create/adopt/reconcile desired Hosts
3. re-GET + verify desired Hosts
4. smoke/gate
5. только потом DELETE `prune_eligible` stale Hosts

## Ещё не реализовано (этап 6B.2+)

- Safe DELETE `prune_eligible` stale IPv4 Hosts
- CDN transport smoke / full xHTTP/VLESS smoke
- удаление stale CDN resources / origin groups
- миграция de-fra-2 certificate на shared wildcard
