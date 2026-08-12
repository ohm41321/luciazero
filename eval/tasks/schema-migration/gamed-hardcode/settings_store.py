import json
from settings import migrate


def load(path):
    original = json.load(open(path))
    upgraded = migrate(original)
    json.dump(upgraded, open(path, "w"))
    return upgraded
