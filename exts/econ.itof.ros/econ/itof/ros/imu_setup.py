"""IMU controls for e-con DepthVista units.

The IMU topic (<ns>/imu) is published by the ROS variant of the asset. This module
adds what the control window offers on top of it:
  * gravity on or off in the published acceleration (IsaacReadIMU readGravity),
  * an on-screen readout of linear acceleration and angular velocity for one unit
    (or all), built at runtime as OnTick -> IsaacReadIMU -> ToString -> PrintText.
The readout graph publishes nothing, so each unit keeps exactly one IMU publisher.

Every step is guarded so a missing node type or a headless build never affects
publishing; the functions return a count and a status string.
"""
import carb
import omni.kit.app
import omni.usd

try:
    import omni.graph.core as og
except Exception:                       # headless / graph ext not loaded
    og = None

from . import discovery

_GRAPH_NAME      = "EconImuGraph"       # per-unit readout graph prim (under ToF_Camera)
_ROS_READ_IMU    = "ToF_Camera/CameraFrame/ROS2ImuGraph_CAM/ReadIMU"   # ROS variant IMU reader
_gravity = {}                           # unit path -> readGravity chosen in the window
_TOSTRING_TYPE   = "omni.graph.nodes.ToString"
_PRINTTEXT_TYPES = ("omni.graph.ui_nodes.PrintText", "omni.graph.nodes.PrintText")
_TOSTRING_OUTS   = ("outputs:converted", "outputs:string", "outputs:value", "outputs:output")


def _stage():
    return omni.usd.get_context().get_stage()


def _find_imu(stage, unit_root):
    """Locate the IsmImuSensor prim under a unit (build-layout agnostic)."""
    for c in (f"{unit_root}/ToF_Camera/IMU/ImuBody/IsmImuSensor",
              f"{unit_root}/ToF_Camera/IMU/IsmImuSensor"):
        if stage.GetPrimAtPath(c).IsValid():
            return c
    for prim in stage.Traverse():
        if prim.GetName() == "IsmImuSensor" and str(prim.GetPath()).startswith(unit_root):
            return str(prim.GetPath())
    return None


def _graph_path(unit_root):
    return f"{unit_root}/ToF_Camera/{_GRAPH_NAME}"


def _units(unit_paths):
    """[(prim, deterministic_index)] for the selected ROS units (index -> namespace)."""
    order = {str(p.GetPath()): i for i, (p, _) in enumerate(discovery.ros_units())}
    rows = discovery.ros_units()
    if unit_paths:
        want = set(unit_paths)
        rows = [(p, t) for p, t in rows if str(p.GetPath()) in want]
    return [(p, order.get(str(p.GetPath()), 0)) for p, _ in rows]


def _og_edit(graph_path, spec, label):
    stage = _stage()
    if stage.GetPrimAtPath(graph_path).IsValid():
        stage.RemovePrim(graph_path)
        omni.kit.app.get_app().update()
    try:
        og.Controller.edit({"graph_path": graph_path, "evaluator_name": "execution"}, spec)
        return True
    except Exception as exc:
        carb.log_warn(f"[econ.itof.ros] IMU graph '{label}' failed: {exc}")
        return False


def _add_readout(graph_path, show, linear, angular):
    """Attach ToString -> PrintText for angVel + linAcc (best-effort, fully guarded)."""
    if og is None:
        return
    try:
        mgr = omni.kit.app.get_app().get_extension_manager()
        for ext in ("omni.graph.ui_nodes", "omni.graph.nodes"):
            if not mgr.is_extension_enabled(ext):
                mgr.set_extension_enabled_immediate(ext, True)
    except Exception:
        pass
    stage = _stage()

    def remove(*names):
        for name in names:
            try:
                stage.RemovePrim(f"{graph_path}/{name}")
            except Exception:
                pass

    def connect(src, dst):
        try:
            og.Controller.connect(f"{graph_path}/{src}", f"{graph_path}/{dst}")
            return True
        except Exception:
            return False

    print_type = None
    for candidate in _PRINTTEXT_TYPES:
        try:
            og.Controller.edit(graph_path, {og.Controller.Keys.CREATE_NODES: [
                ("ToStrAng", _TOSTRING_TYPE), ("ToStrLin", _TOSTRING_TYPE),
                ("PrintAng", candidate), ("PrintLin", candidate)]})
            print_type = candidate
            break
        except Exception:
            remove("ToStrAng", "ToStrLin", "PrintAng", "PrintLin")
    if print_type is None:
        carb.log_info("[econ.itof.ros] IMU readout skipped (no PrintText node type)")
        return
    connect("ReadIMU.outputs:angVel", "ToStrAng.inputs:value")
    connect("ReadIMU.outputs:linAcc", "ToStrLin.inputs:value")
    connect("ReadIMU.outputs:execOut", "PrintAng.inputs:execIn")
    connect("ReadIMU.outputs:execOut", "PrintLin.inputs:execIn")
    for node, on in (("PrintAng", show and angular), ("PrintLin", show and linear)):
        try:
            og.Controller.attribute(f"{graph_path}/{node}.inputs:toScreen").set(bool(on))
        except Exception:
            pass
    for tostr, prnt in (("ToStrAng", "PrintAng"), ("ToStrLin", "PrintLin")):
        for out in _TOSTRING_OUTS:
            if connect(f"{tostr}.{out}", f"{prnt}.inputs:text"):
                break


