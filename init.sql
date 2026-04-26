CREATE TABLE IF NOT EXISTS zone (
    id SERIAL PRIMARY KEY,
    worker_id INTEGER NOT NULL,
    zone_x INTEGER NOT NULL,
    zone_y INTEGER NOT NULL,
    UNIQUE (worker_id, zone_x, zone_y)
);

CREATE TABLE IF NOT EXISTS event (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    left_x INTEGER NOT NULL,
    right_x INTEGER NOT NULL,
    top_y INTEGER NOT NULL,
    bot_y INTEGER NOT NULL,
    worker_id INTEGER NOT NULL,
    zone_id INTEGER REFERENCES zone(id) ON DELETE CASCADE
);