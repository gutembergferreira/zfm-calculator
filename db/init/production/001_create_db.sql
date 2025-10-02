DO
$$
BEGIN
  IF NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'oraculoicms'
  ) THEN
    PERFORM dblink_exec('dbname=' || current_database(),
      'CREATE DATABASE oraculoicms OWNER postgres');
  END IF;
END
$$;
