# Snapshot 合并调试报告

**日期**: 2026-08-02  
**调试者**: AI Assistant  
**目标**: 将 Bekkan 已验证可用的 Snapshot 实现合并到 pond_bekkan 核心，修复合并过程中引入的 API 与着色器错误。

---

## 1. 问题总览

合并后的 `core/snapshot.py` 在 Blender 5.2 下运行时报错，涉及多个层面。经过系统对比 `c4fc568` 合并版与 `a3283fa` 中 Bekkan 原始实现，发现**合并版混入了大量 Pond 旧版（有 bug）的实现风格**，而非完全采用 Bekkan 已验证的代码。

---

## 2. 逐条修复记录

### 2.1 `draw_view3d()` 参数名错误

**报错**:
```
TypeError: draw_view3d() missing required argument 'projection_matrix' (pos 6)
```

**位置**: `_capture` 函数  
**原因**: 合并版使用关键字参数 `proj_matrix=...`，Blender 5.2 API 要求 `projection_matrix=...`。

**修复**: 改为 `projection_matrix=...`。  
**后续**: 进一步发现合并版使用 `off.bind()` + `gpu.matrix.push_pop()` + `draw_background=False`，这是 Pond 旧版写法。Bekkan 原始实现使用 `context.temp_override()` + 位置参数，更稳定。已将整个 `_capture` 函数改回 Bekkan 原始实现。

---

### 2.2 `GPUTexture` Buffer 格式不匹配

**报错**:
```
ValueError: GPUTexture.__new__: Only Buffer of format `FLOAT` is currently supported
```

**位置**: `_capture` 函数  
**原因**: 合并版创建 `GPUOffScreen` 时使用 `format="RGBA8"`，导致 `read()` 返回 UBYTE Buffer，而 Blender 5.2 的 `GPUTexture` 构造函数只接受 FLOAT Buffer。

**修复**: 改为 `format="RGBA32F"`。Bekkan 原始代码中有明确注释说明这一点，合并时被改错。

---

### 2.3 `_free_res` 中 `_offscreens` 类型错误

**位置**: `_free_res` 函数  
**原因**: 合并版缓存 `GPUOffScreen` 对象到 `_offscreens` 字典，但 `_free_res` 统一按 dict 处理，对 `GPUOffScreen` 对象调用 `.pop()` 会抛 `AttributeError`。

**修复**: 由于 `_capture` 已改回 Bekkan 原始实现（不缓存 offscreen），`_offscreens` 字典已无用。已完全移除。

---

### 2.4 `gpu.shader.create_from_info` 着色器编译失败

**报错**:
```
AttributeError: module 'gpu.shader' has no attribute 'from_custom_info'
```

**位置**: `_get_shader` 函数  
**原因**: 合并版错误写成 `gpu.shader.from_custom_info(si)`，正确 API 是 `gpu.shader.create_from_info(si)`。

**修复**: 改为 `gpu.shader.create_from_info(si)`。

---

### 2.5 顶点着色器 GLSL 错误

**位置**: `vert_tex` 字符串  
**原因**: 合并版手动写了 `in`/`out` 声明，且变量名与 `GPUStageInterfaceInfo` 定义不匹配：

```glsl
// 错误代码（合并版）
in vec2 pos;
in vec2 texCoord;
out vec2 texCoord;  // 与 interface 变量名 texCoordInterp 不匹配，且 in/out 同名冲突
void main(){
    gl_Position = vec4(pos, 0.0, 1.0);
    texCoord = texCoordInterp;  // texCoordInterp 未定义
}
```

**修复**: 改回 Bekkan 原始实现。`GPUShaderCreateInfo` 路线中 `in`/`out` 由 API 自动生成：

```glsl
// 正确代码（Bekkan 原始）
void main()
{
    texCoordInterp = texCoord;
    gl_Position = vec4(pos, 0.0, 1.0);
}
```

---

### 2.6 片元着色器 GLSL 错误

**位置**: `frag_tex_srgb` 字符串  
**原因**: 手动 `in`/`out` 声明 + `texture()` 采样坐标变量名不匹配：

```glsl
// 错误代码（合并版）
in vec2 texCoord;       // 不应手动声明
out vec4 fragColor;     // 不应手动声明
uniform sampler2D image;
uniform float decode;
void main(){
    vec4 c = texture(image, texCoord);  // interface 变量名是 texCoordInterp
    ...
}
```

**修复**: 改回 Bekkan 原始实现：

```glsl
// 正确代码（Bekkan 原始）
uniform sampler2D image;
uniform float decode;
void main()
{
    vec4 c = texture(image, texCoordInterp);
    if(decode > 0.5) c.rgb = pow(max(c.rgb, vec3(0.0)), vec3(2.2));
    fragColor = c;
}
```

---

