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

Каждая CDN-enabled VPN node впоследствии получает **собственный** Yandex CDN
Resource и origin. Группа `antiblock_cdn_nodes` — это не общий origin pool.

```
Yandex CDN  (per-node resource, later)
      |
      | origin later handled by HAProxy
      v
antiblock_cdn_nodes  (сейчас: de-fra-2; позже de-fra-3, nl-ams-2, …)
      |
      +-- Remnawave inbound 8447
          tag: VLESS xHTTP packet-up test
```

Origin SNI `origin-cdn.digitalstreamers.xyz` → `127.0.0.1:8447` (без
send-proxy-v2) пока настроен вручную. Этот target его не меняет.

## Orchestration

```
make antiblock-cdn
  |
  +-- ensure inbound          (panel, remnawave_inbounds)
  +-- ensure AntiBlock-Squad membership
  +-- ensure absence from Default-Squad
  +-- activate inbound on antiblock_cdn_nodes
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
| `make antiblock-cdn` | Apply inbound + squads + CDN node activation. |
| `make antiblock-cdn-bootstrap-plan` | Syntax-check + dump desired certificate state. Без Yandex/Cloudflare writes. `--check` не используется. |
| `make antiblock-cdn-bootstrap` | Apply: managed wildcard cert + Cloudflare DNS challenge. |

## Global wildcard certificate bootstrap

Один managed certificate в Yandex Certificate Manager на все будущие
per-node CDN Resources (`cdn-de-fra-3.digitalstreamers.xyz`,
`cdn-nl-ams-2.digitalstreamers.xyz`, …):

```
name:      antiblock-cdn-wildcard
domains:   *.digitalstreamers.xyz
challenge: DNS
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

1. Создать SA в Yandex Cloud folder, где будет сертификат.
2. Выдать роль уровня folder, достаточную для Certificate Manager
   (например `certificate-manager.editor`).
3. Создать authorized key и положить JSON в Ansible Vault:

   `inventory/group_vars/all/vault.yml` → `vault_yandex_cloud_sa_authorized_key`

4. Заполнить `antiblock_cdn_yc_folder_id` (это folder ID, не UUID сертификата).
5. На контроллере для JWT PS256 нужен пакет `cryptography`
   (`$(VENV)/bin/pip install cryptography`).
6. Cloudflare token (`vault_cf_dns_api_token`) должен уметь править зону
   `digitalstreamers.xyz`. После ISSUED automation продолжает reconcile
   канонического renewal CNAME, чтобы случайно удалённый `_acme-challenge`
   восстановился до следующего Renewing.

OAuth / IAM tokens в git не класть. Короткий IAM token
(`vault_yandex_cloud_iam_token`) допустим только для ручного теста.

SA bootstrap (создание SA, роли, ключа) — **prerequisite**, не часть этого
playbook.

### Certificate lifecycle

```
absent → request → VALIDATING → Cloudflare CNAME → PROCESSING → ISSUED
```

- `ISSUED` — успех; канонический renewal CNAME
  `_acme-challenge.<domain> → <certificate_id>.cm.yandexcloud.net`
  продолжает reconcile (не удаляется и восстанавливается, если его стёрли).
  Certificate ID берётся из API как runtime fact, в inventory не хардкодится.
- `VALIDATING` / challenge `PROCESSING` — сертификат ещё выпускается;
  новый certificate с тем же name **не** создаётся; DNS challenge
  name/type/value берутся строго из FULL view Yandex.
- `INVALID` / `RENEWAL_FAILED` / `REVOKED` — fail с диагностикой.

HTTP challenge для wildcard не используется. TXT рядом с CNAME на том же
имени не создаётся (`solo: true` на CNAME).

## Ещё не реализовано

Hosts, HAProxy и per-node Yandex CDN пока **не** автоматизированы:

- Host adoption / reconcile / маркер `VFF:ANTIBLOCK` / safe prune
- HAProxy origin SNI (`origin-cdn.digitalstreamers.xyz` → `127.0.0.1:8447`)
- `haproxy -c` / reload
- per-node CDN Resource / Origin Group
- CDN smoke tests
