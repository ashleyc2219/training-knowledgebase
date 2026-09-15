"""CDK app 進入點：資料 stack（Phase 09）與流程 stack（Phase 41）。

兩個 stack 用**同一個 `env`**，但彼此**沒有**跨 stack 參照：`TrainingKbStack` 以純字串
名稱接進既有的 table 與 bucket，所以
`cdk deploy TrainingKbApp --exclusively` 不會連帶改到 `TrainingKbData`（controller
2026-09-14 裁決）。

`cdk` 的任何子命令都會先合成**整個 app**（`--exclusively` 只限制部署哪一個 stack），
所以流程 stack 的三個部署前提（webhook secret、內容 bucket 名稱、已建好的相依 layer）
缺任何一個時**只跳過它**、把原因印到 stderr，不讓 `TrainingKbData` 的部署被連坐擋住。
真的要部署流程 stack 時三個前提都齊，缺值不會靜靜部署出一支驗簽永遠失敗的 Lambda。
"""

import os
import sys

import aws_cdk as cdk

from infra.scripts.build_lambda_layer import is_built
from infra.training_kb_data_stack import TrainingKbDataStack
from infra.training_kb_stack import (
    CONTENT_BUCKET_CONTEXT,
    CONTENT_BUCKET_ENV,
    LAYER_PATH,
    TrainingKbStack,
)
from training_kb.handlers.github_webhook import SECRET_ENV

# 全案只用一個 region（與 Bedrock 同區），可用 TKB_AWS_REGION 覆寫（00A §3.5）。
DEFAULT_REGION = "us-east-1"

app = cdk.App()
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("TKB_AWS_REGION") or DEFAULT_REGION,
)
TrainingKbDataStack(app, "TrainingKbData", env=env)

missing: list[str] = []
if not os.environ.get(SECRET_ENV):
    missing.append(f"環境變數 {SECRET_ENV}")
if not (app.node.try_get_context(CONTENT_BUCKET_CONTEXT) or os.environ.get(CONTENT_BUCKET_ENV)):
    missing.append(f"環境變數 {CONTENT_BUCKET_ENV} 或 cdk context {CONTENT_BUCKET_CONTEXT}")
if not is_built(LAYER_PATH):
    missing.append(f"{LAYER_PATH}（先跑 uv run python -m infra.scripts.build_lambda_layer）")
if missing:
    print(f"[infra] 跳過 TrainingKbApp，缺少：{'；'.join(missing)}", file=sys.stderr)
else:
    TrainingKbStack(app, "TrainingKbApp", env=env)

app.synth()
