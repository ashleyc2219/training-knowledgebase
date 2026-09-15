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

from aws_cdk import ArnFormat, CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

from infra.scripts.build_lambda_layer import LAYER_ROOT, MARKERS, is_built
from infra.training_kb_data_stack import PRIVATE_PREFIXES, TABLE_NAME, TARGET_INDEX
from training_kb.config import DEFAULT_EMBEDDING_MODEL_ID, DEFAULT_PROJECT_ID
from training_kb.content import PUBLIC_SITE_PREFIX
from training_kb.errors import PermanentError
from training_kb.faults import ENV_NAME_ENV, PRODUCTION
from training_kb.handlers.github_webhook import SECRET_ENV
from training_kb.handlers.import_ import IMPORT_DEADLINE_SECONDS
from training_kb.keys import OPERATIONS_PREFIX
from training_kb.pipeline_starter import STATE_MACHINE_NAMES
from training_kb.pipelines.asl import ASL_LOCAL_PATH
from training_kb.pipelines.common import PipelineName

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

TASK_PREFIXES: tuple[str, ...] = (*PRIVATE_PREFIXES, PUBLIC_SITE_PREFIX)
"""pipeline Lambda：私有四個前綴 ＋ 公開的 `site/`（缺口 1：P24／P25 要寫公開前綴）。"""

WEBHOOK_PREFIXES: tuple[str, ...] = (OPERATIONS_PREFIX,)
"""webhook Lambda：**只有** `operations/`。

它是唯一 `AuthType: NONE` 的公開入口，全部的寫入只有
`ingress._put_canonical_input_once` 的 `operations/<op>/input.json`。給它 `site/*` 等於
讓一個免驗證入口有能力改公開站的內容（驗簽只保證來源，不保證程式沒有其他洞）。
"""

TASK_DDB_ACTIONS = ["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query",
                    "dynamodb:Scan", "dynamodb:PutItem", "dynamodb:UpdateItem",
                    "dynamodb:ConditionCheckItem"]
"""交易寫入由 `PutItem`／`UpdateItem`／`ConditionCheckItem` 授權，**不含** `DeleteItem`。

`DeleteItem` 另外單獨一條（見 `_grant_delete_edges`），而且**不用**
`grant_read_write_data()`——CDK 那個 grant 會把 `DeleteItem` 混進同一條敘述，D-79 要的
「只有一條 `DeleteItem`」就守不住了。
"""

WEBHOOK_DDB_ACTIONS = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                       "dynamodb:Scan"]
"""接入路徑實際用到的四個動作，逐一對得上程式：

| 動作 | 來源 |
|---|---|
| `GetItem` | `operations.get_meta_item`、`rote.get_proc`、`ingress.get_meta`／`get_version` |
| `PutItem` | `operations.put_meta_item`（帶條件的永久去重）、`rote.put_meta`、`ingress.put_edge` |
| `UpdateItem` | `operations.update_meta`（`_revision` 的 compare-and-swap） |
| `Scan` | `rote.list_procs` → `scan_entity("PROC")`（兩層命中要看同 domain／adapter 的全部 PROC） |

**沒有** `Query`／`BatchGetItem`／`ConditionCheckItem`（接入路徑不做交易也不查 GSI），
所以索引 ARN 也不給。
"""


# ---- Phase 54 ----（D-56、D-58：`training-kb-analytics` 的接線由 Phase 54 完成）

ANALYTICS_FUNCTION = "training-kb-analytics"
ANALYTICS_HANDLER = "training_kb.handlers.analytics.handler"
"""非 pipeline 的分析入口：不進 Step Functions，維護者用 boto3 `invoke` 呼叫。"""

ANALYTICS_TIMEOUT = Duration.seconds(60)
"""`metrics` 要掃 VIEW 與 TICKET（`_scan_models` 讀完所有分頁），比 webhook 的 10 秒寬。"""

ANALYTICS_PREFIXES: tuple[str, ...] = (OPERATIONS_PREFIX,)
"""analytics Lambda：**只有** `operations/`。

`metrics` 自己一個 S3 物件都不讀；這個前綴是留給 Phase 55 的
`operations/rules/validated_at.json`（`analytics/status_writer.py` 的唯一寫入者）。
不給 `tutorials/`／`site/`：它既不寫教學也不發布。
"""

ANALYTICS_DDB_ACTIONS = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan",
                         "dynamodb:PutItem", "dynamodb:UpdateItem"]
