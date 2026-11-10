# Presets

The Presets section lives in `src/mpfb/ui/presets/`. Its root panel is `MPFB_PT_Presets_Panel`, which appears as "Manage save files" under the Materials category in Blender's sidebar. Like other root panels in MPFB, it acts purely as a container — all actual controls are in the child panels nested inside it.

The purpose of this section is to let users save the current state of a character (or parts of it) to a file, and later reload that state onto the same or a different character. Two types of save files are supported: complete human character presets and eye material settings. All save files are stored in the user config directory (`LocationService.get_user_config()`).

## Sub-sections

| Sub-section directory | Panel label | Description |
|---|---|---|
| `humanpresets/` | "Human save files" | Save and load complete character presets (morphs, rig, and configuration) |
| `eyesettings/` | "Eye material save files" | Save and load procedural eye shader parameters for the procedural eye material |

## Further reading

- [humanpresets.md](humanpresets.md) — "Human save files" panel
- [eyesettings.md](eyesettings.md) — "Eye material save files" panel
- [UI Layer overview](../index.md)
- [Meta classes](../meta.md) — `Abstract_Panel`, `MpfbOperator`, `MpfbContext`, `pollstrategy`
