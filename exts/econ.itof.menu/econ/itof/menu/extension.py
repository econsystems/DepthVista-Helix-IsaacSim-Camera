"""econ.itof.menu — adds the e-con DepthVista Helix iToF camera asset to Isaac Sim.

Scope: the CAMERA ASSET only.  It registers
    Create > Sensors > Camera and Depth Sensors > e-con > DepthVista Helix iToF
which references the shipped DEPTHVISTA_HELIX USD into the current stage (with a
metersPerUnit-compensating scale).  Publishing / viewing / ground truth live in
the companion **econ.itof.sim** extension, which finds this extension's assets/.
"""

import gc
import os

import carb
import omni.ext
import omni.kit.app
import omni.usd
from omni.kit.menu.utils import MenuItemDescription, add_menu_items, remove_menu_items
from pxr import Usd, UsdGeom

VENDOR = "e-con"
CAMERAS = [
    {"name": "DepthVista Helix iToF", "usd": "DEPTHVISTA_HELIX_GMSL.usd", "prim": "/DEPTHVISTA_HELIX"},
]


def _sensor_glyph():
    """Path to the built-in Sensors menu icon, so the merged item keeps its glyph.
    Name-agnostic across Isaac versions: the icon-providing extension was
    isaacsim.sensors.camera.ui and moves to isaacsim.sensors.experimental.rtx.ui in
    6.0 - match any sensors UI extension that ships data/sensor.svg."""
    try:
        mgr = omni.kit.app.get_app().get_extension_manager()
        for e in mgr.get_extensions():
            name = e.get("name", "")
            if "sensors" in name and name.endswith(".ui"):
                g = os.path.join(mgr.get_extension_path(e["id"]), "data", "sensor.svg")
                if os.path.isfile(g):
                    return g
    except Exception:
        pass
    return None


class Extension(omni.ext.IExt):
    def on_startup(self, ext_id: str):
        self._asset_dir = os.path.join(
            omni.kit.app.get_app().get_extension_manager().get_extension_path(ext_id), "assets")

        leaves = [
            MenuItemDescription(
                name=cam["name"],
                onclick_fn=lambda up=os.path.join(self._asset_dir, cam["usd"]),
                                  pp=cam["prim"]: self._add_camera(up, pp))
            for cam in CAMERAS
        ]
        self._menu_items = [
            MenuItemDescription(name="Sensors", glyph=_sensor_glyph(), sub_menu=[
                MenuItemDescription(name="Camera and Depth Sensors", sub_menu=[
                    MenuItemDescription(name=VENDOR, appear_after="@first", sub_menu=leaves),
                ]),
            ]),
        ]
        add_menu_items(self._menu_items, "Create")

    def on_shutdown(self):
        if getattr(self, "_menu_items", None):
            remove_menu_items(self._menu_items, "Create")
            self._menu_items = None
        gc.collect()

    def _add_camera(self, usd_path: str, prim_prefix: str):
        """Reference the asset at the next free prim path and select it."""
        if not os.path.isfile(usd_path):
            carb.log_error(f"[econ.itof.menu] asset not found: {usd_path}")
            return
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return
        prim_path = self._next_free_path(stage, self._stage_root(stage) + prim_prefix)
        try:
            xform = stage.DefinePrim(prim_path, "Xform")
            xform.GetReferences().AddReference(usd_path.replace(os.sep, "/"))
            self._compensate_units(stage, xform, usd_path)
            omni.usd.get_context().get_selection().set_selected_prim_paths([prim_path], True)
        except Exception as exc:  # never let a click crash the menu
            carb.log_error(f"[econ.itof.menu] failed to add {usd_path}: {exc}")

    @staticmethod
    def _compensate_units(stage, xform, usd_path: str):
        """Scale the wrapper to compensate a metersPerUnit mismatch (references do
        not auto-rescale). Metre-native assets give ratio 1.0, so no scale added."""
        stage_mpu = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
        asset_mpu = UsdGeom.GetStageMetersPerUnit(Usd.Stage.Open(usd_path)) or 1.0
        ratio = asset_mpu / stage_mpu
        if abs(ratio - 1.0) < 1e-9:
            return
        UsdGeom.Xformable(xform).AddScaleOp().Set((ratio, ratio, ratio))

    @staticmethod
    def _stage_root(stage) -> str:
        """Parent under the stage default prim (like the built-in sensors), falling
        back to /World, then the pseudo-root."""
        dp = stage.GetDefaultPrim()
        if dp and dp.IsValid():
            return dp.GetPath().pathString
        if stage.GetPrimAtPath("/World").IsValid():
            return "/World"
        return ""

    @staticmethod
    def _next_free_path(stage, base: str) -> str:
        if not stage.GetPrimAtPath(base).IsValid():
            return base
        i = 1
        while stage.GetPrimAtPath(f"{base}_{i:02d}").IsValid():
            i += 1
        return f"{base}_{i:02d}"
