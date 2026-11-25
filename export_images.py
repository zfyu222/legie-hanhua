from pathlib import Path
from io import BytesIO
from PIL import Image, ImageDraw
import hashlib
import json
import struct

project = Path(__file__).resolve().parent
archive = project / "Game" / "legie.sud"
data = archive.read_bytes()
magic, directory, directory_size = struct.unpack_from("<4sII", data)
if magic != b"PACK" or directory < 12 or directory + directory_size != len(data):
    raise ValueError("Unexpected archive layout")
output = project / "ImageText" / "exported"
output.mkdir(parents=True, exist_ok=False)
provenance = {}
for index, (raw_name, offset, size) in enumerate(
    struct.iter_unpack("<120sII", data[directory:])
):
    name = raw_name.split(b"\0", 1)[0].decode("cp1250")
    if offset < 12 or offset + size > directory:
        raise ValueError(f"Invalid extent for entry {index}: {name}")
    if Path(name).suffix.lower() not in {".tga", ".jpg"}:
        continue
    key = f"{index:03d}.png"
    with Image.open(BytesIO(data[offset:offset + size])) as image:
        image.save(output / key)
    provenance[key] = {
        "asset": archive.name,
        "entry_index": index,
        "texture_name": name,
        "offset": offset,
        "size": size,
    }
(output.parent / "sud-provenance.json").write_text(
    json.dumps(provenance, indent=2), encoding="utf-8"
)
print("Archive SHA-256", hashlib.sha256(data).hexdigest(), "images", len(provenance))
for page in range(0, len(provenance), 64):
    sheet = Image.new("RGB", (960, 800), "#414141")
    draw = ImageDraw.Draw(sheet)
    for slot, key in enumerate(list(provenance)[page:page + 64]):
        x, y = slot % 8 * 120, slot // 8 * 100
        image = Image.open(output / key).convert("RGBA")
        image.thumbnail((116, 80))
        sheet.paste(image, (x, y), image)
        draw.text((x, y + 81), f"{key[:3]} {provenance[key]['texture_name'][:15]}", fill="white")
    sheet.save(project / "Analysis" / f"contact-{page // 64}.png")