"""四個讀 ＋ 兩個寫，逐一對得上程式：

| 動作 | 來源 |
|---|---|
| `GetItem` | `get_version`／`get_tutorial`／`list_feedback_of_version` 的回基表一致讀取 |
| `Query` | `query_by_target`（GSI；`list_feedback_of_version` 的候選）、`query_pk` |
| `Scan` | `list_views_of_version`／`list_tickets`／`list_rules` 的 `_scan_models` |
| `PutItem`／`UpdateItem` | **Phase 55** 的 `apply_rule_status`（D-58：Phase 55 不再動 CDK） |

**沒有** `DeleteItem`（D-79 的那一條只屬於 task function）、沒有 `BatchGetItem`、
沒有 `ConditionCheckItem`、沒有 `bedrock:InvokeModel`（`metrics` 只讀 `CallTrace`，
不呼叫模型）、沒有 `states:StartExecution`（它不啟動任何 pipeline）。
"""

# ---- Phase 54 結束 ----


# ---- Phase 42 ----（D-56、D-58：`training-kb-import` 的接線由 Phase 42 完成）

IMPORT_FUNCTION = "training-kb-import"
IMPORT_HANDLER = "training_kb.handlers.import_.handler"
"""固定匯入入口：維護者用 boto3 `invoke` 餵匯入檔，**不開 Function URL**。

沒有公開入口就沒有驗簽需求，所以它也**不需要** `TKB_GITHUB_WEBHOOK_SECRET`；
全 stack 唯一 `AuthType: NONE` 的公開網址仍然只有 Phase 30 的 webhook。
"""

IMPORT_TIMEOUT = Duration.seconds(int(IMPORT_DEADLINE_SECONDS))
"""與 `handlers/import_.py` 的 `IMPORT_DEADLINE_SECONDS` 同一個數字導出，不各打一份。"""

IMPORT_PREFIXES: tuple[str, ...] = (OPERATIONS_PREFIX,)
"""匯入 Lambda：**只有** `operations/`。

`feedback`／`view` 一個 S3 物件都不寫；這個前綴是給 `ticket`／`release` 分支的
`ingress._put_canonical_input_once`（`operations/<op>/input.json`）。不給
`tutorials/`／`site/`：它既不寫教學也不發布。
"""

IMPORT_MACHINES: tuple[PipelineName, ...] = ("ticket-analysis", "release-update")
"""匯入 Lambda 可以啟動的兩條 pipeline；`feedback-review`（P48）不在內，固定匯入不啟動它。"""

IMPORT_DDB_ACTIONS = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                      "dynamodb:Scan"]
"""四個動作，逐一對得上程式：

| 動作 | 來源 |
|---|---|
| `GetItem` | `get_version`／`get_tutorial`／`get_meta`（去重的存在判斷）、`get_meta_item` |
| `PutItem` | `put_meta`（帶條件）、`put_edge`、`operations.put_meta_item`（去重與取號） |
| `UpdateItem` | `operations.update_meta`／`complete`（`_revision` 的 compare-and-swap） |
| `Scan` | `ticket`／`release` 分支的 `rote.list_procs` → `scan_entity("PROC")` |

**沒有** `Query`／`BatchGetItem`／`ConditionCheckItem`（這條路徑不查 GSI 也不做交易），
所以索引 ARN 也不給；**沒有** `DeleteItem`（D-79 的那一條只屬於 task function）；
**沒有** `bedrock:InvokeModel`（本 Phase 零模型呼叫，Phase 43 加留言分類時才補）。
"""

# ---- Phase 42 結束 ----


# ---- Phase 52 ----（D-23：第二條 state machine 共用同一支 Lambda，不建第二個函式）

RELEASE_UPDATE_MACHINE = STATE_MACHINE_NAMES["release-update"]
RELEASE_ASL_PATH = PROJECT_ROOT / ASL_LOCAL_PATH.format(pipeline="release-update", number=1)
"""`training-kb-release-update` 的名稱與定義檔；名稱唯一來源仍是 `STATE_MACHINE_NAMES`。"""

