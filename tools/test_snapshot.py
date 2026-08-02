"""
Snapshot 功能诊断脚本
在 Blender 5.2 脚本编辑器中运行，验证 snapshot 各组件是否正常。
"""
import bpy
import gpu


def test_shader_api():
    """测试 gpu.shader.create_from_info 是否可用"""
    print("\n[1] gpu.shader API 检查")
    print("  gpu.shader 属性:", [a for a in dir(gpu.shader) if not a.startswith("_")])

    if hasattr(gpu.shader, "create_from_info"):
        print("  create_from_info: OK")
    else:
        print("  create_from_info: MISSING!")
        return False
    return True


def test_shader_compile():
    """测试着色器是否能编译成功"""
    print("\n[2] 着色器编译测试")
    try:
        interface = gpu.types.GPUStageInterfaceInfo("test")
        interface.smooth("VEC2", "texCoordInterp")
        info = gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0, "VEC2", "pos")
        info.vertex_in(1, "VEC2", "texCoord")
        info.vertex_out(interface)
        info.fragment_out(0, "VEC4", "fragColor")
        info.sampler(0, "FLOAT_2D", "image")
        info.push_constant("FLOAT", "decode")
        info.vertex_source("""
void main()
{
    texCoordInterp = texCoord;
    gl_Position = vec4(pos, 0.0, 1.0);
}
""")
        info.fragment_source("""
uniform sampler2D image;
uniform float decode;
void main()
{
    vec4 c = texture(image, texCoordInterp);
    if(decode > 0.5) c.rgb = pow(max(c.rgb, vec3(0.0)), vec3(2.2));
    fragColor = c;
}
""")
        shader = gpu.shader.create_from_info(info)
        print(f"  编译成功: {shader}")
        return True
    except Exception as e:
        print(f"  编译失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_offscreen():
    """测试 GPUOffScreen + draw_view3d 是否正常工作"""
    print("\n[3] GPUOffScreen 测试")
    try:
        off = gpu.types.GPUOffScreen(64, 64, format="RGBA32F")
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0, 0, 0, 1))
        buf = off.texture_color.read()
        print(f"  RGBA32F OffScreen: OK, buffer type={type(buf)}")
        off.free()
        return True
    except Exception as e:
        print(f"  RGBA32F OffScreen: FAILED - {type(e).__name__}: {e}")
        return False


def test_gputexture():
    """测试 GPUTexture 创建"""
    print("\n[4] GPUTexture 测试")
    try:
        import numpy as np
        data = np.zeros((64, 64, 4), dtype=np.float32)
        data[..., 3] = 1.0
        buf = gpu.types.Buffer("FLOAT", 64 * 64 * 4, data)
        tex = gpu.types.GPUTexture((64, 64), format="RGBA8", data=buf)
        print(f"  GPUTexture(RGBA8, FLOAT buffer): OK")
        return True
    except Exception as e:
        print(f"  GPUTexture: FAILED - {type(e).__name__}: {e}")
        return False


def test_snapshot_module():
    """测试 snapshot 模块是否能正常导入和使用"""
    print("\n[5] Snapshot 模块导入测试")
    try:
        from ..core import snapshot
        print(f"  模块导入: OK")
        print(f"  _snaps: {snapshot._snaps}")
        print(f"  disp_snap: {snapshot.disp_snap}")
        print(f"  draw_hdl: {snapshot.draw_hdl}")
        return True
    except Exception as e:
        print(f"  模块导入: FAILED - {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all():
    print("=" * 60)
    print("Snapshot 功能诊断")
    print("=" * 60)

    results = []
    results.append(("gpu.shader API", test_shader_api()))
    results.append(("着色器编译", test_shader_compile()))
    results.append(("GPUOffScreen", test_offscreen()))
    results.append(("GPUTexture", test_gputexture()))
    results.append(("Snapshot 模块", test_snapshot_module()))

    print("\n" + "=" * 60)
    print("结果汇总")
    print("=" * 60)
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {name}: {status}")

    all_ok = all(ok for _, ok in results)
    print(f"\n总体: {'ALL PASS' if all_ok else 'SOME FAILED'}")
    return all_ok


if __name__ == "__main__":
    run_all()