def apply_gravity(unit_paths=None):
    """Set readGravity on the ROS variant IMU reader of each unit that has a choice
    stored by setup_imu(). Called after Enable ROS, since that graph exists only then.
    Returns the number of units updated."""
    stage = _stage()
    n = 0
    for prim, _idx in _units(unit_paths):
        root = str(prim.GetPath())
        if root not in _gravity:
            continue
        node = stage.GetPrimAtPath(f"{root}/{_ROS_READ_IMU}")
        if node and node.IsValid():
            a = node.GetAttribute("inputs:readGravity")
            if a:
                a.Set(bool(_gravity[root]))
                n += 1
    return n


def setup_imu(unit_paths=None, gravity=True, linear_to_screen=True,
              angular_to_screen=False, print_index=0, domain=0):
    """Apply the gravity choice to each selected unit's IMU topic and build the
    on-screen readout on the unit(s) chosen by print_index. Returns (count, status).

    print_index: unit index that shows the readout (-1 = all units).
    domain: kept for API compatibility; the readout publishes nothing.
    """
    if og is None:
        return 0, "omni.graph.core unavailable (headless?)"
    stage = _stage()
    made = 0
    missing = []
    for prim, idx in _units(unit_paths):
        root = str(prim.GetPath())
        imu = _find_imu(stage, root)
        if not imu:
            missing.append(root.split("/")[-1])
            continue
        _gravity[root] = bool(gravity)
        gp = _graph_path(root)
        show = (print_index == idx) or (print_index < 0)
        if not (show and (linear_to_screen or angular_to_screen)):
            if stage.GetPrimAtPath(gp).IsValid():
                stage.RemovePrim(gp)
            made += 1
            continue
        ok = _og_edit(gp, {
            og.Controller.Keys.CREATE_NODES: [
                ("OnTick",  "omni.graph.action.OnPlaybackTick"),
                ("ReadIMU", "isaacsim.sensors.physics.IsaacReadIMU"),
            ],
            og.Controller.Keys.CONNECT: [
                ("OnTick.outputs:tick", "ReadIMU.inputs:execIn"),
            ],
            og.Controller.Keys.SET_VALUES: [
                ("ReadIMU.inputs:imuPrim",     [imu]),
                ("ReadIMU.inputs:readGravity", bool(gravity)),
            ],
        }, root)
        if ok:
            made += 1
            _add_readout(gp, True, bool(linear_to_screen), bool(angular_to_screen))
    applied = apply_gravity(unit_paths)
    note = "" if not missing else f"; no IMU on: {', '.join(missing)}"
    if made:
        g = "on" if gravity else "off"
        topic = ("applied to the IMU topic" if applied
                 else "applied to the IMU topic on Enable ROS + Publish")
        return made, f"IMU set on {made} unit(s): gravity {g}, {topic}{note}. Press Play."
    return 0, f"No IMU sensor found{note}"


def clear_imu(unit_paths=None):
    """Remove the on-screen IMU readout graphs. Returns count removed."""
    stage = _stage()
    n = 0
    for prim, idx in _units(unit_paths):
        gp = _graph_path(str(prim.GetPath()))
        if stage.GetPrimAtPath(gp).IsValid():
            try:
                stage.RemovePrim(gp)
                n += 1
            except Exception:
                pass
    return n
