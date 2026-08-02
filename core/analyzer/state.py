"""工程分析：✓/× 标记状态持久化

标记状态（已完成 / 不再提醒）以 JSON 字典存在 Scene 的
analyzer_props.states_json 上，随 .blend 保存 —— 即「不再提醒」按工程生效。
（合并自 Bekkan/STOOL_part/Analyzer/state.py，纯平移）
"""
import json


def get_states(scene):
    """返回 {finding_key: 'done'/'dismissed'} 字典"""
    props = getattr(scene, "analyzer_props", None)
    if props is None:
        return {}
    raw = props.states_json
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def set_state(scene, key, value):
    """value: 'done' / 'dismissed' / None（清除标记）"""
    props = getattr(scene, "analyzer_props", None)
    if props is None:
        return
    states = get_states(scene)
    if value is None:
        states.pop(key, None)
    else:
        states[key] = value
    props.states_json = json.dumps(states)


def clear_states(scene):
    props = getattr(scene, "analyzer_props", None)
    if props is None:
        return
    props.states_json = ""
