"""Build a version-bound LEGIE localization from reviewed offline resources."""
import argparse
import csv
import hashlib
import io
import json
import re
import struct
import subprocess
import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFilter, ImageFont


EXE_HASH = "54cd6383ba5735f990f681f44f6d8116ac4768502a94a03a1831f9c68fac27ad"
SUD_HASH = "40a834807c841617527764b581215950e14f2f9dbccdac7425d6600158f29347"
IMAGE_BASE = 0x400000
CODE_DELTA = 0xC00
ENGINE_MESSAGES = {0x1A175C, 0x1A17B8, 0x1A1800, 0x1AA014}
ORIGINAL_SYMBOLS = {
    "original_preload": 0x4B8A74, "load_glyph_material": 0x4B8908,
    "assign_string": 0x404820, "make_sprite": 0x4B9354, "sprite_name": 0x4B92C0,
    "draw_space": 0x4B9635, "draw_original": 0x4B95FD, "draw_next": 0x4B963C,
    "delete_next": 0x4B9744, "delete_original": 0x4B9719, "delete_lookup": 0x4B9725,
    "move_next": 0x4B98C1, "move_original": 0x4B9850, "move_lookup": 0x4B985C,
    "fade_next": 0x4B99CC, "fade_original": 0x4B9969, "fade_lookup": 0x4B9975,
}
HOOKS = [
    (0x4B9277, "e8 f8 f7 ff ff", 0xE8, "preload"),
    (0x4B95F6, "3c 20 74 3b 8d 55 f4", 0xE9, "draw_glyph"),
    (0x4B9712, "80 7c 38 ff 20 74 2b", 0xE9, "delete_glyph"),
    (0x4B9849, "80 7c 30 ff 20 74 71", 0xE9, "move_glyph"),
    (0x4B9962, "80 7c 38 ff 20 74 63", 0xE9, "fade_glyph"),
]
GLYPH_SOURCE = Path(__file__).with_name("glyphs.s")
NATIVE_ASCII = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -():.,/!?+'&%#"
PACK_ENTRY = struct.Struct("<120sII")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def aligned(value, granularity):
    return (value + granularity - 1) // granularity * granularity


def ansi_string(raw):
    return struct.pack("<iI", -1, len(raw)) + raw + b"\0"


def load_toolchain(directory, scratch, address, glyph_count):
    def call(tool, *args, output=False):
        return subprocess.run([directory / (tool + ".exe"), *args], check=True,
                              text=True, stdout=subprocess.PIPE if output else None).stdout

    obj = scratch / "glyphs.o"
    linked = scratch / "glyphs.pe"
    raw = scratch / "glyphs.bin"
    call("as", "--32", "--defsym", f"glyph_count={glyph_count}", GLYPH_SOURCE, "-o", obj)
    call("ld", "-m", "i386pe", "--image-base", "0", f"--section-start=.text={address:#x}",
         "--disable-reloc-section", "--no-insert-timestamp", "-e", "preload",
         *(f"--defsym={name}={value:#x}" for name, value in ORIGINAL_SYMBOLS.items()),
         obj, "-o", linked)
    call("objcopy", "-O", "binary", "-j", ".text", linked, raw)
    symbol_values = {}
    for line in call("nm", linked, output=True).splitlines():
        match = re.fullmatch(r"([0-9a-f]+) T (\w+)", line.strip())
        if match:
            symbol_values[match[2]] = int(match[1], 16)
    payload = bytearray(raw.read_bytes())
    del payload[symbol_values["glyph_names"] - address:]
    return payload, symbol_values


