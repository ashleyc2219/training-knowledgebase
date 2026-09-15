"""流程 stack：兩支 Lambda、`ticket-analysis` state machine、log group 與最小 IAM。

**本 stack 不參照 `TrainingKbData`**（controller 2026-09-14 裁決）。table 與 bucket 用
`Table.from_table_attributes`／`Bucket.from_bucket_name` 以**純字串名稱**接進來，樣板裡
因此沒有任何 `Fn::ImportValue`，`cdk deploy TrainingKbApp --exclusively` 才能單獨部署而
不碰同一波次正在修改的 data stack。名稱的唯一來源仍然只有一份：table 用 P09 模組的
`TABLE_NAME` 常數，bucket 用 cdk context `tkb:content-bucket` 或環境變數
`TKB_CONTENT_BUCKET`（`load_settings` 的預設值 `training-kb-content` 在雲端不存在，
所以這裡**沒有**預設值，缺值直接失敗）。

Lambda 的相依（`pydantic`／`jsonschema`）由 `infra/scripts/build_lambda_layer.py` 產出的
layer 提供：`Code.from_asset("src")` 只帶原始碼（COMMON.md R2）。Phase 42／48／52／54
沿用 `self.deps_layer`，不各自再做一支。
"""

import os
import pathlib
from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

from infra.scripts.build_lambda_layer import LAYER_ROOT
from infra.training_kb_data_stack import PRIVATE_PREFIXES, TABLE_NAME, TARGET_INDEX
from training_kb.config import DEFAULT_EMBEDDING_MODEL_ID, DEFAULT_PROJECT_ID
from training_kb.content import PUBLIC_SITE_PREFIX
from training_kb.errors import PermanentError
from training_kb.handlers.github_webhook import SECRET_ENV
from training_kb.pipeline_starter import STATE_MACHINE_NAMES
from training_kb.pipelines.asl import ASL_LOCAL_PATH

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_PATH = PROJECT_ROOT / "src"
LAYER_PATH = LAYER_ROOT
ASL_PATH = PROJECT_ROOT / ASL_LOCAL_PATH.format(pipeline="ticket-analysis", number=1)

CONTENT_BUCKET_ENV = "TKB_CONTENT_BUCKET"
CONTENT_BUCKET_CONTEXT = "tkb:content-bucket"
"""`cdk deploy -c tkb:content-bucket=<name>`；沒給就讀同名的環境變數。"""

TICKET_ANALYSIS_MACHINE = STATE_MACHINE_NAMES["ticket-analysis"]
PIPELINE_TASK_FUNCTION = "training-kb-pipeline-task"
WEBHOOK_FUNCTION = "training-kb-webhook"
"""00A §3.5、D-23：Lambda 與 state machine **不同名**，三條 pipeline 共用同一支函式。"""

TASK_TIMEOUT = Duration.seconds(90)
"""設計 §14.3：Lambda 90 秒、ASL Task 120 秒；兩者不同是刻意的。"""

WEBHOOK_TIMEOUT = Duration.seconds(10)
"""handler 自己守 8 秒 deadline（`WEBHOOK_DEADLINE_SECONDS`），函式逾時留一點餘裕。"""

MEMORY_MB = 512
"""記憶體同時決定 CPU：webhook 的八秒期限包含冷啟動與 `pydantic` import，128 MB 太緊。"""

ALL_PREFIXES: tuple[str, ...] = (*PRIVATE_PREFIXES, PUBLIC_SITE_PREFIX)
"""私有四個前綴 ＋ 公開的 `site/`（缺口 1：P24／P25 要寫公開前綴）。"""

DDB_ACTIONS = ["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:Scan",
               "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:ConditionCheckItem"]
"""交易寫入由 `PutItem`／`UpdateItem`／`ConditionCheckItem` 授權，**不含** `DeleteItem`。

`DeleteItem` 另外單獨一條（見 `_grant_delete_edges`），而且**不用**
`grant_read_write_data()`——CDK 那個 grant 會把 `DeleteItem` 混進同一條敘述，D-79 要的
「只有一條 `DeleteItem`」就守不住了。
"""


