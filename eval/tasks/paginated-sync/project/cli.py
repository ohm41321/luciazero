from client import Client
from service import active_names


def demo_transport(cursor):
    return {
        "items": [{"name": "Ada", "active": True}, {"name": "Lin", "active": False}],
        "next_cursor": None,
    }


def main(transport=demo_transport):
    for name in active_names(Client(transport)):
        print(name)


if __name__ == "__main__":
    main()
