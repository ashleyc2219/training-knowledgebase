"""`writing` 套件入口：只 re-export Bedrock 邊界的公開名稱。"""

from training_kb.writing.client import BedrockWriter, CallTrace, Writer

__all__ = ["BedrockWriter", "CallTrace", "Writer"]
