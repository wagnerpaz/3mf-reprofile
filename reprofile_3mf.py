#!/usr/bin/env python3
"""
3mf-reprofile — swap the machine profile of a .3mf project WITHOUT losing what
the model's author tuned.

Works with any slicer in the Orca family — OrcaSlicer, Bambu Studio, Elegoo
Slicer, Creality Print, Anycubic, Qidi, Snapmaker — because they all store the
settings in the same place inside the 3MF. It does NOT work with PrusaSlicer or
Cura, which use a different structure.

The problem this solves
-----------------------
Your slicer opens a .3mf authored on another machine, but on opening it applies
its own preset on top and silently overwrites the author's process settings.
Measured on a real pair of the same model (Bambu X1 Carbon -> Elegoo Centauri
Carbon): bottom shell 0 -> 0.6, elephant foot 0.15 -> 0.1, inner wall 300 -> 200
mm/s, solid infill zig-zag -> monotonic, fan timings changed. None of it asked.

The idea
--------
Build the output `project_settings.config` by scope:

  machine  -> ALWAYS from the donor (a .3mf you saved in YOUR OWN slicer). It is
              what makes the file print on your printer: G-code flavour,
              start/end G-code, bed area, acceleration limits.
  filament -> from the donor by default (it is the spool YOU will use), unless
              --author-filament is given.
  process  -> from the AUTHOR. This is what you want to keep: walls, infill,
              seam, speeds, supports, layer height.

And on top of all that, whatever the author declared as a deliberate change —
the source file's own `different_settings_to_system` field — is treated as
untouchable and never yields to the preset.

Two corrections the format demands
----------------------------------
1. Arity: a multi-extruder machine stores one value per extruder (a list of 4);
   a single-extruder one stores a list of 1. Without collapsing these, 67 of the
   149 differences in a real pair were only this — noise, not change.
2. Shape: some forks store certain keys as a scalar where others use a list of
   one. The output copies the donor's shape, key by key.

What is NOT touched: geometry, colour painting, support painting, modifiers and
per-object settings. The output file is the entire source zip with a single
member rewritten.

Usage:
    python reprofile_3mf.py source.3mf --donor my_project.3mf -o output.3mf
"""

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

CONFIG = "Metadata/project_settings.config"

# ---------------------------------------------------------------------------
# Key classification.
#
# There is no scope marker inside the file, so the split is by name. Rule:
# anything matching MACHINE or FILAMENT comes from the donor; EVERYTHING else is
# treated as process and comes from the author. Process keys I don't know about
# land in that catch-all on purpose — over-preserving is the goal — but the
# report lists every one of them so you can check instead of trusting.
# ---------------------------------------------------------------------------

MACHINE_PREFIXES = (
    "machine_", "printer_", "printable_", "printhost_", "extruder_",
    "print_host", "host_type", "bed_", "gcode_", "z_hop",
    "retraction_", "retract_", "wipe_distance", "wipe",
    "nozzle_diameter", "nozzle_type", "nozzle_volume", "nozzle_height",
    "nozzle_hrc", "auxiliary_fan", "support_air_filtration",
    "use_relative_e_distances", "use_firmware_retraction", "silent_mode",
    "single_extruder_multi_material", "purge_in_prime_tower",
    "best_object_pos", "head_wrap_detect_zone",
)

MACHINE_EXACT = {
    "before_layer_change_gcode", "layer_change_gcode", "change_filament_gcode",
    "machine_start_gcode", "machine_end_gcode", "machine_pause_gcode",
    "template_custom_gcode", "time_lapse_gcode", "printing_by_object_gcode",
    "bed_exclude_area", "curr_bed_type", "filename_format", "thumbnails",
    "default_print_profile", "default_filament_profile", "printer_technology",
    "inherits", "inherits_group", "from", "version", "name", "is_custom_defined",
    "upward_compatible_machine", "支持的打印机", "print_settings_id",
    "printer_settings_id", "printer_model", "printer_variant",
    "different_settings_to_system",
    # Compatibility lists: if these come from the author, the slicer decides the
    # profile is incompatible with your own printer and ignores the file.
    # Always from the donor.
    "print_compatible_printers", "filament_compatible_printers",
    "compatible_printers", "compatible_printers_condition",
    "compatible_prints", "compatible_prints_condition",
}

