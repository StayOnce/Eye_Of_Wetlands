import json
import os
import re
from flask import Flask, render_template, jsonify,request
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.lkeap.v20240522 import lkeap_client, models

app = Flask(__name__)

# 加载数据
DATA_PATH = os.path.join(os.path.dirname(__file__), 'data', 'lakes_data.json')
with open(DATA_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

quarters = data['quarters']
lakes = data['lakes']
ei_series = data['ei_series']
pi_series = data['pi_series']
lake_dict = {lake['name']: lake for lake in lakes}

# 辅助函数：计算箱线图数据（按季度聚合所有湖泊EI）
def compute_boxplot_data():
    box_data = {q: [] for q in quarters}
    for lake_name, vals in ei_series.items():
        for i, q in enumerate(quarters):
            box_data[q].append(vals[i])
    return [box_data[q] for q in quarters]

# 辅助函数：生成预警信息（基于最近两个季度变化）
def generate_warnings():
    warnings = []
    for lake in lakes:
        name = lake['name']
        ei_vals = ei_series[name]
        pi_vals = pi_series[name]
        if len(ei_vals) >= 2:
            ei_change = ei_vals[-1] - ei_vals[-2]
            pi_change = pi_vals[-1] - pi_vals[-2]
            if ei_change < -0.02 and pi_change < 0.01:
                warnings.append({
                    "lake": name,
                    "type": "生态退化预警",
                    "message": f"生态质量连续下降 {ei_change:.2f}，公众感知未响应，存在滞后风险。",
                    "severity": "high"
                })
            elif lake['d'] < 0.55:
                warnings.append({
                    "lake": name,
                    "type": "协调度偏低",
                    "message": f"生态与感知耦合协调度仅 {lake['d']:.3f}，公众诉求与生态修复脱节。",
                    "severity": "medium"
                })
            elif pi_change > 0.05 and ei_change < -0.01:
                warnings.append({
                    "lake": name,
                    "type": "感知异常上升",
                    "message": "公众满意度异常升高但生态实际下滑，需核查数据真实性。",
                    "severity": "medium"
                })
    return warnings[:5]

# ---------- API 路由 ----------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/lakes')
def get_lakes():
    """返回湖泊基础信息（含最新EI、PI、D、坐标）"""
    return jsonify(lakes)

@app.route('/api/ei_timeseries')
def get_ei_timeseries():
    """EI时序数据"""
    series = [{"name": name, "data": vals} for name, vals in ei_series.items()]
    return jsonify({"quarters": quarters, "series": series})

@app.route('/api/pi_timeseries')
def get_pi_timeseries():
    """PI时序数据"""
    series = [{"name": name, "data": vals} for name, vals in pi_series.items()]
    return jsonify({"quarters": quarters, "series": series})

@app.route('/api/boxplot')
def get_boxplot():
    """箱线图数据"""
    return jsonify({"quarters": quarters, "data": compute_boxplot_data()})

@app.route('/api/heatmap')
def get_heatmap():
    """热力图数据"""
    return jsonify({
        "lake_names": list(ei_series.keys()),
        "quarters": quarters,
        "values": [ei_series[name] for name in ei_series.keys()]
    })

@app.route('/api/ccd_scatter')
def get_ccd_scatter():
    """当前EI-PI散点图数据"""
    scatter = [{"name": l["name"], "ei": l["ei"], "pi": l["pi"], "d": l["d"], "type": l["type"]} for l in lakes]
    return jsonify(scatter)

@app.route('/api/warnings')
def get_warnings():
    return jsonify(generate_warnings())

@app.route('/api/lake_detail/<lake_name>')
def lake_detail(lake_name):
    """单个湖泊详细信息（用于场景模拟）"""
    lake = next((l for l in lakes if l["name"] == lake_name), None)
    if not lake:
        return jsonify({"error": "Lake not found"}), 404
    ei_vals = ei_series[lake_name]
    pi_vals = pi_series[lake_name]
    return jsonify({
        "name": lake_name,
        "type": lake["type"],
        "ei_current": lake["ei"],
        "pi_current": lake["pi"],
        "d": lake["d"],
        "ei_trend": ei_vals[-3:],
        "pi_trend": pi_vals[-3:],
        "quarters": quarters[-3:],
        "coord": lake["coord"]
    })

# ========== 新增：大模型对话接口 ==========
def remove_markdown(text: str) -> str:
    """移除常见的 Markdown 格式标记，保留纯文本"""
    # 移除加粗 **text** 或 __text__
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    # 移除斜体 *text* 或 _text_
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    # 移除行内代码 `code`
    text = re.sub(r'`(.*?)`', r'\1', text)
    # 移除链接 [text](url)
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    # 移除标题标记 # ## 等
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    # 移除列表标记 - 或 *
    text = re.sub(r'^[\-\*]\s+', '', text, flags=re.MULTILINE)
    return text

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'error': '消息不能为空'}), 400

    # 提取上下文
    lake_context = get_lake_context(user_message)
    # 如果用户没有提及具体湖泊，但询问的是全局问题（如“平均”、“哪个最”），则提供全局摘要
    global_keywords = ['平均', '所有', '哪个', '最高', '最低', '排名', '比较']
    if not lake_context and any(kw in user_message for kw in global_keywords):
        lake_context = get_global_summary()

    # 构建系统提示
    system_prompt = """你是湿地生态专家。请基于以下提供的真实数据回答用户问题。
如果数据中没有相关信息，请使用你的知识回答，但不要编造具体数字。
回答时使用纯文本，不要使用任何Markdown语法（如**加粗**、`代码块`、列表标记等）。
直接输出自然语言段落。"""
    if lake_context:
        system_prompt += f"\n\n以下是与用户问题相关的湖泊数据：\n{lake_context}\n"

    # 调用腾讯云大模型
    secret_id = os.environ.get("TENCENT_SECRET_ID")
    secret_key = os.environ.get("TENCENT_SECRET_KEY")
    if not secret_id or not secret_key:
        return jsonify({'error': '服务器未配置腾讯云密钥'}), 500

    try:
        from tencentcloud.common import credential
        from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
        from tencentcloud.lkeap.v20240522 import lkeap_client, models

        cred = credential.Credential(secret_id, secret_key)
        client = lkeap_client.LkeapClient(cred, "ap-guangzhou")

        req = models.ChatCompletionsRequest()
        params = {
            "Model": "deepseek-r1",   # 或 "hunyuan-lite" 更快
            "Messages": [
                {"Role": "system", "Content": system_prompt},
                {"Role": "user", "Content": user_message}
            ],
            "Stream": False
        }
        req.from_json_string(json.dumps(params))
        resp = client.ChatCompletions(req)
        raw_reply = resp.Choices[0].Message.Content
        clean_reply = remove_markdown(raw_reply)
        return jsonify({'reply': clean_reply})
    except TencentCloudSDKException as err:
        return jsonify({'error': f'腾讯云API错误: {err}'}), 500
    except Exception as e:
        return jsonify({'error': f'服务器内部错误: {str(e)}'}), 500

