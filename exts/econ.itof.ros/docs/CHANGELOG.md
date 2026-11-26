# Changelog

## [1.0.0]

- First public release.

### Update 2026-11-26 (same version)

- Each unit's TF frame and every frame_id it publishes (depth, points, camera_info, IMU) now carry the unit's own name (`Helix_iToF`, `Helix_iToF_01`, …); several units no longer share one frame name.
- Works with the updated econ.itof.menu camera assets.
- Control window: **Head TF frame** field (parent frame of each unit's TF frame, default `world`), a **ROS 2 debug** topic list, and an **IMU** section (gravity in the published acceleration, on-screen IMU readout).
- **Enable ROS + Publish** can be pressed again at any time, for example after changing the selected resolutions; it recomposes the publishers cleanly.
