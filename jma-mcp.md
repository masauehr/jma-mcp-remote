# jma-mcp — 気象庁天気予報 MCP サーバー

気象庁の公開APIをMCPサーバーとして公開し、Claude Codeから自然言語で天気予報を取得できるようにするプロジェクト。

---

## 概要

| 項目 | 内容 |
|---|---|
| プロトコル | MCP（Model Context Protocol） / stdio ベース |
| データソース | 気象庁公開API（jma.go.jp） |
| 対象エリア | 全国（エリアコード指定） |
| 使い方 | Claude Codeに自然言語で質問するだけ |
| GitHub | https://github.com/masauehr/jma-mcp |

---

## MCPとは何か

### MCP（Model Context Protocol）の基礎

**MCP（Model Context Protocol）** は、Anthropicが策定したオープン標準プロトコルで、
AIモデル（Claude）と外部ツール・データソースを接続するための仕組みです。

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP の基本構造                            │
│                                                             │
│  ┌──────────┐    MCP プロトコル    ┌──────────────────────┐ │
│  │  Claude  │ ◄──────────────────► │    MCP サーバー      │ │
│  │ (AIモデル)│   (JSON-RPC over     │  (外部ツール・DB等)  │ │
│  └──────────┘    stdio/HTTP)       └──────────────────────┘ │
│                                                             │
│  Claude は「どんなツールがあるか」を問い合わせ、              │
│  必要に応じてツールを呼び出して結果を受け取る               │
└─────────────────────────────────────────────────────────────┘
```

### なぜ MCP が必要か

| 問題 | MCPなし | MCPあり |
|---|---|---|
| リアルタイムデータ | Claudeは学習データしか知らない | 外部APIからリアルタイム取得 |
| 専門データベース | アクセス不可 | MCPサーバー経由でアクセス可能 |
| ローカルファイル | 読み込めない | ローカルMCPサーバーが仲介 |

### MCP の通信方式（stdio）

このプロジェクトは **stdio（標準入出力）ベース** の通信方式を採用。
Claude Code がサブプロセスとして `server.py` を起動し、標準入出力でやり取りします。

```
Claude Code
    │
    │  標準入力（stdin）に JSON-RPC リクエストを送信
    ▼
┌────────────────────────────┐
│  python3 server.py         │  ← サブプロセスとして起動
│                            │
│  ① ツール一覧を返す         │
│  ② ツールの引数を受け取る   │
│  ③ JMA API に HTTPリクエスト│
│  ④ 結果を整形して返す       │
└────────────────────────────┘
    │
    │  標準出力（stdout）に JSON-RPC レスポンスを返す
    ▼
Claude Code（結果を受け取り、回答に組み込む）
```

---

## 気象庁データ取得の仕組み

### 全体のデータフロー

```
ユーザーの質問
「東京の天気を教えて」
        │
        ▼
┌───────────────────┐
│   Claude (LLM)    │  「東京の天気を調べよう」と判断
│                   │  → search_area("東京") を呼び出す
└─────────┬─────────┘
          │ MCP プロトコル（stdio）
          ▼
┌───────────────────┐
│  server.py        │  エリアコード検索: 東京都 → 130000
│  (MCPサーバー)    │
└─────────┬─────────┘
          │ MCPプロトコル（stdio）
          ▼
┌───────────────────┐
│   Claude (LLM)    │  「コード 130000 で予報を取得しよう」
│                   │  → get_forecast("130000") を呼び出す
└─────────┬─────────┘
          │ MCP プロトコル（stdio）
          ▼
┌───────────────────┐
│  server.py        │  HTTP GET リクエスト
│  (MCPサーバー)    ├──────────────────────────────────────►
└─────────┬─────────┘                                      │
          │                                 ┌──────────────┴──────────────┐
          │                                 │  気象庁 API                  │
          │                                 │  jma.go.jp/bosai/forecast/  │
          │                                 │  data/forecast/130000.json  │
          │                                 └──────────────┬──────────────┘
          │                                                │
          │          JSON データを返す                      │
          │ ◄─────────────────────────────────────────────┘
          │
          │  JSONを整形（日付・天気テキスト・気温）
          │
          ▼
┌───────────────────┐
│   Claude (LLM)    │  整形済みテキストを受け取り
│                   │  読みやすい日本語で回答を生成
└─────────┬─────────┘
          │
          ▼
