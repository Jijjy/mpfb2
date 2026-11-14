# Spec: Stylized look for MPFB2 without a new base mesh

Status: draft for sign-off. Date: 2026-11-11, revised 2026-11-14 (shape layer and
Stylization slider dropped, §3.1). Ticket HRGGWH.
Branch `stylize-og`, cut from upstream tip `6ff1eb35` (Joel Palmius, 2026-10-24). None of the
fork's edits are on it.

This replaces the hard-fork spec on `master` (`STYLIZED_SPEC.md`, hand-built `sty01` mesh).
That plan spent Phases 1–2 on a mesh, a binder, and conversion of 1,258 targets, about 1,950 rig joint locators
and the weights, before any character looked different. This one changes the look first and
leaves the mesh alone.

## 1. Goal

MPFB2 characters stop landing in the uncanny valley and read as Overwatch / Fortnite style
heroes: painted skin, flat readable eyes, chunky hair. No mesh reshaping and no
stylization slider (§3.1).

**The HM08 base mesh, its 19,158 vertices (13,380 body), UVs, vertex groups, rigs, weights,
`.mhclo` / `.mhmat` assets, `.mhm` files and all 1,258 targets stay exactly as they are.**
Everything is additive, and a character made by the unmodified add-on still loads.

Non-goals:
- a new or decimated base mesh, LODs, a triangle budget (HM08 is not low-poly; the silhouette
  and the shading carry the look, not the count)
- toon / cel NPR shading and outlines
- removing the realistic skin, eyes or any asset path
- converting community assets

## 2. Why the valley happens, and what it dictates

Research (kept from the earlier spec):

- **MacDorman & Chattopadhyay 2016** (*Cognition* 146): mismatched realism between features
  reads as eerie.
- **Seyama & Nagayama 2007** (*Presence* 16(4)): the valley shows up when a realistic face
  also has abnormal features, such as enlarged eyes.
- **Zell et al. 2015** (SIGGRAPH Asia): shape drives how realistic a face looks; material,
  above all albedo, drives appeal. Appeal peaks when shape and material are stylized to a
  similar degree.

MPFB2's default is the worst case: a photo-derived, pore-level skin on an anatomically exact
mesh, with procedural eyes that have veins and a real cornea. The fix here leaves the
shape alone and stylizes **skin, eyes and hair together** (rules R1–R3), which needs no new
topology:

1. **R1:** Skin is painted, not photographic: no pores, no photo texture, no
   skin micro-normal, no veins.
2. **R2:** Skin and eyes change together. Stylized eyes are never shipped on the
   realistic skin, nor the reverse.
3. **R3:** One detail frequency across skin, eyes, hair and teeth: painted, low-frequency.
4. **R4:** Silhouette first. Detail echoes the silhouette shapes (Valve, *Illustrative
   Rendering in TF2*, 2007).

## 3. Approach: textures and hair, mesh untouched

| Layer | What | Touches the mesh? |
|---|---|---|
| B. Skin and eyes | New `STYLIZED` skin type and `STYLIZED_EYES`, made the default | No |
| C. Hair | Chunky `CLUMP` hair-card mode and a hair shader | No |

Letters kept so older tickets still point at the right section.

### 3.1 No shape layer, no stylization slider (decision 2026-11-14)

The first draft had a layer A: a `stylized-default` shape target (eyes +22%, smoothed face,
bigger hands) driven by a 0–2 **Stylization** slider, with a `stylized-chunky` endpoint
above 1.0. Phases 1, 2 and 5 built it. The user does not want it: the fork keeps the HM08
proportions, offers no stylization slider, and gets its look from textures and hair. Body
shape stays whatever the stock macros and targets make it.

## 4. Removed: layer A

Delete what Phases 1, 2 and 5 added (ticket in §9):
- `data/targets/stylization/` (`stylized-default`, `stylized-chunky`) and its `target.json`
  section; `tools/hm08/make_stylized_default.py` and `render_blockout.py`.
- The Stylization slider: `phenotype_stylization.json`, `humanproperties/stylization.json`,
  the model-panel slider, the `HUM_stylization` property, the age fade in `HumanService`,
  and the stylization handling in create, import, randomize and export.
