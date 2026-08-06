# jma-mcp-remote — JMA MCP サーバー リモート版（HTTP/SSE）

[jma-mcp](jma-mcp.md)（stdio ローカル版）をベースに HTTP/SSE 通信へ切り替えたリモートデプロイ版。
Render にデプロイし、Claude.ai Web版・デスクトップアプリ・iPhone版から使用する。
ツール一覧・element キー一覧・出力フォーマットなどの詳細は [jma-mcp.md](jma-mcp.md) を参照（server.py を共有しているため内容は同一）。

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
| ツール内容 | 全21種 | 同一（server.py を共有） |

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

## 認証（OAuth 2.1 + Dynamic Client Registration）

### 背景

2026-08-06、Claude.ai のカスタムコネクタ登録で「サインインサービスに登録できませんでした。もう一度お試しいただくか、コネクタ設定でOAuth Client IDを追加してください」というエラーが発生した。Claude.ai 等のホスト型コネクタは接続時にOAuthメタデータ・Dynamic Client Registration (DCR) を自動で試行する仕様になっており、対応していないサーバーはこのエラーになる。サーバー自体は正常稼働していたが（`curl` で直接 `/sse` に接続するとSSEストリームは問題なく返っていた）、OAuth関連のエンドポイントが存在しなかったことが原因だった。

これに対応するため、簡易的な OAuth 2.1 + DCR を `server.py` に実装した。

### 設計方針

- 本サーバーが扱うのは気象庁の公開データのみで、個人アカウントという概念が存在しない。そのため `/authorize` はログイン画面を挟まず、リクエストされた時点で即座に認可コードを発行する「素通し」の実装とした。目的はホスト型コネクタが要求するOAuthのプロトコル形状（DCR → 認可コード → アクセストークン）を満たして正常接続できるようにすることであり、利用者を認証・識別するものではない。
- クライアント登録情報・認可コード・アクセストークンはすべてインメモリ保持。プロセス再起動（Render無料プランのスリープ復帰等）で消えるが、クライアント側が自動的に再登録・再認可を行うため問題ない。

### 追加されたエンドポイント

| エンドポイント | 用途 |
|---|---|
| `GET /.well-known/oauth-authorization-server` | 認可サーバーメタデータ（RFC 8414） |
| `GET /.well-known/oauth-protected-resource` | 保護対象リソースメタデータ（RFC 9728） |
| `POST /register` | Dynamic Client Registration（RFC 7591） |
| `GET /authorize` | 認可エンドポイント（PKCE対応、即時リダイレクト） |
| `POST /token` | トークンエンドポイント（authorization_code / refresh_token） |

`/sse` と `/messages/` は `Authorization: Bearer <token>` ヘッダーが必須になった。未認証アクセスには `401` と `WWW-Authenticate` ヘッダー（`resource_metadata` を指す）を返す。Claude Code の `.mcp.json` 経由（`url` 直指定）で使う場合は、クライアントがOAuthフローに対応していないとトークンを取得できず接続できなくなる点に注意。

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

差分は起動部分（`main()` → `create_app()`）と、リモート版のみが持つOAuth 2.1 + DCR実装（上記「認証」セクション参照）。ツールの実装自体は同一。
