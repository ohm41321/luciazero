import json

from settings import migrate


def load(path):
    with open(path, encoding="utf-8") as source:
        original = json.load(source)
    upgraded = migrate(original)
    if upgraded != original:
        with open(path, "w", encoding="utf-8") as output:
            json.dump(upgraded, output, sort_keys=True)
    return upgraded
