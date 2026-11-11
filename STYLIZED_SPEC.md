# Spec: Stylized look for MPFB2 without a new base mesh

Status: draft for sign-off. Date: 2026-11-11. Ticket HRGGWH.
Branch `stylize-og`, cut from upstream tip `6ff1eb35` (Joel Palmius, 2026-10-24). None of the
fork's edits are on it.

This replaces the hard-fork spec on `master` (`STYLIZED_SPEC.md`, hand-built `sty01` mesh).
That plan spent Phases 1–2 on a mesh, a binder, and conversion of 1,258 targets, about 1,950 rig joint locators
and the weights, before any character looked different. This one changes the look first and
leaves the mesh alone.

## 1. Goal

MPFB2 characters stop landing in the uncanny valley and read as Overwatch / Fortnite style
heroes: clean shapes, big readable eyes, painted skin, chunky hair.

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
mesh, with procedural eyes that have veins and a real cornea. The fix is to **move shape,
skin and eyes together** (rules R1–R3), which needs no new topology:

1. **R1:** Skin is stylized at least as far as the shape: no pores, no photo texture, no
   skin micro-normal, no veins.
2. **R2:** Shape, skin and eyes change together. A larger eye is never shipped on the
   realistic skin.
3. **R3:** One detail frequency across skin, eyes, hair and teeth: painted, low-frequency.
4. **R4:** Silhouette first. Detail echoes the silhouette shapes (Valve, *Illustrative
   Rendering in TF2*, 2007).

## 3. Approach: three additive layers

| Layer | What | Touches the mesh? |
|---|---|---|
| A. Shape | `stylization` slider driving a shipped HM08 target set | Only as a normal target on the stack |
| B. Skin and eyes | New `STYLIZED` skin type and `STYLIZED_EYES`, made the default | No |
| C. Hair | Optional chunky `CLUMP` hair-card mode and a hair shader | No |

Layers A and B alone remove most of the valley and are Phases 1–3. C is optional.

### 3.1 Why a slider and not a baked-in shape

The earlier plan baked the shape into the mesh. Here it is a target, so:
- nothing re-binds: clothes, bodyparts, rigs and proxies keep fitting, because they follow
  the target stack already;
- the user can dial it to 0 and get stock MPFB2 back, which is also the regression test;
- it stays one file plus a JSON entry, easy to review and to retune.

## 4. Layer A: shape

### 4.1 `stylized-default` target

Reuse the work on `master`, commit `c57db8ec`:
- `tools/hm08/make_stylized_default.py` builds `stylized-default.target.gz` over HM08's full
  19,158 vertices (helpers and joint cubes included, so eyes, teeth, clothes and rigs follow).
  Regions are soft, symmetric masks from the default rig's skin weights.
- `tools/hm08/render_blockout.py` renders the comparison sheets.
- The target was tuned over PRXJX2 and is the shape the user last reviewed.

Port both files unchanged (`git checkout master -- tools/hm08/`), then re-run the script on
this branch to confirm that it reproduces the committed target byte for byte (it reads only
`base.obj` and the default rig weights, which are identical on both branches).

