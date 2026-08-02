# 合并后的唯一 AddonPreferences（一个插件包只能有一个偏好类）
# 内含：界面模式切换（仅合体版显示）+ 蛙灾 16 模块开关 + 颈椎拯救者设置。
# bl_idname = __package__：合体版=pond_bekkan，独立版=Pond / bekkan_visn，
# 独立版用户原来的偏好设置（模块开关/收藏类别）因此可以继承。
import bpy
from bpy.types import AddonPreferences, PropertyGroup
from bpy.props import (BoolProperty, StringProperty, EnumProperty,
                       CollectionProperty, IntProperty)

from . import _build_mode
from .ui.pond.prefs import MODULES


def _on_mode_update(self, context):
    """合体版：切换蛙灾/别馆 UI"""
    if _build_mode.BUILD_MODE != "combined":
        return
    try:
        from . import ui
        ui.apply_mode(self.mode)
    except Exception as e:
        print(f"[pond_bekkan] 模式切换失败: {e}")


# 颈椎拯救者的类别排除项（原 AddonManager/preferences.py 的 ADDONMANAGER_CategoryExcludeItem）
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
        name="打开新文件时自动恢复面板（建议保持默认）",
        description="打开新文件时自动将面板恢复到原始类别",
        default=True
    )
    excluded_categories: StringProperty(
        name="默认排除的类别（不建议修改）",
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
                self._draw_addonmanager(layout)
        elif bm == "pond":
            self._draw_pond_toggles(layout)
        else:
            self._draw_addonmanager(layout)

    def _draw_pond_toggles(self, layout):
        box = layout.box()
        box.label(text="池塘模块开关（关掉的模块不在「池塘」页显示）", icon='PREFERENCES')
        grid = box.grid_flow(row_major=True, columns=4, even_columns=True,
                             even_rows=True, align=True)
        for key, label in MODULES:
            grid.prop(self, key, text=label, toggle=True)

    def _draw_addonmanager(self, layout):
        # 颈椎拯救者设置（原 AddonManager 偏好面板内容）
        box = layout.box()
        box.label(text="颈椎拯救者 · 使用须知", icon='ERROR')
        box.label(text="1. 本插件会改变N面板上插件的显示顺序")
        box.label(text="2. 被管理的插件在使用时会在原N面板位置会被隐藏")
        box.label(text="介意勿用！", icon='INFO')

        layout.separator()

        box = layout.box()
        box.label(text="自动恢复设置:", icon='RECOVER_LAST')
        box.prop(self, "auto_restore_on_new_file")
        layout.separator()

        box = layout.box()
        box.label(text="类别排除设置:", icon='FILTER')

        box.prop(self, "excluded_categories")
        box.label(text="默认排除类别 (英文逗号分隔，不建议修改)", icon='INFO')

        row = box.row()
        row.operator("addonmanager.scan_available_categories",
                     text="扫描可用类别", icon='FILE_REFRESH')
        row.label(text="初始化或插件更新后请点击", icon='ERROR')
        row = box.row()
        row.prop(self, "show_category_list",
                 icon='TRIA_DOWN' if self.show_category_list else 'TRIA_RIGHT',
                 text="其他可排除类别" if not self.show_category_list else "其他可排除类别 (点击折叠)")

        if self.show_category_list:
            row.prop(self, "columns_count", text="列数")

        if self.show_category_list and len(self.available_categories) > 0:
            total_items = len(self.available_categories)
            items_per_column = max(1, total_items // self.columns_count + (1 if total_items % self.columns_count else 0))

            box.label(text="点击选择要额外排除的类别:")
            row = box.row()

            default_excluded = [cat.strip() for cat in self.excluded_categories.split(',') if cat.strip()]

            for col_idx in range(self.columns_count):
                if col_idx * items_per_column >= total_items:
                    break
                col = row.column()
                for i in range(items_per_column):
                    item_idx = col_idx * items_per_column + i
                    if item_idx < total_items:
                        item = self.available_categories[item_idx]
                        if item.name not in default_excluded:
                            item_row = col.row()
                            item_row.prop(item, "exclude", text=item.name)

            row = box.row()
            row.operator("addonmanager.apply_excluded_categories",
                         text="应用排除设置", icon='CHECKMARK')
        elif self.show_category_list:
            box.label(text="请先扫描可用类别", icon='INFO')

        box = layout.box()
        box.label(text="收藏设置", icon='SOLO_ON')
        box.prop(self, "favorite_categories")
        box.label(text="收藏类别 (英文逗号分隔)", icon='INFO')


# 蛙灾 16 个模块开关：名单只维护一份（ui/pond/prefs.py 的 MODULES），
# 动态挂到偏好类上（与原 PondPreferences 相同的手法）
for _key, _label in MODULES:
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