ユーザーへの回答
「東京都の天気予報：4月14日(火) くもり...」
```

### 気象庁 API のエンドポイント

気象庁の防災情報ページ（bosai.jma.go.jp）が内部で使用しているAPIと同一。
**認証不要・無料**（利用規約の遵守が必要）。

| エンドポイント | 取得データ |
|---|---|
| `/bosai/forecast/data/forecast/{code}.json` | 3日間予報・週間予報 |
| `/bosai/forecast/data/overview_forecast/{code}.json` | 天気概況テキスト |
| `/bosai/warning/data/r8/{code}.json` | 警報・注意報発表状況（新体系。旧 `warning/data/warning/` は凍結） |
| `/bosai/warning/data/r8/map_time.json` | 警報システム全体の最終更新（稼働判定） |
| `/bosai/warning_timeline/data/{code}.json` | 時系列情報（3時間ごとの警報等の見通し） |
| `/bosai/probability/data/probability/r8/{code}.json` | 早期注意情報（警報級の可能性。新体系） |
| `/bosai/forecaster_comment/data/comments/{code}.txt` | 気象台からのコメント（HTML。<<特記事項>>含む） |
| `/bosai/information/data/r8/information.json` | 気象情報一覧（府県・地方・全般気象情報。約1か月分） |
| `/bosai/information/data/r8/denbun/{json_name}.json` | 気象情報本文（見出し＋解説文） |
| `/bosai/typhoon/data/targetTc.json` | 発生中の台風の一覧（`get_typhoon`） |
| `/bosai/typhoon/data/{TC番号}/specifications.json` ・ `forecast.json` | 台風の諸元（実況・予報）・予報円（`get_typhoon`） |
| `data.jma.go.jp /stats/data/mdrr/{category}/alltable/{elem}_rct.csv` | 最新観測値（降水量・気温・風速・積雪 等） |
| `data.jma.go.jp /stats/data/mdrr/rank_daily/data{MMDD}.html` | 全国観測値ランキング（上位10地点） |
| `data.jma.go.jp /stats/data/mdrr/rank_update/d{MMDD}.html` | 観測史上1位の値 更新状況 |
| `data.jma.go.jp /risk/probability/guidance/download2w.php?2week_t_{num}.csv` | 2週間気温予報CSV（地域番号指定） |
| `data.jma.go.jp /risk/probability/guidance/download.php?month1_t_{num}.csv` | 1ヶ月予報CSV（地域番号指定） |
| `data.jma.go.jp /cpd/longfcst/kaisetsu/?term={term}` | 3ヶ月・6ヶ月予報 解説資料（SPA、URL参照） |
| `data.jma.go.jp /cpd/souten/data/{reg_no}.json` | 早期天候情報（地域別JSON） |
| `data.jma.go.jp /cpd/souten/data/flg.json` | 早期天候情報 発表フラグ（全国） |
| `data.jma.go.jp /cpd/elnino/` | エルニーニョ監視速報ページ（SPA、URL参照） |
| `/bosai/tidelevel/data/tide/tide_time.json` | 潮位データ基準時刻 |
| `/bosai/tidelevel/data/tide/tide_obs_{YYYYMMDD}_{code}.json` | 潮位観測データ（15秒間隔・最大5760点/日） |
| `/bosai/tidelevel/const/tide_astro/tide_astro_{YYYY}_{code}.json` | 天文潮位（1時間間隔・年間データ） |
| `/bosai/tidelevel/const/tide_area.json` | 全国潮位観測所一覧（全国39地区166局） |

### 2026-05-28 の新体系（防災気象情報）への対応 ※2026-09-24 実施

2026-05-28 の防災気象情報の新体系（警戒レベル中心）への移行で、**警報・早期注意情報・気象情報・台風情報の JSON の配信先と形式が変わった**。
旧ファイルは削除されず **5/28（台風は 5/27）のまま更新されない**ため、旧パスのままだと「警報なし」など**古い内容が返り続ける**（エラーにならないので気づきにくい）。
`r8` は「令和8年版」の意味で、将来（r9 等）変わりうる。`server.py` は 404 のとき警報ページから現行の版を探して自動で追従する（`fetch_json_versioned`）。

| データ | 旧（〜5/28。凍結） | 新（現行） | 主な変更点 |
|---|---|---|---|
| 警報・注意報 | `warning/data/warning/{code}.json` | `warning/data/r8/{code}.json` | 辞書 → **報のリスト**（種別ごと: VPWW55=大雨, 56=土砂災害, 57=高潮, 58=暴風, 59=波浪, 61=その他）。`warning.class10Items / class20Items[].kinds[]`（`code`・`status`）。コードは "03" のような2桁文字列。種別ごとに最新の報だけが現状で、継続中の警報は古い報のまま残る |
| 警報システムの全体更新 | — | `warning/data/r8/map_time.json` | `latestControlDatetime`（動作中かの判定に使う。6時間以上古ければ更新停止の疑い） |
| 時系列情報（**新規**） | — | `warning_timeline/data/{code}.json`（**版の番号なし**） | 3時間ごとの明日までの見通し（市町村単位）。5・11・17・23時発表＋随時更新の**予測情報**。`significancyParts[].locals[].codes` の**十の位が危険度レベル**（1=なし 2=注意 3=警戒 4=危険 5=災害切迫） |
| 早期注意情報 | `probability/data/probability/{code}.json` | `probability/data/probability/r8/{code}.json` | 短期が**6時間ごと（明後日まで）**に。「雨」が**「大雨」と「土砂災害」に分離**。各地域に解説文 `text`。`timeDefineArray` を追加 |
| 気象情報一覧 | `information/data/information.json` | `information/data/r8/information.json` | 約1か月分（約270件）。PDF資料の項目（`controlTitle` なし）を含む |
| 気象情報本文 | `information/data/denbun/{json_name}.json` | `information/data/r8/denbun/{json_name}.json` | 本文に `<br>` を含む |
| 台風情報 | `information/data/typhoon.json`（一覧）＋ `typhoon/{fileName}` | `typhoon/data/targetTc.json`（発生中の台風）・`typhoon/data/{TC番号}/specifications.json`（諸元・実況・予報）・`forecast.json`（予報円） | 新ツール `get_typhoon`。`get_information` への台風の統合は廃止 |

**変更されていなかったもの**（2026-09-24 に全数で鮮度を確認）: 予報 `forecast/data/forecast/`・概況 `overview_forecast/`・予報官コメント `forecaster_comment/`・地震 `quake/data/list.json`・津波 `tsunami/data/list.json`（空 = 発表なし）・潮位 `tidelevel/`・地域コード `common/const/area.json`・`data.jma.go.jp` 系（観測値・長期予報）。

**警報コード（新体系のレベル付き名称）**: 大雨 `10`=レベル2注意報・`3`=レベル3警報・`43`=レベル4危険警報・`33`=レベル5特別警報／土砂災害 `29`・`9`・`49`・`39`／高潮 `19`・`8`・`48`・`38`。洪水 `18`（注意報）・`4`（警報）などは従来どおり。コードは int に正規化して照合する（`warning_name()`）。

### コード表・仕様の参照先

コードの意味や仕様が不明なとき・誤りが疑われるときは、気象庁の公式XMLデータ仕様サイトを確認する。

| サイト | 内容 |
|---|---|
| **https://xml.kishou.go.jp** | 気象庁 XML 電文仕様の公式サイト。コード表・電文解説資料の一覧 |
| https://xml.kishou.go.jp/tec_material.html | 技術資料一覧（電文解説資料・コード表のExcelダウンロード） |

**特によく参照するコード表:**
- `jmaxml_YYYYMMDD_code.xlsx`（技術資料ページからダウンロード）
  - 最新版: `jmaxml_20260326_code.xlsx`（令和8年3月26日更新）
  - シート「警報等情報要素コード管理表」→ `WeatherWarning` コード一覧
  - bosai JSON API の `warnings[].code` はこの TELOPS コードを使用
  - 令和6年度追加: レベル制警報（土砂災害警報/注意報/特別警報/危険警報、大雨/高潮危険警報）

### JSON → テキスト変換の仕組み

```
気象庁API レスポンス（生JSON）
        │
        │  例: weatherCodes: ["201", "300", "101"]
        │
        ▼
