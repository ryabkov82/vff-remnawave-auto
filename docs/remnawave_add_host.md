# Role: remnawave_add_host

Роль идемпотентно создаёт и reconcile’ит **Host** в Remnawave Panel и привязывает
их к Node.

---

## Назначение

1. Резолвит **Node UUID** (`remnawave_node_uuid` или поиск по имени).
2. Резолвит **Inbound / Profile UUID** (кэш `remnawave_inbounds_by_tag` или API).
3. Сопоставляет желаемый Host с существующим по `rw_host_match_by`.
4. Создаёт Host (`POST /api/hosts`), если отсутствует.
5. Опционально обновляет inbound / port / **remark** на существующем Host.
6. Опционально prune’ит только managed Host (`tag == VFF:MANAGED`) текущей ноды.

---

## remark vs serverDescription

| Поле | Назначение |
|------|------------|
| `remark` | Отображаемое имя Host в подписке / UI панели. Задаётся в inventory (`remnawave_hosts[].remark` или legacy `remnawave_host_remark`). |
| `serverDescription` | Короткое описание (до 30 символов в API 2.7.4). Брендовая подпись для VPN for Friends / Friends Connect задаётся отдельно через **External Squad `serverDescription`**, а не через Host remark. |

Нейтральные имена Host (например `🇩🇪 Germany 1`) общие для брендов;
бренд показывается через External Squad.

---

## Описание Host-ов

```yaml
remnawave_hosts:
  - remark: "🇳🇱 2 vpn-for-friends"
    address: "ams-02.example.com"
    port: 443
    inbound_tag: "VLESS TCP REALITY"
    sni:
      - example.com

  - remark: "🇳🇱 2 vpn-for-friends (xHTTP)"
    address: "api-ams-02.example.com"
    port: 443
    inbound_tag: "VLESS xHTTP (behind nginx)"
    path: "/api/v1/sync/"
    patch_reality_servernames: false
```

Legacy fallback (если `remnawave_hosts` пуст): `rw_host_remark` /
`remnawave_host_remark`, `rw_host_address` / `remnawave_host_address`.

---

## Режимы сопоставления (`rw_host_match_by`)

| Режим | Ключ | Когда использовать |
|-------|------|--------------------|
| `remark` (default) | exact `remark` | Стабильные имена; **нельзя** переименовать Host без дубликата. |
| `address_port` | `address` + `port` | Legacy. **Опасно**, если Reality и xHTTP делят один `address:443` с разными inbound — режим берёт всех кандидатов и при >1 **падает** (раньше молча брал `first`). |
| `endpoint_inbound` | `address` + `port` + `configProfileUuid` + `configProfileInboundUuid` | **Безопасный** режим для rename и Reality/xHTTP на одном endpoint. |

Правила для всех режимов:

- 0 совпадений → Host отсутствует → create (если не check mode create path);
- 1 совпадение → Host выбран;
- >1 → **fail**, create не вызывается;
- в `fail_msg` — UUID кандидатов и безопасные диагностические поля.

Рекомендуемый ключ для rename: `endpoint_inbound`.
Node UUID в ключ не входит, пока аудит не покажет коллизии на `D`;
в текущем контракте Host.nodes обновляются только если переданы в PATCH.

---

## Переименование remark

По умолчанию выключено:

```yaml
rw_host_set_remark_if_exists: false
rw_host_allow_unmanaged_update: false
```

Включается только вместе с безопасным match mode:

```yaml
rw_host_match_by: "endpoint_inbound"
rw_host_set_remark_if_exists: true
```

### API contract (Remnawave backend 2.7.4)

Подтверждено по `UpdateHostCommand` / `HostsService.updateHost`:

- Endpoint: `PATCH /api/hosts` (не `/hosts/{uuid}`)
- Обязательное поле: `uuid`
- `remark` и прочие поля — **optional** (частичный PATCH)
- Bulk endpoint для remark **нет**
- Успешный статус: `200`, тело `{ "response": HostDto }`
- Частичный PATCH `{ "uuid", "remark" }` **не** сбрасывает nodes, inbound,
  SNI, tag, serverDescription, transport/security, isHidden, viewPosition

