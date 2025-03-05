import json
import logging
import os
import random
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import uuid
import httpx
# 配置日志
logger = logging.getLogger(__name__)

class BaseCookieManager:
    """Cookie管理的基类，提供通用功能"""
    
    def __init__(self, config: Dict[str, Any], state_file: str):
        """初始化Cookie管理器
        
        Args:
            config: Cookie管理配置
            state_file: 保存Cookie状态的文件路径
        """
        self.config = config
        self.state_file = state_file
        self.cookie_states = {}
        self.current_index = 0
        self.valid_indices = []
        self.rotation_count = 0  # 用于跟踪聊天次数，决定何时轮换
        
        # 创建logs目录（如果不存在）
        os.makedirs("logs", exist_ok=True)
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        
        # 加载保存的状态
        self._load_state()
    
    def _load_state(self):
        """从文件加载Cookie状态"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    self.cookie_states = json.load(f)
                logger.info(f"已从 {self.state_file} 加载Cookie状态")
            except Exception as e:
                logger.error(f"加载Cookie状态失败: {str(e)}")
                self.cookie_states = {}
    
    def _save_state(self):
        """保存Cookie状态到文件"""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.cookie_states, f, indent=2)
            logger.debug(f"已保存Cookie状态到 {self.state_file}")
        except Exception as e:
            logger.error(f"保存Cookie状态失败: {str(e)}")
    
    def get_rotation_strategy(self) -> str:
        """获取轮换策略"""
        return self.config.get("rotation_strategy", "round_robin")
    
    def get_rotation_interval(self) -> int:
        """获取轮换间隔"""
        return self.config.get("rotation_interval", 3)
    
    def get_cooldown_minutes(self) -> int:
        """获取冷却时间（分钟）"""
        # 优先使用minutes，如果没有则使用hours并转换为分钟
        if "cooldown_minutes" in self.config:
            return self.config.get("cooldown_minutes", 60)
        return self.config.get("cooldown_hours", 1) * 60
    
    def get_validation_interval_hours(self) -> int:
        """获取验证间隔（小时）"""
        return self.config.get("validation_interval_hours", 1)
    
    def should_rotate(self) -> bool:
        """判断是否应该轮换Cookie"""
        interval = self.get_rotation_interval()
        # 如果间隔为0，表示不轮换
        if interval <= 0:
            return False
            
        self.rotation_count += 1
        if self.rotation_count >= interval:
            self.rotation_count = 0
            return True
        return False
    
    def validate_cookie(self, index: int) -> bool:
        """验证Cookie是否有效（需要子类实现）"""
        raise NotImplementedError("子类必须实现validate_cookie方法")
    
    def get_next_cookie(self) -> Any:
        """获取下一个要使用的Cookie（需要子类实现）"""
        raise NotImplementedError("子类必须实现get_next_cookie方法")
    
    def increment_request_count(self, index: int):
        """增加指定Cookie的请求计数"""
        raise NotImplementedError("子类必须实现increment_request_count方法")
    
    def get_stats(self) -> Dict:
        """获取所有Cookie的统计信息"""
        raise NotImplementedError("子类必须实现get_stats方法")
    
    def mark_cookie_invalid(self, index: int, reason: str = ""):
        """标记Cookie为无效"""
        raise NotImplementedError("子类必须实现mark_cookie_invalid方法")


class YouCookieManager(BaseCookieManager):
    """You.com的Cookie管理器"""
    
    def __init__(self, cookies: List[str], config: Dict[str, Any]):
        """初始化You.com Cookie管理器
        
        Args:
            cookies: Cookie字符串列表
            config: Cookie管理配置
        """
        super().__init__(config, state_file="logs/you_cookie_state.json")
        self.cookies = cookies
        self.chat_mode = "custom"  # 默认为custom模式
        self.mode_rotation_count = 0
        
        # 初始化Cookie状态
        for i, cookie in enumerate(cookies):
            cookie_id = f"cookie_{i}"
            if cookie_id not in self.cookie_states:
                self.cookie_states[cookie_id] = {
                    "cookie": cookie,
                    "valid": None,  # 未验证
                    "last_checked": None,
                    "request_count": 0,
                    "last_used": None,
                    "email": "UNKNOWN",
                    "subscription_tier": "UNKNOWN",
                    "is_cooling": False,
                    "next_available": None
                }
        
        # 初始化Agent模式ID存储
        if "agent_modes" not in self.cookie_states:
            self.cookie_states["agent_modes"] = {}
        
        # 验证所有Cookie
        self.validate_all_cookies()
    
    def validate_all_cookies(self):
        """验证所有Cookie"""
        self.valid_indices = []
        for i in range(len(self.cookies)):
            cookie_id = f"cookie_{i}"
            state = self.cookie_states.get(cookie_id, {})
            
            # 如果Cookie状态未知或上次检查超过验证间隔，重新验证
            last_checked = state.get("last_checked")
            validation_interval = self.get_validation_interval_hours()
            
            if state.get("valid") is None or (
                last_checked and 
                (datetime.now() - datetime.fromisoformat(last_checked)).total_seconds() > validation_interval * 3600
            ):
                is_valid = self.validate_cookie(i)
            else:
                is_valid = state.get("valid", False)
            
            if is_valid and not state.get("is_cooling", False):
                self.valid_indices.append(i)
        
        logger.info(f"You.com: 有效Cookie数量: {len(self.valid_indices)}/{len(self.cookies)}")
    
    def validate_cookie(self, index: int) -> bool:
        """验证Cookie是否有效
        
        Args:
            index: Cookie索引
            
        Returns:
            Cookie是否有效
        """
        import requests
        
        cookie_id = f"cookie_{index}"
        cookie = self.cookies[index]
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": cookie
        }
        
        try:
            # 尝试获取用户数据来验证Cookie
            response = requests.get(
                headers=headers,
                url='https://you.com/_next/data/ee50cd42bdfa0bd3ad044daa2349a6179381d5ef/en-US/search.json'
            )
            
            # 检查状态码
            if response.status_code == 403:
                logger.warning(f"You.com Cookie验证失败: 状态码 403 (Cookie已失效)")
                self._update_cookie_state(index, False)
                return False
            

            
            if response.status_code != 200:
                logger.warning(f"You.com Cookie验证失败: 状态码 {response.status_code}\n返回Json:{response.json}")
                self._update_cookie_state(index, False)
                return False
            
            # 尝试解析响应
            data = response.json()
            
            # 提取邮箱和订阅信息
            launch_darkly_context = data.get("pageProps", {}).get("launchDarklyContext", {})
            email = launch_darkly_context.get("email", "UNKNOWN")
            
            you_pro_state = data.get("pageProps", {}).get("youProState", {})
            subscription_tier = "free"
            if you_pro_state:
                subscriptions = you_pro_state.get("subscriptions", [])
                if subscriptions:
                    subscription_tier = subscriptions[0].get("tier", "free")
            
            # 更新Cookie状态
            self._update_cookie_state(index, True, email, subscription_tier)
            
            logger.info(f"You.com Cookie验证成功: {email} ({subscription_tier})")
            return True
            
        except Exception as e:
            logger.error(f"You.com Cookie验证错误: {str(e)}")
            self._update_cookie_state(index, False, error=str(e))
            return False
    
    def _update_cookie_state(self, index: int, is_valid: bool, email: str = "UNKNOWN", 
                            subscription_tier: str = "UNKNOWN", error: str = ""):
        """更新Cookie状态"""
        cookie_id = f"cookie_{index}"
        
        self.cookie_states[cookie_id].update({
            "valid": is_valid,
            "last_checked": datetime.now().isoformat(),
            "email": email if is_valid else self.cookie_states[cookie_id].get("email", "UNKNOWN"),
            "subscription_tier": subscription_tier if is_valid else self.cookie_states[cookie_id].get("subscription_tier", "UNKNOWN"),
        })
        
        if error:
            self.cookie_states[cookie_id]["error"] = error
        
        self._save_state()
    
    def get_next_cookie(self) -> str:
        """获取下一个要使用的Cookie
        
        Returns:
            下一个Cookie字符串
            
        Raises:
            Exception: 当没有可用Cookie时抛出
        """
        if not self.cookies:
            raise Exception("没有可用的You.com Cookie")
        
        # 验证所有Cookie
        self.validate_all_cookies()
        
        if not self.valid_indices:
            raise Exception("所有You.com Cookie都已失效")
        
        # 根据不同模式选择Cookie
        rotation_strategy = self.get_rotation_strategy()
        
        if rotation_strategy == "round_robin":
            # 轮询模式
            if self.current_index in self.valid_indices:
                current_position = self.valid_indices.index(self.current_index)
                next_position = (current_position + 1) % len(self.valid_indices)
                self.current_index = self.valid_indices[next_position]
            else:
                self.current_index = self.valid_indices[0]
        elif rotation_strategy == "random":
            # 随机模式
            self.current_index = random.choice(self.valid_indices)
        elif rotation_strategy == "least_used":
            # 最少使用模式
            self.current_index = min(
                self.valid_indices, 
                key=lambda i: self.cookie_states.get(f"cookie_{i}", {}).get("request_count", 0)
            )
        else:
            # 默认轮询
            if self.current_index in self.valid_indices:
                current_position = self.valid_indices.index(self.current_index)
                next_position = (current_position + 1) % len(self.valid_indices)
                self.current_index = self.valid_indices[next_position]
            else:
                self.current_index = self.valid_indices[0]
        
        # 更新使用记录
        cookie_id = f"cookie_{self.current_index}"
        self.cookie_states[cookie_id]["last_used"] = datetime.now().isoformat()
        
        # 保存状态
        self._save_state()
        
        # 检查是否需要轮换聊天模式（仅针对You.com）
        self.update_chat_mode()
        
        return self.cookies[self.current_index]
    
    def update_chat_mode(self):
        """更新聊天模式（在custom和agent之间切换）"""
        mode_rotation_interval = self.get_rotation_interval()
        
        # 如果间隔为0，表示不轮换
        if mode_rotation_interval <= 0:
            return
            
        self.mode_rotation_count += 1
        if self.mode_rotation_count >= mode_rotation_interval:
            self.mode_rotation_count = 0
            # 切换模式
            self.chat_mode = "agent" if self.chat_mode == "custom" else "custom"
            logger.info(f"You.com: 已切换聊天模式为 {self.chat_mode}")
    
    
    def increment_request_count(self, index: int):
        """增加指定Cookie的请求计数
        
        Args:
            index: Cookie索引
        """
        if 0 <= index < len(self.cookies):
            cookie_id = f"cookie_{index}"
            if cookie_id in self.cookie_states:
                self.cookie_states[cookie_id]["request_count"] = self.cookie_states[cookie_id].get("request_count", 0) + 1
                self._save_state()
    
    def mark_cookie_invalid(self, index: int, reason: str = ""):
        """标记Cookie为无效
        
        Args:
            index: Cookie索引
            reason: 无效原因
        """
        if 0 <= index < len(self.cookies):
            cookie_id = f"cookie_{index}"
            if cookie_id in self.cookie_states:
                self.cookie_states[cookie_id]["valid"] = False
                self.cookie_states[cookie_id]["error"] = reason
                self.cookie_states[cookie_id]["invalidated_at"] = datetime.now().isoformat()
                
                # 从有效索引列表中移除
                if index in self.valid_indices:
                    self.valid_indices.remove(index)
                
                logger.warning(f"已标记Cookie {index} 为无效: {reason}")
                self._save_state()
    
    def start_cooldown(self, index: int):
        """开始Cookie冷却
        
        Args:
            index: Cookie索引
        """
        if 0 <= index < len(self.cookies):
            cookie_id = f"cookie_{index}"
            if cookie_id in self.cookie_states:
                cooldown_minutes = self.get_cooldown_minutes()
                next_available = datetime.now() + timedelta(minutes=cooldown_minutes)
                
                self.cookie_states[cookie_id]["is_cooling"] = True
                self.cookie_states[cookie_id]["next_available"] = next_available.isoformat()
                
                # 从有效索引列表中移除
                if index in self.valid_indices:
                    self.valid_indices.remove(index)
                
                logger.info(f"Cookie {index} 开始冷却，将在 {next_available} 后可用")
                self._save_state()
    
    def check_cooldowns(self):
        """检查所有Cookie的冷却状态"""
        for i in range(len(self.cookies)):
            cookie_id = f"cookie_{i}"
            state = self.cookie_states.get(cookie_id, {})
            
            if state.get("is_cooling", False) and state.get("next_available"):
                next_available = datetime.fromisoformat(state["next_available"])
                
                if datetime.now() >= next_available:
                    # 冷却结束
                    self.cookie_states[cookie_id]["is_cooling"] = False
                    self.cookie_states[cookie_id]["next_available"] = None
                    
                    # 如果Cookie有效，添加回有效索引列表
                    if state.get("valid", False) and i not in self.valid_indices:
                        self.valid_indices.append(i)
                    
                    logger.info(f"Cookie {i} 冷却结束，现在可用")
                    self._save_state()

    def get_agent_mode(self, model_name: str) -> str:
        """获取指定模型的Agent模式ID
        
        Args:
            model_name: 模型名称
            
        Returns:
            Agent模式ID，如果不存在则返回空字符串
        """
        agent_modes = self.cookie_states.get("agent_modes", {})
        
        # 检查模型是否有有效的agent模式
        if model_name in agent_modes and agent_modes[model_name].get("valid", True):
            return agent_modes[model_name].get("agent_id", "")
        
        return ""

    def add_agent_mode(self, model_name: str, agent_id: str):
        """添加模型的Agent模式ID
        
        Args:
            model_name: 模型名称
            agent_id: Agent模式ID
        """
        if "agent_modes" not in self.cookie_states:
            self.cookie_states["agent_modes"] = {}
        
        self.cookie_states["agent_modes"][model_name] = {
            "agent_id": agent_id,
            "created_at": datetime.now().isoformat(),
            "valid": True
        }
        
        logger.info(f"已为模型 {model_name} 添加Agent模式ID: {agent_id}")
        self._save_state()

    def mark_agent_mode_invalid(self, model_name: str, reason: str = ""):
        """标记模型的Agent模式为无效
        
        Args:
            model_name: 模型名称
            reason: 无效原因
        """
        if "agent_modes" in self.cookie_states and model_name in self.cookie_states["agent_modes"]:
            self.cookie_states["agent_modes"][model_name]["valid"] = False
            self.cookie_states["agent_modes"][model_name]["error"] = reason
            self.cookie_states["agent_modes"][model_name]["invalidated_at"] = datetime.now().isoformat()
            
            logger.warning(f"已标记模型 {model_name} 的Agent模式为无效: {reason}")
            self._save_state()

    def start_mode_cooldown(self, mode: str):
        """开始特定聊天模式的冷却
        
        Args:
            mode: 要冷却的聊天模式（custom或agent模式ID）
        """
        # 存储冷却中的模式
        if "mode_cooldowns" not in self.cookie_states:
            self.cookie_states["mode_cooldowns"] = {}
        
        cooldown_minutes = self.get_cooldown_minutes()
        next_available = datetime.now() + timedelta(minutes=cooldown_minutes)
        
        self.cookie_states["mode_cooldowns"][mode] = {
            "is_cooling": True,
            "next_available": next_available.isoformat(),
            "started_at": datetime.now().isoformat()
        }
        
        logger.info(f"聊天模式 {mode} 开始冷却，将在 {next_available} 后可用")
        self._save_state()

    def is_mode_in_cooldown(self, mode: str) -> bool:
        """检查特定聊天模式是否在冷却中
        
        Args:
            mode: 要检查的聊天模式
            
        Returns:
            模式是否在冷却中
        """
        if "mode_cooldowns" not in self.cookie_states:
            return False
        
        mode_cooldown = self.cookie_states["mode_cooldowns"].get(mode, {})
        if not mode_cooldown.get("is_cooling", False):
            return False
        
        # 检查冷却是否已过期
        next_available = mode_cooldown.get("next_available")
        if next_available:
            if datetime.now() >= datetime.fromisoformat(next_available):
                # 冷却已结束
                mode_cooldown["is_cooling"] = False
                mode_cooldown["next_available"] = None
                self._save_state()
                return False
        
        return True
        
    def start_mode_cooldown(self, mode: str):
        """开始特定聊天模式的冷却
        
        Args:
            mode: 要冷却的聊天模式（custom或agent模式ID）
        """
        # 存储冷却中的模式
        if "mode_cooldowns" not in self.cookie_states:
            self.cookie_states["mode_cooldowns"] = {}
        
        cooldown_minutes = self.get_cooldown_minutes()
        next_available = datetime.now() + timedelta(minutes=cooldown_minutes)
        
        self.cookie_states["mode_cooldowns"][mode] = {
            "is_cooling": True,
            "next_available": next_available.isoformat(),
            "started_at": datetime.now().isoformat()
        }
        
        logger.info(f"聊天模式 {mode} 开始冷却，将在 {next_available} 后可用")
        self._save_state()

    def is_mode_in_cooldown(self, mode: str) -> bool:
        """检查特定聊天模式是否在冷却中
        
        Args:
            mode: 要检查的聊天模式
            
        Returns:
            模式是否在冷却中
        """
        if "mode_cooldowns" not in self.cookie_states:
            return False
        
        mode_cooldown = self.cookie_states["mode_cooldowns"].get(mode, {})
        if not mode_cooldown.get("is_cooling", False):
            return False
        
        # 检查冷却是否已过期
        next_available = mode_cooldown.get("next_available")
        if next_available:
            if datetime.now() >= datetime.fromisoformat(next_available):
                # 冷却已结束
                mode_cooldown["is_cooling"] = False
                mode_cooldown["next_available"] = None
                self._save_state()
                return False
        
        return True


    def get_chat_mode(self, model_name: str = None) -> str:
        """
        获取当前的聊天模式，考虑冷却状态和自动创建Agent模式
        
        参数:
            model_name: 模型名称，例如 "claude_3_7_sonnet"
            
        返回:
            聊天模式，例如 "custom" 或代理模式 ID
        """
        # 检查自定义模式是否处于冷却状态
        custom_cooling = self.is_mode_in_cooldown("custom")
        
        # 如果提供了 model_name，检查其代理模式是否可用
        agent_id = ""
        agent_cooling = False
        if model_name:
            agent_id = self.get_agent_mode(model_name)
            
            # 如果没有找到Agent模式ID，尝试创建一个
            if not agent_id and self.chat_mode == "agent":
                logger.info(f"模型 {model_name} 没有对应的Agent模式ID，尝试创建...")
                agent_id = self.create_agent_mode(model_name)
            
            if agent_id:
                agent_cooling = self.is_mode_in_cooldown(agent_id)
        
        # 根据当前模式和冷却状态的决策逻辑
        if self.chat_mode == "custom":
            if custom_cooling:
                # 如果自定义模式在冷却，并且代理模式可用，则切换到代理模式
                if agent_id and not agent_cooling:
                    logger.info(f"自定义模式正在冷却，切换到代理模式 {agent_id}")
                    return agent_id
                else:
                    # 如果两种模式都在冷却，或者没有可用的代理模式，仍然返回自定义模式
                    # 调用者应适当地处理冷却状态
                    logger.info("自定义模式正在冷却，但没有可用的替代方案")
                    return "custom"
            else:
                # 自定义模式未冷却，直接使用
                return "custom"
        else:  # self.chat_mode == "agent"
            if agent_id:
                if agent_cooling:
                    # 如果代理模式在冷却，并且自定义模式可用，则切换到自定义模式
                    if not custom_cooling:
                        logger.info(f"代理模式 {agent_id} 正在冷却，切换到自定义模式")
                        return "custom"
                    else:
                        # 如果两种模式都在冷却，仍然返回代理模式
                        # 调用者应适当地处理冷却状态
                        logger.info(f"代理模式 {agent_id} 正在冷却，但没有可用的替代方案")
                        return agent_id
                else:
                    # 代理模式未冷却，直接使用
                    return agent_id
            else:
                # 没有可用的代理模式 ID，回退到自定义模式
                logger.info(f"未找到模型 {model_name} 的Agent模式ID，无法创建，回退到自定义模式")
                return "custom"


    def create_agent_mode(self, model_name: str) -> str:
        """
        为指定模型创建一个Agent模式
        
        Args:
            model_name: 模型名称，例如 "claude_3_7_sonnet"
            
        Returns:
            创建的Agent模式ID，如果创建失败则返回空字符串
        """
        logger.info(f"正在为模型 {model_name} 创建Agent模式...")
        
        try:
            import requests
            
            # 获取当前Cookie
            cookie = self.cookies[self.current_index]
            
            # 准备请求
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Cookie": cookie,
                "Content-Type": "application/json"
            }
            
            # 准备请求体
            payload = {
                "aiModel": model_name,
                "name": str(uuid.uuid4())[:5],
                "instructions": "",
                "instructionsSummary": "",
                "isUserOwned": True,
                "visibility": "public",
                "hideInstructions": False,
                "teams": [],
                "hasLiveWebAccess": False,
                "hasPersonalization": True,
                "includeFollowUps": False,
                "advancedReasoningMode": "off",
                "sources": [],
                "webAccessConfig": {}
            }
            
            # 发送请求
            response = requests.post(
                "https://you.com/api/custom_assistants/assistants",
                headers=headers,
                json=payload
            )
            
            # 检查响应
            if response.status_code == 200:
                data = response.json()
                agent_id = data.get("chat_mode_id", "")
                
                if agent_id:
                    # 保存新创建的Agent模式ID
                    self.add_agent_mode(model_name, agent_id)
                    logger.info(f"成功为模型 {model_name} 创建Agent模式: {agent_id}")
                    return agent_id
                else:
                    logger.warning(f"创建Agent模式失败: 响应中没有chat_mode_id")
                    return ""
            else:
                logger.warning(f"创建Agent模式失败: 状态码 {response.status_code}, 响应: {response.text}")
                return ""
                
        except Exception as e:
            logger.error(f"创建Agent模式时出错: {str(e)}")
            return ""
class XCredentialManager(BaseCookieManager):
    """X.ai凭证管理器"""
    
    def __init__(self, credentials: List[Dict[str, str]], config: Dict[str, Any]):
        """初始化X.ai凭证管理器
        
        Args:
            credentials: 凭证字典列表，每个字典包含cookie、authorization和x-csrf-token
            config: 凭证管理配置
        """
        super().__init__(config, state_file="logs/x_credential_state.json")
        self.credentials = credentials
        
        # 初始化凭证状态
        for i, cred in enumerate(credentials):
            cred_id = f"credential_{i}"
            if cred_id not in self.cookie_states:
                self.cookie_states[cred_id] = {
                    "credential": cred,
                    "valid": None,  # 未验证
                    "last_checked": None,
                    "request_count": 0,
                    "last_used": None,
                    "username": "UNKNOWN",
                    "is_cooling": False,
                    "next_available": None
                }
        
        # 验证所有凭证
        self.validate_all_cookies()
    
    def validate_all_cookies(self):
        """验证所有凭证"""
        self.valid_indices = []
        for i in range(len(self.credentials)):
            cred_id = f"credential_{i}"
            state = self.cookie_states.get(cred_id, {})
            
            # 如果凭证状态未知或上次检查超过验证间隔，重新验证
            last_checked = state.get("last_checked")
            validation_interval = self.get_validation_interval_hours()
            
            if state.get("valid") is None or (
                last_checked and 
                (datetime.now() - datetime.fromisoformat(last_checked)).total_seconds() > validation_interval * 3600
            ):
                is_valid = self.validate_cookie(i)
            else:
                is_valid = state.get("valid", False)
            
            if is_valid and not state.get("is_cooling", False):
                self.valid_indices.append(i)
        
        logger.info(f"X.ai: 有效凭证数量: {len(self.valid_indices)}/{len(self.credentials)}")
    
    def validate_cookie(self, index: int) -> bool:
        """验证凭证是否有效
        
        Args:
            index: 凭证索引
            
        Returns:
            凭证是否有效
        """
        import requests
        
        cred_id = f"credential_{index}"
        cred = self.credentials[index]
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": cred.get("cookie", ""),
            "Authorization": cred.get("authorization", ""),
            "x-csrf-token": cred.get("x-csrf-token", "")
        }
        
        try:
            # 尝试获取用户数据来验证凭证
            response = requests.get(
                headers=headers,
                url='https://api.x.com/graphql/3Eo8X-0b-XJA3E9kO0oYPw/UserByScreenName'
            )
            
            # 检查状态码
            if response.status_code != 200:
                logger.warning(f"X.ai凭证验证失败: 状态码 {response.status_code}")
                self._update_credential_state(index, False)
                return False
            
            # 尝试解析响应
            data = response.json()
            
            # 提取用户名
            username = "UNKNOWN"
            try:
                result = data.get("data", {}).get("user", {})
                if result:
                    username = result.get("legacy", {}).get("screen_name", "UNKNOWN")
            except:
                pass
            
            # 更新凭证状态
            self._update_credential_state(index, True, username)
            
            logger.info(f"X.ai凭证验证成功: {username}")
            return True
            
        except Exception as e:
            logger.error(f"X.ai凭证验证错误: {str(e)}")
            self._update_credential_state(index, False, error=str(e))
            return False
    
    def _update_credential_state(self, index: int, is_valid: bool, username: str = "UNKNOWN", error: str = ""):
        """更新凭证状态"""
        cred_id = f"credential_{index}"
        
        self.cookie_states[cred_id].update({
            "valid": is_valid,
            "last_checked": datetime.now().isoformat(),
            "username": username if is_valid else self.cookie_states[cred_id].get("username", "UNKNOWN")
        })
        
        if error:
            self.cookie_states[cred_id]["error"] = error
        
        self._save_state()
    
    def get_next_cookie(self) -> Dict[str, str]:
        """获取下一个要使用的凭证
        
        Returns:
            下一个凭证字典
            
        Raises:
            Exception: 当没有可用凭证时抛出
        """
        if not self.credentials:
            raise Exception("没有可用的X.ai凭证")
        
        # 验证所有凭证
        self.validate_all_cookies()
        
        if not self.valid_indices:
            raise Exception("所有X.ai凭证都已失效")
        
        # 根据不同模式选择凭证
        rotation_strategy = self.get_rotation_strategy()
        
        if rotation_strategy == "round_robin":
            # 轮询模式
            if self.current_index in self.valid_indices:
                current_position = self.valid_indices.index(self.current_index)
                next_position = (current_position + 1) % len(self.valid_indices)
                self.current_index = self.valid_indices[next_position]
            else:
                self.current_index = self.valid_indices[0]
        elif rotation_strategy == "random":
            # 随机模式
            self.current_index = random.choice(self.valid_indices)
        elif rotation_strategy == "least_used":
            # 最少使用模式
            self.current_index = min(
                self.valid_indices, 
                key=lambda i: self.cookie_states.get(f"credential_{i}", {}).get("request_count", 0)
            )
        else:
            # 默认轮询
            if self.current_index in self.valid_indices:
                current_position = self.valid_indices.index(self.current_index)
                next_position = (current_position + 1) % len(self.valid_indices)
                self.current_index = self.valid_indices[next_position]
            else:
                self.current_index = self.valid_indices[0]
        
        # 更新使用记录
        cred_id = f"credential_{self.current_index}"
        self.cookie_states[cred_id]["last_used"] = datetime.now().isoformat()
        
        # 保存状态
        self._save_state()
        
        return self.credentials[self.current_index]
    
    def increment_request_count(self, index: int):
        """增加指定凭证的请求计数
        
        Args:
            index: 凭证索引
        """
        if 0 <= index < len(self.credentials):
            cred_id = f"credential_{index}"
            if cred_id in self.cookie_states:
                self.cookie_states[cred_id]["request_count"] = self.cookie_states[cred_id].get("request_count", 0) + 1
                self._save_state()
    
    def mark_cookie_invalid(self, index: int, reason: str = ""):
        """标记凭证为无效
        
        Args:
            index: 凭证索引
            reason: 无效原因
        """
        if 0 <= index < len(self.credentials):
            cred_id = f"credential_{index}"
            if cred_id in self.cookie_states:
                self.cookie_states[cred_id]["valid"] = False
                self.cookie_states[cred_id]["error"] = reason
                self.cookie_states[cred_id]["invalidated_at"] = datetime.now().isoformat()
                
                # 从有效索引列表中移除
                if index in self.valid_indices:
                    self.valid_indices.remove(index)
                
                logger.warning(f"已标记X.ai凭证 {index} 为无效: {reason}")
                self._save_state()
    
    def start_cooldown(self, index: int):
        """开始凭证冷却
        
        Args:
            index: 凭证索引
        """
        if 0 <= index < len(self.credentials):
            cred_id = f"credential_{index}"
            if cred_id in self.cookie_states:
                cooldown_minutes = self.get_cooldown_minutes()
                next_available = datetime.now() + timedelta(minutes=cooldown_minutes)
                
                self.cookie_states[cred_id]["is_cooling"] = True
                self.cookie_states[cred_id]["next_available"] = next_available.isoformat()
                
                # 从有效索引列表中移除
                if index in self.valid_indices:
                    self.valid_indices.remove(index)
                
                logger.info(f"X.ai凭证 {index} 开始冷却，将在 {next_available} 后可用")
                self._save_state()
    
    def get_stats(self) -> Dict:
        """获取所有凭证的统计信息
        
        Returns:
            凭证统计信息
        """
        stats = {
            "total_credentials": len(self.credentials),
            "valid_credentials": len(self.valid_indices),
            "current_index": self.current_index,
            "credentials": []
        }
        
        for i, cred in enumerate(self.credentials):
            cred_id = f"credential_{i}"
            state = self.cookie_states.get(cred_id, {})
            cookie_preview = cred.get("cookie", "")[:20] + "..." if len(cred.get("cookie", "")) > 20 else cred.get("cookie", "")
            
            stats["credentials"].append({
                "index": i,
                "preview": cookie_preview,
                "valid": state.get("valid", False),
                "username": state.get("username", "UNKNOWN"),
                "request_count": state.get("request_count", 0),
                "last_used": state.get("last_used"),
                "last_checked": state.get("last_checked"),
                "is_cooling": state.get("is_cooling", False),
                "next_available": state.get("next_available")
            })
        
        return stats
    
    def check_cooldowns(self):
        """检查所有凭证的冷却状态"""
        for i in range(len(self.credentials)):
            cred_id = f"credential_{i}"
            state = self.cookie_states.get(cred_id, {})
            
            if state.get("is_cooling", False) and state.get("next_available"):
                next_available = datetime.fromisoformat(state["next_available"])
                
                if datetime.now() >= next_available:
                    # 冷却结束
                    self.cookie_states[cred_id]["is_cooling"] = False
                    self.cookie_states[cred_id]["next_available"] = None
                    
                    # 如果凭证有效，添加回有效索引列表
                    if state.get("valid", False) and i not in self.valid_indices:
                        self.valid_indices.append(i)
                    
                    logger.info(f"X.ai凭证 {i} 冷却结束，现在可用")
                    self._save_state()


class GrokCookieManager(BaseCookieManager):
    """Grok.com的Cookie管理器"""
    
    def __init__(self, cookies: List[str], config: Dict[str, Any]):
        """初始化Grok.com Cookie管理器
        
        Args:
            cookies: Cookie字符串列表
            config: Cookie管理配置
        """
        super().__init__(config, state_file="logs/grok_cookie_state.json")
        self.cookies = cookies
        
        # 初始化Cookie状态
        for i, cookie in enumerate(cookies):
            cookie_id = f"cookie_{i}"
            if cookie_id not in self.cookie_states:
                self.cookie_states[cookie_id] = {
                    "cookie": cookie,
                    "valid": None,  # 未验证
                    "last_checked": None,
                    "request_count": 0,
                    "last_used": None,
                    "username": "UNKNOWN",
                    "is_cooling": False,
                    "next_available": None
                }
        
        # 验证所有Cookie
        self.validate_all_cookies()
    
    def validate_all_cookies(self):
        """验证所有Cookie"""
        self.valid_indices = []
        for i in range(len(self.cookies)):
            cookie_id = f"cookie_{i}"
            state = self.cookie_states.get(cookie_id, {})
            
            # 如果Cookie状态未知或上次检查超过验证间隔，重新验证
            last_checked = state.get("last_checked")
            validation_interval = self.get_validation_interval_hours()
            
            if state.get("valid") is None or (
                last_checked and 
                (datetime.now() - datetime.fromisoformat(last_checked)).total_seconds() > validation_interval * 3600
            ):
                is_valid = self.validate_cookie(i)
            else:
                is_valid = state.get("valid", False)
            
            if is_valid and not state.get("is_cooling", False):
                self.valid_indices.append(i)
        
        logger.info(f"Grok.com: 有效Cookie数量: {len(self.valid_indices)}/{len(self.cookies)}")
    
    def validate_cookie(self, index: int) -> bool:
        """验证Cookie是否有效
        
        Args:
            index: Cookie索引
            
        Returns:
            Cookie是否有效
        """
        import requests
        
        cookie_id = f"cookie_{index}"
        cookie = self.cookies[index]
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": cookie
        }
        
        try:
            # 尝试获取用户数据来验证Cookie
            response = requests.get(
                headers=headers,
                url='https://grok.x.ai/api/user'
            )
            
            # 检查状态码
            if response.status_code != 200:
                logger.warning(f"Grok.com Cookie验证失败: 状态码 {response.status_code}")
                self._update_cookie_state(index, False)
                return False
            
            # 尝试解析响应
            data = response.json()
            
            # 提取用户名
            username = "UNKNOWN"
            if data and "username" in data:
                username = data["username"]
            
            # 更新Cookie状态
            self._update_cookie_state(index, True, username)
            
            logger.info(f"Grok.com Cookie验证成功: {username}")
            return True
            
        except Exception as e:
            logger.error(f"Grok.com Cookie验证错误: {str(e)}")
            self._update_cookie_state(index, False, error=str(e))
            return False
    
    def _update_cookie_state(self, index: int, is_valid: bool, username: str = "UNKNOWN", error: str = ""):
        """更新Cookie状态"""
        cookie_id = f"cookie_{index}"
        
        self.cookie_states[cookie_id].update({
            "valid": is_valid,
            "last_checked": datetime.now().isoformat(),
            "username": username if is_valid else self.cookie_states[cookie_id].get("username", "UNKNOWN")
        })
        
        if error:
            self.cookie_states[cookie_id]["error"] = error
        
        self._save_state()
    
    def get_next_cookie(self) -> str:
        """获取下一个要使用的Cookie
        
        Returns:
            下一个Cookie字符串
            
        Raises:
            Exception: 当没有可用Cookie时抛出
        """
        if not self.cookies:
            raise Exception("没有可用的Grok.com Cookie")
        
        # 验证所有Cookie
        self.validate_all_cookies()
        
        if not self.valid_indices:
            raise Exception("所有Grok.com Cookie都已失效")
        
        # 根据不同模式选择Cookie
        rotation_strategy = self.get_rotation_strategy()
        
        if rotation_strategy == "round_robin":
            # 轮询模式
            if self.current_index in self.valid_indices:
                current_position = self.valid_indices.index(self.current_index)
                next_position = (current_position + 1) % len(self.valid_indices)
                self.current_index = self.valid_indices[next_position]
            else:
                self.current_index = self.valid_indices[0]
        elif rotation_strategy == "random":
            # 随机模式
            self.current_index = random.choice(self.valid_indices)
        elif rotation_strategy == "least_used":
            # 最少使用模式
            self.current_index = min(
                self.valid_indices, 
                key=lambda i: self.cookie_states.get(f"cookie_{i}", {}).get("request_count", 0)
            )
        else:
            # 默认轮询
            if self.current_index in self.valid_indices:
                current_position = self.valid_indices.index(self.current_index)
                next_position = (current_position + 1) % len(self.valid_indices)
                self.current_index = self.valid_indices[next_position]
            else:
                self.current_index = self.valid_indices[0]
        
        # 更新使用记录
        cookie_id = f"cookie_{self.current_index}"
        self.cookie_states[cookie_id]["last_used"] = datetime.now().isoformat()
        
        # 保存状态
        self._save_state()
        
        return self.cookies[self.current_index]
    
    def increment_request_count(self, index: int):
        """增加指定Cookie的请求计数
        
        Args:
            index: Cookie索引
        """
        if 0 <= index < len(self.cookies):
            cookie_id = f"cookie_{index}"
            if cookie_id in self.cookie_states:
                self.cookie_states[cookie_id]["request_count"] = self.cookie_states[cookie_id].get("request_count", 0) + 1
                self._save_state()
    
    def mark_cookie_invalid(self, index: int, reason: str = ""):
        """标记Cookie为无效
        
        Args:
            index: Cookie索引
            reason: 无效原因
        """
        if 0 <= index < len(self.cookies):
            cookie_id = f"cookie_{index}"
            if cookie_id in self.cookie_states:
                self.cookie_states[cookie_id]["valid"] = False
                self.cookie_states[cookie_id]["error"] = reason
                self.cookie_states[cookie_id]["invalidated_at"] = datetime.now().isoformat()
                
                # 从有效索引列表中移除
                if index in self.valid_indices:
                    self.valid_indices.remove(index)
                
                logger.warning(f"已标记Grok.com Cookie {index} 为无效: {reason}")
                self._save_state()
    
    def start_cooldown(self, index: int):
        """开始Cookie冷却
        
        Args:
            index: Cookie索引
        """
        if 0 <= index < len(self.cookies):
            cookie_id = f"cookie_{index}"
            if cookie_id in self.cookie_states:
                cooldown_minutes = self.get_cooldown_minutes()
                next_available = datetime.now() + timedelta(minutes=cooldown_minutes)
                
                self.cookie_states[cookie_id]["is_cooling"] = True
                self.cookie_states[cookie_id]["next_available"] = next_available.isoformat()
                
                # 从有效索引列表中移除
                if index in self.valid_indices:
                    self.valid_indices.remove(index)
                
                logger.info(f"Grok.com Cookie {index} 开始冷却，将在 {next_available} 后可用")
                self._save_state()
    
    def check_cooldowns(self):
        """检查所有Cookie的冷却状态"""
        for i in range(len(self.cookies)):
            cookie_id = f"cookie_{i}"
            state = self.cookie_states.get(cookie_id, {})
            
            if state.get("is_cooling", False) and state.get("next_available"):
                next_available = datetime.fromisoformat(state["next_available"])
                
                if datetime.now() >= next_available:
                    # 冷却结束
                    self.cookie_states[cookie_id]["is_cooling"] = False
                    self.cookie_states[cookie_id]["next_available"] = None
                    
                    # 如果Cookie有效，添加回有效索引列表
                    if state.get("valid", False) and i not in self.valid_indices:
                        self.valid_indices.append(i)
                    
                    logger.info(f"Grok.com Cookie {i} 冷却结束，现在可用")
                    self._save_state()
    
    def get_stats(self) -> Dict:
        """获取所有Cookie的统计信息
        
        Returns:
            Cookie统计信息
        """
        stats = {
            "total_cookies": len(self.cookies),
            "valid_cookies": len(self.valid_indices),
            "current_index": self.current_index,
            "cookies": []
        }
        
        for i, cookie in enumerate(self.cookies):
            cookie_id = f"cookie_{i}"
            state = self.cookie_states.get(cookie_id, {})
            cookie_preview = cookie[:20] + "..." if len(cookie) > 20 else cookie
            
            stats["cookies"].append({
                "index": i,
                "preview": cookie_preview,
                "valid": state.get("valid", False),
                "username": state.get("username", "UNKNOWN"),
                "request_count": state.get("request_count", 0),
                "last_used": state.get("last_used"),
                "last_checked": state.get("last_checked"),
                "is_cooling": state.get("is_cooling", False),
                "next_available": state.get("next_available")
            })
        
        return stats
    


    