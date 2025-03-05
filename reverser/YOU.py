import json
import logging
import shutil
import sys
import uuid
import time
import os
import asyncio
from typing import Dict, List, Optional, Generator, Any, AsyncGenerator
import aiohttp
import requests
import random
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/youcom_client.log', encoding='utf-8', mode='a')
    ]
)
logger = logging.getLogger("YouClient")

class YouComReverser:
    """You.com API客户端实现"""
    
    def __init__(self, cookies: List[str] = [], cookie_manager=None):
        """初始化You.com客户端
        
        Args:
            cookies: Cookie字符串列表
            cookie_manager: Cookie管理器实例
        """
        logger.info("初始化You.com客户端")
        
        # 创建logs目录（如果不存在）
        os.makedirs("logs", exist_ok=True)
        
        # 使用提供的Cookie管理器或创建新的
        self.cookie_manager = cookie_manager
        
        # 获取初始Cookie
        if cookies and self.cookie_manager:
            try:
                current_cookie = self.cookie_manager.get_next_cookie()
                logger.info("初始Cookie验证成功")
            except Exception as e:
                logger.error(f"初始Cookie验证失败: {str(e)}")
                current_cookie = cookies[0] if cookies else ""
        else:
            current_cookie = ""
            logger.warning("未提供Cookie或Cookie管理器")
        
        self.base_url = 'https://you.com'
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": current_cookie
        }
        
        # 初始化数据容器
        self.email = "UNKNOWN"
        self.subscription_info = {}
        self.ai_models = []

        
        # 请求统计
        self.request_stats = {
            "total_requests": 0,
            "requests_by_model": {},
            "requests_by_date": {}
        }
        
        # 获取初始数据
        if cookies:
            self._fetch_initial_data()
        
        logger.info("You.com客户端初始化完成")
    
    def _update_cookie(self) -> bool:
        """更新当前使用的Cookie
        
        Returns:
            是否成功更新Cookie
        """
        try:
            if self.cookie_manager:
                cookie = self.cookie_manager.get_next_cookie()
                self.headers["Cookie"] = cookie
                logger.info("已更新Cookie")
                return True
            return False
        except Exception as e:
            logger.error(f"更新Cookie失败: {str(e)}")
            return False
    
    def _fetch_initial_data(self) -> None:
        """从You.com获取初始数据"""
        logger.info("获取初始数据...")
        try:
            response = requests.get(
                headers=self.headers,
                url=f'{self.base_url}/_next/data/ee50cd42bdfa0bd3ad044daa2349a6179381d5ef/en-US/search.json'
            )
            
            # 检查是否需要更新Cookie
            if response.status_code == 403:
                logger.warning("Cookie已失效，尝试更新Cookie")
                if self._update_cookie():
                    # 重新尝试请求
                    response = requests.get(
                        headers=self.headers,
                        url=f'{self.base_url}/_next/data/ee50cd42bdfa0bd3ad044daa2349a6179381d5ef/en-US/search.json'
                    )
            
            if response.status_code == 200:
                data = response.json()
                
                # 从launchDarklyContext提取邮箱
                launch_darkly_context = data.get("pageProps", {}).get("launchDarklyContext", {})
                self.email = launch_darkly_context.get("email", "UNKNOWN")
                logger.info(f"邮箱: {self.email}")
                
                # 提取订阅信息
                you_pro_state = data.get("pageProps", {}).get("youProState", {})
                if you_pro_state:
                    subscriptions = you_pro_state.get("subscriptions", [])
                    if subscriptions:
                        for sub in subscriptions:
                            self.subscription_info = {
                                "service": sub.get("service"),
                                "tier": sub.get("tier"),
                                "plan_name": sub.get("plan_name"),
                                "subscription_id": sub.get("subscription_id"),
                                "provider": sub.get("provider"),
                                "start_date": sub.get("start_date"),
                                "cancel_at_period_end": sub.get("cancel_at_period_end"),
                                "interval": sub.get("interval")
                            }
                            logger.info(f"订阅: {self.subscription_info.get('service', 'unknown')} - {self.subscription_info.get('tier', 'unknown')}")
                
                # 提取AI模型
                self.ai_models = data.get("pageProps", {}).get("aiModels", [])
                logger.info(f"找到 {len(self.ai_models)} 个AI模型")
                
            else:
                logger.error(f"获取初始数据错误: 状态码 {response.status_code}")
                
        except Exception as e:
            logger.error(f"获取初始数据错误: {str(e)}")
    
    def _generate_trace_id(self) -> str:
        """生成跟踪ID
        
        Returns:
            生成的跟踪ID
        """
        return str(uuid.uuid4())
    
    def get_account_info(self) -> Dict:
        """获取账户信息
        
        Returns:
            账户信息字典
        """
        return {
            "object": "account",
            "email": self.email,
            "subscription": self.subscription_info
        }
        
    def list_models(self) -> List[Dict]:
        """获取模型列表
        
        Returns:
            模型列表
        """
        model_list = []
        
        for model in self.ai_models:
            model_list.append({
                "id": f"You.com:{model.get('id')}",
                "object": "model",
                "created": 1677610602,
                "owned_by": model.get('company', 'unknown'),
                "permission": [],
                "root": model.get('id'),
                "parent": None,
                "context_length": model.get('contextLimit', 4096)
            })
        
        return model_list
    
    def upload_file(self, file_path: str) -> Dict:
        """上传文件到You.com
        
        Args:
            file_path: 文件路径
            
        Returns:
            上传文件的信息
        
        Raises:
            Exception: 上传失败时抛出异常
        """
        logger.info(f"上传文件: {file_path}")
        
        try:
            # 准备文件
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            # 生成一个类似WebKit的边界
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
            
            # 设置正确的Content-Type
            temp_headers = self.headers.copy()
            temp_headers.update({
                'Content-Type': f'multipart/form-data; boundary={boundary}',
                'Accept': '*/*',
                'Origin': 'https://you.com',
                'Referer': 'https://you.com/chat'
            })
            
            # 手动构建multipart/form-data请求体
            with open(file_path, 'rb') as f:
                file_content = f.read()
                
            body = []
            # 添加文件部分
            body.append(f'--{boundary}'.encode())
            body.append(f'Content-Disposition: form-data; name="file"; filename="{file_name}"'.encode())
            body.append(f'Content-Type: text/plain'.encode())
            body.append(b'')
            body.append(file_content)
            body.append(f'--{boundary}--'.encode())
            
            # 发送请求
            logger.info("尝试上传文件")
            response = requests.post(
                f'{self.base_url}/api/upload',
                headers=temp_headers,
                data=b'\r\n'.join(body)
            )
            
            # 检查是否需要更新Cookie
            if response.status_code == 403:
                logger.warning("文件上传失败，Cookie已失效，尝试更新Cookie")
                if self._update_cookie():
                    # 更新请求头
                    temp_headers["Cookie"] = self.headers["Cookie"]
                    # 重新尝试请求
                    response = requests.post(
                        f'{self.base_url}/api/upload',
                        headers=temp_headers,
                        data=b'\r\n'.join(body)
                    )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"文件上传成功")
                
                # 更新请求统计
                current_cookie = self.headers["Cookie"]
                if self.cookie_manager:
                    self.cookie_manager.increment_request_count(self.cookie_manager.current_index)
                
                # 返回文件信息
                return {
                    "source_type": "user_file",
                    "filename": result.get("filename"),
                    "user_filename": result.get("user_filename", file_name),
                    "size_bytes": file_size
                }
            else:
                logger.error(f"文件上传失败: 状态码 {response.status_code}")
                logger.error(f"响应: {response.text}")
                raise Exception(f"文件上传失败: 状态码 {response.status_code}")
                    
        except Exception as e:
            logger.error(f"文件上传错误: {str(e)}")
            raise
        
    def _parse_sse_response(self, response) -> Generator[Dict, None, None]:
        """解析SSE响应
        
        Args:
            response: 请求响应对象
                
        Yields:
            解析后的事件数据
        """
        try:
            buffer = ""
            thinking_mode = False
            
            # 逐行读取响应
            for line in response.iter_lines():
                # 添加错误处理，防止连接中断
                try:
                    if not line:
                        # 空行表示事件结束
                        if buffer:
                            # 处理完整事件
                            event_type = None
                            event_data = None
                            
                            # 解析事件类型和数据
                            for part in buffer.split('\n'):
                                if part.startswith('event:'):
                                    event_type = part[6:].strip()
                                elif part.startswith('data:'):
                                    event_data = part[5:].strip()
                            
                            # 处理事件
                            if event_type and event_data:
                                try:
                                    data = json.loads(event_data)
                                except json.JSONDecodeError:
                                    data = event_data
                                
                                
                                # 处理不同类型的事件
                                if event_type == "youChatUpdate" and isinstance(data, dict) and "t" in data:
                                    # 思维链部分
                                    if not thinking_mode:
                                        thinking_mode = True
                                        yield {"type": "thinking_start"}
                                    
                                    thinking_content = data.get("t", "")
                                    yield {
                                        "type": "thinking",
                                        "content": thinking_content
                                    }
                                elif event_type == "youChatToken":
                                    # 实际回复部分
                                    if thinking_mode:
                                        thinking_mode = False
                                        yield {"type": "thinking_end"}
                                    
                                    token = ""
                                    if isinstance(data, dict):
                                        token = data.get("youChatToken", "")
                                    
                                    yield {
                                        "type": "token",
                                        "content": token
                                    }
                                elif event_type == "done":
                                    # 响应完成
                                    if thinking_mode:
                                        thinking_mode = False
                                        yield {"type": "thinking_end"}
                                    
                                    yield {
                                        "type": "done",
                                        "content": data
                                    }
                                else:
                                    # 其他事件类型
                                    yield {
                                        "type": event_type,
                                        "content": data
                                    }
                            
                            # 重置缓冲区
                            buffer = ""
                        continue
                    
                    # 将行添加到缓冲区
                    line_str = line.decode('utf-8', errors='replace')
                    if buffer:
                        buffer += '\n'
                    buffer += line_str
                except Exception as line_error:
                    logger.warning(f"处理SSE行时出错: {str(line_error)}")
                    # 继续处理下一行，而不是中断整个流程
                    continue
            
            # 确保思维模式正确结束
            if thinking_mode:
                yield {"type": "thinking_end"}
                
        except Exception as e:
            # 详细的错误信息
            logger.error(f"解析SSE响应错误: {str(e)}")
            logger.error(f"响应状态码: {response.status_code}")
            
            # 尝试获取响应内容
            try:
                content_preview = ""
                if hasattr(response, 'text'):
                    content_preview = response.text[:1000]
                elif hasattr(response, 'raw'):
                    content_preview = response.raw.read(1000).decode('utf-8', errors='replace')
            except:
                content_preview = "无法获取响应内容"
                
            logger.error(f"响应内容前1000字符: {content_preview}")
            # 不抛出异常，而是返回一个错误事件
            yield {
                "type": "error",
                "content": f"解析SSE响应失败: <Response [{response.status_code}]>"
            }
                    
    
    async def chat(self, 
                message: str, 
                files: List[Dict] = None, 
                model: str = "claude_3_5_sonnet", 
                chat_mode: str = "custom") -> AsyncGenerator[str, None]:
        """发送聊天请求并处理响应（异步版本）"""
        
        # 获取聊天模式（如果有Cookie管理器）
        if self.cookie_manager and hasattr(self.cookie_manager, 'get_chat_mode'):
            chat_mode = self.cookie_manager.get_chat_mode(model)
            logger.info(f"使用Cookie管理器提供的聊天模式: {chat_mode}")
        
        # 生成必要的ID
        chat_id = self._generate_trace_id()
        conversation_turn_id = self._generate_trace_id()
        query_trace_id = chat_id
        trace_id = f"{chat_id}|{conversation_turn_id}|{int(time.time() * 1000)}"
        
        # 准备请求参数 - 修复参数格式
        params = {
            "page": 1,
            "count": 10,
            "safeSearch": "Off",
            "mkt": "en-GB",
            "enable_worklow_generation_ux": "true",  # 使用布尔值而非字符串
            "incognito": "true",  # 修复拼写和类型
            "domain": "youchat",
            "use_personalization_extraction": "true",
            "queryTraceId": query_trace_id,
            "chatId": chat_id,
            "conversationTurnId": conversation_turn_id,
            "pastChatLength": 0,
            "selectedChatMode": chat_mode,
            "selectedAiModel": model,
            "enable_agent_clarification_questions": "true",
            "traceId": trace_id,
            "use_nested_youchat_updates": "true",
            "q": message,
            "chat": []
        }
        
        # 添加文件信息
        if files:
            params["sources"] = json.dumps(files)
        
        logger.info(f"发送聊天请求: {message[:50]}...")

        try:
            # 使用aiohttp发送异步请求，正确配置流式处理
            timeout = aiohttp.ClientTimeout(total=None)  # 无总超时
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f'{self.base_url}/api/streamingSearch',
                    headers=self.headers,
                    params=params
                ) as response:
                    logger.info(f"聊天请求返回状态码:{response.status}")
                    
                    # 检查是否需要更新Cookie
                    if response.status == 403:
                        logger.warning("聊天请求失败，Cookie已失效，尝试更新Cookie")
                        if self._update_cookie():
                            # 重新尝试请求
                            async with session.get(
                                f'{self.base_url}/api/streamingSearch',
                                headers=self.headers,
                                params=params
                            ) as response:
                                if response.status != 200:
                                    logger.error(f"聊天请求失败: 状态码 {response.status}")
                                    error_text = await response.text()
                                    logger.error(f"响应: {error_text}")
                                    raise Exception(f"聊天请求失败: 状态码 {response.status}")
                                
                                # 处理响应
                                full_response = ""
                                in_thinking = False
                                
                                # 使用正确的流式处理方法
                                buffer = ""
                                async for chunk, _ in response.content.iter_chunks():
                                    text = chunk.decode('utf-8', errors='replace')
                                    buffer += text
                                    
                                    # 处理完整的SSE事件
                                    while '\n\n' in buffer:
                                        parts = buffer.split('\n\n', 1)
                                        event_text = parts[0]
                                        buffer = parts[1]
                                        
                                        # 解析事件
                                        event_type = None
                                        event_data = None
                                        
                                        for line in event_text.split('\n'):
                                            if line.startswith('event:'):
                                                event_type = line[6:].strip()
                                            elif line.startswith('data:'):
                                                event_data = line[5:].strip()
                                        
                                        # 处理事件
                                        if event_type and event_data:
                                            try:
                                                data = json.loads(event_data)
                                            except json.JSONDecodeError:
                                                data = event_data
                                            
                                            # 处理不同类型的事件
                                            if event_type == "youChatUpdate" and isinstance(data, dict) and "t" in data:
                                                if not in_thinking:
                                                    in_thinking = True
                                                    yield "<Model_thinking>\n\n"
                                                yield data.get("t", "")
                                            elif event_type == "youChatToken":
                                                if in_thinking:
                                                    in_thinking = False
                                                    yield "\n\n</Model_thinking>\n\n"
                                                
                                                token = ""
                                                if isinstance(data, dict):
                                                    token = data.get("youChatToken", "")
                                                
                                                full_response += token
                                                yield token
                                            elif event_type == "done":
                                                if in_thinking:
                                                    in_thinking = False
                                                    yield "\n\n</Model_thinking>\n\n"
                                                break
                        else:
                            raise Exception("更新Cookie失败")
                    
                    elif response.status != 200:
                        logger.error(f"聊天请求失败: 状态码 {response.status}")
                        error_text = await response.text()
                        logger.error(f"响应: {error_text}")
                        raise Exception(f"聊天请求失败: 状态码 {response.status}")
                    
                    # 处理响应 - 使用正确的流式处理方法
                    full_response = ""
                    in_thinking = False
                    
                    buffer = ""
                    async for chunk, _ in response.content.iter_chunks():
                        text = chunk.decode('utf-8', errors='replace')
                        buffer += text
                        
                        # 处理完整的SSE事件
                        while '\n\n' in buffer:
                            parts = buffer.split('\n\n', 1)
                            event_text = parts[0]
                            buffer = parts[1]
                            
                            # 解析事件
                            event_type = None
                            event_data = None
                            
                            for line in event_text.split('\n'):
                                if line.startswith('event:'):
                                    event_type = line[6:].strip()
                                elif line.startswith('data:'):
                                    event_data = line[5:].strip()
                            
                            # 处理事件
                            if event_type and event_data:
                                try:
                                    data = json.loads(event_data)
                                except json.JSONDecodeError:
                                    data = event_data
                                
                                # 处理不同类型的事件
                                if event_type == "youChatUpdate" and isinstance(data, dict) and "t" in data:
                                    if not in_thinking:
                                        in_thinking = True
                                        yield "<Model_thinking>\n\n"
                                    yield data.get("t", "")
                                elif event_type == "youChatToken":
                                    if in_thinking:
                                        in_thinking = False
                                        yield "\n\n</Model_thinking>\n\n"
                                    
                                    token = ""
                                    if isinstance(data, dict):
                                        token = data.get("youChatToken", "")
                                    
                                    full_response += token
                                    yield token
                                elif event_type == "done":
                                    if in_thinking:
                                        in_thinking = False
                                        yield "\n\n</Model_thinking>\n\n"
                                    break

        except Exception as e:
            logger.error(f"聊天请求错误: {str(e)}")
            raise
        
    def convert_and_upload_chat_history(self, 
                                    messages: List[Dict], 
                                    filename: str = "chat_history.txt", 
                                    use_prefixes: bool = False) -> Dict:
        """将OpenAI格式的聊天历史转换为txt文件并上传
        
        Args:
            messages: OpenAI格式的聊天历史 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
            filename: 要创建的文件名
            use_prefixes: 是否在每条消息前添加Human/Assistant前缀
            
        Returns:
            上传文件的信息
        """
        logger.info(f"转换并上传聊天历史，文件名: {filename}, 使用前缀: {use_prefixes}")
        
        # 创建消息文件
        message_path = "Message.txt"
        with open(message_path, mode='w+', encoding='utf-8') as message_file:
            # 将聊天历史写入文件
            for message in messages:
                role = message.get("role", "")
                content = message.get("content", "")
                if use_prefixes:
                    if role == "user":
                        message_file.write(f"Human: {content}\n\n")
                    elif role == "assistant":
                        message_file.write(f"Assistant: {content}\n\n")
                    else:
                        message_file.write(f"{role.capitalize()}: {content}\n\n")
                else:
                    message_file.write(f"{content}\n\n")
        
        try:
            # 创建要上传的副本
            upload_path = os.path.join(os.path.dirname(message_path), filename)
            shutil.copy2(message_path, upload_path)
            
            # 上传文件副本
            file_info = self.upload_file(upload_path)
            
            # 删除临时文件
            os.remove(upload_path)
            return file_info
            
        except Exception as e:
            logger.error(f"转换并上传聊天历史错误: {str(e)}")
            # 确保临时文件被删除

            if os.path.exists(upload_path):
                os.remove(upload_path)
            raise
    
    async def chat_with_history(self, 
                        message: str, 
                        chat_history: List[Dict], 
                        filename: str = "Useless.txt",
                        use_prefixes: bool = False,
                        model: str = "claude_3_5_sonnet", 
                        chat_mode: str = "custom") -> AsyncGenerator[str, None]:
        """将聊天历史转换为文件，上传后发送聊天请求
        
        Args:
            message: 用户消息
            chat_history: OpenAI格式的聊天历史
            filename: 文件名
            use_prefixes: 是否使用Human/Assistant前缀
            model: 要使用的AI模型
            chat_mode: 聊天模式 (custom或agent)
            
        Yields:
            聊天响应的每个token
        """
        logger.info(f"使用聊天历史进行对话: {message[:25]}...")
        
        # 获取聊天模式（如果有Cookie管理器）
        if self.cookie_manager and hasattr(self.cookie_manager, 'get_chat_mode'):
            # 修复：传递model参数
            chat_mode = self.cookie_manager.get_chat_mode(model)
            logger.info(f"使用Cookie管理器提供的聊天模式: {chat_mode}")
        
        # 转换并上传聊天历史
        file_info = self.convert_and_upload_chat_history(
            chat_history, 
            filename=filename, 
            use_prefixes=use_prefixes
        )
        
        # 使用上传的文件进行聊天
        async for token in self.chat(
            message=message,
            files=[file_info],
            model=model,
            chat_mode=chat_mode
        ):
            yield token
    
    def get_stats(self) -> Dict:
        """获取请求统计和Cookie状态
        
        Returns:
            统计信息
        """
        stats = {
            "account": {
                "email": self.email,
                "subscription": self.subscription_info
            },
            "requests": self.request_stats,
            "cookies": self.cookie_manager.get_stats() if self.cookie_manager else {}
        }
        
        return stats
    
    def rotate_cookie(self, mode: str = None) -> bool:
        """手动轮换Cookie
        
        Args:
            mode: 轮换模式 (如果提供)
            
        Returns:
            是否成功轮换
        """
        if mode:
            self.cookie_rotation_mode = mode
            
        return self._update_cookie()
    
    async def _parse_sse_response_async(self, response) -> AsyncGenerator[Dict, None]:
        """异步解析SSE响应
        
        Args:
            response: 异步请求响应对象
                
        Yields:
            解析后的事件数据
        """
        buffer = ""
        thinking_mode = False
        
        # 逐行读取响应
        async for line in response.content:
            try:
                line_str = line.decode('utf-8', errors='replace')
                
                if not line_str.strip():
                    # 空行表示事件结束
                    if buffer:
                        # 处理完整事件
                        event_type = None
                        event_data = None
                        
                        # 解析事件类型和数据
                        for part in buffer.split('\n'):
                            if part.startswith('event:'):
                                event_type = part[6:].strip()
                            elif part.startswith('data:'):
                                event_data = part[5:].strip()
                        
                        # 处理事件
                        if event_type and event_data:
                            try:
                                data = json.loads(event_data)
                            except json.JSONDecodeError:
                                data = event_data
                            
                            # 处理不同类型的事件
                            if event_type == "youChatUpdate" and isinstance(data, dict) and "t" in data:
                                # 思维链部分
                                if not thinking_mode:
                                    thinking_mode = True
                                    yield {"type": "thinking_start"}
                                
                                thinking_content = data.get("t", "")
                                yield {
                                    "type": "thinking",
                                    "content": thinking_content
                                }
                            elif event_type == "youChatToken":
                                # 实际回复部分
                                if thinking_mode:
                                    thinking_mode = False
                                    yield {"type": "thinking_end"}
                                
                                token = ""
                                if isinstance(data, dict):
                                    token = data.get("youChatToken", "")
                                
                                yield {
                                    "type": "token",
                                    "content": token
                                }
                            elif event_type == "done":
                                # 响应完成
                                if thinking_mode:
                                    thinking_mode = False
                                    yield {"type": "thinking_end"}
                                
                                yield {
                                    "type": "done",
                                    "content": data
                                }
                            else:
                                # 其他事件类型
                                yield {
                                    "type": event_type,
                                    "content": data
                                }
                        
                        # 重置缓冲区
                        buffer = ""
                    continue
                
                # 将行添加到缓冲区
                if buffer:
                    buffer += '\n'
                buffer += line_str
            except Exception as line_error:
                logger.warning(f"处理SSE行时出错: {str(line_error)}")
                # 继续处理下一行，而不是中断整个流程
                continue
        
        # 确保思维模式正确结束
        if thinking_mode:
            yield {"type": "thinking_end"}