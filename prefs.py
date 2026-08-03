# 合并后的唯一 AddonPreferences（一个插件包只能有一个偏好类）
# 内含：界面模式切换（仅合体版显示）+ 蛙灾 16 模块开关 + 别馆 8 模块开关。
# AddonManager（颈椎拯救者）的偏好字段仍保留在类中，但不在面板显示，
# 以维持旧版偏好继承与核心运行；默认值已写死。
# bl_idname = __package__：合体版=pond_bekkan，独立版=Pond / bekkan_visn，
# 独立版用户原来的偏好设置（模块开关/收藏类别）因此可以继承。
import bpy
from bpy.types import AddonPreferences, PropertyGroup
from bpy.props import (BoolProperty, StringProperty, EnumProperty,
                       CollectionProperty, IntProperty)

from . import _build_mode
from .ui.pond.prefs import MODULES as POND_MODULES
from .ui.bekkan.prefs import MODULES as BEKKAN_MODULES


def _switch_sidebar_category(mode):
    """把当前所有 3D Viewport 的 N 面板切到对应 category 并打开面板。"""
    screen = bpy.context.screen
    if not screen:
        return
    category = "池塘" if mode == "POND" else "别馆"
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        space = area.spaces.active
        if not space or space.type != 'VIEW_3D':
            continue
        # 确保 N 面板打开
        space.show_region_ui = True
        for region in area.regions:
            if region.type == 'UI':
                try:
                    region.active_panel_category = category
                    region.tag_redraw()
                except Exception:
                    pass
                break


def _on_mode_update(self, context):
    """合体版：切换蛙灾/别馆 UI。

    通过 bpy.app.timers 把真正的 UI 重建推迟到下一帧，
    避免在 operator 执行或面板绘制过程中 unregister/register 类导致崩溃；
    重建完成后把 3D Viewport 的 N 面板切到对应 category。
    """
    if _build_mode.BUILD_MODE != "combined":
        return

    def _apply_mode():
        try:
            from . import ui
            ui.apply_mode(self.mode)
            _switch_sidebar_category(self.mode)
        except Exception as e:
            print(f"[pond_bekkan] 模式切换失败: {e}")
        return None

    bpy.app.timers.register(_apply_mode, first_interval=0.01)


# 颈椎拯救者的类别排除项（原 AddonManager/preferences.py 的 ADDONMANAGER_CategoryExcludeItem）
# 保留在偏好类中以供核心读取；UI 已删除，默认值写死。
class ADDONMANAGER_CategoryExcludeItem(PropertyGroup):
    name: StringProperty(name="Category Name")
    exclude: BoolProperty(
        name="Exclude",
        description="Exclude this category from the addon manager",
        default=False
    )


class PondBekkanPreferences(AddonPreferences):
    bl_idname = __package__

    # ── 界面模式（仅合体版在 draw 中显示；独立版该字段闲置） ──
    mode: EnumProperty(
        name="界面模式",
        description="蛙灾模式 = 池塘四抽屉 UI；别馆模式 = 别馆工具箱 UI",
        items=[
            ("POND", "蛙灾模式", "池塘 UI（四抽屉 + 模块开关）"),
            ("BEKKAN", "别馆模式", "别馆 UI（快照 + 工具箱）"),
        ],
        default="POND",  # 决策点 4：合体版默认蛙灾模式
        update=_on_mode_update,
    )

    # ── 颈椎拯救者设置（原 AddonManager/preferences.py 字段） ──
    # 这些字段不再显示在偏好面板中，默认值即写死配置。
    favorite_categories: StringProperty(
        name="收藏的类别",
        description="收藏的类别列表，用逗号分隔",
        default=""
    )
    auto_restore_on_exit: BoolProperty(
        name="退出时自动恢复面板",
        description="关闭Blender或打开新文件时自动将面板恢复到原始类别",
        default=True
    )
    auto_restore_on_new_file: BoolProperty(
        name="打开新文件时自动恢复面板",
        description="打开新文件时自动将面板恢复到原始类别",
        default=True
    )
    excluded_categories: StringProperty(
        name="默认排除的类别",
        description="始终排除的基础类别，用逗号分隔",
        default="Item,Tool,View,Create,Relations,Edit,Physics,Grease Pencil"
    )
    additional_excluded_categories: StringProperty(
        name="额外排除的类别",
        description="通过UI选择排除的额外类别",
        default=""
    )
    show_category_list: BoolProperty(
        name="显示类别列表",
        description="展开/折叠类别列表",
        default=False
    )
    columns_count: IntProperty(
        name="列数",
        description="类别列表显示的列数",
        default=3,
        min=1,
        max=5
    )
    available_categories: CollectionProperty(type=ADDONMANAGER_CategoryExcludeItem)

    # ── draw ──

    def draw(self, context):
        layout = self.layout
        bm = _build_mode.BUILD_MODE
        if bm == "combined":
            box = layout.box()
            row = box.row(align=True)
            row.prop(self, "mode", expand=True)
            layout.separator()
            if self.mode == "POND":
                self._draw_pond_toggles(layout)
            else:
                self._draw_bekkan_toggles(layout)
        elif bm == "pond":
            self._draw_pond_toggles(layout)
        else:
            self._draw_bekkan_toggles(layout)

    def _draw_pond_toggles(self, layout):
        box = layout.box()
        box.label(text="池塘模块开关（关掉的模块不在「池塘」页显示）", icon='PREFERENCES')
        grid = box.grid_flow(row_major=True, columns=4, even_columns=True,
                             even_rows=True, align=True)
        for key, label in POND_MODULES:
            grid.prop(self, key, text=label, toggle=True)

    def _draw_bekkan_toggles(self, layout):
        box = layout.box()
        box.label(text="别馆模块开关（关掉的模块不在「别馆」页显示）", icon='PREFERENCES')
        grid = box.grid_flow(row_major=True, columns=4, even_columns=True,
                             even_rows=True, align=True)
        for key, label in BEKKAN_MODULES:
            grid.prop(self, key, text=label, toggle=True)


# 蛙灾/别馆模块开关：名单只维护一份（ui/pond/prefs.py / ui/bekkan/prefs.py 的 MODULES），
# 动态挂到偏好类上（与原 PondPreferences 相同的手法）
for _key, _label in POND_MODULES:
    PondBekkanPreferences.__annotations__[_key] = BoolProperty(
        name=_label, default=True)

for _key, _label in BEKKAN_MODULES:
    PondBekkanPreferences.__annotations__[_key] = BoolProperty(
        name=_label, default=True)


_classes = (
    ADDONMANAGER_CategoryExcludeItem,
    PondBekkanPreferences,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