┌─────────────────────────────────────┐
│  WEATHER_CODE_MAP による変換         │
│  （気象庁 TELOPS 準拠 / 約100種類）  │
│                                     │
│  "201" → "曇時々晴"                  │
│  "300" → "雨"                        │
│  "101" → "晴時々曇"                  │
└─────────────────────────────────────┘
        │
        │  ISO 8601 → 日本語日付変換
        │  "2026-04-14T00:00:00+09:00" → "4月14日(火)"
        │
        ▼
整形済みテキスト（Claudeに渡す）
```

---

## 利用可能なツール（全23種）

### 予報・警報系（エリアコード指定）

| ツール名 | 説明 | 主な引数 |
|---|---|---|
| `search_area` | 地域名（部分一致）でエリアコードを検索 | `name`: 検索キーワード |
| `get_forecast` | 3日間の短期天気予報を取得 | `area_code` |
| `get_weekly_forecast` | 週間天気予報を取得 | `area_code` |
| `get_overview` | 天気概況テキストを取得 | `area_code` |
| `get_warning` | 警報・注意報の発表状況を取得（**2026-05-28 の新体系**: レベル2注意報〜レベル5特別警報、市町村別、各種別の最新の報、特記事項） | `area_code` |
| `get_warning_timeline` | **時系列情報（警報等の見通し）**を取得。3時間ごとの明日までの見通し（大雨・土砂災害・高潮・風・雷 等）を市町村別に表示。注意以上の見通しがある市町村だけを表示する予測情報 | `area_code`, `municipality`（省略可） |
| `get_early_warning` | 早期注意情報（警報級の可能性）を**地域ごとの表**（行＝現象、列＝時間区分）で取得。短期＝6時間ごと・明後日まで（最後の区分は12時間。大雨と土砂災害を分離）、週間＝日ごと。値は「高」「中」「－」に統一し、**全現象の行を必ず出力**（全期間が「－」の行も省略しない）。冒頭に「高」「中」の要約、表の後に気象台コメント | `area_code` |
| `get_forecaster_comment` | 気象台からのコメント（警報等の見込み・特記事項）を取得。台風からのうねりなど「<<特記事項>>」セクションもここに含まれる | `area_code` |
| `get_information` | 気象情報（府県・地方・全般）の見出し＋本文を取得。大雨・暴風・高波・台風などの詳細解説文を確認できる。台風の実況・進路予報は `get_typhoon` で取得（旧 typhoon.json の統合は廃止） | `area_code`（省略可）, `info_type`（省略可） |
| `get_typhoon` | **発生中の台風の実況**（位置・気圧・風速・強風域・暴風域）と**進路予報**（予報円・暴風警戒域）を取得 | `typhoon_number`（省略可。例: 26） |
| `get_earthquake_info` | 最近の地震情報を取得（震央地名・M・最大震度・発生日時） | `min_intensity`（震度フィルタ）, `count`（件数） |
| `get_tsunami_info` | 発表中の津波警報・注意報・予報を取得。発表なしの場合はその旨を返す | なし |

### 気象の状況・観測値系（全国データ）

| ツール名 | 説明 | 主な引数 |
|---|---|---|
| `get_mdrr_data` | 全国観測所の最新値を取得（降水量・気温・風速・積雪 等 20種）。各地点の値が記録された時刻を毎行表示し、風速系（`mxwsp`/`gust`）は風向も併せて表示。降水要素は`daily_max=true`で「現在値」ではなく「本日の最大値」でランキング可能 | `element`（必須）, `prefecture`, `top_n`, `daily_max` |
| `get_daily_ranking` | 全国観測値ランキング（上位10地点）を取得 | `date`（MM/DD）, `element` |
| `get_record_update` | 観測史上1位の値 更新状況を取得 | `date`（MM/DD） |

### 長期予報・気候情報系（地域番号指定）

| ツール名 | 説明 | 主な引数 | 更新頻度 |
|---|---|---|---|
| `get_twoweek_forecast` | 2週間気温予報（8〜12日先の5日間平均気温）を取得。高い/低い確率付き | `region_num` | 毎日9:30頃 |
| `get_monthly_forecast` | 1ヶ月予報（向こう7・14・28日間の気温傾向）を取得 | `region_num` | 毎週木曜9:30頃 |
| `get_3month_forecast` | 3ヶ月予報の解説資料URLと概要を取得（季節規模の見通し） | なし | 毎月下旬 |
| `get_6month_forecast` | 暖候期・寒候期予報（6ヶ月見通し）の解説資料URLと概要を取得 | なし | 年2回（2月・9月下旬） |
| `get_early_weather_info` | 早期天候情報（2週間先の顕著な高温・低温・多雨・少雨・多雪の可能性）を取得 | `region_num`（省略可） | 毎週月・木（発表時のみ） |
| `get_elnino_monitor` | エルニーニョ監視速報のURLと概要を取得（季節予報の背景情報） | なし | 毎月10日頃 |

### 潮位観測系（観測点コード指定）

| ツール名 | 説明 | 主な引数 |
|---|---|---|
| `get_tide_observation` | 観測点コードを指定して現在の潮位・天文潮位・気象偏差（高潮指標）・過去数時間の推移を取得 | `station_code`（必須）, `hours_back`（デフォルト3・最大12） |
| `search_tide_stations` | 全国の潮位観測所を名前・住所キーワードで検索して観測点コードを調べる | `keyword`（省略時は全国一覧） |

**長期予報系の `region_num` 一覧**

| 番号 | 地域名 |
|---|---|
| 11 | 北海道地方 |
| 15 | 東北地方 |
| 20 | 関東甲信地方 |
| 22 | 東海地方 |
| 23 | 近畿地方 |
| 26 | 中国地方 |
| 29 | 四国地方 |
| 30 | 九州北部地方（山口県を含む） |
| 31 | 九州南部・奄美地方 |
| 34 | 沖縄地方 |

> `get_early_weather_info` のみ `0` で全国指定が可能。

#### `get_mdrr_data` の element キー一覧

| カテゴリ | キー |
|---|---|
| 降水量 | `pre1h` / `pre3h` / `pre6h` / `pre12h` / `pre24h` / `pre48h` / `pre72h` / `predaily` |
| 降水量（全時間区分まとめて） | `pre_all`（1h/3h/6h/12h/24h/48h/72hの日最大値ランキングを一括取得。時間区分を指定しない「降水量の日最大ランキング」のような質問で使う） |
| 風速 | `mxwsp`（最大風速）/ `gust`（最大瞬間風速） |
| 気温 | `mxtem`（最高気温）/ `mntem`（最低気温） |
| 積雪・降雪 | `snc` / `mxsnc` / `snd3h` / `snd6h` / `snd12h` / `snd24h` / `snd48h` / `snd72h` |

### エリアコードの例

| 地域名 | エリアコード |
|---|---|
| 沖縄本島地方 | 471000 |
| 東京都 | 130000 |
| 大阪府 | 270000 |
| 福岡県 | 400000 |
| 北海道（札幌）| 016000 |

---

## セットアップ手順

### 1. リポジトリをクローン

```bash
git clone https://github.com/masauehr/jma-mcp.git ~/projects/jma_mcp
cd ~/projects/jma_mcp
```

### 2. 依存パッケージのインストール

```bash
pip3 install -r requirements.txt
# mcp, requests がインストールされる
```

### 3. Claude Code に登録

#### プロジェクトローカル登録（そのプロジェクトのみ）

プロジェクトディレクトリに `.mcp.json` を作成:

```json
{
  "mcpServers": {
    "jma": {
      "command": "python3",
      "args": ["/Users/ユーザー名/projects/jma_mcp/server.py"]
    }
  }
}
```

> **注意**: `args` にはサーバーの**絶対パス**を指定すること（`~/` は使えない）。

> **注意（接続失敗の原因になりやすい）**: `command` の `python3` が、`mcp` パッケージ未導入の Python（別の仮想環境など）に解決されると、`ModuleNotFoundError: mcp` で **「Connection closed」** となり接続に失敗する。`mcp` と `requests` を導入した Python の**絶対パス**（例: `/opt/homebrew/bin/python3`）を `command` に指定すること。確認: `/opt/homebrew/bin/python3 -c 'import mcp, requests'`。

#### グローバル登録（どのディレクトリからでも使えるようにする）

```bash
claude mcp add --scope user jma python3 /Users/masahiro/projects/jma_mcp/server.py
```

`~/.claude.json` に書き込まれ、どのディレクトリで Claude Code を起動しても使えるようになる。

### 4. 登録確認

Claude Code を再起動後、`/mcp` コマンドで `jma` サーバーが表示されれば完了。

---

## 使い方

Claude Code のチャットで日本語で質問するだけ。

```
「東京の今日の天気を教えて」
「大阪の週間天気予報は？」
「沖縄の天気概況を見せて」
「沖縄への注意報の発表状況は？」
「沖縄県への早期注意情報を教えて」
「今日の全国降水量ランキングを見せて」
「沖縄の最高気温を全地点確認したい」
「今日、観測史上1位を更新した地点は？」
「北海道の積雪上位10地点は？」
「九州北部地方の2週間の気温傾向は？」
「今月の気温は平年より高い？（1ヶ月予報）」
「この夏の3ヶ月予報を教えて」
「今年の寒候期予報（6ヶ月）は？」
「九州北部地方の早期天候情報を教えて」
「エルニーニョの現況と今後の見通しは？」
「台風の最新情報を教えて」
「那覇の現在の潮位を教えて」
「宮崎の潮位偏差（高潮）の状況は？」
「石垣島の潮位を過去6時間で見せて」
「潮位観測所のコードを調べたい（宮崎）」
```

Claudeが自動でツールを選択し、気象庁から最新データを取得して回答します。

### 回答フォーマットのルール

JMAツールの結果を表示する際は、**必ず末尾に出典リンクを付けること**。

| 情報種別 | 使用ツール | 出典リンク |
|---|---|---|
| 短期天気予報 | `get_forecast` | `https://www.jma.go.jp/bosai/forecast/#area_type=offices&area_code={area_code}` |
| 週間天気予報 | `get_weekly_forecast` | `https://www.jma.go.jp/bosai/forecast/#area_type=offices&area_code={area_code}` |
| 警報・注意報（新体系: レベル付き） | `get_warning` | `https://www.jma.go.jp/bosai/map.html#contents=warning&areaCode={area_code}` |
| 時系列情報（警報等の見通し） | `get_warning_timeline` | `https://www.jma.go.jp/bosai/warning_timeline/` |
| 早期注意情報（警報級の可能性） | `get_early_warning` | `https://www.jma.go.jp/bosai/probability/#area_type=offices&area_code={area_code}&lang=ja` |
| 津波情報 | `get_tsunami_info` | `https://www.jma.go.jp/bosai/map.html#5/38.411/143.987/&elem=info&contents=tsunami` |
| 台風情報（実況・進路予報） | `get_typhoon` | `https://www.jma.go.jp/bosai/information/typhoon.html#` |
| 気象情報（府県・地方） | `get_information` | `https://www.jma.go.jp/bosai/information/#area_type=offices&area_code={area_code}&format=table` |
| 潮位観測（現在値・推移） | `get_tide_observation` | `https://www.jma.go.jp/bosai/tidelevel/#area_type=class20s&area_code={area_code}&point_code={station_code}&filter=0&class30s={class30_code}` |
| 潮位観測所の検索 | `search_tide_stations` | `https://www.jma.go.jp/bosai/tidelevel/` |

