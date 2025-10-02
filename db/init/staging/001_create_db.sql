DO
$$
BEGIN
  IF NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'oraculoicms_staging'
  ) THEN
    PERFORM dblink_exec('dbname=' || current_database(),
      'CREATE DATABASE oraculoicms_staging OWNER postgres');
  END IF;
END
$$;
