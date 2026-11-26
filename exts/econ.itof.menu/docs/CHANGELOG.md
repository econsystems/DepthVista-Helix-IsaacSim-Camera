# Changelog

## [2.1.0]

- First public release.

### Update 2026-11-26 (same version)

- Camera assets now pass the NVIDIA Isaac Sim sensor asset validator: OmniSensorAPI and tick rate on both cameras (HighResolution 30 Hz, LongRange 50 Hz), a render product per camera, and a corrected IR emitter link. Prim names and paths are unchanged.
- ROS configuration: the published TF frame is now the camera's optical frame (+Z forward, +Y down; new `ToF_Camera/CameraFrame/optical_frame`), matching the axes of the depth, point cloud and camera_info. Previously the frame had the module's axes, so point clouds appeared rotated in a `world`-fixed RViz view.
