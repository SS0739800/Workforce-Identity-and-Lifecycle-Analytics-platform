-- Runs once when the container's data volume is first created.
-- The integration tests use their own database so they never touch the development data.
CREATE DATABASE workforce_test;
