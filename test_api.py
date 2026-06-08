import os
import json
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.lkeap.v20240522 import lkeap_client, models

def test_chat():
    # 从环境变量获取密钥
    secret_id = os.environ.get("TENCENT_SECRET_ID")
    secret_key = os.environ.get("TENCENT_SECRET_KEY")

    if not secret_id or not secret_key:
        print("错误：未找到 TENCENT_SECRET_ID 或 TENCENT_SECRET_KEY 环境变量")
        return

    cred = credential.Credential(secret_id, secret_key)
    # 请根据你的实际地域修改，例如 "ap-guangzhou"
    client = lkeap_client.LkeapClient(cred, "ap-guangzhou")

    try:
        # 构造请求
        req = models.ChatCompletionsRequest()
        params = {
            "Model": "deepseek-r1",
            "Messages": [
                {
                    "Role": "user",
                    "Content": "你好，请介绍一下你自己。"
                }
            ],
            "Stream": False
        }
        req.from_json_string(json.dumps(params))

        # 发起调用
        resp = client.ChatCompletions(req)

        # 提取回复内容（根据官方 SDK 返回结构）
        if resp.Choices and len(resp.Choices) > 0:
            reply = resp.Choices[0].Message.Content
            print("大模型回复：", reply)
        else:
            print("未收到有效回复")

    except TencentCloudSDKException as err:
        print("调用失败：", err)

if __name__ == "__main__":
    test_chat()