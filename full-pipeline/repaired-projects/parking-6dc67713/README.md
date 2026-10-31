# Контроль парковочных сессий для служебных авто

Generated run: 6dc67713-7c97-44f8-b639-49519113ebfd. Приложение для водителей технических служб Санкт-Петербурга, позволяющее отслеживать оплаченные парковочные сессии, получать предупреждения о скором окончании оплаты и уведомления о пересечении границ платных зон. Инструмент помогает избежать штрафов и повторных оплат при перемещении между объектами.

## Start and verify

```sh
docker compose -p rwb_6dc67713_7c97_44f8_b639_49519113ebfd build
docker compose -p rwb_6dc67713_7c97_44f8_b639_49519113ebfd up -d --wait
docker compose -p rwb_6dc67713_7c97_44f8_b639_49519113ebfd run --rm checks
docker compose -p rwb_6dc67713_7c97_44f8_b639_49519113ebfd port frontend 80
```

Open the printed localhost port. Only the frontend is published. The database is a project-specific named volume. `.env` contains a randomly generated local database password; do not publish it.

## Contracts and data

Angular 20.1.6, Angular Material 20.1.6, installable PWA shell; .NET 10/C# 14 API; PostgreSQL 17.9 with PostGIS. See `docs/openapi.json` and `app-spec.json`. Generic records persist in a validated JSONB table: this supports all AppSpec field types and independent entities without invented relations. Admin creates/updates/deletes; all other roles can read. Model-owned additions are `backend/Generated/**` (called through `GeneratedExtensions.Map`) and `frontend/src/app/generated/**` (root `GeneratedPanel`). These additions are executed as application code, so use this local pipeline only with trusted operators.

## Demo access and limits

The login selector issues a random, expiring token for a chosen demo role. It deliberately proves role enforcement, not production identity: anyone reaching this local app can select admin. Tokens are stored hashed. No payment gateway, real funds, background mobile GPS, remote map tiles, push delivery, or iOS native app is provided. PWA shell may load offline; API data requires network. PNG icons (192/512) and manifest are included; installation requires a supporting browser and HTTPS or localhost. External services and arbitrary natural-language workflows require explicit generated extensions and domain acceptance tests; the generic renderer itself implements validated CRUD only.

## Parking capability

Enabled. PostGIS `ST_Covers` includes boundaries; shared boundaries select the lexically first zone ID. A driver reports foreground GPS or an explicitly labelled demo route, then explicitly confirms a demo payment and duration (15–1440 minutes). Warning appears when 10 minutes remain, once per session, through polling. Crossing or leaving zones logs an event and payment advice without cancelling, moving or creating paid sessions. An explicit stop or expiry completes the session. The admin can save polygons and rates. Session costs are fixed at confirmation; later rate edits do not change them. The controllable clock is admin-only and enabled for this demo (`TEST_CLOCK_ENABLED=true`); turn it off for ordinary operation. Time is fixed after the first clock operation and advances only through that endpoint. No financial settlement or refunds are performed.

## Persistence verification

After the acceptance suite, restart backend, wait for health, and run:

```sh
docker compose -p rwb_6dc67713_7c97_44f8_b639_49519113ebfd run --rm -e PERSISTENCE_ONLY=1 checks
```

Acceptance creates and retains one updated record per entity to make restart verification observable. `docker compose down` retains database data; `down -v` deletes that project's data.