Scales relative to the HM08 default (from the script's `default` preset):

| Feature | Change |
|---|---|
| Head | +3%, cranium shape unchanged |
| Eyes | +22%, 2.5 mm toward the face plane, rounder openings (lids ×1.8 above, ×1.4 below the eye centre) |
| Nose | −12% toward the cheek plane; +5.5 mm out; nostril flare −80% |
| Ears | concha and folds filled up to the rim |
| Mouth | +6% wider, −5% high, lips −25% in depth, +2.5 mm out, +1.5 mm up |
| Jaw | lower face −10% narrower |
| Face relief | low-pass over the head: no lid creases, philtrum, brow ridge or nasolabial folds |
| Hands / feet | +12% / +10% |
| Neck / shoulders / waist | +6% / +6% / −4% |
| Lower leg | +3% longer |
| Overall | about 7.2 heads tall |

### 4.2 Shipping it

- `src/mpfb/data/targets/stylization/stylized-default.target.gz`, with a new `stylization`
  section in `data/targets/target.json`: one slider, `stylized-default`, `decr-incr` style
  but one-sided, range 0 to 1.
- Shown in the *New human* panel as **Stylization** (new property file
  `ui/new_human/newhuman/properties/phenotype_stylization.json`), stored in the `.mhm` like
  any other modifier, so a shared character round-trips.
- **Default for a new human: 1.0.** `HumanService.create_human` applies it as an ordinary
  target. Old `.mhm` files that lack the key load at 0, so they are not changed.
- Existing target loading, mirroring, `get_target_stack`, shape-key bake on export and
  `fit_clothes_to_human` need no change. The implementation checks this against
  `services/targetservice.py` (`set_target_value`, `bulk_load_targets`) and does not edit it
  unless a test fails.

### 4.3 Macro interaction (the real work in this layer)

The target is a fixed delta measured on the default adult female/male blend. On other macro
states it can over- or under-shoot.

- **Age:** scale the weight by 1 for age ≥ young, fading to 0.5 at child and 0 at baby
  (children already have large eyes and heads).
- **Gender:** the delta is authored on the default (gender 0.5). Check at 0 and 1; if the
  eyes or jaw read wrong, add a second target `stylized-default-male` and cross-fade by
  gender, as the macro targets do. Decide after the first renders.
- **Applying the fade:** do it in `HumanService`, where the stylization weight is set, not by
  adding a new macro axis to the target engine.
- **`stylized-chunky` (optional, later):** a second endpoint (about 6 heads, head +20%,
  hands and feet +25%) so the slider continues from 1.0 to 2.0. Not in Phases 1–3.

### 4.4 What this layer does not do

The surface stays HM08's. Shading (layer B) hides faceting at normal viewing distance, and
the Blender subdivision modifier MPFB2 already offers can be used for close-ups. No
re-topology is attempted: the previous attempt showed that decimation and remeshing of the
face lose the ears and mouth.

## 5. Layer B: skin and eyes

Both are **nodemodel v2** wrappers in `entities/nodemodel/v2/materials/`. The v2 framework is
already in the tree (`composites/`, `abstractgroupwrapper.py`).

Port from `master` rather than writing again: `nodewrapperstylizedskin.py`,
`nodewrapperstylizedeyes.py`, their tests, and the eye presets (`git log master --
src/mpfb/entities/nodemodel/v2/materials`). Check the ported code against this tree's
`MaterialService` and `NodeService`, and drop anything that deletes realistic code.

### 5.1 `STYLIZED` skin

One Principled BSDF, exportable to glTF/FBX. Group inputs:

| Input | Default | Notes |
|---|---|---|
| `SkinTone` | sRGB (0.80, 0.60, 0.48) | Plus 12 swatches in `data/settings/skin_tones.json`. |
| `BloodMap` | `data/textures/sty_bloodmap.png` (1024²) | Painted mask of warm areas: cheeks, nose tip, ears, lips, knuckles, elbows, knees, palms, soles. Painted in HM08's existing UV layout. |
| `BloodTint` | (0.85, 0.35, 0.30), strength 0.25 | Mixed into `SkinTone` through `BloodMap`. Replaces SSS for the warm look. |
| `CavityMap` | AO baked from the HM08 base mesh | Multiplied in at 0.4, tinted toward `BloodTint`, so folds read warm and not grey. |
| `Gradient` | −12% head to feet | Object-space gradient, keeps attention on the face. |
| Roughness | 0.55 (face 0.50, lips 0.40) | Painted mask; range 0.4–0.6. |
| Specular IOR Level | 0.35 | Takes the plastic edge off. |
| Subsurface Weight | 0.05, may be 0 | Radius (1.0, 0.35, 0.2) × 0.5 cm. |
| Normal | none | No micro-normal, no pore noise (R1). |
| `Makeup` | optional decal slot | Lip, liner and blush. |

HM08's UVs and its `mpfb_*` region textures are untouched; the stylized material simply does
not read them. `MaterialService.identify_material` recognises it by the `BloodTint` input.

**Export:** bake `BloodMap`, `CavityMap`, `Gradient` and `SkinTone` into one 2048² albedo so a
game engine gets plain PBR maps, reusing the bake plumbing in `services/hairbakeservice.py`.
Needed for Fortnite/Overwatch-style delivery, so it is Phase 3, not optional.

### 5.2 `STYLIZED_EYES`

- **Sclera:** flat (0.92, 0.90, 0.88), a soft darker edge, no veins.
- **Iris:** two-colour radial gradient `IrisInner` → `IrisOuter`, dark limbal ring at 15% width,
  pupil radius 0.35 of the iris; the iris fills about 55% of the visible opening.
- **Catchlight:** painted elliptical highlight at the upper outer side, emission 1.5, so it
  reads the same under any light.
- **Shell:** Roughness 0.05, Coat 0.5, one opaque mesh. No transmission shell, no alpha blend.

Eye *size* comes from layer A (the target scales the eye helpers, and the eyeball `.mhclo`
fits to them). Nothing in the eye asset changes. Presets follow the existing
`ui/presets/eyesettings` pattern.

### 5.3 Wiring and defaults

- Add `STYLIZED` to the skin types and `STYLIZED_EYES` to the eye materials in
  `MaterialService` and the New human panel. **Existing types stay.**
- **New-human default becomes `STYLIZED` skin and `STYLIZED_EYES`.** Characters created
  before the change, and `.mhm` files that name a skin type, keep what they name.
- A one-click "Make stylized" operator on an existing character sets stylization 1.0, the
  stylized skin and the stylized eyes together, so R2 holds by construction.
- Teeth, tongue and the stock eyebrows/eyelashes: recoloured by presets (flat white teeth,
  tongue tinted to `BloodTint`, solid-colour brows). **No new meshes.**

### 5.4 Studio lighting (optional)

A "Stylized studio" operator: key light, cool fill, strong rim, gradient world. For look
development only; it exists on `master` as commit `54a821ec` and may be ported as is.

## 6. Layer C: hair (optional)

Only after A and B are signed off.

- Extend `services/haircardservice.py` with a `CLUMP` `CARDS_MODE`: guide curves grouped by the
  existing CLUSTER_BOX PCA code, each clump a closed tapered tube (6 sides at the root, 3 at
  the tip, 2:1 flattened), `max_tris` input, no alpha. On `master`: commit `6149243f`.
- Hair shader `nodewrapperstylizedhair.py`: root-to-tip gradient, one anisotropic sheen band,
  roughness 0.45, no alpha. On `master`: commit `64a63bf3`.
- Existing alpha-card modes stay. `CLUMP` becomes the default only if the user says so.

## 7. Acceptance

A character at defaults, in Cycles and in EEVEE, with stylization 1.0:

1. Passes R1–R4 by inspection against the comparison sheets from `render_blockout.py`.
2. Head-to-height ratio between 0.135 and 0.15.
3. At stylization 0 and the old skin the output equals the unmodified add-on's: same vertex
   positions to 1e-6, same material type.
4. Clothes, hair, eyes, teeth and the default rig fit and pose with no new clipping at
   stylization 0, 0.5 and 1.0.
5. Export to glTF gives only plain PBR (no custom nodes), one albedo per body.
6. The user signs off the lookdev render (Phases 1 and 3). Images are made with the sandbox
   tier (`claude-sandbox`), never the live desktop.

## 8. Tests

The existing harness is kept (`test/execute_tests_headless.bash`).

| Test | Asserts |
|---|---|
| `ccc_data/targets_test.py` | `stylized-default` indices are all below 19,159; every `target.json` entry has a file and the reverse. |
| `bbb_services/humanservice_test.py` | New human at defaults has stylization 1.0 and head/height 0.135–0.15; with it at 0 vertex positions equal the plain add-on's (1e-6); an `.mhm` without the key loads at 0. |
| `bbb_services/humanservice_test.py` (age) | Weight fades 1 → 0.5 → 0 across young, child, baby. |
| `ddd_entities/nodemodel/v2/*` | One test per new wrapper (skin, eyes), as for the existing ones. |
| `bbb_services/materialservice_test.py` | `STYLIZED` is creatable and `identify_material` recognises it; the other skin types still work. |
| `bbb_services/exportservice_test.py` | A stylized character exports with an albedo bake and no custom nodes. |
| `tools/hm08` | `make_stylized_default.py` reproduces the committed target byte for byte. |

No existing test is deleted, since no code is removed.

## 9. Phases

| Phase | Work | Done when |
|---|---|---|
| 1 | Port `tools/hm08/`; ship the target and the `stylization` slider (§4.1–4.2); default 1.0 | `targets_test`, `humanservice_test` pass; renders at gender 0, 0.5, 1 and age young/child approved by the user |
| 2 | Age and gender handling (§4.3) | Renders and fit checks across the macro corners show no over-shoot |
| 3 | Port the `STYLIZED` skin and eyes; wiring, defaults, "Make stylized", teeth/tongue/brow recolour; albedo bake (§5) | `materialservice_test`, wrapper tests and `exportservice_test` pass; the user signs off a lookdev render |
| 4 | Optional: hair `CLUMP` mode and shader (§6); studio lighting (§5.4) | `haircardservice_test` passes |
| 5 | Optional: `stylized-chunky` endpoint | A 6-head character fits clothes |

Phase 1 produces a visible result within the first commit, unlike the old plan.

## 10. Risks

- **Fixed delta on varied bodies.** The target is authored on the default. §4.3 handles age
  and gender; a body with extreme proportions may need a hand-tuned second target. The
  slider can always be lowered.
- **Realistic detail left in the mesh.** HM08 keeps ears, lips and nostrils in higher density
  than a stylized mesh would. The target smooths them and the material hides the rest. If
  Phase 3 renders still show it, try more low-pass in the
  script first, and consider a new mesh only if that fails.
- **Clothes made for realistic bodies** are fitted to the stylized shape by the existing
  fitting, so they follow; very tight asset collars may clip at the neck (+6%). Checked in
  acceptance 4.
- **Realistic assets on a stylized body** (photo-textured clothes, realistic hair) break R3.
  Documented in the panel; not fixed here.
- **Not a game-ready mesh.** Triangle count and LODs are untouched by design. If a hard
  triangle budget returns as a requirement, it is a separate spec with its own mesh decision.
