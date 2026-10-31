CREATE TABLE IF NOT EXISTS pipeline_runs (
 id uuid PRIMARY KEY,
 requirements text NOT NULL,
 status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','blocked','interrupted')),
 created_at timestamptz NOT NULL DEFAULT now(),
 started_at timestamptz,
 finished_at timestamptz,
 heartbeat_at timestamptz,
 worker_id text,
 lease_token uuid,
 message text NOT NULL DEFAULT '',
 app_url text,
 repository_url text,
 metrics jsonb NOT NULL DEFAULT '{"modelCalls":0,"inputTokens":0,"outputTokens":0,"retries":0,"tokenUsageComplete":true}'::jsonb
);
CREATE INDEX IF NOT EXISTS pipeline_runs_queue ON pipeline_runs(created_at,id) WHERE status='queued';
CREATE TABLE IF NOT EXISTS pipeline_claim_requests (
 request_id uuid PRIMARY KEY,
 worker_id text NOT NULL,
 payload jsonb,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS pipeline_steps (
 run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
 stage_id text NOT NULL,
 status text NOT NULL,
 attempt integer NOT NULL CHECK (attempt BETWEEN 1 AND 3),
 message text NOT NULL DEFAULT '',
 started_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 PRIMARY KEY(run_id,stage_id)
);
CREATE TABLE IF NOT EXISTS pipeline_attempts (
 run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
 event_id uuid NOT NULL,
 stage_id text NOT NULL,
 attempt integer NOT NULL,
 payload_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(run_id,event_id)
);
CREATE TABLE IF NOT EXISTS pipeline_logs (
 cursor bigserial PRIMARY KEY,
 run_id uuid NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
 stage_id text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 message text NOT NULL
);
CREATE INDEX IF NOT EXISTS pipeline_logs_run ON pipeline_logs(run_id,cursor);
CREATE TABLE IF NOT EXISTS pipeline_artifacts (
 id uuid PRIMARY KEY,
 run_id uuid NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
 name text NOT NULL,
 kind text NOT NULL,
 path text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(run_id,path)
);