> **注意**: ツール結果に含まれるURLは不正確な場合があるため、上記の正しいURLを使うこと。
> 「早期注意情報」は警報級の可能性（`/bosai/probability/`）であり、警報・注意報（`/bosai/warning/`）とは別物。

### 表示フォーマット統一ルール

#### 短期予報（今日・明日・明後日）
行＝項目、列＝日付。

| 項目 | 今日（M/D(曜)） | 明日（M/D(曜)） | 明後日（M/D(曜)） |
|------|---------------|---------------|-----------------|
| 天気 | … | … | … |
| 降水確率 | 0-6h:x% 6-12h:x% 12-18h:x% 18-24h:x% | 同左 | 同左 |
| 最高気温 | x℃ | x℃ | x℃ |
| 最低気温 | x℃ | x℃ | x℃ |

#### 週間予報
行＝日付、列＝項目。

| 日付 | 天気 | 降水確率 | 最高気温 | 最低気温 | 信頼度 |
|------|------|---------|---------|---------|--------|
| M/D(曜) | … | x% | x℃ | x℃ | A/B/C |

#### 早期注意情報（警報級の可能性）
新形式（2026-05-28〜）: 短期は**6時間ごと（明後日まで）**、週間は**日ごと**。行＝現象種別、列＝時間区分。値は「高」「中」「－」で統一。
列見出しは各区分の**開始時刻**（`M/D(曜)H時〜`）をそのまま使う（「今夕まで」「今夜」などの呼び替えはしない）。
`get_early_warning` の出力（地域ごとの表・全現象行・気象台コメント付き）は、この形式に合わせてある。