class TrainingKbStack(Stack):
    """流程 stack；`self.deps_layer` 供 Phase 42／48／52／54 沿用（不各自再做 layer）。"""

    def __init__(self, scope: Construct, construct_id: str, *,
                 content_bucket: str | None = None, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
        table = dynamodb.Table.from_table_attributes(
            self, "TrainingKbTable", table_name=TABLE_NAME, global_indexes=[TARGET_INDEX])
        bucket = s3.Bucket.from_bucket_name(
            self, "TrainingKbContent", self._content_bucket(content_bucket))
        self.deps_layer = self._layer()
        base_env = {
            "TKB_TABLE_NAME": TABLE_NAME,
            "TKB_CONTENT_BUCKET": bucket.bucket_name,
            "TKB_AWS_REGION": self.region,
            "TKB_PROJECT_ID": DEFAULT_PROJECT_ID,
            "TKB_EMBEDDING_MODEL_ID": DEFAULT_EMBEDDING_MODEL_ID,
            # TKB_GENERATION_MODEL_ID 刻意不設：O5 BLOCKED，不得填猜測值（00A §3.5）。
            # BedrockWriter 只有在真的呼叫生成模型時才丟 PermanentError，建構不受影響。
        }
        self.task_function = self._function(
            "PipelineTaskFunction", PIPELINE_TASK_FUNCTION,
            "training_kb.pipelines.common.pipeline_task_handler", TASK_TIMEOUT, base_env)
        self.webhook_function = self._function(
            "WebhookFunction", WEBHOOK_FUNCTION,
            "training_kb.handlers.github_webhook.handler", WEBHOOK_TIMEOUT,
            # 值只由部署當下的 shell 提供；缺值讓 synth 當場 KeyError，比部署出一支
            # 永遠驗簽失敗的 Lambda 好（明文環境變數的取捨見 Phase 41 報告 §5）。
            {**base_env, SECRET_ENV: os.environ[SECRET_ENV]})
        for function in (self.task_function, self.webhook_function):
            self._grant_data(function, table, bucket)
        self._grant_delete_edges(self.task_function, table)
        self.task_function.add_to_role_policy(iam.PolicyStatement(
            # O5 BLOCKED 期間只列已核定用途的 embedding 模型；生成模型的 ARN 等
            # TKB_GENERATION_MODEL_ID 有實測值之後再加（00A §3.5）。
            actions=["bedrock:InvokeModel"],
            resources=[f"arn:aws:bedrock:{self.region}::foundation-model/"
                       f"{DEFAULT_EMBEDDING_MODEL_ID}"]))
        self.webhook_url = self.webhook_function.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE)
        self.log_group = logs.LogGroup(
            self, "TicketAnalysisLogs",
            log_group_name=f"/aws/vendedlogs/states/{TICKET_ANALYSIS_MACHINE}",
            retention=logs.RetentionDays.ONE_MONTH, removal_policy=RemovalPolicy.DESTROY)
        self.ticket_analysis = sfn.StateMachine(
            self, "TicketAnalysis", state_machine_name=TICKET_ANALYSIS_MACHINE,
            state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_file(str(ASL_PATH)),
            definition_substitutions={
                "PipelineTaskFunctionArn": self.task_function.function_arn},
            logs=sfn.LogOptions(destination=self.log_group, level=sfn.LogLevel.ALL),
            timeout=Duration.minutes(15))
        self.task_function.grant_invoke(self.ticket_analysis)
        self.ticket_analysis.grant_start_execution(self.webhook_function)
        self._grant_execution_lookup(self.webhook_function)
        CfnOutput(self, "TicketAnalysisStateMachineArn",
                  value=self.ticket_analysis.state_machine_arn)
        CfnOutput(self, "WebhookFunctionUrl", value=self.webhook_url.url)
        CfnOutput(self, "TicketAnalysisLogGroup", value=self.log_group.log_group_name)
        CfnOutput(self, "PipelineTaskFunctionName", value=self.task_function.function_name)

    # --- 私有 helper -----------------------------------------------------------

    def _content_bucket(self, override: str | None) -> str:
        """bucket 名稱：建構參數 -> cdk context -> 環境變數；**沒有預設值**。

        `load_settings` 的 `training-kb-content` 在這個帳號不存在，退回它只會讓 Lambda
        在第一次 `get_object` 才爆 `NoSuchBucket`，所以缺值就當場失敗。
        """
        name = override or self.node.try_get_context(CONTENT_BUCKET_CONTEXT) \
            or os.environ.get(CONTENT_BUCKET_ENV)
        if not name:
            raise PermanentError(
                f"缺少內容 bucket 名稱：請設 {CONTENT_BUCKET_ENV} 或 "
                f"cdk context {CONTENT_BUCKET_CONTEXT}")
        return str(name)

    def _layer(self) -> lambda_.LayerVersion:
        if not LAYER_PATH.is_dir():
            raise FileNotFoundError(
                f"缺少 Lambda 相依 layer：{LAYER_PATH}；"
                "先跑 uv run python -m infra.scripts.build_lambda_layer")
        return lambda_.LayerVersion(
            self, "DependencyLayer", layer_version_name="training-kb-deps",
            code=lambda_.Code.from_asset(str(LAYER_PATH)),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            compatible_architectures=[lambda_.Architecture.X86_64])

    def _function(self, construct_id: str, name: str, handler: str,
                  timeout: Duration, environment: dict[str, str]) -> lambda_.Function:
        """兩支 Lambda 的共同形狀；架構固定 x86_64，與 layer 的 wheel 平台一致。"""
        return lambda_.Function(
            self, construct_id, function_name=name,
            runtime=lambda_.Runtime.PYTHON_3_12, architecture=lambda_.Architecture.X86_64,
            code=lambda_.Code.from_asset(str(SOURCE_PATH),
                                         exclude=["**/__pycache__", "**/*.pyc"]),
            layers=[self.deps_layer], handler=handler, timeout=timeout,
            memory_size=MEMORY_MB, environment=environment)

    def _grant_data(self, function: lambda_.Function, table: dynamodb.ITable,
                    bucket: s3.IBucket) -> None:
        """單表（含唯一索引）＋ 五個 key 前綴；形狀照 P09 資料角色，不用 CDK 的 grant。

        `s3:ListBucket` 是 bucket 層級動作，資源必須是 bucket ARN：沒有它，真實 S3 會把
        「key 不存在」回成 403 而不是 404，Phase 07 的 `get_object -> None` 就不成立。
        """
        function.add_to_role_policy(iam.PolicyStatement(
            actions=DDB_ACTIONS,
            resources=[table.table_arn, f"{table.table_arn}/index/{TARGET_INDEX}"]))
        function.add_to_role_policy(iam.PolicyStatement(
            actions=["s3:GetObject", "s3:PutObject"],
            resources=[bucket.arn_for_objects(f"{prefix}*") for prefix in ALL_PREFIXES]))
        function.add_to_role_policy(iam.PolicyStatement(
            actions=["s3:ListBucket"], resources=[bucket.bucket_arn],
            conditions={"StringLike": {"s3:prefix": [f"{prefix}*" for prefix in ALL_PREFIXES]}}))

    def _grant_delete_edges(self, function: lambda_.Function, table: dynamodb.ITable) -> None:
        """缺口 2（D-79）：唯一一條 `dynamodb:DeleteItem`，資源只有這張表本體。

        D-79 逐字要的是「只准刪 `SK begins_with APPLIED_TO#`」，但 DynamoDB 的 IAM 條件鍵
        只有 `dynamodb:LeadingKeys`（比 **PK**）、`dynamodb:Attributes` 這些，**沒有**比 SK
        的條件鍵，所以在 IAM 層做不到逐字等價（controller 2026-09-14 裁決）。範圍改由
        程式層 `Repository.DELETABLE_RELATIONS`（只有 `APPLIED_TO`）守住，這裡只把授權
        收到最小：單表、單動作、不給索引、不給 `dynamodb:*`。
        """
        function.add_to_role_policy(iam.PolicyStatement(
            actions=["dynamodb:DeleteItem"], resources=[table.table_arn]))

    def _grant_execution_lookup(self, function: lambda_.Function) -> None:
        """缺口 3：P32 的續跑判斷要 `DescribeExecution`，`_build_wiring` 要 `GetCallerIdentity`。

        `release-update`／`feedback-review` 的 state machine 由 P52／P48 建立，那時同一支
        stack 再把它們的 execution ARN 加進來；現在只授權真的存在的這一條。
        """
        function.add_to_role_policy(iam.PolicyStatement(
            actions=["states:DescribeExecution"],
            resources=[f"arn:aws:states:{self.region}:{self.account}:execution:"
                       f"{TICKET_ANALYSIS_MACHINE}:*"]))
        function.add_to_role_policy(iam.PolicyStatement(
            actions=["sts:GetCallerIdentity"], resources=["*"]))  # 沒有資源層級授權
