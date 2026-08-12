def active_names(client):
    return [item["name"] for item in client.iter_items() if item.get("active")]
