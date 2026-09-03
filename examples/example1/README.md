# Example 1 — DepthVista Helix cameras and an over-pallet camera stand on UR10 Palletizing

Isaac Sim's **UR10 Palletizing** example (Robotics Examples → CORTEX) runs a UR10
arm that picks boxes and stacks them onto a pallet using Cortex behaviours.
[`add_itof_to_ur10_palletizing.py`](add_itof_to_ur10_palletizing.py) augments
that scene with two DepthVista Helix iToF cameras — an eye-in-hand camera on the
wrist and an eye-to-hand camera over the pallet — together with a stand that
carries the over-pallet camera.

![UR10 Palletizing scene with the iToF cameras and the camera stand](../../docs/Example1_Palletization/images/00-overview.png)

### What it adds

| Prim | Role | Translate | Rotate XYZ | Scale |
|------|------|-----------|------------|-------|
| `…/ur10/ee_link/DEPTHVISTA_HELIX` | Wrist camera (eye-in-hand) | (0.07, 0.055, 0) | (180, -90, 90) | mm → m |
| `…/pallet/DEPTHVISTA_HELIX` | Over the pallet (eye-to-hand) | (0, 0, 1.5) | (-90, 0, 0) | mm → m |
| `…/dolly/CameraStand/Stand` | Referenced Isaac Stand prop | (1.2, 0, 1.88193) | (0, 0, 0) | (1.2, 1.2, 3.66786) |
| `…/dolly/CameraStand/Cylinder` | Stand arm (Create → Mesh → Cylinder) | (0.6, 0, 1.88) | (0, 90, 0) | (0.0282, 0.07185, 1.3) |

All prims are created under `/World/Ur10Table`. The cameras reference the same
USD as the Create menu and are placed at true scale. The stand and its arm are
grouped under a single `CameraStand` node, so they behave as one part. The
script is idempotent — re-running it replaces what it created.

### Requirements

- The extension installed, so the DepthVista Helix USD is available — see the
  [main README](../../README.md#installation).
- The **UR10 Palletizing** example loaded (Step 1 below).

### Step 1 — Load the UR10 Palletizing example

Open the Robotics Examples browser via **Window → Robotics Examples**:

![Window menu with Robotics Examples](../../docs/Example1_Palletization/images/01-window-robotics-examples.png)

Select **CORTEX → UR10 Palletizing**, then click **LOAD** (Load World and Task):

![Robotics Examples browser with UR10 Palletizing selected](../../docs/Example1_Palletization/images/02-load-ur10-palletizing.png)

### Step 2 — Run the script

Open the Script Editor (**Window → Script Editor**):

![Window menu with Script Editor](../../docs/Example1_Palletization/images/03-window-script-editor.png)

Choose **File → Open**:

![Script Editor File menu, Open](../../docs/Example1_Palletization/images/04-script-editor-open.png)

Select `econ-isaac-sim/examples/example1/add_itof_to_ur10_palletizing.py`, then **Run**
(or press **Ctrl+Enter**):

![add_itof_to_ur10_palletizing.py loaded in the Script Editor](../../docs/Example1_Palletization/images/05-example-script-loaded.png)

The console reports each prim it adds:

```
[econ] camera /World/Ur10Table/ur10/ee_link/DEPTHVISTA_HELIX …
[econ] camera /World/Ur10Table/pallet/DEPTHVISTA_HELIX …
[econ] prop   /World/Ur10Table/dolly/CameraStand/Stand …
[econ] prop   /World/Ur10Table/dolly/CameraStand/Cylinder …
[econ] done — 4 prim(s) added (2 cameras + 2 stand parts).
```

The two cameras and the camera stand now appear in the palletizing scene:

![Cameras and camera stand in the scene](../../docs/Example1_Palletization/images/06-result-cameras-stand.png)

### Output — stream and visualise

With the cameras in the scene, open the **e-con iToF** control window (see the
[main README](../../README.md#the-e-con-itof-control-window)): click **Refresh list**, tick
both units, and click **Enable ROS + Publish** (leave **Web viewer** on). Press **Play** —
it publishes ROS 2 depth, point cloud, camera_info, IMU and TF for both cameras, and serves
the browser depth viewer.

**Browser depth viewer** (`http://localhost:8211/`) — live, colour-mapped depth
tiles and interactive point clouds, with no RViz required:

![Browser depth viewer](../../docs/Example1_Palletization/gifs/web-viewer.gif)

**RViz** — the per-camera point clouds fused in the `world` frame:

![RViz point clouds](../../docs/Example1_Palletization/gifs/rviz.gif)

Published topics (two units → `Helix_iToF` over the pallet, `Helix_iToF_01` on the wrist;
each unit's `/tf` is namespaced, `/clock` is global):

```
$ ros2 topic list
/clock
/Helix_iToF/tf
/Helix_iToF/highres/camera_info
/Helix_iToF/highres/depth
/Helix_iToF/highres/points
/Helix_iToF/longrange/camera_info
/Helix_iToF/longrange/depth
/Helix_iToF/longrange/points
/Helix_iToF/imu
/Helix_iToF_01/tf
/Helix_iToF_01/highres/camera_info
/Helix_iToF_01/highres/depth
/Helix_iToF_01/highres/points
/Helix_iToF_01/longrange/camera_info
/Helix_iToF_01/longrange/depth
/Helix_iToF_01/longrange/points
/Helix_iToF_01/imu
```

### Demo videos

- ▶ [**Browser depth viewer**](../../docs/Example1_Palletization/videos/web-viewer-demo.webm) — live depth tiles and interactive point clouds.
- ▶ [**RViz point clouds**](../../docs/Example1_Palletization/videos/rviz-demo.webm) — the fused point clouds and the published topics.
