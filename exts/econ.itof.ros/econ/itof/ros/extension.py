"""econ.itof.ros - the e-con DepthVista Helix iToF control extension for Isaac Sim.

A self-contained control window (menu: 'e-con iToF') for:
  * one-tap ROS 2 publishing - by selecting the pre-baked `ROS` variant on the
    DepthVista units you pick (no runtime graph building, no external script),
  * the localhost browser depth/point-cloud preview,
  * an in-Isaac ground-truth depth viewer + scene projection,
  * a one-click camera-on-a-stand test rig.

The DepthVista camera USD is provided by the companion **econ.itof.menu** extension
(Create > Sensors > e-con); this extension locates that asset via the extension
manager, so the two stay cleanly separated:

    econ.itof.menu  ->  add the camera asset (Create menu)
    econ.itof.ros   ->  publish / view / ground truth (this window)
"""
import gc
import os

import carb
import omni.ext
import omni.kit.app
import omni.ui as ui
from omni.kit.menu.utils import MenuItemDescription, add_menu_items, remove_menu_items

from . import discovery, publisher, scene_setup
from .viewer_gt import ViewerGT
from .window import ItofWindow

ASSET_PROVIDER = "econ.itof.menu"     # companion extension that ships the camera USD
MENU_ROOT = "e-con iToF"


