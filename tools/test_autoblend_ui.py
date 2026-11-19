"""一次性 GUI 实例：侧边栏真实绘制、视图合成、一次撤销/重做。"""
import importlib
import json
import os
from pathlib import Path
import sys
import traceback

import addon_utils
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = addon_utils.enable(ROOT.name, default_set=True)
assert addon is not None
ab = importlib.import_module(ROOT.name + ".core.autoblend")
ui = importlib.import_module(ROOT.name + ".ui")
panel_module = importlib.import_module(ROOT.name + ".ui.bekkan.light_compose_panel")
ui.apply_mode("BEKKAN")
panel_module.unregister()
panel_module.BEKKAN_PT_light_compose.bl_options = set()
panel_module.BEKKAN_PT_autoblend.bl_options = set()
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
area.spaces.active.show_region_ui = True
directory = ROOT / "temp" / (f"autoblend-ui{bpy.app.version[0]}{bpy.app.version[1]}")
directory.mkdir(parents=True, exist_ok=True)
state = {"step": 0, "draws": 0, "draw_error": None}
original_draw = panel_module.BEKKAN_PT_autoblend.draw


def draw(self, context):
    try:
        original_draw(self, context)
        state["draws"] += 1
    except Exception:
        state["draw_error"] = traceback.format_exc()
        raise


panel_module.BEKKAN_PT_autoblend.draw = draw
panel_module.register()


def finish(error=None):
    result = {"ok": error is None and state["draw_error"] is None,
              "blender": bpy.app.version_string, **state, "error": error}
    (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result["ok"] else 1)


def advance():
    try:
        region = next(r for r in area.regions if r.type == "WINDOW")
        with bpy.context.temp_override(window=window, area=area, region=region):
            step = state["step"]
            if step == 0:
                next(r for r in area.regions if r.type == "UI").active_panel_category = "别馆"
                bpy.ops.ed.undo_push(message="Before AutoBlend")
            elif step == 1:
                assert bpy.ops.render.autoblend_setup_visn("EXEC_DEFAULT", True) == {"FINISHED"}
                assert area.spaces.active.shading.use_compositor == "ALWAYS"
            elif step == 2:
                bpy.ops.ed.undo()
            elif step == 3:
                assert ab.compositor_tree(bpy.context.scene) is None
                bpy.ops.ed.redo()
            elif step == 4:
                assert ab.get_autoblend_node(ab.compositor_tree(bpy.context.scene)) is not None
                assert bpy.ops.render.autoblend_mask_visn(mask_type="NOISE") == {"FINISHED"}
                material = bpy.data.materials.new("UI Test Material")
                bpy.data.objects["Cube"].data.materials.append(material)
                bpy.ops.object.select_all(action="DESELECT")
                bpy.data.objects["Cube"].select_set(True)
                assert bpy.ops.render.autoblend_add_visn() == {"FINISHED"}
            elif step == 5:
                assert state["draws"] > 0
                bpy.ops.screen.screenshot(filepath=str(directory / "panel.png"))
                finish()
        state["step"] += 1
        area.tag_redraw()
        return 0.8
    except Exception:
        finish(traceback.format_exc())


bpy.app.timers.register(advance, first_interval=1)
