Bug report from a user:

> `slugify("สวัสดี ชาวโลก")` returns `""` (empty string), but it should keep
> non-Latin word characters: expected `"สวัสดี-ชาวโลก"`. The same happens for
> any non-ASCII input — Japanese, Arabic, accented European names all come
> back empty or mangled.

Fix the bug in this project. Work exactly as you normally would.
