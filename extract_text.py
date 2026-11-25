from collections import defaultdict
from pathlib import Path
import hashlib
import json
import re
import struct
import sys

project = Path(__file__).resolve().parent
sys.path.insert(0, str(project.parents[1] / "Tools" / "localization"))
from workflow_resource_occurrences import export_occurrences

binary = (project / "Game" / "legie.exe").read_bytes()
digest = hashlib.sha256(binary).hexdigest()
if digest != "54cd6383ba5735f990f681f44f6d8116ac4768502a94a03a1831f9c68fac27ad":
    raise ValueError(f"Unsupported legie.exe SHA-256: {digest}")

image_base = 0x400000
code_delta = 0xC00
references = defaultdict(list)
cursor = 0x1C1C00
while cursor < 0x1C1C00 + 0x11C38:
    page, block_size = struct.unpack_from("<II", binary, cursor)
    for (entry,) in struct.iter_unpack("<H", binary[cursor + 8:cursor + block_size]):
        rva = page + (entry & 0xfff)
        if entry >> 12 == 3 and 0x1000 <= rva < 0x1BC708:
            operand = rva - code_delta
            (address,) = struct.unpack_from("<I", binary, operand)
            references[address].append(operand)
    cursor += block_size

# Language-resource suffix and punctuation glyph configuration are runtime keys.
runtime_keys = {0x170098, 0x1700A4}
engine_messages = {0x1A175C, 0x1A17B8, 0x1A1800, 0x1AA014}
rows = []
context = {}
locations = []
for match in re.finditer(rb"\xff{4}", binary):
    offset = match.start() + 8
    in_language_table = 0x162E2C <= offset <= 0x170134
    if (not in_language_table and offset not in engine_messages) or offset in runtime_keys:
        continue
    (length,) = struct.unpack_from("<I", binary, offset - 4)
    value = binary[offset:offset + length]
    if not 1 <= length <= 4000 or binary[offset + length] != 0:
        continue
    if not re.fullmatch(rb"[\x20-\x7e\x80-\xff\t\r\n]+", value) or not value.strip():
        continue
    source = value.decode("cp1250")
    address = image_base + offset + code_delta
    operands = references[address]
    if not operands:
        raise ValueError(f"No PE relocation references for {offset:#x}")
    if offset in engine_messages:
        kind = "engine_message"
    elif offset < 0x16352C:
        kind = "object_name"
    elif offset < 0x16FE80:
        kind = "dialogue_or_interaction"
    elif offset <= 0x170074:
        kind = "ending"
    else:
        kind = "settings"
    for operand in operands:
        resource = f"legie.exe#ansi={offset:06x}/reference={operand:06x}"
        rows.append({"resource": resource, "source": source})
        locations.append({
            "file_offset": offset,
            "virtual_address": address,
            "operand_file_offset": operand,
            "operand_virtual_address": image_base + operand + code_delta,
            "encoding": "cp1250",
            "source_byte_length": length,
        })
        context[str(len(rows))] = {
            "group": kind,
            "text_type": kind,
            "resource": resource,
        }

source_csv = project / "legie_text.csv"
mapping_path = source_csv.with_suffix(".mapping.json")
print(export_occurrences(rows, source_csv, mapping_path))
mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
mapping["binary_sha256"] = digest
for entry, location in zip(mapping["records"], locations, strict=True):
    entry.update(location)
mapping_path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
source_csv.with_suffix(".context.json").write_text(
    json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