class Extension(omni.ext.IExt):
    # lifecycle
    def on_startup(self, ext_id: str):
        self._ext_root = omni.kit.app.get_app().get_extension_manager().get_extension_path(ext_id)
        self._window = None
        self._viewer = ViewerGT()

        self._menu = [
            MenuItemDescription(name="Control Window", onclick_fn=self._toggle_window),
            MenuItemDescription(name="Enable ROS + Publish", onclick_fn=self.start_publishing),
            MenuItemDescription(name="Disable ROS", onclick_fn=self.stop_publishing),
            MenuItemDescription(name="Open Web Viewer", onclick_fn=self.open_web_viewer),
            MenuItemDescription(name="Open Depth Viewer (GT)", onclick_fn=self.open_image_viewer),
            MenuItemDescription(name="Place Camera on Stand", onclick_fn=self.place_camera_stand),
        ]
        add_menu_items(self._menu, MENU_ROOT)
        self._show_window()

    def on_shutdown(self):
        try:
            publisher.stop_web_viewer()
        except Exception:
            pass
        if getattr(self, "_menu", None):
            remove_menu_items(self._menu, MENU_ROOT)
            self._menu = None
        if getattr(self, "_viewer", None) is not None:
            try:
                self._viewer.destroy()
            except Exception:
                pass
            self._viewer = None
        if self._window is not None:
            self._window.destroy()
            self._window = None
        gc.collect()

    # window (docked next to the Property panel, like the ZED panel)
    def _show_window(self):
        if self._window is None:
            self._window = ItofWindow(self)
            self._window.deferred_dock_in("Property", ui.DockPolicy.TARGET_WINDOW_IS_ACTIVE)
        self._window.visible = True

    def _toggle_window(self):
        if self._window is None:
            self._show_window()
        else:
            self._window.visible = not self._window.visible

    def _status(self, text, ok=True):
        carb.log_info(f"[econ.itof.ros] {text}")
        if self._window is not None:
            self._window.set_status(text, ok)

    # asset dir (from the companion econ.itof.menu extension)
    def _asset_dir(self):
        mgr = omni.kit.app.get_app().get_extension_manager()
        for e in mgr.get_extensions():
            if e.get("name") == ASSET_PROVIDER:
                d = os.path.join(mgr.get_extension_path(e["id"]), "assets")
                if os.path.isdir(d):
                    return d
        local = os.path.join(self._ext_root, "assets")
        return local if os.path.isdir(local) else None

    # unit list for the panel
    def list_units(self):
        """[(prim_path, label)] for every DepthVista unit that has a ROS variant.
        Single unit -> just its prim name; multiple -> the path with the common parent
        stripped, so only the distinguishing part shows (e.g. 'DEPTHVISTA_HELIX' vs
        'Econ_iToF_Rig/DEPTHVISTA_HELIX')."""
        paths = [str(p.GetPath()) for p, _ in discovery.ros_units()]
        if not paths:
            return []
        if len(paths) == 1:
            return [(paths[0], paths[0].split("/")[-1])]
        common = os.path.commonpath(paths)
        return [(p, (p[len(common):].lstrip("/") or p.split("/")[-1])) for p in paths]

    # publishing (select the baked ROS variant on the chosen units)
    async def _settle(self):
        """Stop playback and let PhysX release its simulation views (a couple update
        frames) BEFORE recomposing the stage - otherwise the variant toggle
        invalidates live views and spams '[omni.physx.tensors] ... invalidated'."""
        if publisher.stop_timeline():
            app = omni.kit.app.get_app()
            for _ in range(3):
                await app.next_update_async()

    def start_publishing(self, web_viewer: bool = True, domain: int = 0,
                         unit_paths=None, camera_keys=("highres", "longrange")):
        import asyncio
        asyncio.ensure_future(self._start_async(bool(web_viewer), int(domain),
                                                unit_paths, tuple(camera_keys)))

    async def _start_async(self, web_viewer, domain, unit_paths, camera_keys):
        await self._settle()
        n = publisher.start(unit_paths=unit_paths, camera_keys=camera_keys, domain=domain)
        allu, rosu, ng = publisher.diagnostics()
        if not n:
            if allu and not rosu:
                self._status(f"{allu} DepthVista prim(s) found but none has a ROS "
                             "variant - rebuild the asset (bake_ros_variant.py + build.sh).",
                             False)
            else:
                self._status("No DepthVista unit found (add one via econ.itof.menu, "
                             "then Refresh).", False)
            return
        if web_viewer and publisher.start_web_viewer(unit_paths=unit_paths,
                                                     camera_keys=camera_keys):
            if self._window is not None:
                self._window.show_web_url(publisher.web_viewer_url())
        if self._window is not None:
            self._window.set_ros_active(True)
        self._status(f"ROS on {n} unit(s), {ng} graph(s) composed - press Play to publish.")

    def stop_publishing(self, unit_paths=None):
        import asyncio
        asyncio.ensure_future(self._stop_async(unit_paths))

    async def _stop_async(self, unit_paths):
        await self._settle()
        n = publisher.stop(unit_paths=unit_paths)
        if self._window is not None:
            self._window.set_ros_active(False)
        self._status(f"ROS disabled on {n} unit(s)." if n else "Nothing to stop.", bool(n))

    # scene setup
    def place_camera_stand(self):
        adir = self._asset_dir()
        if not adir:
            self._status("Camera asset not found - enable econ.itof.menu.", False)
            return
        n = scene_setup.place_camera_stand(adir)
        self._status("Placed camera-on-stand rig (grab /World/Econ_iToF_Rig to move it)."
                     if n else "Could not place rig (see console).", bool(n))

    # viewers (Replicator GT - independent of ROS)
    def _camera_paths(self, unit_paths, camera_keys):
        units = discovery.find_units()
        if unit_paths:
            want = set(unit_paths)
            units = [(p, t) for p, t in units if str(p.GetPath()) in want]
        paths = []
        for prim, _ in units:
            for key in camera_keys:
                cp = discovery.find_camera(prim, key)
                if cp:
                    paths.append(cp)
        return paths

    def open_web_viewer(self, unit_paths=None, camera_keys=("highres", "longrange")):
        ok = publisher.start_web_viewer(unit_paths=unit_paths, camera_keys=tuple(camera_keys))
        if not ok:
            self._status("Web viewer failed - no camera found "
                         "(add one via econ.itof.menu, then Refresh).", False)
            return
        url = publisher.web_viewer_url()
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
        if self._window is not None:
            self._window.show_web_url(url)
        self._status("Web viewer opened (press Play to see depth).")

    def open_image_viewer(self, unit_paths=None, camera_keys=("longrange",)):
        paths = self._camera_paths(unit_paths, camera_keys)
        ok = bool(paths) and self._viewer.open_viewer(paths)
        self._status("Depth viewer open." if ok
                     else "No camera found (add one via econ.itof.menu).", ok)

    def set_gt_projection(self, on: bool, offset: float = 0.0001,
                          unit_paths=None, camera_keys=("longrange",),
                          stride: int = 2, psize: int = 5):
        paths = self._camera_paths(unit_paths, camera_keys)
        self._viewer.set_gt_projection(bool(on), float(offset), paths,
                                       stride=int(stride), psize=int(psize))
        self._status(f"GT projection {'ON' if on else 'off'} "
                     f"(offset {offset:g} m, stride {stride}, size {psize})."
                     if paths else "No camera found for GT projection.",
                     bool(paths) or not on)
