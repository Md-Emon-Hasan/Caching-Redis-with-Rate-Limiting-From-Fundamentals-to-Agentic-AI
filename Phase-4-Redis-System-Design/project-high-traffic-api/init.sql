-- Runs automatically the FIRST time the postgres container starts
-- (mounted into /docker-entrypoint-initdb.d/ via docker-compose.yml)

CREATE TABLE IF NOT EXISTS products (
    id     SERIAL PRIMARY KEY,
    name   TEXT NOT NULL,
    price  NUMERIC(10, 2) NOT NULL,
    views  INTEGER DEFAULT 0
);

INSERT INTO products (name, price, views) VALUES
    ('Wireless Mouse',       19.99, 500),
    ('Mechanical Keyboard',  89.99, 420),
    ('USB-C Hub',            34.50, 300),
    ('Laptop Stand',         45.00, 150),
    ('Webcam 1080p',         59.99, 100);
