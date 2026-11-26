"""ROS 2 publishing - driven entirely by the pre-baked `ROS` variant, no script.

Each DepthVista asset ships a `ROS = {Disabled, Enabled}` variant whose Enabled
selection payloads ready-made graphs (namespaces + TF + IMU) from
``assets/configurations/DEPTHVISTA_HELIX_*_ROS.usd``.  Publishing is just selecting
that variant on the chosen units and pressing Play - no runtime graph building.

Camera discovery lives in ``discovery``; the browser preview in ``web_viewer``.
The offline generator of the baked graphs (``ros2/*.py``) is a build-time tool and
is never imported here.
"""
import carb
from pxr import Sdf, Usd

from . import discovery, web_viewer

_CAM_GRAPH = {"highres": "ROS2Camera_CAM_HIGHRES", "longrange": "ROS2Camera_CAM_LONGRANGE"}
_BASE_NS = "Helix_iToF"                           # head namespace base
_TF_NODE = "ToF_Camera/ROS2TFGraph/ComputeTF"     # baked TF tree node (ROS variant)
_web = None


def _frame_name(prim):
    a = prim.GetAttribute("isaac:nameOverride")
    return (a.Get() if a and a.Get() else prim.GetName())


def _parent_frame_prim(unit_prim, frame):
    """The prim published as `frame`: the nearest prim above the unit with that frame
    name (for example a robot's base_link), else the unit's own root prim, which is
    then published under that name."""
    q = unit_prim.GetParent()
    while q and q.IsValid() and not q.IsPseudoRoot():
        if _frame_name(q) == frame:
            return q
        q = q.GetParent()
    (unit_prim.GetAttribute("isaac:nameOverride")
     or unit_prim.CreateAttribute("isaac:nameOverride", Sdf.ValueTypeNames.String)).Set(frame)
    return unit_prim


def set_tf_parent_frame(unit_paths=None, frame="world"):
    """Set the parent TF frame of each selected unit's frame. 'world' (default) keeps
    the unit a child of world; any other name makes it a child of that frame (see
    _parent_frame_prim). Runs after start(), once the TF graph exists. Returns the
    number of units updated."""
    frame = (frame or "world").strip() or "world"
    n = 0
    for p, _ in _selected(unit_paths):
        node = p.GetStage().GetPrimAtPath(p.GetPath().AppendPath(_TF_NODE))
        if not (node and node.IsValid()):
            continue
        rel = node.GetRelationship("inputs:parentPrim") or node.CreateRelationship("inputs:parentPrim")
        rel.SetTargets([] if frame == "world" else [_parent_frame_prim(p, frame).GetPath()])
        n += 1
    if n:
        carb.log_info(f"[econ.itof.ros] TF parent frame '{frame}' on {n} unit(s)")
    return n


def _apply_namespace(unit_prim, index):
    """Author a DETERMINISTIC per-unit head namespace on ToF_Camera: unit 0 ->
    'Helix_iToF', unit 1 -> 'Helix_iToF_01', ...  This overrides the baked token so
    multiple cameras get distinct topics/frames instead of relying on the bridge's
    (order-dependent) auto-dedup."""
    tof = unit_prim.GetStage().GetPrimAtPath(
        unit_prim.GetPath().AppendChild("ToF_Camera"))
    if not (tof and tof.IsValid()):
        return
    ns = _BASE_NS if index == 0 else f"{_BASE_NS}_{index:02d}"
    a = (tof.GetAttribute("isaac:namespace")
         or tof.CreateAttribute("isaac:namespace", Sdf.ValueTypeNames.String))
    a.Set(ns)
    # The unit's frame gets the same name as its namespace, on the TF frame prim and on
    # every publisher's frame_id, so several units never share one frame name.
    frame = tof.GetPrimAtPath("CameraFrame/optical_frame")
    if frame and frame.IsValid():
        (frame.GetAttribute("isaac:nameOverride")
         or frame.CreateAttribute("isaac:nameOverride", Sdf.ValueTypeNames.String)).Set(ns)
    for root in (unit_prim, tof):
        for p in Usd.PrimRange(root.GetPrimAtPath("Graphs") if root is unit_prim else root):
            fid = p.GetAttribute("inputs:frameId")
            if fid and fid.Get():
                fid.Set(ns)


def stop_timeline():
    """Stop playback before recomposing the stage (a variant toggle mid-play
    invalidates PhysX simulation views -> error spam).  Returns True if it was
    playing (so the caller can wait a couple frames for views to be released)."""
    try:
        import omni.timeline
        tl = omni.timeline.get_timeline_interface()
        if tl.is_playing():
            tl.stop()
            return True
    except Exception:
        pass
    return False


