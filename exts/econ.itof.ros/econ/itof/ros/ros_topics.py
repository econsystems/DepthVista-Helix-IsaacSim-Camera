"""ROS 2 topic + node listing for the control window's debug panel - Isaac's OWN ROS 2.

Uses the ROS 2 that ships INSIDE Isaac (the `isaacsim.ros2.core` / `isaacsim.ros2.bridge`
bundle the bridge runs on) - NOT an external `/opt/ros`. So it lists exactly what the
Isaac ROS 2 bridge publishes, on the same RMW + domain, with nothing to source.

It talks to `rclpy` DIRECTLY in a SUBPROCESS (Isaac's kit python) rather than the `ros2`
CLI: the CLI drags in a long entry-point dependency chain (packaging/numpy/lark/
catkin_pkg/...) and hides import failures as `KeyError: 'list'`, whereas a tiny rclpy
graph query needs only rclpy + the rmw .so. The subprocess is isolated from the bridge's
in-process rclpy, so it can never disturb it (in-process rclpy caused the
'SingleThreadedExecutor _sigint_gc' crash). Discovery is passive (a short sleep - the DDS
threads fill the graph cache), so no executor is created and no _sigint_gc noise appears.

`list_all()` returns {"topics": [(name, types)], "source": str}.
"""
import os
import sys
import subprocess
import tempfile

import omni.kit.app

_LAST_ERR = ""              # last subprocess failure reason (surfaced in the panel)

# rclpy graph probe: init on its own context, let DDS discover, print the topic list.
# No spin_once -> no executor -> no _sigint_gc. Wait is substituted in.
_PROBE = r'''
import sys, time
import rclpy
from rclpy.context import Context
ctx = Context()
rclpy.init(context=ctx)
node = rclpy.create_node("econ_itof_probe", context=ctx)
time.sleep({wait})
try:
    for name, types in sorted(node.get_topic_names_and_types()):
        sys.stdout.write("T\t%s\t%s\n" % (name, ",".join(types)))
finally:
    node.destroy_node()
    rclpy.shutdown(context=ctx)
'''


def _kit_python(start):
    """Isaac's kit python3, found by walking up from an ext path (<isaac>/kit/python/
    bin/python3). Bundle location moved between versions, so don't hard-code it."""
    d = start
    for _ in range(7):
        cand = os.path.join(d, "kit", "python", "bin", "python3")
        if os.path.isfile(cand):
            return cand
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    exe = sys.executable or ""
    return exe if os.path.basename(exe).startswith("python") else (exe or None)


def _bundle():
    """(python_exe, rclpy_dir, lib_dir, distro) for Isaac's bundled ROS 2, or Nones.
    The rclpy+lib bundle ships under isaacsim.ros2.core (6.0) OR isaacsim.ros2.bridge
    (5.1), so scan every isaacsim.ros2.* ext for a <distro>/rclpy."""
    try:
        mgr = omni.kit.app.get_app().get_extension_manager()
    except Exception:
        return None, None, None, None
    cands = []
    for e in mgr.get_extensions():
        nm = e.get("name", "")
        if nm.startswith("isaacsim.ros2."):
            p = mgr.get_extension_path(e["id"])
            if p:
                rank = 0 if nm == "isaacsim.ros2.core" else 1 if nm == "isaacsim.ros2.bridge" else 2
                cands.append((rank, p))
    cands.sort(key=lambda t: t[0])                       # prefer core, then bridge, then any
    distro = os.environ.get("ROS_DISTRO") or ""
    for _rank, path in cands:
        for d in ([distro] if distro else []) + ["humble", "jazzy"]:
            rclpy_dir = os.path.join(path, d, "rclpy")
            if os.path.isdir(rclpy_dir):
                return _kit_python(path), rclpy_dir, os.path.join(path, d, "lib"), d
    return None, None, None, None


def _child_env(rclpy_dir, lib_dir, distro, domain):
    """Env for the child: bundled rclpy + rmw libs + the deps rclpy imports (resolved
    from the kit process, since Isaac prebundles are reached by a finder, not sys.path)."""
    env = dict(os.environ)
    extra = []
    for mod in ("numpy", "yaml", "rpyutils", "ament_index_python", "packaging", "lark",
                "rosidl_runtime_py", "rosidl_parser"):
        try:
            m = __import__(mod)
            base = (os.path.dirname(m.__path__[0]) if getattr(m, "__path__", None)
                    else os.path.dirname(getattr(m, "__file__", "") or ""))
            if base and base not in extra:
                extra.append(base)
        except Exception:
            pass
    paths = [rclpy_dir] + extra + [p for p in sys.path if p]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    libs = [lib_dir] + ([env["LD_LIBRARY_PATH"]] if env.get("LD_LIBRARY_PATH") else [])
    env["LD_LIBRARY_PATH"] = os.pathsep.join(libs)
    if distro:
        env["ROS_DISTRO"] = distro
    if domain is not None:
        env["ROS_DOMAIN_ID"] = str(int(domain))
    return env


def _probe(domain, wait, timeout):
    """[(topic, types)] via a bundled-rclpy subprocess, or None on failure."""
    global _LAST_ERR
    py, rclpy_dir, lib_dir, distro = _bundle()
    if not py:
        _LAST_ERR = "Isaac ROS 2 bundle not found (enable isaacsim.ros2.bridge)"
        return None
    env = _child_env(rclpy_dir, lib_dir, distro, domain)
    boot = _PROBE.format(wait=float(wait))
    try:
        p = subprocess.run([py, "-c", boot], capture_output=True, text=True,
                           timeout=timeout, env=env, cwd=tempfile.gettempdir())
    except Exception as exc:
        _LAST_ERR = f"{type(exc).__name__}: {exc}"
        return None
    if p.returncode != 0:
        err = [ln for ln in (p.stderr or "").splitlines() if ln.strip()]
        _LAST_ERR = err[-1] if err else f"rc={p.returncode}"
        return None
    topics = []
    for ln in p.stdout.splitlines():
        parts = ln.split("\t")
        if parts[0] == "T" and len(parts) >= 2:
            topics.append((parts[1], parts[2] if len(parts) > 2 else ""))
    return topics


def list_all(domain: int | None = None, timeout: float = 12.0):
    """{"topics", "source"} from Isaac's bundled rclpy graph query."""
    global _LAST_ERR
    _LAST_ERR = ""
    topics = _probe(domain, wait=2.5, timeout=timeout)
    if topics is None:
        return {"topics": [], "source": f"Isaac ROS 2 error: {_LAST_ERR}"}
    src = "Isaac ROS 2 (rclpy graph)"
    if not topics:
        src = "Isaac ROS 2 ok - nothing up yet (Enable ROS + press Play)"
    return {"topics": topics, "source": src}