**短期（明後日まで・6時間ごと）** ※最後の2区分のみ12時間

| 現象 | 9/24(木)12時〜 | 9/24(木)18時〜 | 9/25(金)0時〜 | 9/25(金)6時〜 | 9/25(金)12時〜 | 9/25(金)18時〜 | 9/26(土)0時〜 | 9/26(土)12時〜 |
|------|------|------|------|------|------|------|------|------|
| 大雨 | 中 | － | － | － | － | － | － | － |
| 土砂災害 | － | － | － | － | － | － | － | － |
| 雪 | － | － | － | － | － | － | － | － |
| 風（風雪） | － | － | － | － | － | － | － | － |
| 波 | － | － | － | － | － | － | － | － |
| 潮位 | － | － | － | － | － | － | － | － |

**週間（明後日以降・日ごと）**

| 現象 | M/D(曜) | M/D(曜) | M/D(曜) | M/D(曜) |
|------|------|------|------|------|
| 雨 | － | － | － | － |
| 雪 | － | － | － | － |
| 風（風雪） | － | － | 中 | 中 |
| 波 | － | － | 中 | 中 |
| 潮位 | － | － | － | 中 |

- 現象名は気象庁の表記のまま（短期は「大雨」と「土砂災害」に分かれ、週間は「雨」）
- 地域が複数ある場合は地域ごとに表を分ける
- データなし・可能性なしは「－」で統一（空欄・「なし」は使わない。雪の「なし」も「－」）
- 発表時刻は時分まで表示。各地域の気象台コメントは、表の後に地域名を付けて省略せず表示
- 全期間が「－」の現象行も省略せず表示する（「可能性なし」であることを示すため）

