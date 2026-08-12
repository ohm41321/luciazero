def active_names(client):
    page = client.fetch_page()
    return [item["name"] for item in page["items"] if item.get("active")]
