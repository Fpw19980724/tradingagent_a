"""Web进度追踪器，用于实时推送LLM调用、工具调用、Agent状态等信息。"""

import json
import threading
import time
from typing import Any, Dict, List, Optional, Union
from queue import Queue

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.messages import AIMessage


class WebProgressTracker(BaseCallbackHandler):
    """Callback handler that tracks progress for web streaming."""

    # Agent名称映射
    ANALYST_MAPPING = {
        "market": "Market Analyst",
        "social": "Social Analyst",
        "news": "News Analyst",
        "fundamentals": "Fundamentals Analyst",
    }

    # 固定团队成员
    FIXED_AGENTS = {
        "research": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "trading": ["Trader"],
        "risk": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
        "portfolio": ["Portfolio Manager"],
    }

    def __init__(self, event_queue: Optional[Queue] = None, selected_analysts: List[str] = None) -> None:
        """
        初始化进度追踪器。

        参数：
            event_queue: 可选的事件队列（用于线程模式）。
            selected_analysts: 选中的分析师列表。
        """
        super().__init__()
        self._lock = threading.Lock()
        self.event_queue = event_queue  # 可选，用于线程模式
        self.selected_analysts = selected_analysts or ["market", "news", "fundamentals"]

        # 统计信息
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.start_time = time.time()

        # Agent状态
        self.agent_status: Dict[str, str] = {}
        self.current_agent: Optional[str] = None
        self._init_agent_status()

        # 最近消息和工具调用
        self.recent_events: List[Dict] = []
        self.max_events = 50

        # 待发送事件列表（用于流式模式）
        self.pending_events: List[Dict] = []

    def _init_agent_status(self) -> None:
        """初始化agent状态。"""
        # 添加选中的分析师
        for analyst in self.selected_analysts:
            if analyst in self.ANALYST_MAPPING:
                self.agent_status[self.ANALYST_MAPPING[analyst]] = "pending"

        # 添加固定团队成员
        for team_agents in self.FIXED_AGENTS.values():
            for agent in team_agents:
                self.agent_status[agent] = "pending"

    def _push_event(self, event_type: str, data: Dict) -> None:
        """推送事件到队列（线程模式）或待发送列表（流式模式）。"""
        event = {
            "type": event_type,
            "timestamp": time.strftime("%H:%M:%S"),
            **data
        }

        # 如果有队列，推送到队列
        if self.event_queue:
            self.event_queue.put(event)

        # 同时保存到待发送列表（用于流式模式获取）
        with self._lock:
            self.pending_events.append(event)
            if len(self.pending_events) > self.max_events:
                self.pending_events.pop(0)

            # 也保存到最近事件列表
            self.recent_events.append(event)
            if len(self.recent_events) > self.max_events:
                self.recent_events.pop(0)

    def _push_event_direct(self, event_type: str, data: Dict) -> None:
        """直接推送事件（用于非回调场景，如chunk分析）。"""
        event = {
            "type": event_type,
            "timestamp": time.strftime("%H:%M:%S"),
            **data
        }

        with self._lock:
            self.pending_events.append(event)
            self.recent_events.append(event)
            if len(self.pending_events) > self.max_events:
                self.pending_events.pop(0)
            if len(self.recent_events) > self.max_events:
                self.recent_events.pop(0)

    def get_pending_events(self) -> List[Dict]:
        """获取并清空待发送事件列表。"""
        with self._lock:
            events = self.pending_events.copy()
            self.pending_events.clear()
            return events

    def _get_stats(self) -> Dict[str, Any]:
        """获取当前统计信息。"""
        elapsed = time.time() - self.start_time
        with self._lock:
            return {
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "elapsed_seconds": int(elapsed),
                "agents_completed": sum(1 for s in self.agent_status.values() if s == "completed"),
                "agents_total": len(self.agent_status),
            }

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        """LLM调用开始。"""
        with self._lock:
            self.llm_calls += 1

        agent_name = self._extract_agent_name(serialized, kwargs)

        self._push_event("llm_start", {
            "call_count": self.llm_calls,
            "agent": agent_name,
        })
        self._push_event("stats", self._get_stats())

    def on_chat_model_start(self, serialized: Dict[str, Any], messages: List[List[Any]], **kwargs: Any) -> None:
        """对话模型开始。"""
        with self._lock:
            self.llm_calls += 1

        agent_name = self._extract_agent_name(serialized, kwargs)

        self._push_event("llm_start", {
            "call_count": self.llm_calls,
            "agent": agent_name,
        })
        self._push_event("stats", self._get_stats())

    def _extract_agent_name(self, serialized: Dict[str, Any], kwargs: Dict[str, Any]) -> str:
        """尝试从调用参数中提取agent名称。"""
        # 优先使用已设置的current_agent
        if self.current_agent:
            return self.current_agent

        # 尝试从kwargs的tags中提取
        tags = kwargs.get("tags", [])
        for tag in tags:
            if tag and not tag.startswith("seq:"):
                return tag

        # 尝试从serialized中提取
        if serialized:
            name = serialized.get("name", "")
            if name and name != "ChatOpenAI":
                return name
            lc = serialized.get("lc", [])
            if lc and len(lc) >= 2:
                return lc[-1]

        # 尝试从kwargs的metadata提取
        metadata = kwargs.get("metadata", {})
        if metadata:
            agent_name = metadata.get("agent_name", "")
            if agent_name:
                return agent_name

        return "LLM"

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """LLM调用结束，提取token用量。"""
        try:
            generation = response.generations[0][0]
        except (IndexError, TypeError):
            return

        usage_metadata = None
        if hasattr(generation, "message"):
            message = generation.message
            if isinstance(message, AIMessage) and hasattr(message, "usage_metadata"):
                usage_metadata = message.usage_metadata

        if usage_metadata:
            with self._lock:
                self.tokens_in += usage_metadata.get("input_tokens", 0)
                self.tokens_out += usage_metadata.get("output_tokens", 0)

            self._push_event("llm_end", {
                "tokens_in": usage_metadata.get("input_tokens", 0),
                "tokens_out": usage_metadata.get("output_tokens", 0),
                "total_in": self.tokens_in,
                "total_out": self.tokens_out,
            })
            self._push_event("stats", self._get_stats())

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> None:
        """工具调用开始。"""
        tool_name = serialized.get("name", "unknown_tool")

        with self._lock:
            self.tool_calls += 1

        args_str = str(input_str)
        if len(args_str) > 100:
            args_str = args_str[:97] + "..."

        self._push_event("tool_start", {
            "tool_name": tool_name,
            "args": args_str,
            "call_count": self.tool_calls,
            "agent": self.current_agent or "Unknown",
        })
        self._push_event("stats", self._get_stats())

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """工具调用结束。"""
        output_str = str(output)
        if len(output_str) > 200:
            output_str = output_str[:197] + "..."

        self._push_event("tool_end", {
            "output": output_str,
        })

    def set_current_agent(self, agent_name: str) -> None:
        """设置当前运行的agent。"""
        with self._lock:
            self.current_agent = agent_name
            if agent_name in self.agent_status:
                self.agent_status[agent_name] = "in_progress"

        self._push_event_direct("agent_start", {
            "agent": agent_name,
            "status": "in_progress",
            "agent_status": self.agent_status,
        })

    def mark_agent_completed(self, agent_name: str) -> None:
        """标记agent完成。"""
        with self._lock:
            if agent_name in self.agent_status:
                self.agent_status[agent_name] = "completed"
            self.current_agent = None

        self._push_event_direct("agent_complete", {
            "agent": agent_name,
            "status": "completed",
            "agent_status": self.agent_status,
        })
        self._push_event_direct("stats", self._get_stats())

    def mark_agent_error(self, agent_name: str, error: str) -> None:
        """标记agent错误。"""
        with self._lock:
            if agent_name in self.agent_status:
                self.agent_status[agent_name] = "error"
            self.current_agent = None

        self._push_event_direct("agent_error", {
            "agent": agent_name,
            "status": "error",
            "error": error,
            "agent_status": self.agent_status,
        })

    def get_full_status(self) -> Dict[str, Any]:
        """获取完整状态信息。"""
        return {
            "stats": self._get_stats(),
            "agent_status": self.agent_status,
            "current_agent": self.current_agent,
            "recent_events": self.recent_events[-20:],
        }