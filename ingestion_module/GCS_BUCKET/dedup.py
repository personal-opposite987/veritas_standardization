import json
import json as _json
import hashlib
from pathlib import Path

def get_content_hash(clinical_data: dict) -> str:
    canonical = json.dumps(clinical_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

print("Current directory:", Path.cwd())
print("JSON files:", list(Path(".").glob("*.json")))

def run_ingestion(folder: str):
    seen_hashes = {}
    unique_records = []
    duplicate_log = []

    for filepath in sorted(Path(folder).glob("*.json")):
        with open(filepath) as f:
            envelope = json.load(f)

        for block in envelope["data"]["responseDetails"]:
            clinical_data = block["data"]
            h = get_content_hash(clinical_data)

            record = {
                "source_file": filepath.name,
                "classifier": block.get("classifier"),
                "content_hash": h,
                "data": clinical_data,
            }

            if h in seen_hashes:
                duplicate_log.append({**record, "duplicate_of": seen_hashes[h]})
            else:
                seen_hashes[h] = filepath.name
                unique_records.append(record)

    return unique_records, duplicate_log


if __name__ == "__main__":
    unique, dupes = run_ingestion(".")

    print(f"Unique: {len(unique)}")
    print(f"Duplicates: {len(dupes)}")

    for d in dupes:
        print(
            f"{d['source_file']} "
            f"is a duplicate of "
            f"{d['duplicate_of']}"
        )

def write_duplicate_log(duplicate_log, output_path="duplicate_log.json"):
    with open(output_path, "w") as f:
        _json.dump(duplicate_log, f, indent=2)