# Material Settings Presets

This file explains the material settings preset JSON formats used by MPFB.

This structure is used both in standalone files (as described below) and as keys in human save files.

## Purpose

Material settings presets store shader parameter values for the stylized eye material.

User presets are saved in the user config directory with the naming pattern `eye_settings.<name>.json`.

## Structure: Eye settings

An eye settings file is a flat JSON object (not zone-keyed) with parameters for the procedural eye shader.

### Parameters

- `Clearcoat` (float) — Clearcoat intensity.
- `Clearcoat Roughness` (float) — Clearcoat roughness.
- `EyeWhiteColor` (array of 4 floats) — Sclera RGBA color.
- `InnerLayerRoughness` (float) — Roughness of the inner eye layer.
- `IrisBumpStrength` (float) — Bump map strength for iris detail.
- `IrisClockwiseMult` (float) — Clockwise pattern multiplier for iris texture.
- `IrisFeatureScale` (float) — Scale of iris procedural features.
- `IrisMajorColor` (array of 4 floats) — Primary iris RGBA color.
- `IrisMinorColor` (array of 4 floats) — Secondary iris detail RGBA color.
- `IrisRadialMult` (float) — Radial pattern multiplier for iris texture.
- `IrisSection1End` (float) — Outer radius of iris section 1.
- `IrisSection2End` (float) — Outer radius of iris section 2.
- `IrisSection3End` (float) — Outer radius of iris section 3.
- `IrisSection4Color` (array of 4 floats) — RGBA color for iris section 4.
- `IrisToEyeWhiteRelation` (float) — Size ratio between iris and sclera.
- `OuterLayerAlpha` (float) — Transparency of the outer cornea layer.
- `OuterLayerColor` (array of 4 floats) — RGBA color tint of the cornea.
- `OuterLayerIOR` (float) — Index of refraction for the cornea.
- `OuterLayerRoughness` (float) — Roughness of the cornea surface.
- `OuterLayerTransmission` (float) — Transmission level of the cornea.
- `PupilColor` (array of 4 floats) — RGBA color of the pupil.
- `PupilSize` (float) — Pupil diameter.

### Example

```json
{
    "Clearcoat": 0.8,
    "Clearcoat Roughness": 0.1,
    "EyeWhiteColor": [0.9, 0.9, 0.9, 1.0],
    "IrisMajorColor": [0.2, 0.4, 0.6, 1.0],
    "IrisMinorColor": [0.1, 0.2, 0.3, 1.0],
    "PupilColor": [0.01, 0.01, 0.01, 1.0],
    "PupilSize": 0.3,
    "OuterLayerIOR": 1.376,
    "OuterLayerTransmission": 1.0,
    "OuterLayerAlpha": 0.1
}
```
