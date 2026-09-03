"""In-Isaac image viewer + ground-truth projection for econ.itof.menu.

This extension publishes via Isaac render products (not the ItofRT renderer), so
its ground truth comes from Isaac **Replicator annotators**:
  * ``distance_to_image_plane`` - perpendicular Z depth (the GT depth image),
  * ``rgb`` - colour (optional preview).
A render product is created per selected camera; the annotator data is shown live
in a ui.Window (colour-mapped depth), and the GT depth can be back-projected onto
the scene geometry as a point overlay drawn via the debug-draw interface, nudged a
small distance toward the sensor (default 0.0001 m) so it floats just in front of
the surface instead of z-fighting it.

Everything is guarded and best-effort - Replicator / debug-draw APIs vary by Kit
version, and this needs one live Isaac Sim run to validate.  Nothing here blocks
ROS 2 publishing (purely additive, like the web viewer).
"""

import time

import numpy as np

import carb
import omni.ui as ui
import omni.usd
import omni.kit.app
from pxr import UsdGeom, Gf

from . import discovery

_DRAW = None


def _range(cam_path):
    """Fixed (near, far) colour range for a camera, by its prim name (operating
    range: highres 0.2-2.0 m, longrange 0.5-6.0 m).  Falls back to a wide default."""
    for _key, (prim_name, _w, _h, _fx, near, far) in discovery.CAMERAS.items():
        if cam_path.endswith(prim_name):
            return near, far
    return 0.2, 6.0


def _draw_iface():
    """isaacsim debug-draw interface (lazy - only when GT projection is used)."""
    global _DRAW
    if _DRAW is None:
        try:
            from isaacsim.util.debug_draw import _debug_draw
            _DRAW = _debug_draw.acquire_debug_draw_interface()
        except Exception as exc:
            carb.log_warn(f"[econ.itof.ros] debug-draw unavailable: {exc}")
            _DRAW = False
    return _DRAW or None


def _turbo_rgba(d, near, far):
    """Colour-map a depth image (m) to RGBA8 over a FIXED [near, far] range, so a
    surface at one depth is one colour and colours are stable frame-to-frame
    (invalid -> transparent)."""
    v = np.isfinite(d) & (d > 0)
    t = np.clip((d - near) / max(far - near, 1e-6), 0, 1)
    t = 1.0 - t                              # near = red, far = blue
    r = np.clip(1.5 - np.abs(t * 4 - 3), 0, 1)
    g = np.clip(1.5 - np.abs(t * 4 - 2), 0, 1)
    b = np.clip(1.5 - np.abs(t * 4 - 1), 0, 1)
    a = v.astype(np.float32)
    return (np.stack([r, g, b, a], axis=-1) * 255).astype(np.uint8)


def _cam_intrinsics(prim, W, H):
    """fx, fy, cx, cy from a UsdGeom.Camera (centred aperture)."""
    cam = UsdGeom.Camera(prim)
    fl = cam.GetFocalLengthAttr().Get() or 4.14
    ha = cam.GetHorizontalApertureAttr().Get() or 4.48
    va = cam.GetVerticalApertureAttr().Get() or 3.36
    fx = W * float(fl) / float(ha)
    fy = H * float(fl) / float(va)
    return fx, fy, W / 2.0, H / 2.0


