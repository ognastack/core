-- migrate:up

CREATE SCHEMA IF NOT EXISTS checks;

-- Create a simple checks table
CREATE TABLE checks.health_checks (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('healthy', 'unhealthy', 'unknown')),
    last_checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT,
    response_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create an index for better query performance
CREATE INDEX idx_health_checks_service_status ON checks.health_checks(service_name, status);
CREATE INDEX idx_health_checks_last_checked ON checks.health_checks(last_checked_at);

-- Create a function to add or update a health check
CREATE OR REPLACE FUNCTION checks.upsert_health_check(
    p_service_name VARCHAR(100),
    p_status VARCHAR(20),
    p_error_message TEXT DEFAULT NULL,
    p_response_time_ms INTEGER DEFAULT NULL
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    check_id INTEGER;
BEGIN
    -- Insert new health check record
    INSERT INTO checks.health_checks (
        service_name, 
        status, 
        error_message, 
        response_time_ms,
        last_checked_at
    )
    VALUES (
        p_service_name, 
        p_status, 
        p_error_message, 
        p_response_time_ms,
        CURRENT_TIMESTAMP
    )
    RETURNING id INTO check_id;
    
    RETURN check_id;
END;
$$;

-- Create a function to get the latest status for each service
CREATE OR REPLACE FUNCTION checks.get_latest_service_status()
RETURNS TABLE (
    service_name VARCHAR(100),
    status VARCHAR(20),
    last_checked_at TIMESTAMP,
    error_message TEXT,
    response_time_ms INTEGER
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT ON (hc.service_name)
        hc.service_name,
        hc.status,
        hc.last_checked_at,
        hc.error_message,
        hc.response_time_ms
    FROM checks.health_checks hc
    ORDER BY hc.service_name, hc.last_checked_at DESC;
END;
$$;

-- Insert some sample data for testing
INSERT INTO checks.health_checks (service_name, status, response_time_ms) VALUES
    ('api-gateway', 'healthy', 45),
    ('user-service', 'healthy', 23),
    ('payment-service', 'unhealthy', 5000);
-- migrate:down