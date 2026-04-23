# jma-mcp-remote — JMA MCP サーバー リモート版（HTTP/SSE）

詳しくは [jma-mcp-remote.md](jma-mcp-remote.md) を参照。

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
| ツール内容 | 全19種 | 同一（server.py を共有） |

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
