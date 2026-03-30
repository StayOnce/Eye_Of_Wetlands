import json
import os
from flask import Flask, render_template, jsonify, request
import numpy as np

app = Flask(__name__)

# 加载数据
DATA_PATH = os.path.join(os.path.dirname(__file__), 'data', 'lakes_data.json')
with open(DATA_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

quarters = data['quarters']
lakes = data['lakes']
ei_series = data['ei_series']
pi_series = data['pi_series']

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)