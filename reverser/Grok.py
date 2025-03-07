import asyncio
import json
import time
import logging
import sys
import cloudscraper
from concurrent.futures import ThreadPoolExecutor
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

class AsyncCloudScraper:
    """异步包装器，用于在异步环境中使用cloudscraper"""
    
    def __init__(self, headers=None, **kwargs):
        """初始化异步cloudscraper包装器"""
        self.headers = headers or {}
        self.scraper_kwargs = kwargs
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False
            },
            delay=0.1,
            interpreter='js2py',
            **kwargs
        )
        
        # 更新headers
        if headers:
            self.scraper.headers.update(headers)
    
    async def close(self):
        """关闭执行器"""
        self.executor.shutdown(wait=False)
    
    async def _run_in_executor(self, func, *args, **kwargs):
        """在线程池中执行同步函数"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, lambda: func(*args, **kwargs))
    
    async def get(self, url, **kwargs):
        """执行GET请求"""
        return await self._run_in_executor(self.scraper.get, url, **kwargs)
    
    async def post(self, url, **kwargs):
        """执行POST请求"""
        return await self._run_in_executor(self.scraper.post, url, **kwargs)
    
    async def put(self, url, **kwargs):
        """执行PUT请求"""
        return await self._run_in_executor(self.scraper.put, url, **kwargs)
    
    async def delete(self, url, **kwargs):
        """执行DELETE请求"""
        return await self._run_in_executor(self.scraper.delete, url, **kwargs)
    
    def update_headers(self, headers):
        """更新headers"""
        self.headers.update(headers)
        self.scraper.headers.update(headers)

    async def aiter_text(self, response):
        """
        模拟httpx的aiter_text方法，为流式响应提供异步迭代器
        """
        # 因为cloudscraper没有直接的流式响应处理方式，我们模拟一个
        # 这里假设响应内容已经完全获取，我们将其分块返回
        if hasattr(response, 'text'):
            text = response.text
            chunk_size = 1024  # 可以调整块大小
            
            for i in range(0, len(text), chunk_size):
                chunk = text[i:i + chunk_size]
                yield chunk
                await asyncio.sleep(0.01)  # 给其他任务一些执行时间

class GrokReverser:
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.client = AsyncCloudScraper(headers=self.headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if exc_type:
            logger.error(f"错误: {exc_type.__name__}: {exc_val}")
        await self.client.close()

    def __init__(self, Cookies: list = None, cookie_manager=None, num: int = 5):
        """初始化 GrokReverser"""
        logger.info("=== 初始化 GrokReverser ===")
        
        # 使用Cookie管理器或直接使用Cookies列表
        self.cookie_manager = cookie_manager
        self.cookies = Cookies or []
        
        # 确保总是初始化cookie_status字典，即使使用cookie_manager
        self.cookie_status = {}
        
        if cookie_manager:
            # 如果有Cookie管理器，尝试获取第一个可用Cookie
            try:
                first_cookie = cookie_manager.get_next_cookie()
                logger.info("使用Cookie管理器提供的Cookie")
                # 为cookie_manager提供的cookie初始化状态
                self.cookie_status[first_cookie] = {
                    "last_used": datetime.now(),
                    "remaining_queries": 0,
                    "total_queries": 0,
                    "window_size": 7200,
                    "is_cooling": False
                }
            except Exception as e:
                logger.error(f"从Cookie管理器获取Cookie失败: {str(e)}")
                first_cookie = self.cookies[0] if self.cookies else ""
        else:
            # 否则使用提供的Cookies列表
            first_cookie = self.cookies[0] if self.cookies else ""
            
            # 初始化Cookie状态 (仅当不使用Cookie管理器时为所有cookies初始化)
            if self.cookies:
                self.cookie_status = {
                    cookie: {
                        "last_used": datetime.now(),
                        "remaining_queries": 0,
                        "total_queries": 0,
                        "window_size": 7200,
                        "is_cooling": False
                    } for cookie in self.cookies
                }
            
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

        # 验证所有Cookie (仅当不使用Cookie管理器时)
        if not cookie_manager and self.cookies:
            logger.info("正在验证所有 Cookie...")
            self._validate_cookies_sync()
            
            valid_cookies = sum(1 for status in self.cookie_status.values() if not status["is_cooling"])
            logger.info(f"有效 Cookie 数量: {valid_cookies}/{len(self.cookies)}")
        # 如果使用cookie_manager，立即获取并刷新当前cookie的状态信息
        elif cookie_manager:
            logger.info("使用Cookie管理器并主动刷新当前Cookie状态...")
            validation_body = {
                "requestKind": "DEFAULT",
                "modelName": "grok-3"
            }
            
            try:
                scraper = cloudscraper.create_scraper(
                    browser={
                        'browser': 'chrome',
                        'platform': 'windows',
                        'mobile': False
                    }
                )
                scraper.headers.update(self.headers)
                
                response = scraper.post(
                    f"{self.base_url}/rest/rate-limits",
                    json=validation_body
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if all(k in data for k in ["windowSizeSeconds", "remainingQueries", "totalQueries"]):
                        # 更新当前Cookie的状态
                        self.cookie_status[first_cookie].update({
                            "remaining_queries": int(data["remainingQueries"]) if data["remainingQueries"] is not None else 0,
                            "total_queries": int(data["totalQueries"]) if data["totalQueries"] is not None else 0,
                            "window_size": int(data["windowSizeSeconds"]) if data["windowSizeSeconds"] is not None else 7200,
                            "is_cooling": int(data["remainingQueries"]) <= 0 if data["remainingQueries"] is not None else False
                        })
                        logger.info(f"Cookie状态刷新成功, 剩余额度: {data['remainingQueries']}/{data['totalQueries']}")
                    else:
                        logger.warning("无法获取完整的API限制信息")
                else:
                    logger.warning(f"刷新Cookie状态失败: 状态码 {response.status_code}")
            except Exception as e:
                logger.error(f"刷新Cookie状态时出错: {str(e)}")
        
        self.num = num
        self.request_count = 0
        # 用于记录CF盾检测状态
        self.cf_challenge_count = 0
        self.last_cf_challenge = None

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
                
                scraper = cloudscraper.create_scraper(
                    browser={
                        'browser': 'chrome',
                        'platform': 'windows',
                        'mobile': False
                    }
                )
                scraper.headers.update(headers)
                
                response = scraper.post(
                    f"{self.base_url}/rest/rate-limits",
                    json=validation_body
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if all(k in data for k in ["windowSizeSeconds", "remainingQueries", "totalQueries"]):
                        self.cookie_status[cookie].update({
                            "remaining_queries": int(data["remainingQueries"]) if data["remainingQueries"] is not None else 0,
                            "total_queries": int(data["totalQueries"]) if data["totalQueries"] is not None else 0,
                            "window_size": int(data["windowSizeSeconds"]) if data["windowSizeSeconds"] is not None else 7200,
                            "is_cooling": int(data["remainingQueries"]) <= 0 if data["remainingQueries"] is not None else False
                        })
                        logger.info(f"✓ Cookie 有效, 剩余额度: {data['remainingQueries']}/{data['totalQueries']}")
                elif response.status_code == 403:
                    # 检查是否是CF盾的问题
                    if "cloudflare" in response.text.lower():
                        logger.warning(f"✗ Cookie 被CloudFlare盾拦截")
                        self.cf_challenge_count += 1
                        self.last_cf_challenge = datetime.now()
                    else:
                        logger.warning(f"✗ Cookie 无效, 状态码: 403")
                    self.cookie_status[cookie]["is_cooling"] = True
                else:
                    logger.warning(f"✗ Cookie 无效, 状态码: {response.status_code}")
                    self.cookie_status[cookie]["is_cooling"] = True
            except Exception as e:
                logger.error(f"✗ Cookie 验证失败: {e}")
                self.cookie_status[cookie]["is_cooling"] = True

    async def _check_cookie_status(self, cookie: str) -> bool:
        """检查单个 Cookie 的状态"""
        try:
            # 如果使用cookie_manager且cookie不在cookie_status中，先初始化
            if cookie not in self.cookie_status:
                self.cookie_status[cookie] = {
                    "last_used": datetime.now(),
                    "remaining_queries": 0,   # 默认为0
                    "total_queries": 0,       # 默认为0
                    "window_size": 7200,      # 默认值
                    "is_cooling": False
                }
                
            validation_body = {
                "requestKind": "DEFAULT",
                "modelName": "grok-3"
            }
            
            headers = self.headers.copy()
            headers["Cookie"] = cookie
            
            # 使用临时客户端以避免影响主客户端的状态
            temp_client = AsyncCloudScraper(headers=headers)
            
            try:
                response = await temp_client.post(
                    f"{self.base_url}/rest/rate-limits",
                    json=validation_body
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if all(k in data for k in ["windowSizeSeconds", "remainingQueries", "totalQueries"]):
                        self.cookie_status[cookie].update({
                            "remaining_queries": int(data["remainingQueries"]) if data["remainingQueries"] is not None else 0,
                            "total_queries": int(data["totalQueries"]) if data["totalQueries"] is not None else 0,
                            "window_size": int(data["windowSizeSeconds"]) if data["windowSizeSeconds"] is not None else 7200,
                            "is_cooling": int(data["remainingQueries"]) <= 0 if data["remainingQueries"] is not None else False
                        })
                        return not self.cookie_status[cookie]["is_cooling"]
                elif response.status_code == 403:
                    # 检查是否是CF盾的问题
                    if "cloudflare" in response.text.lower():
                        logger.warning(f"Cookie被CloudFlare盾拦截")
                        self.cf_challenge_count += 1
                        self.last_cf_challenge = datetime.now()
                        return False
            finally:
                await temp_client.close()
                
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
        # 当使用cookie_manager时，从管理器获取cookie
        if self.cookie_manager:
            try:
                cookie = self.cookie_manager.get_next_cookie()
                # 确保cookie被初始化到cookie_status
                if cookie not in self.cookie_status:
                    self.cookie_status[cookie] = {
                        "last_used": datetime.now(),
                        "remaining_queries": 0,   # 默认为0
                        "total_queries": 0,       # 默认为0
                        "window_size": 7200,      # 默认值
                        "is_cooling": False
                    }
                return cookie
            except Exception as e:
                logger.error(f"从Cookie管理器获取Cookie失败: {e}")
                return None
        
        # 当不使用cookie_manager时，使用内部逻辑
        await self._update_cookie_status()
        
        available_cookies = [
            cookie for cookie, status in self.cookie_status.items()
            if not status["is_cooling"] and int(status.get("remaining_queries", 0)) > 0
        ]
        
        if not available_cookies:
            logger.warning("没有可用的 Cookie")
            return None
            
        best_cookie = max(
            available_cookies,
            key=lambda x: int(self.cookie_status[x].get("remaining_queries", 0))
        )
        
        return best_cookie

    async def update_cookie(self) -> None:
        """更新当前使用的 Cookie"""
        cookie = await self._get_available_cookie()
        if not cookie:
            logger.warning("没有可用的 Cookie，继续使用当前 Cookie")
            return
            
        self.headers["Cookie"] = cookie
        self.client.update_headers({"Cookie": cookie})
        
        status = self.cookie_status[cookie]
        if "remaining_queries" in status and status["remaining_queries"] is not None:
            status["remaining_queries"] = max(0, int(status["remaining_queries"]) - 1)
        status["last_used"] = datetime.now()
        
        if int(status.get("remaining_queries", 0)) <= 0:
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
        max_retries = 3
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                # 尝试获取可用的 Cookie
                cookie = await self._get_available_cookie()
                if cookie:
                    self.headers["Cookie"] = cookie
                    self.client.update_headers({"Cookie": cookie})
                
                response = await self.client.post(f'{self.base_url}/rest/models')
                
                if response.status_code == 403:
                    # 检查是否是CF盾问题
                    response_text = response.text.lower() if hasattr(response, 'text') else ""
                    if "cloudflare" in response_text:
                        retry_count += 1
                        logger.warning(f"请求被CloudFlare盾拦截 (尝试 {retry_count}/{max_retries})")
                        
                        # 处理CloudFlare挑战
                        await self.handle_cloudflare_challenge()
                        
                        # 如果还有重试次数，继续循环
                        if retry_count <= max_retries:
                            continue
                        else:
                            logger.error(f"无法绕过CloudFlare保护，已达到最大重试次数 ({max_retries})")
                            return {"object": "list", "data": [], "error": "CloudFlare protection detected"}
                    else:
                        logger.error(f"获取模型列表失败: 状态码 403 (非CloudFlare)")
                        return {"object": "list", "data": []}
                
                if response.status_code != 200:
                    logger.error(f"获取模型列表失败: 状态码 {response.status_code}")
                    logger.error(f"返回的Text: {response.text}")
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
                retry_count += 1
                error_msg = str(e).lower()
                
                if "cloudflare" in error_msg or "403" in error_msg:
                    logger.warning(f"可能遇到CloudFlare挑战 (尝试 {retry_count}/{max_retries}): {error_msg}")
                    await self.handle_cloudflare_challenge()
                    
                    if retry_count <= max_retries:
                        logger.info("继续尝试获取模型列表...")
                        continue
                
                logger.error(f"获取模型失败: {str(e)}")
                return {"object": "list", "data": []}

    def remove_prefix_from_model_id(self, model_id: str) -> str:
        """移除模型 ID 前缀"""
        if model_id.startswith("Grok.com:"):
            return model_id[len("Grok.com:"):]
        return model_id

    async def handle_cloudflare_challenge(self):
        """处理CloudFlare挑战"""
        logger.warning("检测到CloudFlare挑战，尝试重新创建scraper以绕过保护...")
        
        # 创建新的cloudscraper实例
        self.client = AsyncCloudScraper(
            headers=self.headers, 
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False
            },
            delay=1.0  # 增加延迟以解决一些CF挑战
        )
        
        # 记录挑战事件
        self.cf_challenge_count += 1
        self.last_cf_challenge = datetime.now()
        
        return True

    async def check_response_for_errors(self, response):
        """检查响应中的错误，特别是403错误"""
        if response.status_code == 403:
            if "cloudflare" in response.text.lower():
                logger.warning("检测到CloudFlare保护")
                await self.handle_cloudflare_challenge()
                return False
            else:
                logger.warning(f"403错误，但不是CloudFlare引起的: {response.text[:200]}")
                return False
        return True

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
                self.client.update_headers({"Cookie": current_cookie})
            
            cookie_status = self.cookie_status.get(current_cookie, {
                "remaining_queries": 0,   # 默认为0
                "total_queries": 0        # 默认为0
            })
            
            logger.info("=== 请求状态 ===")
            logger.info(f"当前 Cookie: {current_cookie[:20]}...")
            logger.info(f"剩余额度: {cookie_status.get('remaining_queries', 0)}/{cookie_status.get('total_queries', 0)}")
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
            
            # 计数器用于重试逻辑
            retry_count = 0
            max_retries = 3
            
            while retry_count <= max_retries:
                try:
                    response = await self.client.post(
                        url=f'{self.base_url}/rest/app-chat/conversations/new',
                        json=self.request_body
                    )
                    
                    # 检查403和CloudFlare挑战
                    if response.status_code == 403:
                        if "cloudflare" in response.text:
                            retry_count += 1
                            logger.warning(f"检测到CloudFlare保护，尝试绕过 (尝试 {retry_count}/{max_retries})")
                            await self.handle_cloudflare_challenge()
                            # 如果还有重试次数，继续循环
                            if retry_count <= max_retries:
                                continue
                            else:
                                yield f"无法绕过CloudFlare保护，已达到最大重试次数 ({max_retries})"
                                return
                        else:
                            logger.error(f"403错误，但不是CloudFlare引起的: {response.text[:200]}")
                            yield f"请求被拒绝（状态码403），但不是由CloudFlare引起的。可能是Cookie无效或其他授权问题。"
                            return
                    
                    response.raise_for_status()
                    logger.info(f"请求成功: 状态码 {response.status_code}")
                    
                    # 成功发送请求，退出重试循环
                    break
                    
                except Exception as e:
                    retry_count += 1
                    logger.error(f"请求错误 (尝试 {retry_count}/{max_retries}): {str(e)}")
                    
                    if "cloudflare" in str(e).lower():
                        await self.handle_cloudflare_challenge()
                        if retry_count <= max_retries:
                            continue
                    
                    if retry_count > max_retries:
                        yield f"请求失败，已达到最大重试次数: {str(e)}"
                        return
            
            # 处理成功的响应
            try:
                async for chunk in self.client.aiter_text(response):
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
                
            except Exception as e:
                error_msg = f"处理响应错误: {str(e)}"
                logger.error(error_msg)
                yield f"处理响应错误: {str(e)}"
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
        
        async with GrokReverser(Cookies=cookies) as grok:
            messages = "Hello, how are you?"
            model = "Grok.com:grok-3"
            
            async for chunk in grok.request2Grok(messages, model):
                print(chunk, end="", flush=True)
                
    except Exception as e:
        logger.error(f"运行错误: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())