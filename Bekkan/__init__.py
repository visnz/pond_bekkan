from . import STOOL
from . import Snapshot
import bpy  # type: ignore
bl_info = {
    "name": "Bekkan_visn",
    "category": "3D View",
    "author": "Kimi & visnz",
    "blender": (5, 2, 0),  # 仅支持 Blender 5.2
    "location": "UI",
    "description": "IPR快照工具、一些小工具",
    "version": (1, 3, 0)
}


def register():
    Snapshot.register()
    STOOL.register()


def unregister():
    STOOL.unregister()
    Snapshot.unregister()


if __name__ == "__main__":
    register()
