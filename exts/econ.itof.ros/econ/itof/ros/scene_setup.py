"""Drop a DepthVista Helix iToF camera-on-a-stand test rig into the stage.

The rig has THREE components (as in the original over-pallet stand):
  * Stand    - the vertical mount (Isaac stand prop),
  * Arm      - a horizontal cylinder reaching out from the stand,
  * Camera   - the DepthVista unit, hung at the end of the arm looking down.
All grouped under a movable Xform at the world origin (/World/Econ_iToF_Rig) so you
can grab it and place/aim the whole assembly anywhere.  Idempotent.
"""
import os

import carb
import omni.usd
from pxr import Usd, UsdGeom, Gf

ASSET_USD = "DEPTHVISTA_HELIX_GMSL.usd"
STAND_USD = ("https://omniverse-content-production.s3-us-west-2.amazonaws.com"
             "/Assets/Isaac/5.1/Isaac/Props/Mounts/Stand/stand_instanceable.usd")
RIG = "/World/Econ_iToF_Rig"          # movable group - reposition/aim the whole rig

# Component layout, local to RIG (metres) - EXACT original geometry (see
# examples/example1): the stand's mount sits at z=1.88 with the prop scaled to reach
# the floor, a horizontal arm spans from the stand (x=1.2) toward x=0, and the camera
# hangs at the arm's far end (x=0) looking straight down.
STAND = {"translate": (1.2, 0.0, 1.88193), "rotate": (0.0, 0.0, 0.0),  "scale": (1.2, 1.2, 3.66786)}
ARM   = {"translate": (0.6, 0.0, 1.88),    "rotate": (0.0, 90.0, 0.0), "scale": (0.0282, 0.07185, 1.3)}
# camera mounts at the ARM's far end (x~0), at arm height, looking straight down -
# same frame as stand+arm (the original camera lived under a different parent, hence
# the earlier misalignment).
CAM   = {"translate": (0.0, 0.0, 1.87),    "rotate": (-90.0, 0.0, 0.0)}


def _unit_scale(stage, asset_path):
    stage_mpu = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
    asset_mpu = UsdGeom.GetStageMetersPerUnit(Usd.Stage.Open(asset_path)) or 1.0
    return asset_mpu / stage_mpu


def _set_trs(prim, translate, rotate, scale):
    d = UsdGeom.XformOp.PrecisionDouble
    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    xf.AddTranslateOp(precision=d).Set(Gf.Vec3d(*translate))
    xf.AddRotateXYZOp(precision=d).Set(Gf.Vec3d(*rotate))
    xf.AddScaleOp(precision=d).Set(Gf.Vec3d(*scale))


def _mesh_cylinder(stage, path):
    try:
        import omni.kit.commands
        omni.kit.commands.execute("CreateMeshPrimWithDefaultXform",
                                  prim_type="Cylinder", prim_path=path,
                                  select_new_prim=False)
        prim = stage.GetPrimAtPath(path)
        if prim and prim.IsValid():
            return prim
    except Exception as exc:
        carb.log_warn(f"[econ.itof.ros] mesh-cylinder command failed ({exc})")
    return UsdGeom.Cylinder.Define(stage, path).GetPrim()


def place_camera_stand(asset_dir):
    """Add the 3-component camera-on-a-stand rig at the world origin.  Returns the
    number of prims added (0 on failure).  Grab /World/Econ_iToF_Rig to move it."""
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        carb.log_warn("[econ.itof.ros] no stage open")
        return 0
    asset = os.path.join(asset_dir, ASSET_USD)
    if not os.path.isfile(asset):
        carb.log_error(f"[econ.itof.ros] asset not found: {asset}")
        return 0
    asset = asset.replace(os.sep, "/")

    if stage.GetPrimAtPath(RIG).IsValid():            # idempotent - rebuild
        stage.RemovePrim(RIG)
    if not stage.GetPrimAtPath("/World").IsValid():
        UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Xform.Define(stage, RIG)

    stand = stage.DefinePrim(f"{RIG}/Stand", "Xform")
    stand.GetReferences().AddReference(STAND_USD)
    _set_trs(stand, STAND["translate"], STAND["rotate"], STAND["scale"])

    arm = _mesh_cylinder(stage, f"{RIG}/Arm")
    _set_trs(arm, ARM["translate"], ARM["rotate"], ARM["scale"])

    s = _unit_scale(stage, asset)
    cam = stage.DefinePrim(f"{RIG}/DEPTHVISTA_HELIX", "Xform")
    cam.GetReferences().AddReference(asset)
    _set_trs(cam, CAM["translate"], CAM["rotate"], (s, s, s))

    omni.usd.get_context().get_selection().set_selected_prim_paths([RIG], True)
    carb.log_info(f"[econ.itof.ros] placed 3-part camera-on-stand rig at {RIG}")
    return 3
