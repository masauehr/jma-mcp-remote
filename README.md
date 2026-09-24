# jma-mcp-remote — JMA MCP サーバー リモート版（HTTP/SSE）

詳しくは [jma-mcp-remote.md](jma-mcp-remote.md)（本プロジェクト固有情報）・[jma-mcp.md](jma-mcp.md)（共有ツール一覧・出力フォーマット等）を参照。

---

`jma_mcp`（stdio ローカル版）をベースに HTTP/SSE 通信へ切り替えたリモートデプロイ版。
Render にデプロイし、Claude.ai Web版・デスクトップアプリから使用する。

## 概要

| 項目 | 内容 |
|---|---|
| プロトコル | MCP（Model Context Protocol）/ HTTP + SSE ベース |
| デプロイ先 | Render（Web Service） |
| SSE エンドポイント | `https://jma-mcp-remote.onrender.com/sse` |
| 対応クライアント | Claude.ai Web版・デスクトップアプリ（macOS） |
| 非対応クライアント | iPhone版 Claude（MCP未対応のため要約版になる） |
| GitHub | https://github.com/masauehr/jma-mcp-remote |

## ファイル構成

```
jma_mcp_remote/
├── server.py              # jma_mcp/server.py から起動部分のみ SSE に変更
├── areas.py               # jma_mcp/areas.py からコピー
├── requirements.txt       # mcp, requests, uvicorn, starlette
├── tests/                 # テスト（jma_mcp と共通の新体系テスト。`/opt/homebrew/bin/python3 -m unittest discover -s tests`）
├── render.yaml            # Render デプロイ設定
├── jma-mcp-remote.md      # このプロジェクトの詳細マニュアル
├── .mcp.json              # Claude Code からリモート接続する場合の設定（gitignore済み）
└── .gitignore
```

## ローカル版との違い

| 比較項目 | jma_mcp（ローカル版） | jma_mcp_remote（リモート版） |
|---|---|---|
| 通信方式 | stdio（標準入出力） | HTTP + SSE |
| 起動方法 | Claude Code がサブプロセス起動 | Render 上で常駐 |
| 対応クライアント | Claude Code（CLI） | Claude.ai Web・デスクトップアプリ |
| コスト | 無料（ローカル実行） | Render 無料プラン（スリープあり） |
| ツール内容 | 全23種 | 同一（server.py を共有） |

## 2026-05-28 の新体系（防災気象情報）への対応（2026-09-24）

警報・早期注意情報・気象情報・台風情報の配信先が `data/r8/` に移転し形式も変わったため、ローカル版と同じ改修を適用した（旧パスは 5/28 のまま凍結）。新ツール `get_warning_timeline`（時系列情報）・`get_typhoon`（台風の実況・予報）を追加。`get_early_warning` の出力も新形式（地域ごとの表・全現象行・高/中/－・6時間ごと）に変更。詳細は [jma-mcp.md](jma-mcp.md)。テストは `tests/`（`/opt/homebrew/bin/python3 -m unittest discover -s tests`）。**Render への反映は GitHub への push 後（自動デプロイの設定次第）。**

## Claude.ai への接続

1. Claude.ai 設定 → **コネクタ**
2. **カスタムコネクタを追加**
3. URL: `https://jma-mcp-remote.onrender.com/sse`

> Web版で登録した設定はデスクトップアプリにも自動共有される。

## 注意事項

- Render 無料プランは15分間アクセスがないとスリープ。次回アクセス時に30〜60秒かかる。
- `jma_mcp/server.py` にツールを追加した場合は `jma_mcp_remote/server.py` にも反映すること（差分は起動部分のみ）。

## GitHub

[https://github.com/masauehr/jma-mcp-remote](https://github.com/masauehr/jma-mcp-remote)
