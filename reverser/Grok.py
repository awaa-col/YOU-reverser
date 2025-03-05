import asyncio
import httpx
import json
import time
import logging
import sys
from typing import Dict, List, Optional, AsyncGenerator, Any
from datetime import datetime, timedelta

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/grok_reverser.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class GrokReverser_g:
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.client = httpx.AsyncClient(
            headers=self.headers,
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if exc_type:
            logger.error(f"错误: {exc_type.__name__}: {exc_val}")
        await self.client.aclose()

    def __init__(self, Cookies: list = None, cookie_manager=None, num: int = 5):
        """初始化 GrokReverser
        
        Args:
            Cookies: Cookie字符串列表
            cookie_manager: Cookie管理器实例（优先使用）
            num: 并发数量
        """
        logger.info("=== 初始化 GrokReverser ===")
        
        # 使用Cookie管理器或直接使用Cookies列表
        self.cookie_manager = cookie_manager
        self.cookies = Cookies or []
        
        if cookie_manager:
            # 如果有Cookie管理器，尝试获取第一个可用Cookie
            try:
                first_cookie = cookie_manager.get_next_cookie()
                logger.info("使用Cookie管理器提供的Cookie")
            except Exception as e:
                logger.error(f"从Cookie管理器获取Cookie失败: {str(e)}")
                first_cookie = self.cookies[0] if self.cookies else ""
        else:
            # 否则使用提供的Cookies列表
            first_cookie = self.cookies[0] if self.cookies else ""
            
        if not first_cookie:
            logger.warning("没有提供有效的Cookie，Grok功能将不可用")
        
        # 设置基本属性    
        self.base_url = 'https://grok.com'
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": first_cookie
        }

        # Cookie 状态追踪 (仅当不使用Cookie管理器时)
        if not cookie_manager:
            self.cookie_status: Dict[str, dict] = {
                cookie: {
                    "last_used": datetime.now(),
                    "remaining_queries": None,
                    "total_queries": None,
                    "window_size": None,
                    "is_cooling": False
                } for cookie in self.cookies
            }
            
            self.current_cookie_index = 0
            
            # 验证所有 Cookie
            if self.cookies:
                logger.info("正在验证所有 Cookie...")
                self._validate_cookies_sync()
                
                valid_cookies = sum(1 for status in self.cookie_status.values() if not status["is_cooling"])
                logger.info(f"有效 Cookie 数量: {valid_cookies}/{len(self.cookies)}")
        
        self.num = num
        self.request_count = 0

        # 初始化请求体
        self.request_body = {
            "temporary": False,
            "modelName": "grok-3",
            "message": "hello",
            "fileAttachments": [],
            "imageAttachments": [],
            "disableSearch": False,
            "enableImageGeneration": True,
            "returnImageBytes": False,
            "returnRawGrokInXaiRequest": False,
            "enableImageStreaming": True,
            "imageGenerationCount": 2,
            "forceConcise": False,
            "toolOverrides": {},
            "enableSideBySide": True,
            "isPreset": False,
            "sendFinalMetadata": True,
            "customInstructions": "",
            "deepsearchPreset": "",
            "isReasoning": False
        }
        logger.info("=== 初始化完成 ===")

    def _validate_cookies_sync(self) -> None:
        """同步验证所有 Cookie"""
        validation_body = {
            "requestKind": "DEFAULT",
            "modelName": "grok-3"
        }
        
        for cookie in self.cookies:
            try:
                logger.info(f"验证 Cookie: {cookie[:20]}...")
                headers = self.headers.copy()
                headers["Cookie"] = cookie
                
                with httpx.Client(timeout=10.0) as client:
                    response = client.post(
                        f"{self.base_url}/rest/rate-limits",
                        headers=headers,
                        json=validation_body
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if all(k in data for k in ["windowSizeSeconds", "remainingQueries", "totalQueries"]):
                            self.cookie_status[cookie].update({
                                "remaining_queries": data["remainingQueries"],
                                "total_queries": data["totalQueries"],
                                "window_size": data["windowSizeSeconds"],
                                "is_cooling": data["remainingQueries"] <= 0
                            })
                            logger.info(f"✓ Cookie 有效, 剩余额度: {data['remainingQueries']}/{data['totalQueries']}")
                    else:
                        logger.warning(f"✗ Cookie 无效, 状态码: {response.status_code}")
                        logger.debug(response.text)
                        self.cookie_status[cookie]["is_cooling"] = True
                        
            except Exception as e:
                logger.error(f"✗ Cookie 验证失败: {e}")
                self.cookie_status[cookie]["is_cooling"] = True

    async def _check_cookie_status(self, cookie: str) -> bool:
        """检查单个 Cookie 的状态"""
        try:
            headers = self.headers.copy()
            headers["Cookie"] = cookie
            
            validation_body = {
                "requestKind": "DEFAULT",
                "modelName": "grok-3"
            }
            
            response = await self.client.post(
                f"{self.base_url}/rest/rate-limits",
                headers=headers,
                json=validation_body
            )
            
            if response.status_code == 200:
                data = response.json()
                if all(k in data for k in ["windowSizeSeconds", "remainingQueries", "totalQueries"]):
                    self.cookie_status[cookie].update({
                        "remaining_queries": data["remainingQueries"],
                        "total_queries": data["totalQueries"],
                        "window_size": data["windowSizeSeconds"],
                        "is_cooling": data["remainingQueries"] <= 0
                    })
                    return not self.cookie_status[cookie]["is_cooling"]
            return False
                
        except Exception as e:
            logger.error(f"Cookie 状态检查失败: {str(e)}")
            return False

    async def _update_cookie_status(self) -> None:
        """更新所有 Cookie 的状态"""
        current_time = datetime.now()
        
        for cookie, status in self.cookie_status.items():
            if status["is_cooling"]:
                cooling_time = current_time - status["last_used"]
                window_size = status["window_size"] or 7200
                
                if cooling_time >= timedelta(seconds=window_size):
                    await self._check_cookie_status(cookie)

    async def _get_available_cookie(self) -> Optional[str]:
        """获取可用的 Cookie"""
        await self._update_cookie_status()
        
        available_cookies = [
            cookie for cookie, status in self.cookie_status.items()
            if not status["is_cooling"] and (status["remaining_queries"] or 0) > 0
        ]
        
        if not available_cookies:
            logger.warning("没有可用的 Cookie")
            return None
            
        best_cookie = max(
            available_cookies,
            key=lambda x: self.cookie_status[x]["remaining_queries"] or 0
        )
        
        return best_cookie

    async def update_cookie(self) -> None:
        """更新当前使用的 Cookie"""
        cookie = await self._get_available_cookie()
        if not cookie:
            logger.warning("没有可用的 Cookie，继续使用当前 Cookie")
            return
            
        self.headers["Cookie"] = cookie
        self.client.headers = self.headers
        
        status = self.cookie_status[cookie]
        if status["remaining_queries"] is not None:
            status["remaining_queries"] -= 1
        status["last_used"] = datetime.now()
        
        if status["remaining_queries"] <= 0:
            status["is_cooling"] = True
            
        logger.info(f"已更新 Cookie: {cookie[:20]}...")

    def parse_json(self, text: str) -> tuple[Optional[dict], int]:
        """解析 JSON 数据，处理流式输出中可能包含的多个 JSON"""
        try:
            # 查找第一个完整的 JSON 对象的结束位置
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
                        # 找到一个完整的 JSON 对象
                        try:
                            json_str = text[start_pos:i+1]
                            data = json.loads(json_str)
                            return data, i + 1
                        except json.JSONDecodeError:
                            continue
            
            # 没有找到完整的 JSON 对象
            return None, 0
            
        except Exception as e:
            logger.error(f"JSON 解析错误: {e}")
            return None, 0

    async def list_models(self):
        """获取模型列表"""
        logger.info("=== 获取模型列表 ===")
        try:
            # 尝试获取可用的 Cookie
            cookie = await self._get_available_cookie()
            if cookie:
                self.headers["Cookie"] = cookie
                self.client.headers = self.headers
            
            response = await self.client.post(f'{self.base_url}/rest/models')
            
            if response.status_code != 200:
                logger.error(f"获取模型列表失败: 状态码 {response.status_code}")
                return {"object": "list", "data": []}
                
            models = response.json()
            model_list = [
                {
                    "id": f"Grok.com:{model['modelId']}",
                    "object": "model",
                    "owned_by": "xAI",
                    "permission": [
                        {
                            "object": "permission",
                            "id": f"model-{model['modelId']}-permission",
                            "created": int(time.time()),
                            "allow_create_engine": True,
                            "allow_fine_tuning": False,
                            "organization": "*",
                            "scope": "*"
                        }
                    ]
                }
                for model in models.get("models", [])
            ]

            logger.info(f"获取到 {len(model_list)} 个模型")
            return {
                "object": "list",
                "data": model_list
            }
        except Exception as e:
            logger.error(f"获取模型失败: {e}")
            return {"object": "list", "data": []}

    def remove_prefix_from_model_id(self, model_id: str) -> str:
        """移除模型 ID 前缀"""
        if model_id.startswith("Grok.com:"):
            return model_id[len("Grok.com:"):]
        return model_id

    async def request2Grok(self, messages: str, model: str):
        """发送请求到 Grok"""
        try:
            # 获取并更新 Cookie
            current_cookie = await self._get_available_cookie()
            if not current_cookie:
                logger.warning("没有可用的 Cookie，但仍将尝试使用当前 Cookie")
                yield "警告: 没有可用的 Cookie，响应可能会失败。请检查您的 Cookie 配置。"
                current_cookie = self.headers.get("Cookie", "")
            else:
                self.headers["Cookie"] = current_cookie
                self.client.headers = self.headers
            
            cookie_status = self.cookie_status.get(current_cookie, {
                "remaining_queries": "未知",
                "total_queries": "未知"
            })
            
            logger.info("=== 请求状态 ===")
            logger.info(f"当前 Cookie: {current_cookie[:20]}...")
            logger.info(f"剩余额度: {cookie_status.get('remaining_queries')}/{cookie_status.get('total_queries')}")
            logger.info(f"发送请求到: {self.base_url}")
            logger.info(f"使用模型: {model}")
            
            await self.update_cookie()
            
            model_id = self.remove_prefix_from_model_id(model)
            self.request_body.update({
                'modelName': model_id,
                'message': messages
            })
            
            logger.info("发送 POST 请求...")
            buffer = ""
            
            try:
                response = await self.client.post(
                    url=f'{self.base_url}/rest/app-chat/conversations/new',
                    json=self.request_body
                )
                response.raise_for_status()
                logger.info(f"请求成功: 状态码 {response.status_code}")
                
                async for chunk in response.aiter_text():
                    buffer += chunk
                    logger.debug(f"接收到数据块: {len(chunk)} 字节")
                    
                    while True:
                        data, next_pos = self.parse_json(buffer)
                        if data is None:
                            break
                            
                        response_data = data.get("result", {}).get("response", {})
                        token = response_data.get("token", "")
                        is_soft_stop = response_data.get("isSoftStop", False)
                        
                        if token:
                            logger.debug(f"生成 token: {token}")
                            yield token
                        
                        if is_soft_stop:
                            logger.info("检测到结束标志，完成响应")
                            return
                        
                        buffer = buffer[next_pos:]
                
            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP 错误: {e.response.status_code} - {e.response.reason_phrase}"
                logger.error(error_msg)
                
                # 更新 Cookie 状态
                if current_cookie in self.cookie_status:
                    if e.response.status_code in [401, 403]:
                        self.cookie_status[current_cookie]["is_cooling"] = True
                        logger.warning(f"Cookie 已失效或无权限，已标记为冷却状态")
                
                yield f"请求失败: {error_msg}"
                return
                
            except httpx.RequestError as e:
                error_msg = f"请求错误: {str(e)}"
                logger.error(error_msg)
                yield f"请求错误: {str(e)}"
                return
                
        except Exception as e:
            error_msg = f"请求处理错误: {str(e)}"
            logger.error(error_msg)
            yield f"处理错误: {str(e)}"
            return

# 示例使用
async def main():
    try:
        # 替换为实际的 Cookie
        cookies = ["your_cookie_here"]
        
        async with GrokReverser_g(Cookies=cookies) as grok:
            messages = "Hello, how are you?"
            model = "Grok.com:grok-3"
            
            async for chunk in grok.request2Grok(messages, model):
                print(chunk, end="", flush=True)
                
    except Exception as e:
        logger.error(f"运行错误: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())