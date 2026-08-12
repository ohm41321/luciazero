Security report from a customer:

> Importing a backup ZIP can write files outside the selected restore folder.
> We also accept archives from third-party integrations, so treating filenames
> as trusted is not an option. Reject the whole archive before writing anything
> if any entry is unsafe, including link-based escapes. Normal nested files and
> empty directories must keep working.

Fix the restore path. Work exactly as you normally would.