#### 気象情報（府県気象情報等）
要約・省略せず、XMLの `Body/Comment/Text` を**全文そのまま**表示する。

---

## ファイル構成

```
jma_mcp/
├── server.py          # MCPサーバー本体（ツール定義・API取得・整形）
├── areas.py           # エリアコードマスター（全国の地域コード一覧）
├── requirements.txt   # 依存パッケージ（mcp, requests）
├── tests/             # テスト（新体系対応。`/opt/homebrew/bin/python3 -m unittest discover -s tests`。通信はダミー）
└── .gitignore         # __pycache__, .mcp.json 等を除外
```

---

## 地域コード・地点コードのローカル参照

`~/projects/common/` に地域コード関連ファイルをローカル保存済み。
コード不明時は API を叩かずにこちらを参照する。

| ファイル | 内容 | 件数 |
|---|---|---|
| `area.json` | 気象庁地域コード（offices/class10s/class15s/class20s） | 17,318行 |
| `amedastable.json` | アメダス地点テーブル（コード・座標・地点名） | 1,286地点 |
| `stations.json` | mdrr CSV の観測所番号 ＋ アメダスコード対応表 | 914地点 |

```python
import json
with open('/Users/masahiro/projects/common/area.json') as f:
    d = json.load(f)
for code, v in d['offices'].items():
    if 'キーワード' in v.get('name', ''):
        print(code, v)
```

GitHub: https://github.com/masauehr/common

---

## リモート版（jma_mcp_remote）

HTTP/SSE ベースのリモート MCPサーバー。Claude.ai Web版・デスクトップアプリから使用可能。
詳細は [jma-mcp-remote.md](jma-mcp-remote.md) を参照。

---

## jma_weather_report との違い

