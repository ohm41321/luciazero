def active_names(client): return [x["name"] for x in client.iter_items() if x.get("active")]
