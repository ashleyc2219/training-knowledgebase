"""三支非 pipeline 的 Lambda 入口（00A §3.2、§3.5、D-56、D-62）。

`training-kb-webhook` → `github_webhook.handler`（P30）、
`training-kb-import` → `import_.handler`（P42）、
`training-kb-analytics` → `analytics.handler`（P54／P55）。

三條 pipeline 的 handler 不放這裡，它們留在 `pipelines/*.py`（D-25）。
"""