class ViewerGT:
    def __init__(self):
        self._rep = None
        self._window = None
        self._providers = {}         # cam_path -> ui.ByteImageProvider (one tile each)
        self._gt_models = {}         # cam_path -> SimpleBoolModel (project this cam?)
        self._products = {}          # cam_path -> (render_product, depth_annotator)
        self._sub = None
        self._cams = []
        self._gt_on = False
        self._gt_offset = 0.0001
        self._gt_stride = 6          # pixel decimation for the overlay
        self._gt_psize = 3.0         # on-screen dot size
        self._last = 0.0             # throttle: the depth feed needs ~10 Hz, not 60+
        self._period = 1.0 / 12.0

    # replicator plumbing
    def _rep_mod(self):
        if self._rep is None:
            import omni.replicator.core as rep
            self._rep = rep
        return self._rep

    def _ensure_product(self, cam_path, res):
        if cam_path in self._products:
            return self._products[cam_path]
        rep = self._rep_mod()
        rp = rep.create.render_product(cam_path, res)
        depth = rep.AnnotatorRegistry.get_annotator("distance_to_image_plane")
        depth.attach([rp])
        self._products[cam_path] = (rp, depth)
        return self._products[cam_path]

    # image viewer window
    def open_viewer(self, cam_paths, res=(640, 480)):
        self._cams = [c for c in cam_paths if c]
        if not self._cams:
            carb.log_warn("[econ.itof.ros] no camera to view")
            return False
        try:
            for c in self._cams:
                self._ensure_product(c, res)
        except Exception as exc:
            carb.log_error(f"[econ.itof.ros] could not create render product: {exc}")
            return False
        if self._window is None:
            self._window = ui.Window("iToF Depth Viewer (GT)", width=560, height=360)
            self._window.set_visibility_changed_fn(self._on_visibility)
        self._build_tiles()                     # (re)build for the current cameras
        self._window.visible = True
        if self._sub is None:
            self._sub = (omni.kit.app.get_app().get_update_event_stream()
                         .create_subscription_to_pop(self._on_update,
                                                      name="econ.itof.menu.viewer"))
        return True

    @staticmethod
    def _label(cam_path):
        """Readable tile title: '<unit> / <camera prim name>'."""
        parts = cam_path.strip("/").split("/")
        name = parts[-1]
        unit = parts[parts.index("ToF_Camera") - 1] if "ToF_Camera" in parts else parts[0]
        return f"{unit} / {name}"

    def _build_tiles(self):
        """One labelled tile per camera in a responsive grid: HGrid wraps the tiles by
        window width, so they sit side by side when wide (parallel) and stack when
        narrow (serial).  Each tile owns its own image provider and a projection tick."""
        self._providers = {}
        with self._window.frame:
            with ui.VStack(spacing=4):
                ui.Label("Replicator GT depth (distance_to_image_plane) - "
                         "near=red to far=blue", height=16, style={"color": 0xFFAAAAAA})
                with ui.ScrollingFrame(
                        horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                        vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED):
                    with ui.HGrid(column_width=250, row_height=208):
                        for c in self._cams:
                            prov = ui.ByteImageProvider()
                            self._providers[c] = prov
                            # default: project longrange only (one camera)
                            m = self._gt_models.get(c) or ui.SimpleBoolModel(
                                "longRange" in c)
                            self._gt_models[c] = m
                            with ui.VStack(spacing=2):
                                with ui.HStack(height=16, spacing=4):
                                    ui.CheckBox(m, width=16,
                                                tooltip="Project this camera's GT depth "
                                                        "onto the scene")
                                    ui.Label(self._label(c), word_wrap=True,
                                             style={"color": 0xFF7EC8FF})
                                ui.ImageWithProvider(
                                    prov, width=240, height=180,
                                    fill_policy=ui.IwpFillPolicy.IWP_PRESERVE_ASPECT_FIT)

    def _on_update(self, _):
        # Throttle: this fires every render tick (60+ Hz) but the depth feed only
        # needs ~10 Hz - a cheap time check saves most of the per-frame cost.
        now = time.monotonic()
        if now - self._last < self._period:
            return
        self._last = now
        win_vis = self._window is not None and self._window.visible
        if not win_vis and not self._gt_on:      # nothing to do - skip all reads
            return
        try:
            if win_vis:                           # only build images if the window is shown
                for c in self._cams:
                    prov = self._providers.get(c)
                    pr = self._products.get(c)
                    if prov is None or not pr:
                        continue
                    try:
                        d = pr[1].get_data()
                    except Exception:
                        # render product/annotator invalidated (stage recomposed) -
                        # drop it silently; reopening the viewer recreates it.
                        self._products.pop(c, None)
                        continue
                    if d is None or not getattr(d, "size", 0):
                        continue
                    near, far = _range(c)
                    img = _turbo_rgba(np.asarray(d, dtype=np.float32), near, far)
                    # decimate so the largest side is <= ~256 px per tile - the
                    # per-frame .tolist() cost scales with pixel count.
                    stw = max(1, max(img.shape[:2]) // 256)
                    img = np.ascontiguousarray(img[::stw, ::stw])
                    H, W = img.shape[:2]
                    # set_bytes_data wants a flat uint8 buffer as a list, not bytes.
                    prov.set_bytes_data(img.reshape(-1).tolist(), [W, H])
            if self._gt_on:
                self._draw_gt()
        except Exception as exc:
            carb.log_warn(f"[econ.itof.ros] viewer update: {exc}")

    # in-scene GT projection (debug-draw overlay)
    def set_gt_projection(self, on, offset=0.0001, cam_paths=None, res=(640, 480),
                          stride=2, psize=5):
        self._gt_on = bool(on)
        self._gt_offset = float(offset)
        self._gt_stride = max(1, int(stride))
        self._gt_psize = float(psize)
        if cam_paths:
            self._cams = [c for c in cam_paths if c]
        if on:
            try:
                for c in self._cams:
                    self._ensure_product(c, res)
            except Exception as exc:
                carb.log_error(f"[econ.itof.ros] GT product: {exc}")
                self._gt_on = False
                return False
            if self._sub is None:
                self._sub = (omni.kit.app.get_app().get_update_event_stream()
                             .create_subscription_to_pop(self._on_update,
                                                          name="econ.itof.menu.viewer"))
        else:
            di = _draw_iface()
            if di:
                di.clear_points()
            self._maybe_idle()      # free products/sub if the window is also closed
        return True

    def _draw_gt(self):
        di = _draw_iface()
        if di is None:
            return
        stage = omni.usd.get_context().get_stage()
        xc = UsdGeom.XformCache()
        pts, cols = [], []
        for c in self._cams:
            m = self._gt_models.get(c)
            if m is not None and not m.get_value_as_bool():   # this cam unticked
                continue
            pr = self._products.get(c)
            prim = stage.GetPrimAtPath(c)
            if not pr or not prim or not prim.IsValid():
                continue
            try:
                z = pr[1].get_data()
            except Exception:
                self._products.pop(c, None)         # invalidated - drop silently
                continue
            if z is None or not getattr(z, "size", 0):
                continue
            z = np.asarray(z, dtype=np.float32)
            H, W = z.shape
            st = max(1, int(self._gt_stride))            # user-set decimation (slider)
            fx, fy, cx, cy = _cam_intrinsics(prim, W, H)
            vv, uu = np.mgrid[0:H:st, 0:W:st].astype(np.float32)
            zc = z[::st, ::st]
            m = np.isfinite(zc) & (zc > 0)
            if not m.any():
                continue
            xn = (uu + 0.5 - cx) / fx
            yn = (vv + 0.5 - cy) / fy
            # camera-local points (USD cam: +X right, +Y up, looks -Z; row0=top -> -Y)
            local = np.stack([(xn * zc)[m], (-yn * zc)[m], (-zc)[m]], axis=1)  # (N,3)
            dvals = zc[m]
            # VECTORISED local->world: USD is row-vector, world = [x,y,z,1] @ Mnp
            # (replaces a per-point Gf.Transform Python loop - the old FPS sink).
            M = xc.GetLocalToWorldTransform(prim)
            Mnp = np.array(M, dtype=np.float64).reshape(4, 4)
            h4 = np.concatenate([local, np.ones((local.shape[0], 1))], axis=1)
            world = h4 @ Mnp
            world = world[:, :3] / world[:, 3:4]
            o = (np.array([0.0, 0.0, 0.0, 1.0]) @ Mnp)[:3]
            dirs = o[None, :] - world
            dirs /= (np.linalg.norm(dirs, axis=1, keepdims=True) + 1e-12)
            world = world + dirs * self._gt_offset        # nudge toward sensor
            near, far = _range(c)                        # fixed range: one depth = one colour
            tt = np.clip((dvals - near) / max(far - near, 1e-6), 0, 1)
            tt = 1.0 - tt                               # near = red, far = blue
            col = np.stack([np.clip(1.5 - np.abs(tt * 4 - 3), 0, 1),   # turbo-ish
                            np.clip(1.5 - np.abs(tt * 4 - 2), 0, 1),
                            np.clip(1.5 - np.abs(tt * 4 - 1), 0, 1),
                            np.ones_like(tt)], axis=1)
            pts.append(world); cols.append(col)
        di.clear_points()
        if pts:
            allp = np.concatenate(pts); allc = np.concatenate(cols)
            di.draw_points(allp.tolist(), allc.tolist(), [self._gt_psize] * len(allp))

    def _teardown_products(self):
        """Destroy render products + annotators so Isaac stops the extra per-frame
        annotator render pass (the main hidden GPU cost when the viewer is idle)."""
        try:
            rep = self._rep
            for rp, _ in self._products.values():
                if rep is not None:
                    rep.utils.destroy(rp)
        except Exception:
            pass
        self._products.clear()

    def _maybe_idle(self):
        """When neither the image window is shown NOR GT projection is on, stop all
        per-frame work: clear the overlay, drop the update sub, free render products."""
        win_vis = self._window is not None and self._window.visible
        if win_vis or self._gt_on:
            return
        self._sub = None                          # unsubscribe -> _on_update stops firing
        di = _draw_iface()
        if di:
            di.clear_points()
        self._teardown_products()

    def _on_visibility(self, visible):
        if not visible:
            self._maybe_idle()

    def destroy(self):
        self._sub = None
        di = _draw_iface()
        if di:
            di.clear_points()
        self._teardown_products()
        if self._window is not None:
            self._window.destroy()
            self._window = None
