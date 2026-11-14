"""The bundled targets: target.json and the files under data/targets agree."""
import json, os, re
from .. import LocationService

# Directories under data/targets that target.json does not list on purpose: the macro targets are driven by
# the phenotype sliders, the expression targets by the face units, and _images holds the slider icons.
_UNLISTED_DIRS = {"macrodetails", "expression", "_images"}

# The breast section also holds the cup size / firmness macro targets, which the phenotype sliders drive
# (TargetService.reapply_macro_details) rather than a target.json category.
_BREAST_MACRO = re.compile(r"^(female|male)-(baby|child|young|old)-(min|average|max)muscle-(min|average|max)weight-"
                           r"(min|average|max)cup-(min|average|max)firmness$")


def _targets_dir():
    return LocationService.get_mpfb_data("targets")


def _sections():
    with open(os.path.join(_targets_dir(), "target.json"), "r") as json_file:
        return json.load(json_file)


def _named_targets(sections):
    named = set()
    for section_name, section in sections.items():
        for category in section["categories"]:
            for target in category["targets"]:
                named.add((section_name, target))
            for target in category.get("opposites", {}).values():
                if target:
                    named.add((section_name, target))
    return named


def test_every_target_json_entry_has_a_file():
    """Each target a target.json category names exists as <section>/<name>.target.gz"""
    missing = [(section, name) for section, name in sorted(_named_targets(_sections()))
               if not os.path.isfile(os.path.join(_targets_dir(), section, name + ".target.gz"))]
    assert not missing, "target.json names targets without a file: " + str(missing[:10])


def test_every_target_file_has_a_target_json_entry():
    """Each target file in a section directory is named by target.json, and every directory is a section"""
    sections = _sections()
    named = _named_targets(sections)
    targets_dir = _targets_dir()
    dirs = {entry for entry in os.listdir(targets_dir) if os.path.isdir(os.path.join(targets_dir, entry))}
    unlisted = sorted(dirs - set(sections.keys()) - _UNLISTED_DIRS)
    assert not unlisted, "target directories without a target.json section: " + str(unlisted)
    orphans = []
    for section_name in sections.keys():
        section_dir = os.path.join(targets_dir, section_name)
        if not os.path.isdir(section_dir):
            continue
        for filename in os.listdir(section_dir):
            if not filename.endswith(".target.gz"):
                continue
            name = filename[:-len(".target.gz")]
            if section_name == "breast" and _BREAST_MACRO.match(name):
                continue
            if (section_name, name) not in named:
                orphans.append((section_name, name))
    assert not orphans, "target files without a target.json entry: " + str(sorted(orphans)[:10])

