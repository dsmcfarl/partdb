CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS locations (
    name VARCHAR(255) PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS parts (
    id SERIAL PRIMARY KEY,
    location VARCHAR(255) NOT NULL REFERENCES locations(name),
    description TEXT NOT NULL,
    embedding vector(1536)
);