def _apply_domain(stage, domain):
    for p in stage.Traverse():
        nt = p.GetAttribute("node:type")
        if nt and nt.Get() == "isaacsim.ros2.bridge.ROS2Context":
            a = p.GetAttribute("inputs:domain_id")
            if a:
                a.Set(int(domain))


def _select_cameras(unit_prim, keys):
    """Keep the chosen cameras' graphs active under one unit, deactivate the rest.
    A chosen graph only has its 'active' opinion cleared, so it composes as baked."""
    stage = unit_prim.GetStage()
    for key, gname in _CAM_GRAPH.items():
        g = stage.GetPrimAtPath(unit_prim.GetPath().AppendChild("Graphs").AppendChild(gname))
        if g and g.IsValid():
            if key in set(keys):
                g.ClearActive()
            else:
                g.SetActive(False)


def _selected(unit_paths):
    units = discovery.ros_units()
    if unit_paths:
        want = set(unit_paths)
        units = [(p, t) for p, t in units if str(p.GetPath()) in want]
    return units


def start(unit_paths=None, camera_keys=("highres", "longrange"), domain=0):
    """Enable ROS on the selected units (all ROS-capable units if none given) by
    selecting `ROS=Enabled`, set the domain, and activate only the chosen cameras.
    Returns the number of units switched on."""
    # global index (position in the full sorted unit list) -> stable per-unit suffix,
    # so a given camera always gets the same namespace regardless of what's selected.
    order = {str(p.GetPath()): i for i, (p, _) in enumerate(discovery.ros_units())}
    units = _selected(unit_paths)
    if not units:
        return 0
    stage = units[0][0].GetStage()
    for p, _ in units:
        p.GetVariantSets().GetVariantSet(discovery.VSET).SetVariantSelection("Enabled")
        p.Load()                     # compose the newly-added ROS payload (graphs)
    for p, _ in units:               # after Load so ToF_Camera + graphs exist
        _apply_namespace(p, order.get(str(p.GetPath()), 0))
        _select_cameras(p, camera_keys)
    _apply_domain(stage, domain)
    carb.log_info(f"[econ.itof.ros] ROS=Enabled on {len(units)} unit(s), domain {domain}")
    return len(units)


def diagnostics():
    """(#DepthVista prims, #with-ROS-variant, #OmniGraphs composed) - for the status
    line so a failure is legible: 0 with-ROS-variant => stale asset (rebuild); graphs
    composed but no topics => just press Play (Stop then Play if already running)."""
    stg = discovery.stage()
    if stg is None:
        return (0, 0, 0)
    ng = sum(1 for p in stg.Traverse() if p.GetTypeName() == "OmniGraph")
    return (len(discovery.find_units(stg)), len(discovery.ros_units(stg)), ng)


def stop(unit_paths=None):
    """Disable ROS on the selected units and stop the web viewer."""
    stop_web_viewer()
    units = _selected(unit_paths)
    for p, _ in units:
        _select_cameras(p, _CAM_GRAPH)       # clear camera selection: the next Enable composes fresh graphs
        p.GetVariantSets().GetVariantSet(discovery.VSET).SetVariantSelection("Disabled")
    return len(units)


# browser preview (independent of the ROS graphs)
def _viewer_units(unit_paths, camera_keys):
    out = []
    units = _selected(unit_paths) or discovery.find_units()
    multi = len(units) > 1
    for i, (prim, tag) in enumerate(units):
        base = f"cam{i}" if multi else "cam"
        cams = {}
        for key in camera_keys:
            cp = discovery.find_camera(prim, key)
            if cp:
                cams[key] = dict(path=cp, params=discovery.cam_params(cp, key))
        if cams:
            out.append(dict(unit_id=f"{base}_{tag}" if tag else base, cams=cams))
    return out


def web_viewer_url():
    return f"http://localhost:{web_viewer.PORT}/"


def start_web_viewer(unit_paths=None, camera_keys=("highres", "longrange")):
    """Start the localhost depth/point-cloud preview for the selected cameras."""
    global _web
    units = _viewer_units(unit_paths, camera_keys)
    if not units:
        return False
    try:
        stop_web_viewer()
        _web = web_viewer.WebViewer(units)
        return True
    except Exception as exc:
        carb.log_error(f"[econ.itof.ros] web viewer failed: {exc}")
        _web = None
        return False


def stop_web_viewer():
    global _web
    if _web is not None:
        try:
            _web.destroy()
        except Exception:
            pass
        _web = None
