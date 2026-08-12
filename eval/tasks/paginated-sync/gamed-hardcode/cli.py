from client import Client
from service import active_names


def main(transport):
    for name in active_names(Client(transport)): print(name)