# ---- Phase 52 結束 ----


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
            # 預設 prod：faults.active_fault 在正式部署一律不生效。P59 要做復原演練時
            # 以 TKB_ENV=demo 重新部署（00A §3.5 的執行期開關）。
            "TKB_ENV": os.environ.get(ENV_NAME_ENV, PRODUCTION),
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
        self._grant_data(self.task_function, table, bucket, prefixes=TASK_PREFIXES,
                         actions=TASK_DDB_ACTIONS, with_index=True)
        self._grant_data(self.webhook_function, table, bucket, prefixes=WEBHOOK_PREFIXES,
                         actions=WEBHOOK_DDB_ACTIONS, with_index=False)
        self._grant_delete_edges(self.task_function, table)
        for function in (self.task_function, self.webhook_function):
            # webhook 也要：ingress 的 Agent 回退在這支 Lambda 裡跑 Converse（O5 解鎖後
            # 沒有這條會 AccessDenied）。O5 BLOCKED 期間只列已核定用途的 embedding 模型；
            # 生成模型的 ARN 等 TKB_GENERATION_MODEL_ID 有實測值之後再加（00A §3.5）。
            function.add_to_role_policy(iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[f"arn:aws:bedrock:{self.region}::foundation-model/"
                           f"{DEFAULT_EMBEDDING_MODEL_ID}"]))
        self.webhook_url = self.webhook_function.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE)
        self.log_group = logs.LogGroup(
            self, "TicketAnalysisLogs",
            log_group_name=f"/aws/vendedlogs/states/{TICKET_ANALYSIS_MACHINE}",
            # 證據依賴 execution history 的 90 天保留期，log 要活得比它久一點
            retention=logs.RetentionDays.THREE_MONTHS, removal_policy=RemovalPolicy.DESTROY)
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

        # ---- Phase 54 ----（D-58；只用既有的 `_function`／`_grant_data`，不改別人的程式）
        #
        # 不開 Function URL、不給 `states:StartExecution`（它不啟動任何 pipeline）、
        # 不給 `bedrock:InvokeModel`（`metrics` 只讀 `CallTrace`，不呼叫模型）、
        # 不給 `dynamodb:DeleteItem`（D-79 的那一條只屬於 task function）。
        #
        # 動作清單裡的 `PutItem`／`UpdateItem` 與 `operations/` 是留給 Phase 55 的
        # `apply_rule_status` 與 `operations/rules/validated_at.json`：本 Phase 自己
        # **只讀**，但 D-58 明定 Phase 55 不再動 CDK，現在不給足就會逼它回來改這支
        # 共用檔（Phase 54 §7 Task 4、§11 完成清單）。
        self.analytics_function = self._function(
            "AnalyticsFunction", ANALYTICS_FUNCTION, ANALYTICS_HANDLER,
            ANALYTICS_TIMEOUT, base_env)
        self._grant_data(self.analytics_function, table, bucket,
                         prefixes=ANALYTICS_PREFIXES, actions=ANALYTICS_DDB_ACTIONS,
                         with_index=True)   # GSI：list_feedback_of_version 走 query_by_target
        # ---- Phase 54 結束 ----

        # ---- Phase 42 ----（D-58；只用既有的 `_function`／`_grant_data`，不改別人的程式）
        #
        # 不開 Function URL（維護者用 boto3 invoke）、不給 `bedrock:InvokeModel`
        # （本 Phase 零模型呼叫）、不給 `dynamodb:DeleteItem`、不給 GSI。
        # `states:StartExecution` 見 `_import_machine_arns`：**用名稱組 ARN**，一次授權
        # `ticket-analysis` 與 P52 之後才建立的 `release-update`（controller 2026-09-14）。
        self.import_function = self._function(
            "ImportFunction", IMPORT_FUNCTION, IMPORT_HANDLER, IMPORT_TIMEOUT, base_env)
        self._grant_data(self.import_function, table, bucket, prefixes=IMPORT_PREFIXES,
                         actions=IMPORT_DDB_ACTIONS, with_index=False)
        self.import_function.add_to_role_policy(iam.PolicyStatement(
            actions=["states:StartExecution"], resources=self._import_machine_arns()))
        CfnOutput(self, "ImportFunctionName", value=self.import_function.function_name)
        # ---- Phase 42 結束 ----

        # ---- Phase 52 ----（D-23、D-49；只用既有的 `self.task_function`，不建第二個 Lambda）
        #
        # 七個 Task 的 `Resource` 都是同一支共用函式的**直接 ARN**（沒有
        # `arn:aws:states:::lambda:invoke` 信封，所以 ASL 裡也沒有 `Payload` 外層），
        # 由 `Parameters.pipeline`／`Parameters.task` 分派到
        # `training_kb.pipelines.release:release_update_handler`。
        #
        # `grant_start_execution` **只給 webhook**：Phase 42 的匯入 Lambda 已經用
        # `_import_machine_arns()` 以名稱組 ARN 一次授權兩條 pipeline（controller
        # 2026-09-14 裁決），這裡再 grant 一次只會長出重複的敘述。
        self.release_update_logs = logs.LogGroup(
            self, "ReleaseUpdateLogs",
            log_group_name=f"/aws/vendedlogs/states/{RELEASE_UPDATE_MACHINE}",
            retention=logs.RetentionDays.THREE_MONTHS, removal_policy=RemovalPolicy.DESTROY)
        self.release_update = sfn.StateMachine(
            self, "ReleaseUpdate", state_machine_name=RELEASE_UPDATE_MACHINE,
            state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_file(str(RELEASE_ASL_PATH)),
            definition_substitutions={
                "PipelineTaskFunctionArn": self.task_function.function_arn},
            logs=sfn.LogOptions(destination=self.release_update_logs,
                                level=sfn.LogLevel.ALL),
            timeout=Duration.minutes(15))
        self.task_function.grant_invoke(self.release_update)
        self.release_update.grant_start_execution(self.webhook_function)
        # 缺口 3 的第二半（P41 `_grant_execution_lookup` 留的 TODO）：P32 的續跑判斷會對
        # `release-update` 的 execution 呼叫 `DescribeExecution`，現在這條真的存在了才補。
        self.webhook_function.add_to_role_policy(iam.PolicyStatement(
            actions=["states:DescribeExecution"],
            resources=[f"arn:aws:states:{self.region}:{self.account}:execution:"
                       f"{RELEASE_UPDATE_MACHINE}:*"]))
        CfnOutput(self, "ReleaseUpdateStateMachineArn",
                  value=self.release_update.state_machine_arn)
        CfnOutput(self, "ReleaseUpdateLogGroup",
                  value=self.release_update_logs.log_group_name)
        # ---- Phase 52 結束 ----

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
        """相依 layer；**查的是真的裝好的套件目錄**，不是只看資料夾在不在。

        空的 `build/lambda-layer/python/` 會讓 synth 與 deploy 都成功，卻在第一次 invoke
        才 `Runtime.ImportModuleError: No module named 'pydantic'`。
        """
        if not is_built(LAYER_PATH):
            raise FileNotFoundError(
                f"Lambda 相依 layer 沒有建好（缺 {'／'.join(MARKERS)}）：{LAYER_PATH}；"
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
                    bucket: s3.IBucket, *, prefixes: tuple[str, ...] = TASK_PREFIXES,
                    actions: list[str] | None = None, with_index: bool = True) -> None:
        """單表 ＋ 指定 key 前綴；形狀照 P09 資料角色，**不用** CDK 的 grant。

        三個 keyword 都有預設值（＝ pipeline Lambda 的範圍），只是為了讓既有呼叫端不必
        同時改；**新的呼叫端請明寫自己真正需要的最小集合**。

        兩支 Lambda 的範圍**刻意不同**（見 `WEBHOOK_PREFIXES`／`WEBHOOK_DDB_ACTIONS`）：
        公開入口拿到的權限必須小於內部流程，否則驗簽以外的任何洞都直接等於可以改公開站。

        `s3:ListBucket` 是 bucket 層級動作，資源必須是 bucket ARN：沒有它，真實 S3 會把
        「key 不存在」回成 403 而不是 404，Phase 07 的 `get_object -> None` 就不成立。
        """
        resources = [table.table_arn]
        if with_index:
            resources.append(f"{table.table_arn}/index/{TARGET_INDEX}")
        function.add_to_role_policy(iam.PolicyStatement(
            actions=list(actions if actions is not None else TASK_DDB_ACTIONS),
            resources=resources))
        function.add_to_role_policy(iam.PolicyStatement(
            actions=["s3:GetObject", "s3:PutObject"],
            resources=[bucket.arn_for_objects(f"{prefix}*") for prefix in prefixes]))
        function.add_to_role_policy(iam.PolicyStatement(
            actions=["s3:ListBucket"], resources=[bucket.bucket_arn],
            conditions={"StringLike": {"s3:prefix": [f"{prefix}*" for prefix in prefixes]}}))

    # ---- Phase 42 ----
    def _import_machine_arns(self) -> list[str]:
        """匯入 Lambda 可以啟動的兩條 state machine ARN，由**名稱**組出來（00A §3.5）。

        不用 `machine.grant_start_execution(...)`：`training-kb-release-update` 要到
        [Phase 52] 才有 construct，而 IAM 允許引用尚不存在的資源。用名稱組 ARN 之後
        P52 建它的時候不必回頭碰這支 Lambda（controller 2026-09-14 裁決）。
        `feedback-review`（P48）不在清單裡：固定匯入不啟動它。
        """
        return [self.format_arn(service="states", resource="stateMachine",
                                resource_name=STATE_MACHINE_NAMES[pipeline],
                                arn_format=ArnFormat.COLON_RESOURCE_NAME)
                for pipeline in IMPORT_MACHINES]
    # ---- Phase 42 結束 ----

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
