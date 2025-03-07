import asyncio
import os
import sys
import json
import time
import logging
import uuid
from typing import Dict, Any, AsyncGenerator, Optional, List
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import uvicorn
from datetime import datetime

# 修正导入路径
sys.path.insert(0, os.path.dirname(__file__))

# 导入正确路径的客户端
from reverser.YOU import YouComReverser
from reverser.X import GrokAPI_X
from reverser.Grok import GrokReverser
from reverser.cookie_manager import YouCookieManager, XCredentialManager, GrokCookieManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('api_gateway.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="API Gateway", description="反向代理服务，支持多种AI模型接口")

# 客户端实例
you_client = None
x_client = None
grok_client = None

# Cookie管理器实例
you_cookie_manager = None
x_credential_manager = None
grok_cookie_manager = None

# 配置文件路径
CONFIG_FILE = "config.json"

def load_config() -> Dict[str, Any]:
    """加载配置文件或创建默认配置文件（如果不存在）"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"已加载配置文件: {CONFIG_FILE}")
                
                # 检查是否需要添加YOU专属配置
                if "you_settings" not in config:
                    config["you_settings"] = {
                        "custom_message": "",
                        "custom_filename": ""
                    }
                    save_config(config)
                    logger.info("已添加YOU专属配置到配置文件")
                
                return config
        else:
            # 创建默认配置（使用占位符）
            default_config = {
                "you_cookies": ["YOUR_YOU_COOKIE_HERE"],
                "x_credentials": [{
                    "cookie": "YOUR_X_COOKIE_HERE",
                    "authorization": "YOUR_X_AUTH_HERE",
                    "x-csrf-token": "YOUR_X_CSRF_TOKEN_HERE"
                }],
                "grok_cookies": ["YOUR_GROK_COOKIE_HERE"],
                "log_level": "INFO",
                "cookie_management": {
                    "you": {
                        "rotation_strategy": "round_robin",
                        "rotation_interval": 3,
                        "cooldown_minutes": 60,
                        "validation_interval_hours": 1
                    },
                    "x": {
                        "rotation_strategy": "round_robin",
                        "rotation_interval": 3,
                        "cooldown_hours": 24
                    },
                    "grok": {
                        "rotation_strategy": "round_robin",
                        "rotation_interval": 3,
                        "cooldown_minutes": 60
                    }
                },
                # 添加YOU专属配置
                "you_settings": {
                    "custom_message": "Rest System",  # 默认为空字符串，若为空则以用户最后一条消息为准
                    "custom_filename": ""  # 默认为空字符串，若为空则随机生成文件名(.txt后缀)
                }
            }
            
            # 保存默认配置
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2)
            
            logger.info(f"已创建默认配置文件: {CONFIG_FILE}")
            logger.warning("请替换配置文件中的占位符为您的实际凭证")
            raise SystemExit("请替换配置文件中的占位符为您的实际凭证")
            
    except Exception as e:
        logger.error(f"加载/创建配置文件失败: {str(e)}")
        return {
            "you_cookies": [],
            "x_credentials": [],
            "grok_cookies": [],
            "log_level": "INFO",
            "cookie_management": {
                "you": {
                    "rotation_strategy": "round_robin",
                    "rotation_interval": 3,
                    "cooldown_minutes": 60,
                    "validation_interval_hours": 1
                },
                "x": {
                    "rotation_strategy": "round_robin",
                    "rotation_interval": 3,
                    "cooldown_hours": 24
                },
                "grok": {
                    "rotation_strategy": "round_robin",
                    "rotation_interval": 3,
                    "cooldown_minutes": 60
                }
            },
            "you_settings": {
                "custom_message": "",
                "custom_filename": ""
            }
        }

def check_for_placeholders(config: Dict[str, Any]) -> bool:
    """检查配置中是否包含占位符"""
    has_placeholders = False
    
    # 检查You.com cookies
    for cookie in config.get("you_cookies", []):
        if "YOUR_YOU_COOKIE_HERE" in cookie:
            has_placeholders = True
            logger.warning("You.com cookie包含占位符。请更新config.json中的实际cookie。")
    
    # 检查X.ai凭证
    for cred in config.get("x_credentials", []):
        if "YOUR_X_COOKIE_HERE" in cred.get("cookie", ""):
            has_placeholders = True
            logger.warning("X.ai凭证包含占位符。请更新config.json中的实际凭证。")
    
    # 检查Grok.com cookies
    for cookie in config.get("grok_cookies", []):
        if "YOUR_GROK_COOKIE_HERE" in cookie:
            has_placeholders = True
            logger.warning("Grok.com cookie包含占位符。请更新config.json中的实际cookie。")
    
    return has_placeholders

def save_config(config: Dict[str, Any]):
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        logger.info(f"已保存配置到: {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"保存配置文件失败: {str(e)}")

async def initialize_clients():
    global you_client, x_client, grok_client
    global you_cookie_manager, x_credential_manager, grok_cookie_manager
    
    # 加载配置
    config = load_config()
    
    # 检查占位符
    has_placeholders = check_for_placeholders(config)
    if has_placeholders:
        logger.warning("配置文件包含占位符。某些功能可能无法正常工作。")
        logger.warning("请编辑config.json并替换占位符为您的实际凭证(需要重启以生效)。")
    
    # 设置日志级别
    log_level = config.get("log_level", "INFO")
    logging.getLogger().setLevel(log_level)
    
    # 初始化Cookie管理器
    cookie_management_config = config.get("cookie_management", {})
    
    # 初始化You.com客户端
    you_cookies = config.get("you_cookies", [])
    if you_cookies and not all("YOUR_YOU_COOKIE_HERE" in cookie for cookie in you_cookies):
        try:
            you_cookie_config = cookie_management_config.get("you", {
                "rotation_strategy": "round_robin",
                "rotation_interval": 3,
                "cooldown_minutes": 60,
                "validation_interval_hours": 1
            })
            
            # 初始化You.com Cookie管理器
            you_cookie_manager = YouCookieManager(cookies=you_cookies, config=you_cookie_config)
            
            # 初始化You.com客户端
            you_client = YouComReverser(cookies=you_cookies, cookie_manager=you_cookie_manager)
            logger.info(f"You.com客户端初始化成功，加载了 {len(you_cookies)} 个Cookie")
        except Exception as e:
            logger.error(f"You.com客户端初始化失败: {str(e)}")
    else:
        logger.warning("未提供有效的You.com Cookie，相关功能将不可用")
    
    # 初始化X.com客户端
    x_credentials = config.get("x_credentials", [])
    if x_credentials and not all("YOUR_X_COOKIE_HERE" in cred.get("cookie", "") for cred in x_credentials):
        try:
            x_cookie_config = cookie_management_config.get("x", {
                "rotation_strategy": "round_robin",
                "rotation_interval": 3,
                "cooldown_hours": 24
            })
            
            # 初始化X.ai Cookie管理器
            x_credential_manager = XCredentialManager(credentials=x_credentials, config=x_cookie_config)
            
            # 初始化X.ai客户端
            x_client = await GrokAPI_X(x_credential_manager).__aenter__()
            logger.info(f"X.com客户端初始化成功，加载了 {len(x_credentials)} 个凭证")
        except Exception as e:
            logger.error(f"X.com客户端初始化失败: {str(e)}")
    else:
        logger.warning("未提供有效的X.com凭证，相关功能将不可用")
    
    # 初始化Grok.com客户端
    grok_cookies = config.get("grok_cookies", [])
    if grok_cookies and not all("YOUR_GROK_COOKIE_HERE" in cookie for cookie in grok_cookies):
        try:
            grok_cookie_config = cookie_management_config.get("grok", {
                "rotation_strategy": "round_robin",
                "rotation_interval": 3,
                "cooldown_minutes": 60
            })
            
            # 初始化Grok.com Cookie管理器
            grok_cookie_manager = GrokCookieManager(cookies=grok_cookies, config=grok_cookie_config)
            
            # 初始化Grok.com客户端 - 使用cookie_manager参数
            grok_client = await GrokReverser(Cookies=grok_cookies, cookie_manager=grok_cookie_manager).__aenter__()
            logger.info(f"Grok.com客户端初始化成功，加载了 {len(grok_cookies)} 个Cookie")
        except Exception as e:
            logger.error(f"Grok.com客户端初始化失败: {str(e)}")
            # 不报错，只提醒
            logger.warning("Grok.com客户端未初始化，相关功能将不可用")
    else:
        logger.warning("未提供有效的Grok.com Cookie，相关功能将不可用")

# 在应用启动时初始化客户端
@app.on_event("startup")
async def startup_event():
    logger.info("服务启动中...")
    await initialize_clients()
    logger.info("服务启动完成")

# 在应用关闭时关闭客户端
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("服务关闭中...")
    if x_client:
        await x_client.__aexit__(None, None, None)
    if grok_client:
        await grok_client.__aexit__(None, None, None)
    logger.info("服务已关闭")

# 处理请求的函数
async def process_request(request_data: Dict[Any, Any]) -> AsyncGenerator[str, None]:
    """
    处理请求并路由到相应的客户端
    """
    model = request_data.get("model", "")
    messages = request_data.get("messages", [])
    
    if not messages:
        raise ValueError("消息列表不能为空")
    
    # 加载配置
    config = load_config()
    
    # 确定使用哪个客户端
    if model.startswith("You.com:"):
        if not you_client:
            logger.error("You.com客户端未初始化")
            raise ValueError("You.com客户端未初始化，请检查配置")
        
        # 提取实际模型名称
        actual_model = model.replace("You.com:", "")
        
        # 获取最后一条用户消息
        last_user_message = None
        for msg in reversed(messages):
            if msg["role"] == "user":
                last_user_message = msg["content"]
                break
        
        # 获取当前聊天模式
        chat_mode = you_cookie_manager.get_chat_mode(actual_model)

        # 记录请求信息
        current_cookie_index = you_cookie_manager.current_index
        logger.info(f"\n======\n请求模型来源: You.com")
        logger.info(f"请求模型名: {actual_model}")
        logger.info(f"请求模型使用的Cookie索引: {current_cookie_index}")
        logger.info(f"聊天模式: {chat_mode}")

        # 如果请求数据中有selectedChatMode字段，更新它
        if "selectedChatMode" in request_data:
            request_data["selectedChatMode"] = chat_mode
        # 获取YOU专属配置
        you_settings = config.get("you_settings", {})
        custom_message = you_settings.get("custom_message", "")
        custom_filename = you_settings.get("custom_filename", "")
        
        # 如果提供了自定义消息，则使用它替代最后一条用户消息
        if custom_message:
            logger.info(f"使用配置中的自定义消息替代最后一条用户消息,消息内容:{custom_message[:50]}")
            message_to_send = custom_message
        else:
            message_to_send = last_user_message
        
        # 记录文件名信息
        if custom_filename:
            logger.info(f"使用配置中的自定义文件名: {custom_filename}")
            filename = custom_filename
        else:
            # 生成随机文件名
            filename = f"{uuid.uuid4().hex[:6]}.txt"
            logger.info(f"使用随机生成的文件名: {filename}")
        
        try:
            # 使用聊天历史进行对话
            previous_messages = messages  # 除了最后一条
            
            # 获取下一个要使用的Cookie
            cookie = you_cookie_manager.get_next_cookie()
            
            # 更新客户端的Cookie
            you_client.headers["Cookie"] = cookie
            
            async for token in you_client.chat_with_history(
                message=message_to_send,
                chat_history=previous_messages,
                filename=filename,
                model=actual_model,
                chat_mode=chat_mode
            ):
                # 检查是否包含请求量异常的消息
                if "unusual query volume" in token.lower() or "we've noticed" in token.lower():
                    logger.warning(f"检测到请求量异常，标记模式 {chat_mode} 为冷却状态")
                    you_cookie_manager.start_mode_cooldown(chat_mode)
                
                yield token
                
        except Exception as e:
            error_msg = f"You.com请求失败: {str(e)}"
            logger.error(f"具体的报错信息: {error_msg}")
                        
            raise ValueError(error_msg)
            
    elif model.startswith("X.ai:"):
        if not x_client:
            logger.error("X.ai客户端未初始化")
            raise ValueError("X.ai客户端未初始化，请检查配置")
        
        # 提取实际模型名称
        actual_model = model
        
        # 记录请求信息
        current_index = x_credential_manager.current_index
        logger.info(f"请求模型来源: X.ai")
        logger.info(f"请求模型名: {actual_model}")
        logger.info(f"请求模型使用的凭证索引: {current_index}")
        
        try:
            # 获取下一个要使用的凭证
            credentials = x_credential_manager.get_next_cookie()
            
            # 使用获取的凭证更新客户端
            x_client.current_index = current_index
            
            async for token in x_client.chat_completion(messages, actual_model):
                yield token
                
            # 增加请求计数
            x_credential_manager.increment_request_count(current_index)
                
        except Exception as e:
            error_msg = f"X.ai请求失败: {str(e)}"
            logger.error(f"具体的报错信息: {error_msg}")
            
            # 标记凭证为无效
            x_credential_manager.mark_cookie_invalid(current_index, reason=str(e))
            
            raise ValueError(error_msg)
            
    elif model.startswith("Grok.com:"):
        if not grok_client:
            logger.warning("Grok.com客户端未初始化")
            yield "Grok.com客户端未初始化，请检查配置并确保提供了有效的Cookie。"
            return
        
        # 提取实际模型名称
        actual_model = model
        logger.info(f"使用模型: {actual_model}")
        
        # 合并聊天历史为单个文本
        formatted_messages = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            # 根据角色添加适当的前缀
            if role == "system":
                formatted_messages.append(f"{content}")
            elif role == "user":
                formatted_messages.append(f"{content}")
            elif role == "assistant":
                formatted_messages.append(f"{content}")
        
        # 将所有消息合并为单个文本字符串，用两个换行符分隔
        combined_message = "\n\n".join(formatted_messages)
        
        # 记录请求信息
        current_index = grok_cookie_manager.current_index
        logger.info(f"请求模型来源: Grok.com")
        logger.info(f"请求模型名: {actual_model}")
        logger.info(f"请求模型使用的Cookie索引: {current_index}")
        logger.info(f"发送合并的聊天历史，总长度: {len(combined_message)}")
        
        try:
            # 获取下一个要使用的Cookie
            cookie = grok_cookie_manager.get_next_cookie()
            
            # 更新客户端的Cookie
            grok_client.headers["Cookie"] = cookie
            
            # 发送合并后的消息
            async for token in grok_client.request2Grok(combined_message, actual_model):
                yield token
                
            # 增加请求计数
            grok_cookie_manager.increment_request_count(current_index)
                
        except Exception as e:
            error_msg = f"Grok.com请求失败: {str(e)}"
            logger.error(f"具体的报错信息: {error_msg}")
            
            # 标记Cookie为无效
            grok_cookie_manager.mark_cookie_invalid(current_index, reason=str(e))
            
            # 不抛出异常，而是返回友好提示
            yield f"Grok.com请求失败，可能是Cookie无效或已过期。错误信息: {str(e)}"
            
    else:
        raise ValueError(f"不支持的模型: {model}")

# 创建 OpenAI 格式的流式响应
def create_stream_response_chunk(content: str, finish_reason: Optional[str] = None) -> str:
    """
    创建符合OpenAI格式的流式响应chunk
    
    Args:
        content: 内容
        finish_reason: 完成原因
        
    Returns:
        格式化的响应字符串
    """
    response_data = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "gpt-3.5-turbo",
        "choices": [{
            "index": 0,
            "delta": {
                "content": content
            } if not finish_reason else {},
            "finish_reason": finish_reason
        }]
    }
    return f"data: {json.dumps(response_data)}\n\n"


# 创建非流式响应
async def create_non_stream_response(request_data) -> Dict[str, Any]:
    """
    创建非流式响应
    
    Args:
        request_data: 请求数据
        
    Returns:
        完整的响应数据
    """
    try:
        # 收集完整响应
        full_response = ""
        async for chunk in process_request(request_data):
            full_response += chunk
        
        # 构建 OpenAI 格式的响应
        response_data = {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request_data.get("model", ""),
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": full_response
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,  # 这里可以添加实际的token计数
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }
        
        return response_data
    except Exception as e:
        logger.error(f"非流式响应生成错误: {str(e)}")
        raise

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """
    处理聊天完成请求
    
    Args:
        request: 请求对象
        
    Returns:
        流式或非流式响应
    """
    try:
        # 获取请求内容
        request_data = await request.json()
        
        # 获取流式标志
        stream = request_data.get('stream', False)
        
        if stream:
            # 返回流式响应
            return StreamingResponse(
                stream_generator(request_data),
                media_type='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive',
                    'Content-Type': 'text/event-stream',
                    'X-Accel-Buffering': 'no',  # 禁用Nginx缓冲
                },
                status_code=200
            )
        else:
            # 处理普通响应
            return await create_non_stream_response(request_data)
            
    except Exception as e:
        logger.error(f"请求处理错误: {str(e)}")
        error_response = {
            "error": {
                "message": str(e),
                "type": "internal_error",
                "code": "internal_error"
            }
        }
        return Response(
            content=json.dumps(error_response),
            status_code=500,
            media_type='application/json'
        )

# 创建OpenAI格式的流式响应块
def create_stream_response_chunk(content: str, finish_reason: Optional[str] = None) -> str:
    """
    创建符合OpenAI格式的流式响应chunk
    
    Args:
        content: 内容
        finish_reason: 完成原因
        
    Returns:
        格式化的响应字符串
    """
    response_data = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "gpt-3.5-turbo",
        "choices": [{
            "index": 0,
            "delta": {
                "content": content
            } if not finish_reason else {},
            "finish_reason": finish_reason
        }]
    }
    return f"data: {json.dumps(response_data)}\n\n"

async def stream_generator(request_data) -> AsyncGenerator[str, None]:
    """
    处理流式响应，确保输出符合OpenAI格式，并正确处理异常
    """
    client_id = str(uuid.uuid4())  # 为每个请求生成唯一ID
    logger.info(f"开始处理流式请求 {client_id}")
    
    try:
        # 处理请求
        try:
            async for chunk in process_request(request_data):
                try:
                    # 创建OpenAI格式的响应块
                    formatted_chunk = create_stream_response_chunk(chunk)
                    logger.debug(f"发送块: {formatted_chunk[:50]}...")
                    yield formatted_chunk
                    # 强制刷新缓冲区
                    await asyncio.sleep(0)
                except Exception as chunk_error:
                    logger.warning(f"发送chunk时出错 (请求 {client_id}): {str(chunk_error)}")
                    # 检查是否为连接错误
                    if "Connection" in str(chunk_error) or "socket" in str(chunk_error):
                        logger.info(f"客户端连接已关闭 (请求 {client_id})，停止流式输出")
                        return  # 直接返回而不是break，确保资源被正确释放
                    # 继续处理下一个chunk，而不是中断整个流程
                    continue
            
            # 只有在没有因连接问题中断时才发送完成标记
            try:
                yield create_stream_response_chunk("", finish_reason="stop")
                await asyncio.sleep(0)  # 强制刷新
                yield "data: [DONE]\n\n"
                await asyncio.sleep(0)  # 强制刷新
                logger.info(f"流式输出完成 (请求 {client_id})")
            except Exception as e:
                logger.warning(f"发送完成标记时出错 (请求 {client_id}): {str(e)}")
                # 不抛出异常，让函数正常结束
                
        except asyncio.CancelledError:
            logger.info(f"流式响应被取消 (请求 {client_id})")
            # 优雅地处理取消
            try:
                yield create_stream_response_chunk("", finish_reason="stop")
                await asyncio.sleep(0)
                yield "data: [DONE]\n\n"
                await asyncio.sleep(0)
            except Exception:
                pass  # 忽略取消后的发送错误
            
        except Exception as process_error:
            logger.error(f"处理请求时出错 (请求 {client_id}): {str(process_error)}")
            try:
                error_message = f"处理请求时出错: {str(process_error)}"
                yield create_stream_response_chunk(error_message)
                await asyncio.sleep(0)
                yield create_stream_response_chunk("", finish_reason="stop")
                await asyncio.sleep(0)
                yield "data: [DONE]\n\n"
                await asyncio.sleep(0)
            except Exception as final_e:
                logger.error(f"发送错误响应失败 (请求 {client_id}): {str(final_e)}")
            
    except Exception as e:
        logger.error(f"流式响应生成错误 (请求 {client_id}): {str(e)}")
        try:
            error_response = {
                "error": {
                    "message": str(e),
                    "type": "internal_error",
                    "code": "internal_error"
                }
            }
            yield f"data: {json.dumps(error_response)}\n\n"
            await asyncio.sleep(0)
            yield "data: [DONE]\n\n"
            await asyncio.sleep(0)
        except Exception as final_e:
            logger.error(f"发送最终错误响应失败 (请求 {client_id}): {str(final_e)}")

@app.get("/v1/models")
async def list_models():
    """
    获取所有可用模型列表
    
    Returns:
        模型列表
    """
    try:
        models_list = {
            "object": "list",
            "data": []
        }
        
        # 获取You.com模型
        if you_client:
            try:
                you_models = you_client.list_models()
                for model in you_models:
                    # 保持原有前缀
                    if not model["id"].startswith("You.com:"):
                        model["id"] = f"You.com:{model['id']}"
                    models_list["data"].append(model)
                logger.info(f"获取到 {len(you_models)} 个You.com模型")
            except Exception as e:
                logger.error(f"获取You.com模型失败: {str(e)}")
        
        # 获取X.ai模型
        if x_client:
            try:
                x_models = x_client.list_models()
                models_list["data"].extend(x_models)
                logger.info(f"获取到 {len(x_models)} 个X.ai模型")
            except Exception as e:
                logger.error(f"获取X.ai模型失败: {str(e)}")
        
        # 获取Grok.com模型
        if grok_client:
            try:
                grok_models = await grok_client.list_models()
                if "data" in grok_models:
                    models_list["data"].extend(grok_models["data"])
                    logger.info(f"获取到 {len(grok_models['data'])} 个Grok.com模型")
            except Exception as e:
                logger.error(f"获取Grok.com模型失败: {str(e)}")
        
        return models_list
    except Exception as e:
        logger.error(f"获取模型列表失败: {str(e)}")
        error_response = {
            "error": {
                "message": str(e),
                "type": "internal_error",
                "code": "internal_error"
            }
        }
        return Response(
            content=json.dumps(error_response),
            status_code=500,
            media_type='application/json'
        )

# 启动FastAPI应用的代码
if __name__ == "__main__":
    import uvicorn
    
    # 配置uvicorn服务器
    config = uvicorn.Config(
        app=app,                 # FastAPI应用实例
        host="0.0.0.0",          # 监听所有网络接口
        port=8080,               # 端口号
        log_level="info",        # 日志级别
        reload=False,            # 生产环境不建议开启热重载
        workers=4,               # 工作进程数，建议设置为CPU核心数的2-4倍
        loop="asyncio",          # 使用asyncio事件循环
        timeout_keep_alive=65,   # 保持连接超时时间
        access_log=True,         # 启用访问日志
        limit_concurrency=100,   # 并发连接限制
        backlog=2048,            # 连接队列大小
    )
    
    # 启动服务器
    server = uvicorn.Server(config)
    logger.info("正在启动FastAPI服务器...")
    logger.info("本代码由彩狐狸与YOU.com合作编写,禁止未经允许的将本代码转载到其他地方!")
    server.run()