"""Phase 60 Task 1／2：四支靜態安全檢查與 Snyk 紀錄。

Given／When／Then 寫在每個測試的名稱與 docstring 裡。這支檔**完全離線**：
policy 與 template 由同檔 fixture 合成，`check_secrets` 用 `tmp_path` 現建的 git repo，
`check_output_safety` 只呼叫本專案的 renderer 與 prompt，不連任何外部服務。
"""

import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from infra.scripts.checks import (
    CheckResult,
    ScanRecord,
    check_iam,
    check_output_safety,
    check_public,
    check_secrets,
    probe_site,
    render_scan_report,
    run_all,
)

Policy = Mapping[str, object]

SECRET_KEY = "TKB_" + "GITHUB_WEBHOOK_SECRET"
"""刻意串接：這支檔自己也在 `check_secrets` 的掃描範圍內，寫成完整字面值再接一個賦值
符號會讓本檔變成自己的 finding（那才是真的假陽性）。"""


@pytest.fixture
def policy_factory() -> Callable[..., Policy]:
    """產生一份只含單一 Allow 陳述的最小 bucket policy。"""

    def make(*, resource: str, actions: object = "s3:GetObject",
             principal: object = "*", sid: str = "PublicRead") -> Policy:
        return {"Version": "2012-10-17", "Statement": [
            {"Sid": sid, "Effect": "Allow", "Principal": principal,
             "Action": actions, "Resource": resource}]}

    return make


@pytest.fixture
def template_with_policy() -> Callable[..., Mapping[str, object]]:
    """產生一份只含單一 `AWS::IAM::Policy` 的最小 CDK template。"""

    def make(*, actions: object, resource: object,
             condition: object | None = None) -> Mapping[str, object]:
        statement: dict[str, object] = {
            "Effect": "Allow", "Action": actions, "Resource": resource}
        if condition is not None:
            statement["Condition"] = condition
        return {"Resources": {"SomePolicy": {
            "Type": "AWS::IAM::Policy",
            "Properties": {"PolicyName": "some", "PolicyDocument": {
                "Version": "2012-10-17", "Statement": [statement]}}}}}

    return make


def test_check_public_rejects_whole_bucket(policy_factory: Callable[..., Policy]) -> None:
    """Given 公開整桶的 policy／When check_public／Then fail 並指出 `/*`。"""
    result = check_public(policy_factory(resource="arn:aws:s3:::b/*"))
    assert result.status == "fail"
    assert any("/*" in item for item in result.findings)


def test_check_public_accepts_site_prefix_only(policy_factory: Callable[..., Policy]) -> None:
    """Given 只公開 `site/*`／When check_public／Then pass。"""
    policy = policy_factory(resource="arn:aws:s3:::b/site/*")
    assert check_public(policy).status == "pass"


def test_check_public_rejects_a_private_prefix(policy_factory: Callable[..., Policy]) -> None:
    """Given 公開 `operations/*`／When check_public／Then fail 並列出違規 Sid。"""
    policy = policy_factory(resource="arn:aws:s3:::b/operations/*", sid="Oops")
    result = check_public(policy)
    assert result.status == "fail"
    assert any("Oops" in item for item in result.findings)


def test_check_public_rejects_extra_actions(policy_factory: Callable[..., Policy]) -> None:
    """Given 公開陳述帶 `s3:PutObject`／When check_public／Then fail。"""
    policy = policy_factory(resource="arn:aws:s3:::b/site/*",
                            actions=["s3:GetObject", "s3:PutObject"])
    result = check_public(policy)
    assert result.status == "fail"
    assert any("s3:PutObject" in item for item in result.findings)


def test_check_public_ignores_deny_statements(policy_factory: Callable[..., Policy]) -> None:
    """Given `enforce_ssl` 產生的 `Deny s3:*`／When check_public／Then 不誤判（D-b3）。"""
    policy = {"Version": "2012-10-17", "Statement": [
        {"Sid": "PublicRead", "Effect": "Allow", "Principal": "*",
         "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/site/*"},
        {"Sid": "EnforceSSL", "Effect": "Deny", "Principal": {"AWS": "*"},
         "Action": "s3:*", "Resource": ["arn:aws:s3:::b", "arn:aws:s3:::b/*"],
         "Condition": {"Bool": {"aws:SecureTransport": "false"}}}]}
    assert check_public(policy).status == "pass"


def test_check_iam_rejects_wildcards(
        template_with_policy: Callable[..., Mapping[str, object]]) -> None:
    """Given `dynamodb:*` ＋ `Resource: "*"`／When check_iam／Then fail 且至少兩筆 finding。"""
    result = check_iam(template_with_policy(actions=["dynamodb:*"], resource="*"))
    assert result.status == "fail" and len(result.findings) >= 2


def test_check_iam_requires_list_bucket_to_be_prefix_scoped(
        template_with_policy: Callable[..., Mapping[str, object]]) -> None:
    """Given 沒有 `s3:prefix` 條件的 ListBucket／When check_iam／Then fail 並提到 `s3:prefix`。"""
    result = check_iam(
        template_with_policy(actions=["s3:ListBucket"], resource="arn:aws:s3:::b"))
    assert result.status == "fail"
    assert any("s3:prefix" in item for item in result.findings)