### 2.7 `TakeSnap` 使用 `invoke` 而非 `execute`（Pond 风格混入）

**位置**: `TakeSnap` 操作符  
**原因**: 合并版使用 `invoke(self, context, event)`，依赖 `event.mouse_x/y` 获取 region。Bekkan 原始使用 `execute(self, context)`，直接从 `area.regions` 找 `WINDOW` region，不依赖事件坐标。

**修复**: 改为 `execute`，采用 Bekkan 原始实现。

---

### 2.8 `_draw` 中使用 `bgl`（Pond 4.x 旧代码混入）

**位置**: `_draw` 函数  
**原因**: 合并版使用 `import bgl` + `glBegin/glEnd` 绘制分割线遮罩，这是 Blender 4.x 的旧式 OpenGL 代码，5.2 已废弃。

**修复**: 移除 `bgl`，采用 Bekkan 原始的 `batch_for_shader` 绘制方式。

---

### 2.9 `_draw` 使用 `context` 参数而非 `area_id`（Pond 风格混入）

**位置**: draw handler 注册与 `_draw` 函数  
**原因**: 合并版注册 `draw_handler_add(_draw, (context,), ...)`，传入 `context`。Bekkan 原始注册 `draw_handler_add(_draw, (area_id,), ...)`，传入 `area_id`，然后在函数内用 `bpy.context.area` 获取当前 area，更稳定。

**修复**: 改为传入 `area_id`，函数内使用 `bpy.context.area`。

---

## 3. 合并版 vs Bekkan 原始差异对照（完整版）

| 项目 | Bekkan 原始 (已验证) | 合并版 (c4fc568) | 修复后 |
|---|---|---|---|
| `GPUOffScreen` format | `RGBA32F` | `RGBA8` (错误) | `RGBA32F` |
| `draw_view3d` 调用 | `temp_override` + 位置参数 | `bind()` + `gpu.matrix` + 关键字参数 | `temp_override` + 位置参数 |
| OffScreen 缓存 | 不缓存，每次 `free()` | 缓存到 `_offscreens` | 不缓存，每次 `free()` |
| Shader API | `create_from_info` | `from_custom_info` (错误) | `create_from_info` |
| 顶点着色器 | 无手动 in/out | 手动 in/out，变量名冲突 | 无手动 in/out |
| 片元着色器 | 无手动 in/out | 手动 in/out，变量名不匹配 | 无手动 in/out |
| `TakeSnap` 方法 | `execute` | `invoke` (Pond 风格) | `execute` |
| `_draw` 绘制方式 | `batch_for_shader` | `bgl` (Pond 4.x 旧代码) | `batch_for_shader` |
| draw handler 参数 | `area_id` | `context` (Pond 风格) | `area_id` |
| `_snaps` key 格式 | `"s%d" % _next_id` | `str(area.as_pointer())` | `"s%d" % _next_id` |

---

## 4. 诊断脚本

编写了两个诊断脚本：

1. **`tools/test_gpu_shader.py`**: 测试 `gpu.shader.create_from_info` 可用性
2. **`tools/test_snapshot.py`**: 完整诊断（shader API、着色器编译、GPUOffScreen、GPUTexture、模块导入）

**用法**: 在 Blender 脚本编辑器中运行。

---

## 5. 经验教训

1. **合并时应以已验证版本为基准**：Bekkan 的 Snapshot 已经过桶桶调试确认可用，合并时不应混入 Pond 旧版的有 bug 实现。
2. **GPUShaderCreateInfo 路线的 GLSL 规范**：在 `gpu.types.GPUShaderCreateInfo` 路线中，顶点属性、stage interface 和 fragment output 由 API 自动生成声明，着色器源码中不应手动写 `in`/`out`。
3. **Blender 5.2 GPU API 细节**：
   - `GPUOffScreen.read()` 返回的 Buffer 格式取决于 OffScreen 的 format
   - `GPUTexture` 构造函数只接受 FLOAT Buffer
   - `gpu.shader.create_from_info` 是正确 API 名
4. **Pond 与 Bekkan 代码风格差异**：
   - Pond 使用 `invoke` + `event` 坐标、`_offscreens` 缓存、`bgl` 绘制
   - Bekkan 使用 `execute` + `area.regions`、不缓存、`batch_for_shader` 绘制
   - 合并时应统一采用一种风格，不能混用

---

## 6. TODO

- [ ] 在 Blender 5.2 实机测试：拍快照、对比显示、拖拽分割线、导出图像
- [ ] 测试蛙灾模式和别馆模式下的行为一致性
- [ ] 确认 `SystemExit: 1` 错误（来自 `blender_ext.py`）是否与 snapshot 注册/注销有关
- [ ] 更新 `合并对照清单.md` 第 5 节（快照交互待议）状态
