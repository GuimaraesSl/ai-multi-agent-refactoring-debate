"""Pluggable LLM backend for the specialist and judge agents."""

from refactoring_debate.llm.provider import LLMHandle, build_llm

__all__ = ["LLMHandle", "build_llm"]
