from pathlib import Path

folder = Path("GCS_BUCKET")

json_files = list(folder.glob("*.json"))

for file in json_files:
    print(file.name)