def test_check_iam_accepts_prefix_scoped_list_bucket(
        template_with_policy: Callable[..., Mapping[str, object]]) -> None:
    """Given ListBucket 帶私有前綴條件／When check_iam／Then pass。"""
    condition = {"StringLike": {"s3:prefix": [
        "tutorials/*", "operations/*", "stepfunctions/*", "demo/previews/*", "site/*"]}}
    result = check_iam(template_with_policy(
        actions=["s3:ListBucket"], resource="arn:aws:s3:::b", condition=condition))
    assert result.status == "pass", result.findings


def test_check_iam_rejects_a_prefix_outside_the_approved_list(
        template_with_policy: Callable[..., Mapping[str, object]]) -> None:
    """Given ListBucket 的 `s3:prefix` 多了一個前綴／When check_iam／Then fail 並指出是哪一個。

    （2026-09-15 由突變測試補：原本只驗「有沒有條件」，把子集合比對整條拿掉也不會紅。）
    """
    condition = {"StringLike": {"s3:prefix": ["operations/*", "backups/*"]}}
    result = check_iam(template_with_policy(
        actions=["s3:ListBucket"], resource="arn:aws:s3:::b", condition=condition))
    assert result.status == "fail"
    assert any("backups/*" in item for item in result.findings)


def test_check_iam_ignores_non_iam_resources(
        template_with_policy: Callable[..., Mapping[str, object]]) -> None:
    """Given bucket policy 的 `Deny s3:*`／When check_iam／Then 不掃它（只看 IAM 資源）。"""
    clean = template_with_policy(actions=["dynamodb:GetItem"], resource="arn:aws:dynamodb:::t")
    resources = dict(clean["Resources"])  # type: ignore[arg-type]
    resources["BucketPolicy"] = {
        "Type": "AWS::S3::BucketPolicy",
        "Properties": {"PolicyDocument": {"Statement": [
            {"Effect": "Deny", "Action": "s3:*", "Resource": "*",
             "Condition": {"Bool": {"aws:SecureTransport": "false"}}}]}}}
    result = check_iam({"Resources": resources})
    assert result.status == "pass", result.findings


def test_check_iam_reports_not_run_without_any_iam_resource() -> None:
    """Given 一份沒有 IAM 資源的 template／When check_iam／Then not_run（不是 pass）。"""
    assert check_iam({"Resources": {}}).status == "not_run"


def test_run_all_treats_not_run_as_failure() -> None:
    """Given 一筆 pass 一筆 not_run／When run_all／Then 回非 0。"""
    results = [CheckResult("a", "pass", "src", ()),
               CheckResult("b", "not_run", "snyk", ("未取得權限",))]
    assert run_all(results) != 0


def test_run_all_returns_zero_only_when_everything_passed() -> None:
    """Given 全部 pass／When run_all／Then 回 0。"""
    assert run_all([CheckResult("a", "pass", "src", ())]) == 0


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """一個乾淨的 git repo：`.gitignore` 忽略 `.env`，沒有任何金鑰。"""
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        f"TKB_BEDROCK_REGION=us-east-1\n{SECRET_KEY}=\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "note.md").write_text(
        f"範例：{SECRET_KEY}=s3cr3t-value\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore", ".env.example", "docs/note.md")
    return tmp_path


def test_check_secrets_passes_on_a_clean_tree(repo: Path) -> None:
    """Given 乾淨的 repo／When check_secrets／Then pass，且 scope 寫出排除清單。"""
    result = check_secrets(repo)
    assert result.status == "pass", result.findings
    assert "git ls-files" in result.scope
    assert "docs/" in result.scope and ".superpowers/" in result.scope


