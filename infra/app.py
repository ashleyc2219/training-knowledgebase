"""CDK app 進入點。本 Phase 只實例化資料 stack；流程 stack（TrainingKbApp）由 Phase 41 加入。"""

import os

import aws_cdk as cdk

from infra.training_kb_data_stack import TrainingKbDataStack

# 全案只用一個 region（與 Bedrock 同區），可用 TKB_AWS_REGION 覆寫（00A §3.5）。
DEFAULT_REGION = "us-east-1"

app = cdk.App()
TrainingKbDataStack(
    app,
    "TrainingKbData",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("TKB_AWS_REGION") or DEFAULT_REGION,
    ),
)
app.synth()
