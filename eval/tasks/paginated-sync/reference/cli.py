from client import Client
from service import active_names


def demo_transport(cursor):
    pages = {
        None: {
            "items": [{"name": "Ada", "active": True}, {"name": "Lin", "active": False}],
            "next_cursor": "page 2/+",
        },
        "page 2/+": {"items": [{"name": "Grace", "active": True}], "next_cursor": None},
    }
    return pages[cursor]


def main(transport=demo_transport):
    for name in active_names(Client(transport)):
        print(name)


if __name__ == "__main__":
    main()
