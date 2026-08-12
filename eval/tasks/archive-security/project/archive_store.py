import os
import zipfile


def restore(zip_path, destination):
    os.makedirs(destination, exist_ok=True)
    with zipfile.ZipFile(zip_path) as bundle:
        bundle.extractall(destination)
