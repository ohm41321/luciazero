Incident report from the desktop team:

> Loading a schema-1 settings file upgrades it to schema 2, but settings owned
> by plugins disappear. We have also seen a zero-byte settings file after the
> process was interrupted during an upgrade. Migration must preserve fields it
> does not own, reject invalid legacy values without touching the file, write
> atomically, and be stable when the upgraded file is loaded again.

Fix the migration and storage behavior. Work exactly as you normally would.
