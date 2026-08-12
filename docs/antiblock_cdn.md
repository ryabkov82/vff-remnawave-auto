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
| `make antiblock-cdn` | Apply (API writes на panel + CDN nodes). |

## Ещё не реализовано этим target

Hosts и HAProxy automation пока **не** реализованы данным target:

- Host adoption / reconcile
- маркер `VFF:ANTIBLOCK`
- safe prune
- HAProxy origin SNI (`origin-cdn.digitalstreamers.xyz` → `127.0.0.1:8447`)
- `haproxy -c` / reload
- CDN smoke tests
- Yandex Cloud API / per-node CDN Resource