- An `.mhm` that still carries a stylization entry loads without error and ignores it.

## 5. Layer B: skin and eyes

Both are **nodemodel v2** wrappers in `entities/nodemodel/v2/materials/`. The v2 framework is
already in the tree (`composites/`, `abstractgroupwrapper.py`).

Port from `master` rather than writing again: `nodewrapperstylizedskin.py`,
`nodewrapperstylizedeyes.py`, their tests, and the eye presets (`git log master --
src/mpfb/entities/nodemodel/v2/materials`). Check the ported code against this tree's
`MaterialService` and `NodeService`, and drop anything that deletes realistic code. Master's `materialservice.py` diff removes 596 lines, so port by hand, not by cherry-pick.

### 5.1 `STYLIZED` skin

One Principled BSDF, exportable to glTF/FBX. Group inputs:

| Input | Default | Notes |
|---|---|---|
| `SkinTone` | sRGB (0.80, 0.60, 0.48) | Plus 12 swatches in `data/settings/skin_tones.json`. |
| `BloodMap` | `data/textures/sty_bloodmap.png` (1024²) | Painted mask of warm areas: cheeks, nose tip, ears, lips, knuckles, elbows, knees, palms, soles. Painted fresh in HM08's existing UV layout (master's `sty01_bloodmap.png` is for sty01 UVs and cannot be reused). |
| `BloodTint` | (0.85, 0.35, 0.30), strength 0.04 | Mixed into `SkinTone` through `BloodMap`. Replaces SSS for the warm look. |
| `CavityMap` | AO baked from the HM08 base mesh | Multiplied in at 0.05, tinted toward `BloodTint`, so folds read warm and not grey. |
| `Gradient` | 0 (off) by default; a preset may set −4% head to feet | Object-space gradient, keeps attention on the face. |
| Roughness | 0.55 (face 0.50, lips 0.40) | Painted mask; range 0.4–0.6. |
| Specular IOR Level | 0.35 | Takes the plastic edge off. |
| Subsurface Weight | 0 by default (flat tone) | Radius (1.0, 0.35, 0.2) × 0.5 cm. |
| Normal | none | No micro-normal, no pore noise (R1). |
| `Makeup` | optional decal slot | Lip, liner and blush. |

HM08's UVs and its `mpfb_*` region textures are untouched; the stylized material simply does
not read them. `MaterialService.identify_material` recognises it by the `BloodTint` input.

**Export:** bake `BloodMap`, `CavityMap`, `Gradient` and `SkinTone` into one 2048² albedo so a
game engine gets plain PBR maps, reusing the bake plumbing in `services/hairbakeservice.py`.
Needed for Fortnite/Overwatch-style delivery, so it is Phase 3, not optional.

### 5.2 `STYLIZED_EYES`

- **Sclera:** flat (0.92, 0.90, 0.88), a soft darker edge, no veins.
- **Iris:** one flat colour by default (`IrisInner` = `IrisOuter`; a preset may set a gradient), dark limbal ring at 10% width with hard edges,
  pupil radius 0.35 of the iris; the iris fills about 55% of the visible opening.
- **Catchlight:** painted elliptical highlight at the upper outer side, emission 1.5, so it
  reads the same under any light.
- **Shell:** Roughness 0.5, no coat (a coat mirrors the lights as a pale band over the iris edge), one opaque mesh. No transmission shell, no alpha blend.

Eye size stays HM08's; readability comes from the flat iris, the limbal ring and the
catchlight. Nothing in the eye mesh changes. Presets follow the existing
`ui/presets/eyesettings` pattern.

### 5.3 Wiring and defaults

- Add `STYLIZED` to the skin types and `STYLIZED_EYES` to the eye materials in
  `MaterialService` and the New human panel. **Existing types stay.**
- **New-human default becomes `STYLIZED` skin and `STYLIZED_EYES`.** Characters created
  before the change, and `.mhm` files that name a skin type, keep what they name.
- A one-click "Make stylized" operator on an existing character sets the stylized skin and the stylized eyes together, so R2 holds by construction.
- Teeth, tongue and the stock eyebrows/eyelashes: recoloured by presets (flat white teeth,
  tongue tinted to `BloodTint`, solid-colour brows, upper lashes a thin band with pointed prongs). **No new meshes.** Make stylized recolours them, and so
  does adding one (MAKESKIN material) to a human whose skin is already STYLIZED.

