"""The e-con iToF control window: one-tap ROS 2 publishing (by enabling the baked
variant on selected units), the browser web viewer, the in-Isaac GT depth viewer,
and a camera-on-a-stand test rig.

A thin view: every button calls back into the Extension controller (`ctrl`).
Labels are plain ASCII so the viewport font renders them (no em dashes / arrows).
"""
import omni.ui as ui

WINDOW_TITLE = "e-con iToF"

# palette
_ACCENT = 0xFFE0A030          # section headers (amber)
_LINK = 0xFF7EC8FF            # links / info (blue)
_OK = 0xFF9CDCAA             # good status (green)
_ERR = 0xFF6B6BFF            # error status (red)
_MUTE = 0xFF9A9A9A           # secondary text (grey)
_BTN = {"Button": {"border_radius": 4, "padding": 5},
        "Button:hovered": {"background_color": 0xFF4A4A4A}}
_BTN_ACTIVE = {"Button": {"border_radius": 4, "padding": 5, "background_color": 0xFF3A5A3A},
               "Button:hovered": {"background_color": 0xFF4A6A4A}}


class ItofWindow(ui.Window):
    def __init__(self, ctrl, **kwargs):
        super().__init__(WINDOW_TITLE, width=360, height=560, **kwargs)
        self._ctrl = ctrl
        self._domain = ui.SimpleIntModel(0)
        self._web = ui.SimpleBoolModel(True)
        self._tf_frame = ui.SimpleStringModel("world")       # parent TF frame of each unit
        self._cam_hr = ui.SimpleBoolModel(True)
        self._cam_lr = ui.SimpleBoolModel(True)
        # IMU (inline graph)
        self._imu_gravity = ui.SimpleBoolModel(True)    # True = accel incl. gravity (as shipped)
        self._imu_linear = ui.SimpleBoolModel(True)     # overlay linear acceleration on screen
        self._imu_angular = ui.SimpleBoolModel(False)   # overlay angular velocity on screen
        self._imu_cam = ui.SimpleIntModel(0)            # unit index shown on screen (-1 = all)
        self._gt_project = ui.SimpleBoolModel(False)
        self._gt_offset = ui.SimpleFloatModel(0.0001)
        self._gt_stride = ui.SimpleIntModel(6)
        self._gt_psize = ui.SimpleIntModel(3)
        self._gt_project.add_value_changed_fn(lambda m: self._on_gt_project())
        for _m in (self._gt_offset, self._gt_stride, self._gt_psize):
            _m.add_value_changed_fn(
                lambda m: self._gt_project.get_value_as_bool() and self._on_gt_project())
        self._units = {}          # prim_path -> SimpleBoolModel
        self._units_box = None
        self._status = None
        self._url_label = None
        self._enable_btn = None   # goes green while ROS is active
        self._topics_box = None   # debug: ROS 2 topic list rows
        self._topics_status = None
        self.frame.set_build_fn(self._build)

    def _build(self):
        with ui.ScrollingFrame(
                horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
                vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_ON):
          with ui.VStack(spacing=7, height=0, style={"margin_width": 6}):
            ui.Spacer(height=2)
            self._status = ui.Label("Ready.", word_wrap=True,
                                    style={"color": _OK, "font_size": 14})
            ui.Separator(height=2)

            self._section("ROS 2 PUBLISHING")
            with ui.HStack(height=24, spacing=6):
                ui.Label("Domain ID", width=70)
                ui.IntField(self._domain, width=56)
                ui.Spacer()
                ui.Label("Web viewer", width=72)
                ui.CheckBox(self._web, width=18)
            with ui.HStack(height=24, spacing=6):
                ui.Label("Head TF frame", width=90,
                         tooltip="Parent frame of each unit's TF frame. Default 'world'. "
                                 "Another name, for example a robot's 'base_link', makes "
                                 "the unit a child of the prim with that name above it. "
                                 "Applied on Enable ROS + Publish.")
                ui.StringField(self._tf_frame)

            self._section("DEPTHVISTA UNITS")
            self._button("Refresh list", self._on_refresh,
                         "Scan the stage for DepthVista units with a ROS variant.")
            self._units_box = ui.VStack(spacing=2, height=0)
            self._populate_units()

            self._section("RESOLUTIONS TO STREAM")
            with ui.HStack(height=22, spacing=6):
                ui.CheckBox(self._cam_hr, width=18)
                ui.Label("High-res  1280x960  0.2-2.0 m", width=0)
            with ui.HStack(height=22, spacing=6):
                ui.CheckBox(self._cam_lr, width=18)
                ui.Label("Long-range  640x480  0.5-6.0 m", width=0)

            ui.Spacer(height=3)
            self._enable_btn = self._button("Enable ROS + Publish", self._on_start,
                         "Enable ROS on the checked units (all if none checked); "
                         "press Play to publish.")
            self._button("Disable ROS", self._on_stop,
                         "Disable ROS on the units and stop the web viewer.")
            self._button("Open Web Viewer", self._on_web,
                         "Open the localhost depth + point-cloud browser preview "
                         "(independent of ROS; press Play to see depth).")
            self._url_label = ui.Label("", height=14, style={"color": _LINK})
            self._url_label.visible = False

            ui.Spacer(height=3); ui.Separator(height=2); ui.Spacer(height=3)
            self._section("ROS 2 DEBUG (topic list)")
            self._button("Refresh", self._on_refresh_topics,
                         "ros2 topic list from Isaac's own ROS 2 bridge. "
                         "Enable ROS + press Play first (topics exist only while playing).")
            self._topics_status = ui.Label("Press 'Refresh'.", height=14,
                                           word_wrap=True, style={"color": _MUTE})
            with ui.ScrollingFrame(
                    height=220,
                    horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
                    vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
                    style={"background_color": 0xFF1E1E1E, "border_radius": 4}):
                self._topics_box = ui.VStack(spacing=1, height=0,
                                             style={"margin_width": 6, "margin_height": 4})

            ui.Spacer(height=3); ui.Separator(height=2); ui.Spacer(height=3)
            self._section("IMU")
            with ui.HStack(height=22, spacing=6):
                ui.CheckBox(self._imu_gravity, width=18)
                ui.Label("Gravity (accel incl. ~9.81 at rest)", width=0,
                         tooltip="ON = acceleration including gravity, as a real IMU "
                                 "reports it (default); OFF = motion-only acceleration "
                                 "(0 at rest).")
            with ui.HStack(height=22, spacing=6):
                ui.CheckBox(self._imu_linear, width=18)
                ui.Label("Linear accel to screen", width=0,
                         tooltip="Overlay linear acceleration for the selected unit.")
            with ui.HStack(height=22, spacing=6):
                ui.CheckBox(self._imu_angular, width=18)
                ui.Label("Angular vel to screen", width=0,
                         tooltip="Overlay angular velocity for the selected unit.")
            with ui.HStack(height=22, spacing=6):
                ui.Label("Show camera #", width=90,
                         tooltip="Unit index whose IMU readout shows on screen "
                                 "(0 = first unit; -1 = all units).")
                ui.IntField(self._imu_cam, width=56)
            self._button("Setup IMU", self._on_setup_imu,
                         "Apply the gravity choice to the IMU topic (<ns>/imu) of the "
                         "checked units and show the readout on screen; press Play.")
            self._button("Clear IMU", self._on_clear_imu,
                         "Remove the on-screen IMU readout from the checked units.")

            ui.Spacer(height=3); ui.Separator(height=2); ui.Spacer(height=3)
            self._section("IN-ISAAC DEPTH VIEWER (GT)")
            self._button("Open Depth Viewer", self._on_open_viewer,
                         "In-Isaac window with each camera's Replicator GT depth "
                         "(distance_to_image_plane), colour near=red to far=blue.")
            with ui.HStack(height=22, spacing=6):
                ui.CheckBox(self._gt_project, width=18)
                ui.Label("Project GT depth onto scene", width=0,
                         tooltip="Back-project GT depth onto the scene as a "
                                 "depth-coloured point overlay (per-camera ticks are "
                                 "in the viewer window).")
            with ui.HStack(height=22, spacing=6):
                ui.Label("GT offset [m]", width=90,
                         tooltip="Toward-sensor nudge so the overlay floats just in "
                                 "front of the surface. Default 0.0001.")
                ui.FloatField(self._gt_offset)
            with ui.HStack(height=22, spacing=6):
                ui.Label("point stride", width=90,
                         tooltip="Pixel decimation: 1 = every pixel; higher = lighter.")
                ui.IntSlider(self._gt_stride, min=1, max=8)
            with ui.HStack(height=22, spacing=6):
                ui.Label("point size", width=90, tooltip="On-screen dot size (px).")
                ui.IntSlider(self._gt_psize, min=1, max=10)

            ui.Spacer(height=3); ui.Separator(height=2); ui.Spacer(height=3)
            self._section("SCENE SETUP")
            self._button("Place Camera on Stand", self._on_place,
                         "Drop a camera-on-a-stand rig at the origin; grab "
                         "/World/Econ_iToF_Rig to move and aim it.")
            ui.Spacer(height=6)

    def _section(self, text):
        ui.Spacer(height=3)
        ui.Label(text, style={"font_size": 13, "color": _ACCENT})

    def _button(self, text, cb, tooltip=""):
        return ui.Button(text, height=30, clicked_fn=cb, tooltip=tooltip, style=_BTN)

    def set_status(self, text, ok=True):
        if self._status is not None:
            self._status.text = text
            self._status.style = {"color": _OK if ok else _ERR, "font_size": 14}

    def show_web_url(self, url):
        """Reveal the served-at link (called only when the web viewer opens)."""
        if self._url_label is not None:
            self._url_label.text = f"Served at  {url}"
            self._url_label.visible = True

    def set_ros_active(self, active):
        """Green the Enable button while ROS is on; normal after Disable."""
        if self._enable_btn is not None:
            self._enable_btn.set_style(_BTN_ACTIVE if active else _BTN)

    def _populate_units(self):
        if self._units_box is None:
            return
        self._units_box.clear()
        self._units = {}
        rows = self._ctrl.list_units()
        with self._units_box:
            if not rows:
                ui.Label("None found. Add via Create > Sensors > e-con, then Refresh.",
                         height=16, style={"color": _MUTE})
                return
            for i, (path, label) in enumerate(rows):
                m = ui.SimpleBoolModel(i == 0)      # default: only the first (top) unit
                self._units[path] = m
                with ui.HStack(height=20, spacing=6):
                    ui.CheckBox(m, width=18)
                    ui.Label(label, width=0)

    def _on_refresh(self):
        self._populate_units()
        self.set_status(f"{len(self._units)} unit(s) found.")

    def _on_refresh_topics(self):
        if self._topics_status is not None:
            self._topics_status.text = "Scanning ROS 2..."
        data = self._ctrl.list_ros_debug(domain=self._domain.get_value_as_int())
        self._populate_topics(data)

    def _populate_topics(self, data):
        if self._topics_box is None:
            return
        topics = data.get("topics", [])
        source = data.get("source", "")
        self._topics_box.clear()
        if self._topics_status is not None:
            self._topics_status.text = f"{len(topics)} topic(s) - {source}"
        with self._topics_box:
            ui.Label(f"ros2 topic list  ({len(topics)})",
                     height=15, style={"color": _ACCENT, "font_size": 12})
            if not topics:
                ui.Label("  (none)", height=14, style={"color": _MUTE})
            for name, types in topics:
                ui.Label(name, height=14, style={"color": _LINK, "font_size": 13})
                if types:
                    ui.Label(f"    {types}", height=12,
                             style={"color": _MUTE, "font_size": 11})

    def _selected_units(self):
        return [p for p, m in self._units.items() if m.get_value_as_bool()]

    def _camera_keys(self):
        keys = []
        if self._cam_hr.get_value_as_bool(): keys.append("highres")
        if self._cam_lr.get_value_as_bool(): keys.append("longrange")
        return tuple(keys)

    def _on_start(self):
        if not self._camera_keys():
            self.set_status("Select at least one resolution.", False)
            return
        self._ctrl.start_publishing(
            web_viewer=self._web.get_value_as_bool(),
            domain=self._domain.get_value_as_int(),
            unit_paths=self._selected_units(), camera_keys=self._camera_keys(),
            head_frame=self._tf_frame.get_value_as_string().strip() or "world")

    def _on_setup_imu(self):
        self._ctrl.setup_imu(
            unit_paths=self._selected_units(),
            gravity=self._imu_gravity.get_value_as_bool(),
            linear_to_screen=self._imu_linear.get_value_as_bool(),
            angular_to_screen=self._imu_angular.get_value_as_bool(),
            print_index=self._imu_cam.get_value_as_int(),
            domain=self._domain.get_value_as_int())

    def _on_clear_imu(self):
        self._ctrl.clear_imu(self._selected_units())

    def _on_web(self):
        self._ctrl.open_web_viewer(self._selected_units(), self._camera_keys())

    def _on_stop(self):
        self._ctrl.stop_publishing(self._selected_units())

    def _on_open_viewer(self):
        self._ctrl.open_image_viewer(self._selected_units(), self._camera_keys())

    def _on_gt_project(self):
        self._ctrl.set_gt_projection(self._gt_project.get_value_as_bool(),
                                     self._gt_offset.get_value_as_float(),
                                     self._selected_units(), self._camera_keys(),
                                     stride=self._gt_stride.get_value_as_int(),
                                     psize=self._gt_psize.get_value_as_int())

    def _on_place(self):
        self._ctrl.place_camera_stand()

    def destroy(self):
        self._ctrl = None
        super().destroy()
