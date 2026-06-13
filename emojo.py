# from ollama import chat, generate
# from ollama import ChatResponse, AsyncClient
# import anyio
# from ollama import AsyncClient
#
#
# async def chat_session(message):
#     print("向模型提问……")
#     try:
#         client = AsyncClient()
#         messages = []
#
#         reply = client.generate(model="deepseek-r1", prompt=[{"role": "user", "content": message}],
#                                 stream=False)
#         async for chunk in await reply:
#             print(chunk["response"], end="", flush=True)
#         messages.append({"role": "user", "content": message})  # 自动更新上下文
#     except RuntimeError as e:
#         print(f"error:{e}")
#
#
# # response = generate(
# #     model="deepseek-r1",
# #     prompt="实时解说足球比赛",
# #     stream=True
# # )
# #
# # for chunk in response:
# #     print(chunk["response"], end="", flush=True)  # 逐词输出
# #
# #
# # def get_chat_response():
# #     try:
# #         response: ChatResponse = chat(
# #             model='deepseek-r1',
# #             messages=[
# #                 {"role": "system", "content": "你是一个资深的数据分析专家"},
# #                 {"role": "user",
# #                  "content": "数据分析专家是一名具有丰富的分析经验的专业人士，掌握数据挖掘、数据分析、数据可视化等技能。那么 数据可视化 需要用到Python的哪些技术呢？，请列出5-10种"}
# #             ],
# #             stream=False
# #         )
# #         return response.message.content
# #     except Exception as e:
# #         print(f"在与模型交互时发生错误: {e}")
# #         return None
#
#
# while True:
#     question = input(">>")
#     print(question)
#     chat_session(question)
import requests
import json

# Ollama API的URL
OLLAMA_API_URL = "http://localhost:11434/api/chat"

# 对话历史，用于支持多轮对话
conversation_history = []


def chat_with_ollama(prompt: str):
    answer = ""
    conversation_history.append({"role": "user", "content": prompt})

    # 构建请求体
    payload = {
        "model": "llama3.2:1b",
        "messages": conversation_history,
        "stream": True
    }

    try:
        # 使用 stream=True 来接收流式响应
        with requests.post(OLLAMA_API_URL, json=payload, stream=True) as response:
            response.raise_for_status()  # 如果请求失败（如404, 500），则抛出异常

            full_response = ""
            print("deepseek: ", end="", flush=True)

            # 逐行迭代响应内容
            for line in response.iter_lines():
                if line:
                    # 解码每一行（它们是JSON字符串）
                    chunk = json.loads(line.decode('utf-8'))

                    # 提取消息内容
                    content = chunk['message']['content']
                    print(content, end="", flush=True)
                    full_response += content

                    # 检查对话是否结束
                    if chunk.get('done', False):
                        # 将完整的助手回答添加到历史记录中
                        conversation_history.append({"role": "assistant", "content": full_response})
                        print()

    except requests.exceptions.RequestException as e:
        print(f"\n[错误] 无法连接到Ollama API: {e}")
    except json.JSONDecodeError as e:
        print(f"\n[错误] 解析JSON响应失败: {e}")


if __name__ == "__main__":
    while True:
        question = input(">> ")
        if question.lower() in ["exit", "quit"]:
            print("再见!")
            break
        chat_with_ollama(question)