def patch_executable(executable, translations, glyphs, binutils):
    patched = bytearray(executable)
    pe = struct.unpack_from("<I", patched, 0x3C)[0]
    opt = pe + 24
    section_count = struct.unpack_from("<H", patched, pe + 6)[0]
    opt_size = struct.unpack_from("<H", patched, pe + 20)[0]
    sec_alignment, raw_alignment = struct.unpack_from("<II", patched, opt + 32)
    size_of_image, header_size = struct.unpack_from("<II", patched, opt + 56)
    section_offset = opt + opt_size + section_count * 40
    if section_offset + 40 > header_size:
        raise ValueError("No space for a PE section header")
    virtual_address = IMAGE_BASE + size_of_image
    with tempfile.TemporaryDirectory(prefix="legie-build-") as temp:
        payload, symbols = load_toolchain(binutils, Path(temp), virtual_address, len(glyphs))
    for glyph_index in range(len(glyphs)):
        name = f"zh{glyph_index:03x}".encode("ascii")
        payload.extend(ansi_string(name).ljust(16, b"\0"))
    for entry, translation in translations:
        operand = entry["operand_file_offset"]
        original = struct.unpack_from("<I", executable, operand)[0]
        if original != entry["virtual_address"]:
            raise ValueError(f"Changed string reference at {operand:#x}")
        encoded = b"".join(char.encode("ascii") if char in NATIVE_ASCII
                           else f"~{glyphs[char]:03x}".encode("ascii") for char in translation)
        offset = aligned(len(payload), 4)
        payload.extend(b"\0" * (offset-len(payload)))
        payload.extend(ansi_string(encoded))
        struct.pack_into("<I", patched, operand, virtual_address + offset + 8)
    for address, expected, opcode, symbol in HOOKS:
        position = address - IMAGE_BASE - CODE_DELTA
        expected = bytes.fromhex(expected)
        if executable[position:position+len(expected)] != expected:
            raise ValueError(f"Changed hook at {address:#x}")
        patched[position:position+len(expected)] = (
            struct.pack("<Bi", opcode, symbols[symbol] - address - 5)
            + b"\x90" * (len(expected)-5)
        )
    raw_start = aligned(len(patched), raw_alignment)
    raw_size = aligned(len(payload), raw_alignment)
    struct.pack_into("<H", patched, pe+6, section_count+1)
    struct.pack_into("<I", patched, opt+56, aligned(size_of_image+len(payload), sec_alignment))
    code_size = struct.unpack_from("<I", patched, opt+4)[0]
    struct.pack_into("<I", patched, opt+4, code_size+raw_size)
    struct.pack_into("<8sIIIIIIHHI", patched, section_offset, b".legiezh", len(payload), size_of_image,
                     raw_size, raw_start, 0, 0, 0, 0, 0x60000020)
    patched.extend(b"\0" * (raw_start-len(patched)))
    patched.extend(payload.ljust(raw_size, b"\0"))
    return bytes(patched)


def read_pack(data):
    magic, start, size = struct.unpack_from("<4sII", data)
    if magic != b"PACK" or start < 12 or start+size != len(data):
        raise ValueError("Invalid SUD archive")
    records = []
    for name, offset, length in PACK_ENTRY.iter_unpack(data[start:]):
        if not 12 <= offset <= offset+length <= start:
            raise ValueError("Invalid SUD record range")
        records.append((name, data[offset:offset+length]))
    return records


def write_pack(records):
    payload = bytearray(12)
    directory = bytearray()
    for name, content in records:
        directory.extend(PACK_ENTRY.pack(name, len(payload), len(content)))
        payload.extend(content)
    struct.pack_into("<4sII", payload, 0, b"PACK", len(payload), len(directory))
    payload.extend(directory)
    return bytes(payload)


def tga(image):
    handle = io.BytesIO()
    image.convert("RGBA").save(handle, format="TGA", compression="tga_rle")
    return handle.getvalue()


def glyph_texture(char, font):
    scale = 4
    size = 16*scale
    mask = Image.new("L", (size, size))
    draw = ImageDraw.Draw(mask)
    left, top, right, bottom = font.getbbox(char)
    draw.text(((size-(right-left))/2-left, (size-(bottom-top))/2-top-2),
              char, font=font, fill=255)
    stroke = mask.filter(ImageFilter.MaxFilter(7))
    stroke = Image.eval(stroke, lambda opacity: int(opacity*0.87))
    image = Image.new("RGBA", (size, size), "black")
    image.putalpha(stroke)
    fill = Image.new("RGBA", (size, size), "#f5f5f5")
    fill.putalpha(mask)
    image.alpha_composite(fill)
    return tga(image.resize((16, 16), Image.Resampling.LANCZOS))


def load_translations(source, target, confirmation, executable):
    mapping = json.loads(source.with_suffix(".mapping.json").read_text("utf-8"))
    approval = json.loads(confirmation.read_text("utf-8"))
    if sha(source.read_bytes()) != mapping["source_sha256"]:
        raise ValueError("Source no longer matches extraction mapping")
    if not (approval.get("status") == "passed" and approval.get("semantic_review") == "full"
            and approval.get("source_sha256") == sha(source.read_bytes())
            and approval.get("translation_sha256") == sha(target.read_bytes())):
        raise ValueError("Reviewed translation hashes required")
    with source.open(encoding="utf-8-sig", newline="") as f:
        originals = list(csv.reader(f))
    with target.open(encoding="utf-8-sig", newline="") as f:
        translations = list(csv.reader(f))
    pairs = []
    for n, (entry, (text,), (translation,)) in enumerate(
        zip(mapping["records"], originals, translations, strict=True), 1
    ):
        offset = entry["file_offset"]
        raw = executable[offset:offset+entry["source_byte_length"]]
        if (entry["ordinal"] != n or sha(text.encode("utf-8")) != entry["source_sha256"]
                or raw.decode(entry["encoding"]) != text):
            raise ValueError(f"Changed original at row {n}")
        if translation.count("#") != text.count("#"):
            raise ValueError(f"Changed line segments at row {n}")
        if offset not in ENGINE_MESSAGES:
            pairs.append((entry, translation))
    return pairs