| 比較項目 | jma-mcp | jma_weather_report |
|---|---|---|
| 用途 | インタラクティブな質問応答 | 毎朝の自動レポート生成 |
| トリガー | Claudeへの質問（手動） | GitHub Actions（自動・毎朝5:30） |
| 対象エリア | 全国（動的） | 沖縄本島地方（固定） |
| 出力形式 | Claudeの回答テキスト | Markdownファイル（GitHub公開） |
| 実行環境 | ローカルMac（stdio） | GitHub Actions（クラウド） |

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| `/mcp` で `jma` が表示されない | `.mcp.json` のパス誤り | 絶対パスを確認・修正 |
| `ModuleNotFoundError: mcp` | パッケージ未インストール | `pip3 install mcp requests` |
| 「エリアが見つかりません」 | キーワードが一致しない | `search_area` で別の表記を試す |
| JMA API タイムアウト | ネットワーク問題 | 時間をおいて再試行 |
| ローカルLLMでエリアコードエラー | LLMが整数で渡す（例: `471000` → int） | server.py 側で `str()` 変換済み・スキーマも `anyOf[string, integer]` 対応済み |
| ローカルLLMで「Message exceeds context limit」 | ツール結果がコンテキスト上限を超過 | `get_daily_ranking` の出力は上位5件に制限済み。コンテキスト長 8192 のモデルでは「沖縄の最高気温」のような地域絞り込みは `get_mdrr_data` を使う方が安定 |
| 警報・注意報の種別名が誤表示される | `WARNING_CODE_MAP` のコード番号が誤っていた | 2026-04-14 に公式 TELOPS コード表（`jmaxml_20260326_code.xlsx`）に基づき全件修正・最新化済み。bosai JSON API の `warnings[].code` は TELOPS コードを使用（例: 14=雷注意報、10=大雨注意報）。コード表は **https://xml.kishou.go.jp** の技術資料ページから取得可能 |
| 発表気象台名が誤表示される（例：宮古島地方なのに「石垣島地方気象台」） | Claude が `publishingOffice` を持たない整形データを自力推測していた | 2026-04-23 に `_get_forecast` で `publishingOffice` を取得しヘッダーに明示するよう修正済み |
| 降水確率が「50〜30%」のような範囲表示になる | `pops` を日付のみでグループ化していたため Claude が自己解釈 | 2026-04-23 に時刻から時間帯ラベル（`0-6h`/`6-12h`/`12-18h`/`18-24h`）を生成して日付ごとに集約する整形に変更済み |
| 気温が「最低22℃/最高25℃」「○〜○℃」の不規則な表示になる | `temps` の時刻から最高/最低を判別せず渡していた | 2026-04-23 に `timeDefines` の時刻（6〜18時=最高、それ以外=最低）で分類して整形するよう修正済み |
| 警報・気象情報・早期注意情報・台風情報が古い内容のまま（「警報なし」など）になる | 2026-05-28 の新体系移行で配信先が `data/r8/` 等に移り、**旧パスは 5/28 のまま更新されない**（エラーにならず古い内容が返る） | 2026-09-24 に新パスへ移行済み。旧パス（`warning/data/warning/` 等）を使っていないか確認する。警報は「警報システムの最終更新」の表示（6時間超で警告）も確認 |
| ローカル MCP が「Connection closed」で接続できない | 設定の `command: python3` が `mcp` 未導入の Python（例: 別の仮想環境）に解決され、`ModuleNotFoundError: mcp` で終了している | `mcp`・`requests` 導入済みの Python の絶対パス（例: `/opt/homebrew/bin/python3`）を `command` に指定（`~/.claude.json` と `.mcp.json`）。反映には Claude Code の再起動または `/mcp` での再接続 |
| 出典リンクが表示されない | Claude.ai では CLAUDE.md が読み込まれないため出典表示ルールが適用されない | Claude.ai の Projects カスタム指示（「手順」欄）に表示ルールを追加することで解決。下記「出典リンク表示設定」を参照 |

---

## 出典リンク表示設定（Claude.ai 専用）

Claude Code（CLI）では CLAUDE.md のルールが適用されるため自動表示される。
Claude.ai Web版・デスクトップ・iPhone版では CLAUDE.md が読み込まれないため、**Projects のカスタム指示（「手順」欄）** に以下を追加する。

```
気象庁MCPサーバー（jma-mcp-renderコネクタ）のツール結果を使って回答する際は、ツール結果の末尾にある「出典: 気象庁 https://...」のURLを必ず末尾にそのまま表示すること。URLを省略・変更しないこと。
```

> 設定場所: claude.ai → プロジェクト → 手順を編集

### 気象台コメントの出典について

`get_forecaster_comment` は気象庁の内部API（`/bosai/forecaster_comment/data/comments/{code}.txt`）から取得しているが、一般公開のウェブページが存在しない（404）ため、出典はURL非表示・「出典: 気象庁」のみを表示する。

---

## 実施済みの変更履歴

### 2026-09-24: 気象庁の新体系（2026-05-28）への対応

- **警報・注意報のレベル付き名称**（`WARNING_CODE_MAP` の改定。大雨・高潮・土砂災害の注意報〜特別警報）に対応済み（コード表は上の「2026-05-28 の新体系への対応」）。
- 警報・早期注意情報・気象情報・台風情報の**配信先の移転**（`data/r8/` など）に対応し、新ツール `get_warning_timeline`（時系列情報）と `get_typhoon`（台風の実況・進路予報）を追加した（全23種）。
- `get_early_warning` の出力を新形式（地域ごとの表・全現象行・高/中/－・6時間ごと）に変更。
- 旧パスは 2026-05-28 のまま更新されないため、**旧パスに戻さないこと**。`r8` は将来変わりうるが、404 のとき自動で現行の版を探索する。

---

## 社内活用：RAG チャットボット vs MCP サーバー

社内情報検索にローカルLLMを使う場合、**RAG** と **MCP** の2つのアプローチがある。

### アーキテクチャの違い