### 5.4 Studio lighting (optional)

A "Stylized studio" operator: key light, cool fill, strong rim, gradient world. For look
development only; it exists on `master` as commit `54a821ec` and may be ported as is.

## 6. Layer C: hair (optional)

Only after B is signed off.

- Extend `services/haircardservice.py` with a `CLUMP` `CARDS_MODE`: guide curves grouped by the
  existing CLUSTER_BOX PCA code, each clump a closed tapered tube (6 sides at the root, 3 at
  the tip, 2:1 flattened), `max_tris` input, no alpha. On `master`: commit `6149243f`.
- Hair shader `nodewrapperstylizedhair.py`: matte (roughness 0.85, low specular, no
  anisotropy), root-to-tip gradient with painted strand grooves and a painted highlight band in
  the albedo. The glossy anisotropic first version (`master` commit `64a63bf3`) read
  as plastic on the solid clump tubes (ticket 67). Contact and depth cues (ticket 71): a root
  shade along V, cel-cut ambient occlusion in the crevices, and a soft hairline: the CLUMP hair
  cap carries `mpfb_hairline` (1 on its border) and the shader's alpha is 1 minus it, so the
  cap's dark rim fades over the skin as a contact shadow. Tubes stay opaque. `cards_clump_strays`
  adds thin stray strands off the clumps.
- Existing alpha-card modes stay. `CLUMP` becomes the default only if the user says so.

## 7. Acceptance

A character at defaults, in Cycles and in EEVEE:

1. Passes R1–R4 by inspection.
2. Vertex positions equal the unmodified add-on's to 1e-6; with the old skin and eyes chosen,
   the material types match too.
3. No stylization control anywhere in the UI or the `.mhm`.
4. Clothes, hair, eyes, teeth and the default rig fit and pose with no new clipping.
5. Export to glTF gives only plain PBR (no custom nodes), one albedo per body.
6. The user signs off the lookdev render (Phases 1 and 3). Images are made with the sandbox
   tier (`claude-sandbox`), never the live desktop.

## 8. Tests

The existing harness is kept (`test/execute_tests_headless.bash`).

| Test | Asserts |
|---|---|
| `bbb_services/humanservice_test.py` | New human at defaults has the plain add-on's vertex positions (1e-6); an `.mhm` with a leftover stylization entry loads and ignores it. |
| `ddd_entities/nodemodel/v2/*` | One test per new wrapper (skin, eyes), as for the existing ones. |
| `bbb_services/materialservice_test.py` | `STYLIZED` is creatable and `identify_material` recognises it; the other skin types still work. |
| `bbb_services/exportservice_test.py` | A stylized character exports with an albedo bake and no custom nodes. |

No upstream test is deleted. The fork's own stylization, age-fade and chunky tests go with
layer A.

## 9. Phases

| Phase | Work | Done when |
|---|---|---|
| 1–2 | ~~Shape target, slider, age fade~~ built, then dropped (§3.1) | Removal: ticket 66 (§4) |
| 3 | Port the `STYLIZED` skin and eyes; wiring, defaults, "Make stylized", teeth/tongue/brow recolour; albedo bake (§5) | `materialservice_test`, wrapper tests and `exportservice_test` pass; the user signs off a lookdev render |
| 4 | Optional: hair `CLUMP` mode and shader (§6); studio lighting (§5.4) | `haircardservice_test` passes |
| 5 | ~~`stylized-chunky` endpoint~~ dropped (§3.1) | Removal: ticket 66 |

## 10. Risks

- **Realistic detail left in the mesh.** HM08 keeps ears, lips and nostrils in higher density
  than a stylized mesh would. The painted material has to hide them. If renders
  still show it, push the cavity and roughness masks flatter first; reshaping the mesh is
  out of scope (§3.1).
- **Realistic assets on a stylized body** (photo-textured clothes, realistic hair) break R3.
  Documented in the panel; not fixed here.
- **Not a game-ready mesh.** Triangle count and LODs are untouched by design. If a hard
  triangle budget returns as a requirement, it is a separate spec with its own mesh decision.