def test_check_secrets_flags_an_unignored_env_file(repo: Path) -> None:
    """Given `.env` 沒被 ignore／When check_secrets／Then fail。"""
    (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
    result = check_secrets(repo)
    assert result.status == "fail"
    assert any(".env" in item for item in result.findings)


def test_check_secrets_reports_location_without_the_matched_value(repo: Path) -> None:
    """Given 追蹤檔裡有 AWS access key 樣式／When check_secrets／Then 只印檔案與行號。"""
    leak = "AKIA" + "ABCDEFGHIJKLMNOP"
    (repo / "handler.py").write_text(f"KEY = '{leak}'\n", encoding="utf-8")
    _git(repo, "add", "handler.py")
    result = check_secrets(repo)
    assert result.status == "fail"
    assert any("handler.py:1" in item for item in result.findings)
    assert not any(leak in item for item in result.findings)


def test_check_secrets_ignores_documentation_examples(repo: Path) -> None:
    """Given `docs/` 裡有 `TKB_GITHUB_WEBHOOK_SECRET=s3cr3t-value`／Then 不是 finding。"""
    result = check_secrets(repo)
    assert not any("docs/note.md" in item for item in result.findings)


def test_check_secrets_flags_a_real_webhook_secret_value(repo: Path) -> None:
    """Given 追蹤檔把 webhook secret 填成真值／When check_secrets／Then fail。"""
    (repo / "settings.toml").write_text(
        f'{SECRET_KEY} = "a-real-looking-value"\n', encoding="utf-8")
    _git(repo, "add", "settings.toml")
    result = check_secrets(repo)
    assert result.status == "fail"
    assert any("settings.toml" in item for item in result.findings)


def test_check_output_safety_escapes_hostile_text() -> None:
    """Given 惡意文字餵進 renderer 與每個 prompt／When check_output_safety／Then pass。"""
    result = check_output_safety()
    assert result.status == "pass", result.findings
    assert "prompt_write_tutorial" in result.scope
    assert "render_version_page" in result.scope


def test_check_output_safety_covers_every_prompt_dynamically() -> None:
    """Given `prompts.py` 動態列舉／When check_output_safety／Then 每支都在 scope 裡。"""
    from training_kb.writing import prompts

    names = [name for name in dir(prompts) if name.startswith("prompt_")]
    assert len(names) >= 8
    for name in names:
        assert name in result_scope(), name


def result_scope() -> str:
    return check_output_safety().scope


def test_probe_site_reports_public_200_and_private_403() -> None:
    """Given 公開頁 200、私有前綴 403／When probe_site／Then pass。"""
    seen: list[str] = []

    def opener(url: str) -> tuple[int, str]:
        seen.append(url)
        if "/site/" in url:
            return 200, '<a href="v1.html">v1</a>'
        return 403, ""

    result = probe_site("http://example.invalid", ("operations/x.json",), opener=opener,
                        public_keys=("site/tutorials/a/v1.html",))
    assert result.status == "pass", result.findings
    assert any("/site/" in url for url in seen)


def test_probe_site_fails_when_a_private_prefix_is_readable() -> None:
    """Given 私有前綴回 200／When probe_site／Then fail。"""

    def opener(url: str) -> tuple[int, str]:
        return 200, "leaked"

    result = probe_site("http://example.invalid", ("operations/x.json",), opener=opener)
    assert result.status == "fail"
    assert any("operations/x.json" in item for item in result.findings)


def test_probe_site_is_not_run_without_a_base_url() -> None:
    """Given 沒有 website endpoint／When probe_site／Then not_run（不是 pass）。"""
    assert probe_site("", (), opener=lambda url: (200, "")).status == "not_run"


def test_report_records_version_scope_and_exit_code() -> None:
    """Given 一筆 snyk 紀錄／When render_scan_report／Then 版本、指令、意義與未涵蓋都在。"""
    record = ScanRecord(tool="snyk", version="1.1298.0", command="snyk test",
                        scope="pyproject.toml 的直接與間接依賴", exit_code=1,
                        covered=("dependencies",), not_covered=("secrets", "code"))
    text = render_scan_report([record])
    assert "1.1298.0" in text and "snyk test" in text
    assert "掃描完成，有發現問題" in text
    assert "未涵蓋範圍：code、secrets" in text


def test_report_refuses_unsupported_claim() -> None:
    """Given `covered` 沒有 secrets／When claim 宣稱 secrets 通過／Then ValueError。"""
    record = ScanRecord(tool="snyk", version="1.1298.0", command="snyk test",
                        scope="依賴", exit_code=0, covered=("dependencies",),
                        not_covered=("secrets",))
    with pytest.raises(ValueError, match="secrets"):
        render_scan_report([record], claim="secrets scan 通過")


def test_report_explains_every_documented_exit_code() -> None:
    """Given 退出碼 0／1／2／3／127／Then 各有不同說明，且 1 不是失敗、2、3 不是通過。"""
    meanings = {
        code: render_scan_report([ScanRecord(
            tool="snyk", version="1.1307.2", command="snyk test", scope="依賴",
            exit_code=code, covered=(), not_covered=("code", "dependencies", "secrets"))])
        for code in (0, 1, 2, 3, 127)}
    assert "掃描完成，沒有發現問題" in meanings[0]
    assert "掃描完成，有發現問題" in meanings[1]
    assert "掃描失敗，可重跑" in meanings[2]
    assert "沒有偵測到支援的專案" in meanings[3]
    assert "未安裝或無法執行" in meanings[127]


def test_report_marks_a_non_snyk_tool_explicitly() -> None:
    """Given 替代依賴掃描／When render_scan_report／Then 報告明確標「非 Snyk」。"""
    record = ScanRecord(tool="pip-audit", version="2.9.0",
                        command="uv run --with pip-audit pip-audit", scope="鎖定的依賴",
                        exit_code=0, covered=("dependencies",),
                        not_covered=("code", "secrets"))
    text = render_scan_report([record])
    assert "非 Snyk" in text


def test_scan_records_round_trip_through_json() -> None:
    """Given ScanRecord／When 轉 JSON／Then 欄位齊全（報告要能被人逐項查證）。"""
    record = ScanRecord(tool="snyk", version="1.1307.2", command="snyk test",
                        scope="依賴", exit_code=2, covered=(), not_covered=("secrets",))
    payload = json.loads(json.dumps(record.__dict__))
    assert payload["exit_code"] == 2 and payload["covered"] == []
