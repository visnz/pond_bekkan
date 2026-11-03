"""在独立的 Blender 后台场景中验证全工程 Fake User 清除操作。"""
import sys
from pathlib import Path

import bpy


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pond_bekkan


pond_bekkan.register()
try:
    ids = [
        bpy.data.meshes.new("FakeUserTestMesh"),
        bpy.data.materials.new("FakeUserTestMaterial"),
        bpy.data.actions.new("FakeUserTestAction"),
        bpy.data.images.new("FakeUserTestImage", width=1, height=1),
        bpy.data.collections.new("FakeUserTestCollection"),
        bpy.data.texts.new("FakeUserTestText"),
    ]
    for datablock in ids:
        datablock.use_fake_user = True

    before = {datablock.as_pointer() for datablock in bpy.data.all_ids}
    assert all(datablock.as_pointer() in before for datablock in ids)
    assert bpy.ops.object.clear_all_fake_users_visn() == {"FINISHED"}
    assert all(not datablock.use_fake_user for datablock in ids)
    assert not any(
        datablock.use_fake_user for datablock in bpy.data.all_ids
        if datablock.library is None
    ), "当前工程的本地数据块不应残留 Fake User"
    after = {datablock.as_pointer() for datablock in bpy.data.all_ids}
    assert all(datablock.as_pointer() in after for datablock in ids), "操作不应立即删除数据块"
    assert bpy.ops.object.clear_all_fake_users_visn() == {"FINISHED"}, "重复执行应安全"

    pond_bekkan.ui.apply_mode("BEKKAN")
    assert bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_stage_visn") is not None
    print(f"PASS: cleared {len(ids)} datablock types; no immediate deletion; Bekkan panel registered")
finally:
    pond_bekkan.unregister()