```
【RAG + ローカルLLM】

社内文書（PDF・Word・社内Wiki等）
        │
        │ 前処理（チャンク分割・ベクトル化）
        ▼
┌───────────────────┐
│  ベクトルDB         │  ← 埋め込みベクトルとして保存
│ (Chroma/Qdrant等) │     （スナップショット、定期更新が必要）
└─────────┬─────────┘
          │ 類似検索（質問をベクトル化して近いものを取得）
          ▼
┌───────────────────┐
│   ローカルLLM       │  取得した文書を文脈として受け取り回答生成
│  (Ollama等)        │
└─────────┬─────────┘
          ▼
     ユーザーの回答


【MCP + ローカルLLM】

社内システム（DB・API・ファイルサーバー・社内アプリ等）
        ▲
        │ リアルタイム接続（SQL / REST API / ファイル読み取り等）
        │
┌───────────────────┐
│   MCPサーバー       │  ← 社内システムへのインターフェース
│  (社内に設置)       │     （ツールとして機能を公開）
└─────────┬─────────┘
          │ ツール呼び出し（JSON-RPC）
          ▼
┌───────────────────┐
│   ローカルLLM       │  ツール結果を受け取り回答生成
│  (MCP対応クライアント)│
└─────────┬─────────┘
          ▼
     ユーザーの回答
```

### 詳細比較表

| 比較項目 | RAG + ローカルLLM | MCP + ローカルLLM |
|---|---|---|
| **データの鮮度** | △ 定期更新が必要（インデックス再構築） | ◎ 常にリアルタイム |
| **対応データ形式** | ○ テキスト化できるもの全般（PDF・Word・Markdown等） | ◎ DB・API・ファイル・外部サービス何でも |
| **構築の難易度** | △ 埋め込みモデル選定・チャンク設計・ベクトルDBの運用が必要 | ○ ツール関数を書くだけ（APIが整備されていれば） |
| **回答精度** | △ 検索漏れ・関係ない文書の混入リスクあり | ○ 必要なデータを正確に取得できる |
| **曖昧な質問への対応** | ◎ 意味的類似性で関連文書を横断検索できる | △ ツール設計次第（曖昧な質問はツール選択が難しい） |
| **非構造化データ** | ◎ 得意（文書・議事録・メモ等） | △ 構造化されていないと扱いにくい |
| **構造化データ** | △ テーブル・数値はベクトル検索が苦手 | ◎ 得意（SQL・API直取得） |
| **導入コスト** | 高（埋め込みモデル・ベクトルDB・パイプライン構築） | 中（MCPサーバーのコード開発） |
| **運用コスト** | 高（インデックス更新・品質監視が継続的に必要） | 低（社内システムが変わらなければほぼ不要） |

### どちらが向いているか

```
┌──────────────────────────────────────────────────────────┐
│  RAG が向いているケース                                    │
│                                                          │
│  ・社内マニュアル・規程・議事録など「文書の山」を検索したい  │
│  ・質問が曖昧・幅広い（「先月の会議で出た話って何？」）     │
│  ・データに構造がなく、APIもない                           │
│  ・過去の知識・ノウハウを蓄積・横断検索したい              │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  MCP が向いているケース                                    │
│                                                          │
│  ・社内DBや業務システムに最新データを問い合わせたい         │
│  ・「今日の在庫数は？」「○○案件の状況は？」など具体的質問   │
│  ・社内に REST API や DB が整備されている                  │
│  ・データの鮮度が重要（リアルタイム性が求められる）         │
│  ・複数のシステムをまたいで情報を集めたい                  │
└──────────────────────────────────────────────────────────┘
```

### 業務シナリオ別の選択例

| 業務シナリオ | 向いている方式 | 理由 |
|---|---|---|
| 社内規程・就業規則を調べる | RAG | 文書の意味的検索が必要 |
| 特定顧客の受注履歴を調べる | MCP | DBへのリアルタイム照会 |
| 過去のプロジェクト報告書を横断検索 | RAG | 非構造化文書の横断検索 |
| 在庫・納期の確認 | MCP | 最新データが必須 |
| 社内FAQ・ヘルプデスク | RAG | 質問の幅が広く文書ベース |
| 勤怠・経費システムの照会 | MCP | 構造化DBへの直接アクセス |
| 複数システムを横断した状況確認 | MCP | ツールを組み合わせて実行 |

### 両方を組み合わせる構成（現実解）

実際の社内展開では **RAGとMCPを併用する**のが最も現実的。
RAG自体をMCPのツールのひとつとして実装すれば、LLMが状況に応じて使い分けを自動判断できる。

```
ユーザーの質問
        │
        ▼
┌───────────────────┐
│   ローカルLLM       │
│  (MCP対応)          │
└──┬─────────────┬──┘
   │             │
   ▼             ▼
┌──────┐    ┌──────────────┐
│ RAG  │    │  MCPサーバー   │
│ツール│    │              │
│(MCP  │    │ ・社内DB      │
│経由で│    │ ・業務API     │
│呼び  │    │ ・ファイル    │
│出す) │    │   サーバー    │
└──┬───┘    └──────┬───────┘
   │               │
   ▼               ▼
ベクトルDB      社内システム群
（文書検索）    （リアルタイム）
```

- **RAG** → 「過去の知識・文書を探す」ための記憶装置
- **MCP** → 「今の状態・データを取ってくる」ためのアクセス手段
- **現実の社内導入** → 両方をMCP経由で統合し、LLMに使い分けさせるのが最強構成
