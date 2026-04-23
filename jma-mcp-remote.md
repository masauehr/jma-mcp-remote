# jma-mcp-remote — JMA MCP サーバー リモート版（HTTP/SSE）

`jma_mcp`（stdio ローカル版）をベースに HTTP/SSE 通信へ切り替えたリモートデプロイ版。
Render にデプロイし、Claude.ai Web版・デスクトップアプリ・iPhone版から使用する。

---

## 概要

| 項目 | 内容 |
|---|---|
| プロトコル | MCP（Model Context Protocol）/ HTTP + SSE ベース |
| デプロイ先 | Render（Web Service） |
| SSE エンドポイント | `https://jma-mcp-remote.onrender.com/sse` |
| 対応クライアント | Claude.ai Web版・デスクトップアプリ（macOS）・iPhone版 |
| GitHub | https://github.com/masauehr/jma-mcp-remote |

---

## ローカル版との違い

| 比較項目 | jma_mcp（ローカル版） | jma_mcp_remote（リモート版） |
|---|---|---|
| 通信方式 | stdio（標準入出力） | HTTP + SSE |
| 起動方法 | Claude Code がサブプロセス起動 | Render 上で常駐 |
| 対応クライアント | Claude Code（CLI） | Claude.ai Web・デスクトップアプリ・iPhone版 |
| 設定ファイル | `.mcp.json`（command/args） | `.mcp.json` または Claude.ai 設定（url） |
| コスト | 無料（ローカル実行） | Render 無料プラン（スリープあり） |
| ツール内容 | 全19種 | 同一（server.py を共有） |

---

## ファイル構成

```
jma_mcp_remote/
├── server.py          # jma_mcp/server.py から起動部分のみ SSE に変更
├── areas.py           # jma_mcp/areas.py からコピー
├── requirements.txt   # mcp, requests, uvicorn, starlette
├── render.yaml        # Render デプロイ設定
├── README.md          # プロジェクト概要
├── jma-mcp-remote.md  # このファイル（詳細マニュアル）
├── .mcp.json          # Claude Code からリモート接続する場合の設定（gitignore済み）
└── .gitignore
```

---

## Render へのデプロイ手順

### 1. Render ダッシュボードを開く

https://dashboard.render.com

### 2. Web Service を新規作成

- **New → Web Service**
- GitHub リポジトリ `masauehr/jma-mcp-remote` を接続

### 3. ビルド・起動設定

| 項目 | 設定値 |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python server.py` |
| Root Directory | （空欄） |

### 4. デプロイ完了後の確認

Render のログに以下が表示されれば起動成功：

```
Uvicorn running on http://0.0.0.0:XXXXX
```

---

## Claude.ai への接続手順

### Web版・デスクトップアプリ・iPhone版 共通

1. 設定 → **コネクタ**
2. **カスタムコネクタを追加**
3. 以下を入力：
   - 名前: `jma-mcp-render`（任意）
   - URL: `https://jma-mcp-remote.onrender.com/sse`
4. **追加** → 接続確認

> Web版で登録した設定はデスクトップアプリ・iPhone版にも自動共有される。  
> 同じURLを再登録しようとすると「A server with this URL already exists.」エラーが出るが、これは登録済みのため問題なし。  
> iPhone版はコネクタをONにすることで動作する（2026-04-23 動作確認済み）。

### Claude Code から使う場合（jma_mcp_remote/ 内のみ）

`jma_mcp_remote/.mcp.json`（gitignore済み）に記載済み：

```json
{
  "mcpServers": {
    "jma-remote": {
      "url": "https://jma-mcp-remote.onrender.com/sse"
    }
  }
}
```

---

## 出典リンク表示設定（Projectsカスタム指示）

Claude.ai では CLAUDE.md が読み込まれないため、出典URLを表示するには **Projects のカスタム指示（「手順」欄）** に以下を追加する。

```
気象庁MCPサーバー（jma-mcp-renderコネクタ）のツール結果を使って回答する際は、ツール結果の末尾にある「出典: 気象庁 https://...」のURLを必ず末尾にそのまま表示すること。URLを省略・変更しないこと。
```

> 設定場所: claude.ai → プロジェクト → 手順を編集  
> Web版・デスクトップ・iPhone版すべてで共有される。

---

## クライアント別対応状況

| クライアント | MCP 対応 | 気象庁データ取得 | 備考 |
|---|---|---|---|
| Claude Code（CLI） | ✅ | ✅ ローカル版 | `jma_mcp/.mcp.json` を使用 |
| Claude.ai Web版 | ✅ | ✅ リモート版 | コネクタ登録済み |
| Claude デスクトップアプリ（macOS） | ✅ | ✅ リモート版 | Web版と設定共有 |
| Claude iPhone版 | ✅ | ✅ リモート版 | コネクタをONにすれば動作。2026-04-23 動作確認済み |

---

## 注意事項

### Render 無料プランのスリープ

- 15分間アクセスがないとスリープ状態になる
- 次のアクセス時に起動まで **30〜60秒** かかる
- 接続タイムアウトになる場合は少し待って再試行

### server.py の更新

`jma_mcp/server.py` にツールを追加した場合は `jma_mcp_remote/server.py` にも反映すること。

差分は起動部分（`main()` → `create_app()`）のみ。ツールの実装は同一。
