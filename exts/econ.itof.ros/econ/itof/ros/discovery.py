"""Self-contained discovery of DepthVista Helix iToF units + cameras in the stage.

Read-only USD queries - no dependency on the standalone ros2 script.  The extension
uses these to list units in the panel, resolve camera prims, and read intrinsics for
the viewers.
"""
import omni.usd
from pxr import Sdf, Usd, UsdGeom

# asset base-name -> short type tag (matched most-specific first)
ASSET_TYPES = {"DEPTHVISTA_HELIX_GMSL": "gmsl",
               "DEPTHVISTA_HELIX_USB": "usb",
               "DEPTHVISTA_HELIX": ""}
# key -> (camera prim name, fallback width, height, fx_px, near_m, far_m)
CAMERAS = {"highres":   ("econ_iToF_highResolution", 1280, 960, 1183.0, 0.2, 2.0),
           "longrange": ("econ_iToF_longRange",       640, 480,  591.5, 0.5, 6.0)}
VSET = "ROS"
_SKIP = ("/OmniverseKit_", "/Render/")


def stage():
    ctx = omni.usd.get_context()
    return ctx.get_stage() if ctx else None


def find_units(stg=None):
    """Every DepthVista unit prim (has a ToF_Camera child), sorted by path so the
    order (cam0, cam1, ...) is deterministic.  Returns [(prim, type_tag)]."""
    stg = stg or stage()
    if stg is None:
        return []
    names = sorted(ASSET_TYPES, key=len, reverse=True)
    out = []
    for prim in stg.Traverse():
        if not prim.GetChild("ToF_Camera").IsValid():
            continue
        nm = prim.GetName()
        for base in names:
            if nm == base or nm.startswith(base + "_"):
                out.append((prim, ASSET_TYPES[base]))
                break
    return sorted(out, key=lambda t: str(t[0].GetPath()))


def ros_units(stg=None):
    """Units that carry the baked `ROS` variant set (enable-able from the panel)."""
    return [(p, t) for p, t in find_units(stg) if VSET in p.GetVariantSets().GetNames()]


def unit_label(prim, tag):
    """Panel label: prim name + type, e.g. 'DEPTHVISTA_HELIX_01 (gmsl)'."""
    return f"{prim.GetName()}" + (f"  ({tag})" if tag else "")


def find_camera(unit_prim, key, stg=None):
    """Resolve a camera prim path within one unit's subtree for the given key."""
    stg = stg or stage()
    prim_name = CAMERAS[key][0]
    # after baking, cameras live under a resolution group: CameraFrame/<key>/<name>
    for direct in (f"{unit_prim.GetPath()}/ToF_Camera/CameraFrame/{key}/{prim_name}",
                   f"{unit_prim.GetPath()}/ToF_Camera/CameraFrame/{prim_name}"):
        if stg.GetPrimAtPath(Sdf.Path(direct)).IsValid():
            return direct
    for p in Usd.PrimRange(unit_prim):                 # scoped to the unit (names repeat)
        if (p.IsA(UsdGeom.Camera) and p.GetName() == prim_name
                and not str(p.GetPath()).startswith(_SKIP)):
            return str(p.GetPath())
    return None


def cam_params(cam_path, key, stg=None):
    """Intrinsics/clipping for one camera - authored attrs win, else fallback consts."""
    stg = stg or stage()
    _, W, H, FX, near, far = CAMERAS[key]
    prim = stg.GetPrimAtPath(cam_path) if stg else None
    if prim and prim.IsValid():
        def authored(name):
            at = prim.GetAttribute(name)
            return at.Get() if at and at.HasAuthoredValue() else None
        res = authored("info:resolution")
        if res:
            try:
                W, H = (int(x) for x in str(res).lower().split("x"))
            except Exception:
                pass
        fx = authored("info:fx_px")
        if fx is None:
            cam = UsdGeom.Camera(prim)
            fl, ha = cam.GetFocalLengthAttr().Get(), cam.GetHorizontalApertureAttr().Get()
            if fl and ha:
                fx = float(fl) * W / float(ha)
        if fx:
            FX = float(fx)
        dr = authored("isaac:depthRange")
        if dr is not None:
            near, far = float(dr[0]), float(dr[1])
    return dict(width=W, height=H, fx=FX, fy=FX, cx=W / 2.0, cy=H / 2.0,
                near_m=near, far_m=far)
