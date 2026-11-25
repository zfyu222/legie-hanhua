"""Recover the bound source CSV from a local original installation."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("mapping", type=Path)
parser.add_argument("game", type=Path)
args = parser.parse_args()
mapping = json.loads(args.mapping.read_bytes())
game = args.game.resolve(strict=True)
prefix = args.mapping.name.removesuffix(".mapping.json")
target = args.mapping.with_name(prefix + ".csv")
resources = {}
output = io.StringIO(newline="")
writer = csv.writer(output)
for ordinal, record in enumerate(mapping["records"], 1):
    resource = record.get("file", "legie.exe")
    if resource not in resources:
        path = (game / resource).resolve(strict=True)
        if not path.is_relative_to(game):
            raise ValueError(f"Resource outside the original game directory: {resource}")
        resources[resource] = path.read_bytes()
    offset = record.get("offset", record.get("file_offset"))
    length = record.get("length", record.get("source_byte_length"))
    raw = resources[resource][offset:offset + length]
    text = raw.decode(record["encoding"])
    if ordinal != record["ordinal"] or len(raw) != length or hashlib.sha256(text.encode("utf-8")).hexdigest() != record["source_sha256"]:
        raise ValueError(f"Original resource differs at row {ordinal}: {resource}")
    writer.writerow([text])
content = output.getvalue().encode("utf-8")
if hashlib.sha256(content).hexdigest() != mapping["source_sha256"]:
    raise ValueError("Reconstructed CSV differs from the recorded source hash")
with target.open("xb") as handle:
    handle.write(content)
print(f"{target}: {len(mapping['records'])} verified rows")
