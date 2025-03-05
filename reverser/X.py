import asyncio
import httpx
import json
import time
import logging
import sys
from typing import Dict, List, Optional, Tuple, Any, AsyncGenerator
from datetime import datetime, timedelta

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/grok_api.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class GrokAPI_X:
    def __init__(self, credentials_list: List[Dict[str, str]]):
        """
        初始化 GrokAPI
        credentials_list: [
            {
                "cookie": "cookie_value",
                "authorization": "auth_value",
                "x-csrf-token": "token_value"
            },
            ...
        ]
        """
        logger.info("=== 初始化 GrokAPI_X ===")
        if not credentials_list:
            logger.warning("没有提供凭证，X.ai功能将不可用")
            
        # 凭证状态追踪
        self.credentials_status = {}
        for i, cred in enumerate(credentials_list):
            self.credentials_status[i] = {
                "is_cooling": False,
                "is_valid": False,  # 标记凭证是否有效
                "remaining_queries": None,
                "cooldown_hours": None,
                "last_check": None,
                "next_available": None,
                "total_used": 0,
                "credentials": cred
            }
            
        self.current_index = 0
        self.valid_indices = []  # 跟踪有效的索引列表
        
        # 初始化请求体模板
        self.request_body = {
            "responses": [],
            "systemPromptName": "",
            "grokModelOptionId": "",
            "conversationId": "",
            "returnSearchResults": True,
            "returnCitations": True,
            "promptMetadata": {
                "promptSource": "NATURAL",
                "action": "INPUT"
            },
            "imageGenerationCount": 4,
            "requestFeatures": {
                "eagerTweets": False,
                "serverHistory": True
            },
            "enableCustomization": False,
            "enableSideBySide": True,
            "toolOverrides": {},
            "isDeepsearch": False,
            "isReasoning": False
        }
        
        logger.info(f"已加载 {len(credentials_list)} 个凭证集")

    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
        
        if self.credentials_status:
            await self.validate_all_credentials()
        
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if exc_type:
            logger.error(f"错误: {exc_type.__name__}: {exc_val}")
        await self.client.aclose()

    async def get_current_headers(self) -> Dict[str, str]:
        """获取当前凭证的headers"""
        # 确保使用有效的凭证
        await self.ensure_valid_credential()
        cred = self.credentials_status[self.current_index]["credentials"]
        logger.debug(f"当前使用凭证: {self.current_index}")
        return {
            "cookie": cred["cookie"],
            "authorization": cred["authorization"],
            "x-csrf-token": cred["x-csrf-token"],
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        }

    async def validate_credentials(self, index: int) -> bool:
        """验证单个凭证"""
        try:
            # 临时设置当前索引
            temp_index = self.current_index
            self.current_index = index
            
            # 尝试创建会话
            conversation_id = await self.create_conversation_for_validation()
            
            # 恢复当前索引
            self.current_index = temp_index
            
            if conversation_id:
                self.credentials_status[index].update({
                    "is_cooling": False,
                    "is_valid": True,
                    "next_available": None
                })
                if index not in self.valid_indices:
                    self.valid_indices.append(index)
                logger.info(f"凭证验证成功 (index {index})")
                return True
            else:
                self.credentials_status[index].update({
                    "is_cooling": False,
                    "is_valid": False,
                    "next_available": None
                })
                if index in self.valid_indices:
                    self.valid_indices.remove(index)
                logger.warning(f"凭证验证失败 (index {index})")
                return False
                
        except Exception as e:
            logger.error(f"凭证验证失败 (index {index}): {e}")
            self.credentials_status[index].update({
                "is_cooling": False,
                "is_valid": False,
                "next_available": None
            })
            if index in self.valid_indices:
                self.valid_indices.remove(index)
            return False

    async def create_conversation_for_validation(self) -> Optional[str]:
        """创建新会话（仅用于验证）"""
        try:
            url = "https://x.com/i/api/graphql/vvC5uy7pWWHXS2aDi1FZeA/CreateGrokConversation"
            
            # 直接使用当前索引的凭证
            cred = self.credentials_status[self.current_index]["credentials"]
            headers = {
                "cookie": cred["cookie"],
                "authorization": cred["authorization"],
                "x-csrf-token": cred["x-csrf-token"],
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
            }
            
            response = await self.client.post(url, headers=headers)
            logger.info(f"HTTP Request: POST {url} \"{response.status_code} {response.reason_phrase}\"")
            
            # 检查响应状态码
            if response.status_code == 403:
                logger.error(f"凭证无效 (index {self.current_index}): 403 Forbidden")
                return None
                
            data = response.json()
            return data["data"]["create_grok_conversation"]["conversation_id"]
            
        except Exception as e:
            logger.error(f"创建会话失败: {e}")
            return None

    async def validate_all_credentials(self):
        """验证所有凭证"""
        logger.info("开始验证所有凭证...")
        
        # 验证所有凭证
        for idx in range(len(self.credentials_status)):
            is_valid = await self.validate_credentials(idx)
            logger.info(f"凭证 {idx}: {'有效' if is_valid else '无效'}")
        
        valid_count = len(self.valid_indices)
        total_count = len(self.credentials_status)
        
        logger.info(f"验证完成: {valid_count}/{total_count} 个有效凭证")
        
        if valid_count == 0:
            logger.warning("没有可用的凭证")
            return False
        
        # 确保当前索引设为一个有效的凭证
        if self.valid_indices:
            self.current_index = self.valid_indices[0]
            return True
        return False

    async def ensure_valid_credential(self) -> bool:
        """确保当前使用的是有效凭证"""
        # 如果当前凭证有效，直接返回
        if (self.current_index in self.credentials_status and 
            self.credentials_status[self.current_index]["is_valid"] and
            not self.credentials_status[self.current_index]["is_cooling"]):
            return True
            
        # 尝试切换到有效凭证
        return await self.switch_credentials()

    async def switch_credentials(self) -> bool:
        """切换到下一个可用的凭证"""
        if not self.valid_indices:  # 如果没有有效凭证
            # 尝试重新验证所有凭证
            if not await self.validate_all_credentials():
                logger.error("没有有效的凭证可用")
                return False
        
        # 找到下一个有效且未冷却的凭证
        original_index = self.current_index
        for _ in range(len(self.credentials_status)):
            # 找到下一个有效索引
            if self.current_index in self.valid_indices:
                current_position = self.valid_indices.index(self.current_index)
                next_position = (current_position + 1) % len(self.valid_indices)
                self.current_index = self.valid_indices[next_position]
            elif self.valid_indices:
                # 如果当前索引不在有效列表中，使用第一个有效索引
                self.current_index = self.valid_indices[0]
            else:
                # 没有有效凭证
                logger.error("没有有效的凭证可用")
                return False
                
            # 检查该凭证是否在冷却中
            status = self.credentials_status[self.current_index]
            
            # 如果凭证未冷却，可以使用
            if not status["is_cooling"]:
                logger.info(f"已切换到凭证 {self.current_index}")
                return True
                
            # 如果凭证在冷却但已过冷却时间，重新验证
            if status["next_available"] and datetime.now() >= status["next_available"]:
                if await self.validate_credentials(self.current_index):
                    logger.info(f"已切换到凭证 {self.current_index}（冷却已过期）")
                    return True
                    
            # 如果已经尝试了所有凭证并回到原点，表示没有可用凭证
            if self.current_index == original_index:
                break
        
        logger.error("所有凭证都在冷却中或无效")
        return False

    def parse_json(self, text: str) -> Tuple[Optional[dict], int]:
        """解析JSON数据"""
        try:
            brace_count = 0
            start_pos = -1
            
            for i, char in enumerate(text):
                if char == '{':
                    if brace_count == 0:
                        start_pos = i
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0 and start_pos != -1:
                        try:
                            json_str = text[start_pos:i+1]
                            data = json.loads(json_str)
                            return data, i + 1
                        except json.JSONDecodeError:
                            continue
            
            return None, 0
            
        except Exception as e:
            logger.error(f"JSON解析错误: {e}")
            return None, 0

    async def handle_cooldown(self, message: str):
        """处理凭证冷却"""
        if "You've reached your limit" in message:
            import re
            pattern = r"limit of (\d+).+?(\d+) hours"
            match = re.search(pattern, message)
            if match:
                queries = int(match.group(1))
                hours = int(match.group(2))
                
                self.credentials_status[self.current_index].update({
                    "is_cooling": True,
                    "remaining_queries": 0,
                    "cooldown_hours": hours,
                    "last_check": datetime.now(),
                    "next_available": datetime.now() + timedelta(hours=hours)
                })
                
                logger.warning(f"凭证 {self.current_index} 已达到限制，冷却时间: {hours} 小时")
                
                # 从有效列表中移除
                if self.current_index in self.valid_indices:
                    self.valid_indices.remove(self.current_index)
                
                if not await self.switch_credentials():
                    raise Exception("所有凭证都在冷却中")

    def format_messages(self, messages: List[dict], model_format: str) -> List[dict]:
        """格式化消息"""
        if messages[-1]["role"] != "user":
            raise Exception("最后一条消息必须为User消息")
            
        if model_format == "single":
            # 单一消息模式，将所有消息合并为一条
            all_content = " ".join([m["content"] for m in messages])
            return [{
                "message": all_content,
                "sender": 1,
                "fileAttachments": []
            }]
        
        # 对话模式，保留消息历史
        formatted = []
        for msg in messages:
            formatted_msg = {
                "message": msg["content"],
                "sender": 1 if msg["role"] == "user" else 2,
                "fileAttachments": []
            }
            formatted.append(formatted_msg)
            
        logger.debug(f"格式化后的消息: {formatted}")
        return formatted

    async def create_conversation(self) -> Optional[str]:
        """创建新会话"""
        try:
            url = "https://x.com/i/api/graphql/vvC5uy7pWWHXS2aDi1FZeA/CreateGrokConversation"
            headers = await self.get_current_headers()
            response = await self.client.post(url, headers=headers)
            
            # 检查响应状态码
            if response.status_code == 403:
                logger.error(f"凭证无效 (index {self.current_index}): 403 Forbidden")
                # 标记凭证为无效
                self.credentials_status[self.current_index]["is_valid"] = False
                if self.current_index in self.valid_indices:
                    self.valid_indices.remove(self.current_index)
                    
                # 尝试切换凭证
                if not await self.switch_credentials():
                    raise Exception("没有可用的凭证")
                return None
                
            data = response.json()
            conversation_id = data["data"]["create_grok_conversation"]["conversation_id"]
            logger.info(f"创建会话成功: {conversation_id}")
            return conversation_id
            
        except Exception as e:
            logger.error(f"创建会话失败: {e}")
            return None

    async def chat_completion(self, messages: List[dict], model: str):
        """发送聊天请求"""
        try:
            # 首先确保使用有效凭证
            if not await self.ensure_valid_credential():
                logger.error("没有可用的凭证")
                yield "错误: 没有可用的凭证，请检查您的凭证配置。"
                return
                
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    # 创建新会话
                    conversation_id = await self.create_conversation()
                    if not conversation_id:
                        # 如果创建失败但切换凭证成功，重试
                        if await self.switch_credentials():
                            retry_count += 1
                            logger.info(f"重试创建会话 ({retry_count}/{max_retries})")
                            continue
                        logger.error("创建会话失败且无法切换凭证")
                        yield "错误: 创建会话失败，请检查您的凭证配置。"
                        return

                    # 准备请求
                    model_format = "single" if ":single" in model else "dialog"
                    model_id = model.replace("X.ai:", "").replace(":dialog", "").replace(":single", "")
                    
                    logger.info(f"使用模型: {model_id}, 格式: {model_format}")
                    
                    self.request_body.update({
                        "responses": self.format_messages(messages, model_format),
                        "grokModelOptionId": model_id,
                        "conversationId": conversation_id
                    })

                    # 发送请求
                    url = "https://grok.x.com/2/grok/add_response.json"
                    headers = await self.get_current_headers()
                    
                    logger.info(f"发送请求到: {url}")
                    
                    async with self.client.stream(
                        'POST', 
                        url, 
                        json=self.request_body,
                        headers=headers
                    ) as response:
                        response.raise_for_status()
                        
                        logger.info(f"开始接收响应流")
                        buffer = ""
                        async for chunk in response.aiter_text():
                            buffer += chunk
                            logger.debug(f"接收到数据块: {len(chunk)} 字节")
                            
                            while True:
                                data, next_pos = self.parse_json(buffer)
                                if not data:
                                    break
                                    
                                if "result" in data and "message" in data["result"]:
                                    message = data["result"]["message"]
                                    
                                    # 检查冷却
                                    if "You've reached your limit" in message:
                                        logger.warning(f"检测到冷却消息: {message}")
                                        await self.handle_cooldown(message)
                                    
                                    yield message
                                    
                                buffer = buffer[next_pos:]
                                
                    # 更新凭证使用统计
                    self.credentials_status[self.current_index]["total_used"] += 1
                    logger.info(f"请求完成，凭证 {self.current_index} 已使用 {self.credentials_status[self.current_index]['total_used']} 次")
                    
                    break  # 如果成功完成，退出循环
                    
                except httpx.HTTPStatusError as e:
                    logger.error(f"HTTP错误: {e.response.status_code} - {e.response.reason_phrase}")
                    
                    if e.response.status_code in [401, 403]:
                        # 标记凭证为无效
                        self.credentials_status[self.current_index]["is_valid"] = False
                        if self.current_index in self.valid_indices:
                            self.valid_indices.remove(self.current_index)
                        
                        # 尝试切换凭证
                        if await self.switch_credentials():
                            retry_count += 1
                            logger.info(f"切换凭证后重试 ({retry_count}/{max_retries})")
                            continue
                        else:
                            logger.error("所有凭证都不可用")
                            yield "错误: 所有凭证都不可用，请检查您的凭证配置。"
                            return
                    
                    elif retry_count < max_retries - 1:
                        retry_count += 1
                        logger.info(f"HTTP错误后重试 ({retry_count}/{max_retries})")
                        continue
                    else:
                        logger.error(f"达到最大重试次数 ({max_retries})")
                        yield f"错误: 请求失败 ({e.response.status_code}), 请稍后再试。"
                        return
                        
                except Exception as e:
                    logger.error(f"请求错误: {str(e)}")
                    
                    if "您的API冷却中" in str(e) or "凭证无效" in str(e):
                        # 尝试切换凭证
                        if await self.switch_credentials():
                            retry_count += 1
                            logger.info(f"切换凭证后重试 ({retry_count}/{max_retries})")
                            continue
                        else:
                            logger.error("所有凭证都不可用")
                            yield "错误: 所有凭证都不可用，请检查您的凭证配置。"
                            return
                    
                    elif retry_count < max_retries - 1:
                        retry_count += 1
                        logger.info(f"请求错误后重试 ({retry_count}/{max_retries})")
                        continue
                    else:
                        logger.error(f"达到最大重试次数 ({max_retries})")
                        yield f"错误: 请求失败，请稍后再试。错误信息: {str(e)}"
                        return
                        
        except Exception as e:
            logger.error(f"聊天请求失败: {str(e)}")
            yield f"处理错误: {str(e)}"

    def list_models(self) -> List[Dict[str, Any]]:
        """获取模型列表"""
        return [
            {
                "id": "X.ai:grok-3:single",
                "object": "model",
                "owned_by": "x.ai",
                "permission": [],
                "context_length": 8192
            },
            {
                "id": "X.ai:grok-3:dialog",
                "object": "model",
                "owned_by": "x.ai",
                "permission": [],
                "context_length": 8192
            }
        ]

# 使用示例
async def main():
    # 准备凭证列表
    credentials_list = [
        {
            "cookie": "your_cookie_here",
            "authorization": "your_auth_here",
            "x-csrf-token": "your_token_here"
        }
    ]
    
    try:
        async with GrokAPI_X(credentials_list) as grok:
            messages = [
                {"role": "user", "content": "Hello, how are you?"}
            ]
            model = "X.ai:grok-3:dialog"
            
            async for chunk in grok.chat_completion(messages, model):
                print(chunk, end="", flush=True)
                
    except Exception as e:
        logger.error(f"运行错误: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())