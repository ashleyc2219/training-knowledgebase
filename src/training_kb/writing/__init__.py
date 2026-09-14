"""`writing` 套件入口：只 re-export Bedrock 邊界的公開名稱。"""

from training_kb.writing.client import CallTrace

__all__ = ["CallTrace"]
