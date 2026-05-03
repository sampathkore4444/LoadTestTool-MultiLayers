CREATE EXTENSION pg_stat_statements;

CREATE TABLE requests (
    id SERIAL PRIMARY KEY,
    uid INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    payload JSONB
);

CREATE INDEX idx_requests_uid ON requests(uid);

INSERT INTO requests (uid, payload) VALUES (1, '{"test": true}');
INSERT INTO requests (uid, payload) VALUES (2, '{"test": true}');