def get_lake_context(user_query: str) -> str:
    """根据用户问题中的湖泊名，返回该湖泊的详细数据摘要"""
    # 找出问题中出现的湖泊名称
    mentioned = [name for name in lake_dict.keys() if name in user_query]
    if not mentioned:
        return ""  # 未提及任何湖泊，返回空

    context_parts = []
    for lake_name in mentioned:
        lake = lake_dict[lake_name]
        ei_vals = ei_series[lake_name]
        pi_vals = pi_series[lake_name]
        # 最近四个季度的数据
        recent_quarters = quarters[-4:] if len(quarters) >= 4 else quarters
        recent_ei = ei_vals[-4:] if len(ei_vals) >= 4 else ei_vals
        recent_pi = pi_vals[-4:] if len(pi_vals) >= 4 else pi_vals

        trend_lines = []
        for q, ei, pi in zip(recent_quarters, recent_ei, recent_pi):
            trend_lines.append(f"{q}: EI={ei:.3f}, PI={pi:.3f}")
        trend_str = "；".join(trend_lines)

        context = f"""
        湖泊：{lake_name}
        类型：{lake.get('type', '未知')}
        最新季度 EI：{lake['ei']:.3f}
        最新季度 PI：{lake['pi']:.3f}
        耦合协调度 D：{lake['d']:.3f}
        近四季趋势：{trend_str}"""
        context_parts.append(context)

    return "\n".join(context_parts)


def get_global_summary() -> str:
    """返回所有湖泊的统计摘要（当用户问全局问题时使用）"""
    avg_ei = sum(l['ei'] for l in lakes) / len(lakes)
    avg_pi = sum(l['pi'] for l in lakes) / len(lakes)
    best_d = max(lakes, key=lambda x: x['d'])
    worst_d = min(lakes, key=lambda x: x['d'])
    return f"""
所有湖泊统计：
- 平均 EI：{avg_ei:.3f}
- 平均 PI：{avg_pi:.3f}
- 耦合协调度最高的湖泊：{best_d['name']}（D={best_d['d']:.3f}）
- 耦合协调度最低的湖泊：{worst_d['name']}（D={worst_d['d']:.3f}）
"""

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)