Роль отправляет **только** `{uuid, remark}`. Delete/recreate для rename
запрещены.

### Защиты

Роль падает без изменений при:

- неоднозначном match;
- rename без `endpoint_inbound`;
- rename unmanaged Host без `rw_host_allow_unmanaged_update=true`;
- пустом desired remark;
- неизвестном `rw_host_match_by`;
- `rw_host_update_api_confirmed=false`;
- ответе API, где UUID изменился или remark не стал желаемым;
- ошибке PATCH (без fallback на create/delete).

Unmanaged Host (`tag != VFF:MANAGED`) можно видеть в аудите, но нельзя
менять без явного allow.

### Check mode

```bash
make hosts-plan LIMIT=de-fra-1 EXTRA='-e rw_host_match_by=endpoint_inbound -e rw_host_set_remark_if_exists=true'
```

В check mode:

- PATCH не выполняется;
- показывается `planned_rename` (UUID, old → new);
- `changed=true` только если rename реально нужен.

После успешного rename локальный `_rw_hosts_existing` обновляется, чтобы
следующий элемент цикла и prune видели новое имя.

---

## Prune

Не расширяется:

- удаляются только Host с `tag == VFF:MANAGED`;
- scope `per_node` (только текущая нода);
- unmanaged не удаляются;
- rename **не** проставляет managed tag старым мигрированным Host.

При `endpoint_inbound` prune сравнивает ключи
`address:port:profileUuid:inboundUuid`, чтобы rename не приводил к ложному
удалению.

---

## Аудит (read-only)

```bash
make hosts-audit LIMIT=panel
```

Playbook: `playbooks/audit_hosts.yml` (роль `remnawave_hosts_audit`).

- Только `GET` (`/hosts`, `/nodes`, `/config-profiles/inbounds`)
- Отчёты: `build/remnawave-hosts-audit.json`, `build/remnawave-hosts-audit.md`
- Токен не печатается и не попадает в отчёты (`no_log` на URI)

---

## Пример будущего безопасного rollout

**Не меняйте production remark, пока не готов audit + check mode.**

1. `make hosts-audit LIMIT=panel` — зафиксировать UUID / коллизии / unmanaged.
2. В inventory (отдельным коммитом) заменить remark на нейтральные имена.
3. Для **одного** тестового хоста:

```bash
make hosts-plan LIMIT=de-fra-1 \
  EXTRA='-e rw_host_match_by=endpoint_inbound -e rw_host_set_remark_if_exists=true -e rw_host_prune=false'
```

4. Применить только этот LIMIT (без prune на первом шаге):

```bash
make nodes LIMIT=de-fra-1 TAGS=register_host \
  EXTRA='-e rw_host_match_by=endpoint_inbound -e rw_host_set_remark_if_exists=true -e rw_host_prune=false'
```

5. Повторить — `changed=0`.
6. Раскатать остальные ноды с `LIMIT=...`.

Пример будущей конфигурации (только документация; inventory сейчас не менять):

```yaml
rw_host_match_by: "endpoint_inbound"
rw_host_set_remark_if_exists: true

remnawave_hosts:
  - remark: "🇩🇪 Germany 1"
    address: "edge-fra-01.digitalstreamers.xyz"
    port: 443
    inbound_tag: "VLESS TCP REALITY (DS)"
```

---

## Запуск

```bash
make nodes LIMIT=nl-ams-2 TAGS=register_host
make hosts-audit LIMIT=panel
make hosts-plan LIMIT=de-fra-1
```

---

## Примечания

- Managed marker: `tag: VFF:MANAGED` (не `serverDescription`).
- Совместно с `remnawave_register_node`, `remnawave_reality_servernames`.
- Массового Make-target для rename всех Host без `LIMIT` и явного флага нет.