FILAMENT_PREFIXES = (
    "filament_", "nozzle_temperature", "chamber_temp", "cool_plate_temp",
    "eng_plate_temp", "hot_plate_temp", "textured_plate_temp",
    "supertack_plate_temp", "fan_", "overhang_fan_", "close_fan_",
    "additional_cooling_fan_speed", "slow_down_", "reduce_fan_stop_start_freq",
    "enable_overhang_bridge_fan", "complete_print_exhaust_fan_speed",
    "during_print_exhaust_fan_speed", "activate_air_filtration",
    "support_material_interface_fan_speed", "enable_pressure_advance",
    "pressure_advance", "temperature_vitrification", "required_nozzle_HRC",
    "impact_strength_z", "activate_chamber_temp_control",
)

FILAMENT_EXACT = {"filament_settings_id", "filament_ids", "filament_colour",
                  "default_filament_colour", "flush_volumes_matrix",
                  "flush_volumes_vector", "flush_multiplier"}


def scope_of(key: str) -> str:
    if key in MACHINE_EXACT or key.startswith(MACHINE_PREFIXES):
        return "machine"
    if key in FILAMENT_EXACT or key.startswith(FILAMENT_PREFIXES):
        return "filament"
    return "process"


def read_config(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        if CONFIG not in z.namelist():
            raise SystemExit(
                f"{path.name}: has no {CONFIG} — it is a mesh-only .3mf, with no "
                "author settings to preserve."
            )
        return json.loads(z.read(CONFIG).decode("utf-8"))


def match_shape(value, template):
    """Return `value` in the shape of `template` (scalar vs list, and arity)."""
    if isinstance(template, list):
        items = value if isinstance(value, list) else [value]
        if not items:
            return list(template)
        # Multi-extruder -> single extruder: if the author had the same value on
        # every extruder it is a single value; if they differed, the first one is
        # the primary extruder, which is the one a single-tool machine uses.
        if len(template) == 1:
            return [items[0]]
        return (items + [items[-1]] * len(template))[: len(template)]
    if isinstance(value, list):
        return value[0] if value else template
    return value


def author_declared(source: dict) -> set:
    """The keys the author changed on purpose, according to the file itself."""
    field = source.get("different_settings_to_system", [])
    if isinstance(field, str):
        field = [field]
    keys = set()
    for block in field:
        for part in str(block).split(";"):
            part = part.strip()
            if part:
                keys.add(part)
    return keys


def reprofile(source_p: Path, donor_p: Path, output_p: Path,
              author_filament: bool) -> dict:
    source = read_config(source_p)
    donor = read_config(donor_p)

    untouchable = author_declared(source)
    result = dict(donor)

    report = {
        "source": source.get("printer_model", "?"),
        "donor": donor.get("printer_model", "?"),
        "untouchable": sorted(untouchable),
        "preserved": [],
        "shape_only": [],
        "from_machine": [],
        "filament_from_donor": [],
        "skipped_absent_in_donor": [],
        "warnings": [],
    }

    for key, author_value in source.items():
        if key not in donor:
            report["skipped_absent_in_donor"].append(key)
            continue

        scope = scope_of(key)
        forced = key in untouchable

        if scope == "machine" and not forced:
            report["from_machine"].append(key)
            continue
        if scope == "filament" and not (forced or author_filament):
            report["filament_from_donor"].append(key)
            continue

        new_value = match_shape(author_value, donor[key])
        if new_value == donor[key]:
            report["shape_only"].append(key)
        else:
            report["preserved"].append(
                {"key": key, "was": donor[key], "now": new_value,
                 "author_declared": forced}
            )
        result[key] = new_value

    # Physical-limit warning: an author speed above what the machine accepts.
    ceiling = donor.get("machine_max_speed_x") or donor.get("machine_max_speed_e")
    try:
        ceiling = float(ceiling[0] if isinstance(ceiling, list) else ceiling)
    except (TypeError, ValueError, IndexError):
        ceiling = None
    if ceiling:
        for item in report["preserved"]:
            if not item["key"].endswith("_speed"):
                continue
            try:
                v = float(str(item["now"][0] if isinstance(item["now"], list)
                              else item["now"]).rstrip("%"))
            except ValueError:
                continue
            if v > ceiling:
                report["warnings"].append(
                    f"{item['key']} = {v} is above the machine limit "
                    f"({ceiling}). Kept the author's value, but check it."
                )

    # The output file is the entire source zip — geometry, colour painting,
    # support painting and per-object settings pass through untouched — with a
    # single member rewritten.
    shutil.copyfile(source_p, output_p)
    _rewrite_member(output_p, CONFIG,
                    json.dumps(result, ensure_ascii=False, indent=4).encode("utf-8"))
    return report


def _rewrite_member(zip_path: Path, member: str, content: bytes) -> None:
    tmp = zip_path.with_suffix(".tmp3mf")
    with zipfile.ZipFile(zip_path) as src, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = content if info.filename == member else src.read(info.filename)
            dst.writestr(info, data)
    tmp.replace(zip_path)


def print_report(r: dict, verbose: bool) -> None:
    print(f"\n  source : {r['source']}")
    print(f"  donor  : {r['donor']}")
    print(f"\n  declared by the author as deliberate ({len(r['untouchable'])}):")
    for k in r["untouchable"]:
        print(f"      {k}")
    print(f"\n  author settings preserved   : {len(r['preserved'])}")
    print(f"  already equal / shape only  : {len(r['shape_only'])}")
    print(f"  replaced by your machine    : {len(r['from_machine'])}")
    print(f"  filament taken from donor   : {len(r['filament_from_donor'])}")
    if r["skipped_absent_in_donor"]:
        print(f"  source keys with no donor counterpart (skipped): "
              f"{len(r['skipped_absent_in_donor'])}")

    highlights = [p for p in r["preserved"] if p["author_declared"]]
    if highlights:
        print("\n  the untouchable ones, value by value:")
        for p in highlights:
            print(f"      {p['key']}: {p['was']} -> {p['now']}")

    if verbose and r["preserved"]:
        print("\n  every preserved setting:")
        for p in r["preserved"]:
            print(f"      {p['key']}: {p['was']} -> {p['now']}")

    for warning in r["warnings"]:
        print(f"\n  [WARNING] {warning}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Swap the machine profile of a .3mf (Orca family) while "
                    "keeping the model author's tuning.")
    ap.add_argument("source", type=Path,
                    help="the .3mf authored on another machine (MakerWorld, "
                         "Bambu, etc.)")
    ap.add_argument("--donor", type=Path, required=True,
                    help="a .3mf YOU saved in your own slicer; the machine "
                         "profile comes from it")
    ap.add_argument("-o", "--output", type=Path,
                    help="output file (default: <source> - reprofiled.3mf)")
    ap.add_argument("--author-filament", action="store_true",
                    help="also copy the author's filament profile (by default it "
                         "comes from the donor, which is the spool you will use)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list every preserved setting, not only the declared ones")
    args = ap.parse_args()

    if not args.source.exists():
        print(f"cannot find {args.source}", file=sys.stderr)
        return 1
    if not args.donor.exists():
        print(f"cannot find donor {args.donor}", file=sys.stderr)
        return 1

    output = args.output or args.source.with_name(
        f"{args.source.stem} - reprofiled.3mf")
    r = reprofile(args.source, args.donor, output, args.author_filament)
    print_report(r, args.verbose)
    print(f"\n  written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
