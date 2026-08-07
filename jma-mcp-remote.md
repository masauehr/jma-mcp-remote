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
| 認証 | OAuth 2.1 + Dynamic Client Registration（簡易実装、2026-08-06追加。詳細は下記「認証」参照） |
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
| 認証（OAuth） | **なし・不要** | あり（簡易 OAuth 2.1 + DCR、2026-08-06追加） |

> **重要**: OAuth対応は `jma_mcp_remote/server.py` にのみ実装されており、`jma_mcp/server.py`（ローカルstdio版）は今回一切変更していない。stdioはClaude Codeがサブプロセスの標準入出力を直接読み書きする方式で、外部からアクセス可能なHTTPエンドポイントを持たないため、そもそも「誰でも接続できてしまう」というリスクが存在しない。OAuthはHTTP/SSEで外部公開するリモート版だけが必要とする仕組み。今後 `jma_mcp/server.py` にツールを追加した場合も、同期先の `jma_mcp_remote/server.py` 側は **ツール定義部分のみ** 反映すればよく、`create_app()` 以降のOAuth実装部分は触らなくてよい。

---

## ファイル構成

```
jma_mcp_remote/
├── server.py          # jma_mcp/server.py から起動部分のみ SSE に変更
├── areas.py           # jma_mcp/areas.py からコピー
├── requirements.txt   # mcp(<2.0.0に固定), requests, uvicorn, starlette
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

## 認証（OAuth 2.1 + Dynamic Client Registration）※2026-08-06追加・リモート版のみ

### 背景：何が起きていたか

2026-08-06、Claude.ai のカスタムコネクタ登録で以下のエラーが発生した。

```
jma-mcp-renderのサインインサービスに登録できませんでした。もう一度お試しいただくか、
コネクタ設定でOAuth Client IDを追加してください。
```

調査したところ、サーバー自体は正常に稼働していた（`curl` で直接 `https://jma-mcp-remote.onrender.com/sse` に接続すると、SSEストリーム（`event: endpoint` と ping）が問題なく返っていた）。原因は **Claude.ai 側の仕様** にあった。Claude.ai 等のホスト型コネクタは、リモートMCPサーバーへの接続時にOAuthメタデータ・Dynamic Client Registration (DCR) を自動で試行する。これはMCPの[Authorization仕様](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)に沿った挙動で、サーバー側が対応していない場合は今回のような「サインインサービスへの登録失敗」エラーになる。当時の `server.py` にはOAuth関連のエンドポイント（`/.well-known/oauth-authorization-server` 等）が一切存在せず、これらへのリクエストはすべて404を返していた。

これに対応するため、簡易的な OAuth 2.1 + DCR を `server.py` に実装した。

### デプロイでつまずいた2つの問題

OAuthコード自体はローカルでは正常動作を確認済みだったが、Renderへのデプロイでは2回連続で失敗した。

**失敗1：`dict[str, dict]` 構文がRenderのPython環境で非対応**

```
File "/opt/render/project/src/server.py", line XXXX, in <module>
    _oauth_clients: dict[str, dict] = {}
TypeError: 'type' object is not subscriptable
```

`dict[str, dict]` のような組み込み型のサブスクリプト構文（PEP 585）は **Python 3.9以降でしか使えない**。本プロジェクトには `runtime.txt` や `.python-version` などPythonバージョンを固定するファイルが存在せず、Renderのデフォルト環境が3.9未満だったため、モジュール読み込み時（起動直後）に `TypeError` でクラッシュしていた。ローカル環境ではPython 3.14系を使っていたため、この非互換に気づけなかった。

→ 型注釈を外し `_oauth_clients = {}` のような素の `dict` に変更して解決。

**失敗2：`mcp>=1.0.0` の上限なし指定が最新メジャーバージョンを掴んだ**

```
File "/opt/render/project/src/server.py", line 328, in <module>
    @server.list_tools()
     ^^^^^^^^^^^^^^^^^
AttributeError: 'Server' object has no attribute 'list_tools'
```

`requirements.txt` の `mcp>=1.0.0` は上限を指定していなかったため、このビルドでリリースされたばかりの `mcp 2.0.0`（`Server` クラスのAPIが破壊的に変更されたメジャーバージョン）を取得してしまい、`list_tools`/`call_tool` デコレータが存在せず起動時にクラッシュした。ローカルには以前から `mcp 1.27.0` が入っていたため、こちらも気づけなかった。

→ `requirements.txt` を `mcp>=1.0.0,<2.0.0` に固定して解決。

