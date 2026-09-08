# 3mf-reprofile

Swap the machine profile of a `.3mf` project **without losing what the model's
author tuned**.

Works with any slicer in the Orca family — OrcaSlicer, Bambu Studio, Elegoo
Slicer, Creality Print, Anycubic, Qidi, Snapmaker — because they all store the
settings in the same place inside the 3MF. It does **not** work with PrusaSlicer
or Cura, which use a different structure.

## The problem

Your slicer opens the `.3mf` you downloaded from MakerWorld, but on opening it
applies its own preset on top and silently overwrites the author's process
settings.

Measured on a real pair of the same model saved on two machines (Bambu X1 Carbon
and Elegoo Centauri Carbon): of the 149 differences between the two files, **67
were shape only** (the multi-extruder machine stores one value per extruder, in a
list of 4; the single-nozzle one stores a list of 1) and **82 were real value
changes**. Some of those 82 are machine settings, and replacing them is correct —
G-code flavour from Marlin to Klipper, start and end G-code, bed area. The rest
is the author's work quietly going away:

| setting | author | became |
|---|---|---|
| `bottom_shell_thickness` | 0 | 0.6 |
| `elefant_foot_compensation` | 0.15 | 0.1 |
| `inner_wall_speed` | 300 | 200 |
| `internal_solid_infill_pattern` | zig-zag | monotonic |
| `ensure_vertical_shell_thickness` | enabled | ensure_all |

## How it fixes that

The output `project_settings.config` is assembled by scope:

- **machine** → always from the *donor*, a `.3mf` you saved in your own slicer.
  It is what makes the file print on your printer.
- **filament** → from the donor by default, because it is the spool *you* will
  use (`--author-filament` flips this).
- **process** → from the author. Walls, infill, seam, speeds, supports, layer
  height.

On top of that, whatever the author declared as a deliberate change — the
`different_settings_to_system` field the file already carries — is treated as
untouchable and never yields to the preset.

Two corrections the format demands: **arity** (per-extruder lists collapse to the
target machine's extruder count) and **shape** (some forks store certain keys as
a scalar where others use a list of one). The output copies the donor's shape,
key by key.

**Not touched:** geometry, colour painting, support painting, modifiers and
per-object settings. The output file is the entire source zip with a single
member rewritten.

## Usage

```
python reprofile_3mf.py model_from_makerworld.3mf \
    --donor any_project_of_mine.3mf \
    -o "model - my printer.3mf"
```

Options: `--author-filament` to bring the author's filament profile across as
well, `-v` to list every preserved setting and not only the declared ones.

The report goes to the screen: what was preserved, what was replaced by your
machine, what was shape only, and a warning when an author value goes past your
machine's physical limit — in that case the value is preserved anyway and the
warning is left with you, instead of the tool deciding behind your back.

Requires Python 3.8+ and the standard library only.

## Status

Tested on the Bambu Lab → Elegoo Centauri Carbon path: zip intact, every internal
member identical to the original except the config one, 27 author settings
preserved. The other slicers in the family should work through the same
mechanism, but have not been run yet — if one opens wrong, the `-v` report is the
starting point.
