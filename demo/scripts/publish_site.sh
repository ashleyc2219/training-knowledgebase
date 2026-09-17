#!/usr/bin/env bash
# 更新公開教學站的「外觀」：上傳 CSS／JS，再重建所有索引頁。
#
# 什麼會變：site/assets/style.css、site/assets/widget.js、site/index.html、
#           site/tutorials/<slug>/index.html（全部教學的版本紀錄頁），以及
#           「表裡已標發布、公開站卻還沒有」的版本頁（種子資料；只補缺的）。
# 什麼不會變：已存在的版本頁 v<n>.html 與 v<n>.diff.txt（一次性產物，不可覆寫；
#             新版面只會套用在之後發布的新版本，但新的 CSS 對舊頁一樣生效）。
#
# 用法（在專案根目錄）：
#   export TKB_AWS_REGION=us-east-1
#   export TKB_CONTENT_BUCKET=training-kb-content-example
#   demo/scripts/publish_site.sh            # 上傳資產 + 補缺的版本頁 + 重建索引
#   demo/scripts/publish_site.sh --assets   # 只上傳資產（改 CSS／JS 時）
#   demo/scripts/publish_site.sh --pages    # 只補缺的版本頁（seed --apply 之後）
#   demo/scripts/publish_site.sh --index    # 只重建索引（改 site.py 的索引版面時）
set -euo pipefail

cd "$(dirname "$0")/../.."

: "${TKB_AWS_REGION:?請先 export TKB_AWS_REGION=us-east-1}"
: "${TKB_CONTENT_BUCKET:?請先 export TKB_CONTENT_BUCKET=<bucket 名稱>}"

mode="${1:-all}"
bucket="$TKB_CONTENT_BUCKET"
region="$TKB_AWS_REGION"

if [[ "$mode" == "all" || "$mode" == "--assets" ]]; then
  echo "[publish_site] 上傳資產到 s3://$bucket/site/assets/"
  aws s3 cp demo/site_assets/style.css "s3://$bucket/site/assets/style.css" \
    --region "$region" --content-type "text/css; charset=utf-8" --cache-control "max-age=60"
  aws s3 cp demo/site_assets/widget.js "s3://$bucket/site/assets/widget.js" \
    --region "$region" --content-type "text/javascript; charset=utf-8" --cache-control "max-age=60"
fi

if [[ "$mode" == "all" || "$mode" == "--pages" || "$mode" == "--index" ]]; then
  echo "[publish_site] mode=${mode}：補缺的版本頁 / 重建索引"
  MODE="$mode" uv run python - <<'PY'
import os

import boto3

from training_kb.config import load_settings
from training_kb.errors import PublishError
from training_kb.ingress import approved_categories
from training_kb.operations import OperationCoordinator
from training_kb.publishing import Publisher
from training_kb.repository import Repository
from training_kb.site import SiteRenderer

settings = load_settings()
repository = Repository(
    boto3.resource("dynamodb", region_name=settings.aws_region).Table(settings.table_name),
    boto3.resource("s3", region_name=settings.aws_region).Bucket(settings.content_bucket),
)
# 回饋 widget 的類別按鈕來自核定表（P43），與 Lambda 端發布時的設定一致。
renderer = SiteRenderer(categories=tuple(sorted(approved_categories(repository))))
publisher = Publisher(repository, renderer, OperationCoordinator(repository))
mode = os.environ.get("MODE", "all")
slugs = sorted(str(item["slug"]) for item in repository.scan_entity("TUTORIAL")
               if item.get("current_version"))
if mode in ("all", "--pages"):
    for slug in slugs:
        try:
            for key in publisher.publish_recorded_pages(slug):
                print(f"  補上 site/{key}")
        except PublishError as error:   # 例如驗收殘留的教學：版本資料不完整就跳過，不擋其他篇
            print(f"  略過 {slug}：{error}")
if mode in ("all", "--index"):
    for slug in slugs:
        publisher.write_tutorial_index(slug)
        print(f"  重建 site/tutorials/{slug}/index.html")
    publisher.write_site_index()
    print(f"  重建 site/index.html（{len(slugs)} 篇）")
PY
fi

echo "[publish_site] 完成。用瀏覽器開："
echo "  http://$bucket.s3-website-$region.amazonaws.com/site/index.html"