**教訓**: ローカルの動作確認だけでは、クリーンな本番環境固有の問題（Pythonバージョン・依存ライブラリの新規メジャーリリース）を検知できない。`requirements.txt` は上限を切らないと将来同種の事故が再発しうる点に注意（`starlette>=0.40.0` 等、他の依存も同じリスクを抱えている）。

### 設計方針：なぜログイン画面なしの「素通し」実装なのか

- 本サーバーが扱うのは気象庁の公開データのみで、個人アカウントという概念が存在しない。そのため `/authorize` はログイン画面を挟まず、リクエストされた時点で即座に認可コードを発行する実装とした。目的はホスト型コネクタが要求するOAuthのプロトコル形状（DCR → 認可コード → アクセストークン）を満たして正常接続できるようにすることであり、**利用者を認証・識別するものではない**。事実上、誰でも自由にクライアント登録・トークン取得ができる（＝実質的なアクセス制限効果はない）。これは、扱っているデータが非公開・個人情報を含まないためリスクとして許容できるという判断による。将来、個人情報や書き込み操作を扱うようになった場合はこの設計のままでは不十分なので、実際のユーザー認証（パスワード・外部IDプロバイダ連携等）に置き換える必要がある。
- クライアント登録情報・認可コード・アクセストークンはすべてインメモリ保持（`_oauth_clients` / `_oauth_auth_codes` / `_oauth_access_tokens` / `_oauth_refresh_tokens` の4つの `dict`）。プロセス再起動（Render無料プランのスリープ復帰・再デプロイ等）で消えるが、クライアント側が自動的に再登録・再認可を行うため実用上問題ない。

### 認証フローの流れ

```
① Claude.ai 等のクライアントが POST /register でクライアント登録（DCR）
   → client_id を払い出し、_oauth_clients に保存

② クライアントが GET /authorize?client_id=...&redirect_uri=...&code_challenge=...
   にアクセス（PKCE の code_challenge を添える）
   → ログイン画面なしで即座に認可コード(code)を発行し、
     redirect_uri へ 302 リダイレクト（?code=...&state=...）
   → code は _oauth_auth_codes に60秒だけ保存

③ クライアントが POST /token に code と code_verifier を渡す
   → code_verifier から code_challenge を再計算して一致を検証（PKCE）
   → 一致すればアクセストークン（1時間有効）とリフレッシュトークンを発行

④ 以降、/sse・/messages/ へのアクセスには
   Authorization: Bearer <access_token> ヘッダーが必須
   → トークンが無い・無効・期限切れの場合は 401 を返し、
     WWW-Authenticate ヘッダーで /.well-known/oauth-protected-resource を案内
```

### 追加されたエンドポイント

| エンドポイント | 用途 |
|---|---|
| `GET /.well-known/oauth-authorization-server` | 認可サーバーメタデータ（RFC 8414） |
| `GET /.well-known/oauth-protected-resource` | 保護対象リソースメタデータ（RFC 9728） |
| `POST /register` | Dynamic Client Registration（RFC 7591） |
| `GET /authorize` | 認可エンドポイント（PKCE対応、即時リダイレクト） |
| `POST /token` | トークンエンドポイント（authorization_code / refresh_token） |

`/sse` と `/messages/` は `Authorization: Bearer <token>` ヘッダーが必須になった。未認証アクセスには `401` と `WWW-Authenticate` ヘッダー（`resource_metadata` を指す）を返す。Claude Code の `.mcp.json` 経由（`url` 直指定）で使う場合は、クライアントがOAuthフローに対応していないとトークンを取得できず接続できなくなる点に注意（実際、この用途では `jma_mcp_remote/.mcp.json` ではなく `jma_mcp/.mcp.json`（ローカルstdio版）を使い続けている）。

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

差分は起動部分（`main()` → `create_app()`）と、**リモート版のみが持つOAuth 2.1 + DCR実装**（上記「認証」セクション参照）。ツール本体の実装は同一なので、同期の際はツール定義部分だけをコピーすればよく、OAuth関連コード（`create_app()` 以降）は触らなくてよい。逆に、OAuth側の実装を変更してもツール本体には影響しないため `jma_mcp/server.py` への反映は不要。

### 依存ライブラリのバージョン固定

2026-08-06のデプロイ失敗を教訓に、`requirements.txt` は `mcp` を `<2.0.0` に固定済み（詳細は上記「認証」→「デプロイでつまずいた2つの問題」参照）。`requests` / `uvicorn` / `starlette` は依然として上限なし（`>=` のみ）なので、将来これらのメジャーバージョンアップで同様の事故が起きる可能性がある。デプロイが原因不明で失敗した場合は、まずRenderのビルドログで実際にインストールされたパッケージバージョンを確認すること。
