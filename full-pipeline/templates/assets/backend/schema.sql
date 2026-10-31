CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE IF NOT EXISTS schema_migrations(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS records(
 id uuid PRIMARY KEY, entity text NOT NULL, payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS records_entity_idx ON records(entity);
CREATE TABLE IF NOT EXISTS mock_integration_calls(
 actor text NOT NULL, provider_id text NOT NULL, operation_id text NOT NULL, request_id text NOT NULL,
 request_payload jsonb NOT NULL, response_payload jsonb NOT NULL, status_code integer NOT NULL,
 origin text NOT NULL CHECK(origin IN ('business','contract')), created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(actor,provider_id,operation_id,request_id));
CREATE TABLE IF NOT EXISTS demo_tokens(token_hash text PRIMARY KEY, role text NOT NULL, actor text NOT NULL, expires_at timestamptz NOT NULL);
CREATE TABLE IF NOT EXISTS parking_zones(
 id text PRIMARY KEY, name text NOT NULL, rate numeric(12,2) NOT NULL CHECK(rate>=0),
 boundary geometry(Polygon,4326) NOT NULL);
CREATE INDEX IF NOT EXISTS parking_zones_boundary_idx ON parking_zones USING gist(boundary);
CREATE TABLE IF NOT EXISTS parking_positions(
 id bigserial PRIMARY KEY, actor text NOT NULL, location geometry(Point,4326) NOT NULL,
 zone_id text REFERENCES parking_zones(id), recorded_at timestamptz NOT NULL);
CREATE TABLE IF NOT EXISTS parking_sessions(
 id uuid PRIMARY KEY, actor text NOT NULL, zone_id text NOT NULL REFERENCES parking_zones(id),
 started_at timestamptz NOT NULL, ended_at timestamptz, end_reason text,
 expires_at timestamptz NOT NULL, cost numeric(12,2) NOT NULL, warning_emitted boolean NOT NULL DEFAULT false, CHECK(ended_at IS NULL OR ended_at >= started_at));
CREATE UNIQUE INDEX IF NOT EXISTS one_active_session ON parking_sessions(actor) WHERE ended_at IS NULL;
CREATE TABLE IF NOT EXISTS demo_clock(id integer PRIMARY KEY CHECK(id=1), value timestamptz NOT NULL);
INSERT INTO parking_zones(id,name,rate,boundary) VALUES
 ('A','Центральная зона',100,ST_GeomFromText('POLYGON((30.31 59.93,30.32 59.93,30.32 59.94,30.31 59.94,30.31 59.93))',4326)),
 ('B','Речная зона',60,ST_GeomFromText('POLYGON((30.32 59.93,30.33 59.93,30.33 59.94,30.32 59.94,30.32 59.93))',4326))
 ON CONFLICT(id) DO NOTHING;
INSERT INTO schema_migrations(version) VALUES(1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS parking_events(
 id bigserial PRIMARY KEY, actor text NOT NULL, kind text NOT NULL, message text NOT NULL,
 from_zone text, to_zone text, session_id uuid REFERENCES parking_sessions(id), recorded_at timestamptz NOT NULL);
CREATE TABLE IF NOT EXISTS business_outbox (
  event_id uuid PRIMARY KEY,
  actor text NOT NULL,
  endpoint_id text NOT NULL,
  business_key text NOT NULL,
  envelope jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  attempts integer NOT NULL DEFAULT 0,
  last_error text,
  kafka_partition integer,
  kafka_offset bigint,
  UNIQUE(actor,endpoint_id,business_key)
);
CREATE INDEX IF NOT EXISTS business_outbox_pending ON business_outbox(created_at) WHERE published_at IS NULL;
CREATE TABLE IF NOT EXISTS business_inbox (
  event_id uuid PRIMARY KEY REFERENCES business_outbox(event_id),
  processed_at timestamptz NOT NULL DEFAULT now(),
  kafka_partition integer NOT NULL,
  kafka_offset bigint NOT NULL,
  deliveries integer NOT NULL DEFAULT 1,
  last_kafka_offset bigint NOT NULL
);
CREATE TABLE IF NOT EXISTS business_activity (
  event_id uuid PRIMARY KEY REFERENCES business_inbox(event_id),
  actor text NOT NULL,
  endpoint_id text NOT NULL,
  label text NOT NULL,
  business_key text NOT NULL,
  result jsonb NOT NULL,
  occurred_at timestamptz NOT NULL,
  processed_at timestamptz NOT NULL DEFAULT now()
);