def replace_textures(project, records, image_patch):
    manifest = json.loads((image_patch/"IMAGE_PATCH_MANIFEST.json").read_text("utf-8"))
    source = project/"legie_images_text.csv"
    translated = project/"legie_images_text_translated.csv"
    if (manifest.get("status") != "ready_for_engine_adapter"
            or manifest.get("mode") != "texture"
            or manifest.get("visual_review", {}).get("status") != "passed"
            or manifest.get("source_sha256") != sha(source.read_bytes())
            or manifest.get("translation_sha256") != sha(translated.read_bytes())
            or manifest.get("mapping_sha256") != sha(source.with_suffix(".mapping.json").read_bytes())):
        raise ValueError("Visually verified localization texture manifest required")
    replaced = set()
    for item in manifest["files"]:
        texture = (image_patch/item["path"]).resolve()
        if not texture.is_relative_to(image_patch.resolve()) or sha(texture.read_bytes()) != item["sha256"]:
            raise ValueError("Changed localization texture")
        for source_record in item["sources"]:
            asset = source_record["provenance"]
            index = asset["entry_index"]
            name, old = records[index]
            if (index in replaced or asset["asset"] != "legie.sud"
                    or name.split(b"\0", 1)[0].decode("cp1250") != asset["texture_name"]
                    or not asset["texture_name"].endswith(".tga")):
                raise ValueError(f"Invalid duplicate or mismatched texture entry {index}")
            with Image.open(texture) as image, Image.open(io.BytesIO(old)) as original:
                if image.size != original.size:
                    raise ValueError(f"Texture dimensions changed: {texture}")
                records[index] = name, tga(image)
            replaced.add(index)
    return len(replaced)


def build(project, destination, binutils, font_path, smoke, image_patch):
    originals = project/"Analysis"/"original"
    if not originals.is_dir():
        originals = project/"Game"
    executable = (originals/"legie.exe").read_bytes()
    archive = (originals/"legie.sud").read_bytes()
    if (sha(executable), sha(archive)) != (EXE_HASH, SUD_HASH):
        raise ValueError("Unsupported installed LEGIE build")
    if smoke:
        # Disposable check of the setting label and cancel from real source offsets.
        mapping = json.loads((project/"legie_text.mapping.json").read_text("utf-8"))
        sample = {0x1700B0:"(F7,F8)鼠标灵敏度", 0x170104:"普通", 0x163670:"取消"}
        pairs = [(r, sample[r["file_offset"]]) for r in mapping["records"]
                 if r["file_offset"] in sample]
    else:
        pairs = load_translations(project/"legie_text.csv", project/"legie_text_translated.csv",
                                  project/"TranslateFiles/reports/final_validation.json", executable)
    chars = sorted({char for _, text in pairs for char in text if char not in NATIVE_ASCII})
    if len(chars) > 4096:
        raise ValueError("Too many distinct glyphs for the three-digit escape")
    with TTFont(font_path) as font_table:
        missing = [char for char in chars if ord(char) not in font_table.getBestCmap()]
    if missing:
        raise ValueError(f"Font lacks these translated glyphs: {missing!r}")
    glyphs = {char: index for index, char in enumerate(chars)}
    patched = patch_executable(executable, pairs, glyphs, binutils)
    records = read_pack(archive)
    replacing = replace_textures(project, records, image_patch) if image_patch else 0
    font = ImageFont.truetype(font_path, 53)
    payload = records + [(f"zh{index:03x}.tga".encode("ascii").ljust(120,b"\0"),
                          glyph_texture(char, font)) for char, index in glyphs.items()]
    packaged = write_pack(payload)
    if read_pack(packaged) != payload:
        raise ValueError("SUD round-trip failed")
    destination.mkdir(parents=True, exist_ok=False)
    (destination/"legie.exe").write_bytes(patched)
    (destination/"legie.sud").write_bytes(packaged)
    print(f"{len(pairs)} text references, {replacing} replacement textures, "
          f"{len(glyphs)} glyphs, {len(payload)} SUD entries")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--binutils", type=Path, required=True)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--image-patch", type=Path)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.destination, args.binutils,
          args.font, args.smoke, args.image_patch)
