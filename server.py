"""
JMA MCP サーバー（リモート HTTP/SSE 版）
気象庁APIをMCPツールとして公開するSSEベースのサーバー。
Render 等のクラウド環境にデプロイして使用する。
"""
import asyncio
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import requests
import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Mount, Route

from areas import AREA_CODE_MAP, search_area_by_name

# 日本標準時
JST = timezone(timedelta(hours=9))

# JMA API エンドポイント
FORECAST_URL     = "https://www.jma.go.jp/bosai/forecast/data/forecast/{area_code}.json"
OVERVIEW_URL     = "https://www.jma.go.jp/bosai/forecast/data/overview_forecast/{area_code}.json"
WARNING_URL      = "https://www.jma.go.jp/bosai/warning/data/warning/{area_code}.json"
PROBABILITY_URL  = "https://www.jma.go.jp/bosai/probability/data/probability/{area_code}.json"
MDRR_BASE_URL       = "https://www.data.jma.go.jp/stats/data/mdrr"
MDRR_RANKING_URL    = MDRR_BASE_URL + "/rank_daily/data{mmdd}.html"
MDRR_RECORD_UPD_URL = MDRR_BASE_URL + "/rank_update/d{mmdd}.html"
FORECASTER_COMMENT_URL = "https://www.jma.go.jp/bosai/forecaster_comment/data/comments/{area_code}.txt"
INFORMATION_LIST_URL   = "https://www.jma.go.jp/bosai/information/data/information.json"
INFORMATION_DENBUN_URL = "https://www.jma.go.jp/bosai/information/data/denbun/{json_name}.json"
TYPHOON_LIST_URL       = "https://www.jma.go.jp/bosai/information/data/typhoon.json"
TYPHOON_DENBUN_URL     = "https://www.jma.go.jp/bosai/information/data/typhoon/{json_name}"
QUAKE_LIST_URL         = "https://www.jma.go.jp/bosai/quake/data/list.json"
TSUNAMI_LIST_URL       = "https://www.jma.go.jp/bosai/tsunami/data/list.json"
# 2週間気温予報・1ヶ月予報 確率予測CSVエンドポイント
TWOWEEK_CSV_URL    = "https://www.data.jma.go.jp/risk/probability/guidance/download2w.php?2week_t_{num}.csv"
MONTHLY_CSV_URL    = "https://www.data.jma.go.jp/risk/probability/guidance/download.php?month1_t_{num}.csv"
# 季節予報解説資料（3ヶ月・6ヶ月）ページ ※ JavaScript SPA のため静的取得不可
LONGFCST_KAISETSU_URL = "https://www.data.jma.go.jp/cpd/longfcst/kaisetsu/?term={term}"
LONGFCST_TWOWEEK_PAGE = "https://www.data.jma.go.jp/cpd/twoweek/"
# 早期天候情報ページ（JavaScript SPA）
SOUTEN_URL = "https://www.data.jma.go.jp/cpd/souten/?reg_no={reg_no}&elem={elem}"
SOUTEN_BASE_URL = "https://www.data.jma.go.jp/cpd/souten/"
SOUTEN_DATA_URL = "https://www.data.jma.go.jp/cpd/souten/data/{reg_no}.json"
SOUTEN_FLG_URL  = "https://www.data.jma.go.jp/cpd/souten/data/flg.json"
# エルニーニョ監視速報ページ
ELNINO_URL = "https://www.data.jma.go.jp/cpd/elnino/"

# 気象の状況 CSV エレメント定義
# key → (表示名, CSVパス, 単位, ソート順)
MDRR_ELEMENTS = {
    "pre1h":    ("1時間降水量",   "pre_rct/alltable/pre1h00_rct.csv",       "mm",   "desc"),
    "pre3h":    ("3時間降水量",   "pre_rct/alltable/pre3h00_rct.csv",       "mm",   "desc"),
    "pre6h":    ("6時間降水量",   "pre_rct/alltable/pre6h00_rct.csv",       "mm",   "desc"),
    "pre12h":   ("12時間降水量",  "pre_rct/alltable/pre12h00_rct.csv",      "mm",   "desc"),
    "pre24h":   ("24時間降水量",  "pre_rct/alltable/pre24h00_rct.csv",      "mm",   "desc"),
    "pre48h":   ("48時間降水量",  "pre_rct/alltable/pre48h00_rct.csv",      "mm",   "desc"),
    "pre72h":   ("72時間降水量",  "pre_rct/alltable/pre72h00_rct.csv",      "mm",   "desc"),
    "predaily": ("日降水量",      "pre_rct/alltable/predaily00_rct.csv",    "mm",   "desc"),
    "mxwsp":    ("最大風速",      "wind_rct/alltable/mxwsp00_rct.csv",      "m/s",  "desc"),
    "gust":     ("最大瞬間風速",  "wind_rct/alltable/gust00_rct.csv",       "m/s",  "desc"),
    "mxtem":    ("最高気温",      "tem_rct/alltable/mxtemsadext00_rct.csv", "℃",   "desc"),
    "mntem":    ("最低気温",      "tem_rct/alltable/mntemsadext00_rct.csv", "℃",   "asc"),
    "snc":      ("現在の積雪",    "snc_rct/alltable/snc00_rct.csv",         "cm",   "desc"),
    "mxsnc":    ("最深積雪",      "snc_rct/alltable/mxsnc00_rct.csv",       "cm",   "desc"),
    "snd3h":    ("3時間降雪量",   "snc_rct/alltable/snd3h00_rct.csv",       "cm",   "desc"),
    "snd6h":    ("6時間降雪量",   "snc_rct/alltable/snd6h00_rct.csv",       "cm",   "desc"),
    "snd12h":   ("12時間降雪量",  "snc_rct/alltable/snd12h00_rct.csv",      "cm",   "desc"),
    "snd24h":   ("24時間降雪量",  "snc_rct/alltable/snd24h00_rct.csv",      "cm",   "desc"),
    "snd48h":   ("48時間降雪量",  "snc_rct/alltable/snd48h00_rct.csv",      "cm",   "desc"),
    "snd72h":   ("72時間降雪量",  "snc_rct/alltable/snd72h00_rct.csv",      "cm",   "desc"),
}

# 警報・注意報コード → 名称マッピング（気象庁TELOPS準拠）
# 出典: https://xml.kishou.go.jp/tec_material.html
#   コード管理表一式 jmaxml_20260326_code.xlsx / WeatherWarning シート（令和8年3月26日更新）
# ※ bosai JSON API の warnings[].code はこの TELOPS コードを使用している
WARNING_CODE_MAP = {
    # 解除
    "0": "解除",
    # 警報
    "2": "暴風雪警報",
    "3": "大雨警報",           # 又はレベル３大雨警報
    "4": "洪水警報",
    "5": "暴風警報",
    "6": "大雪警報",
    "7": "波浪警報",
    "8": "高潮警報",           # 又はレベル３高潮警報
    "9": "土砂災害警報",       # レベル３土砂災害警報（令和6年度追加）
    # 注意報
    "10": "大雨注意報",        # 又はレベル２大雨注意報
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "高潮注意報",        # 又はレベル２高潮注意報
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "土砂災害注意報",    # レベル２土砂災害注意報（令和6年度追加）
    # 特別警報
    "32": "暴風雪特別警報",
    "33": "大雨特別警報",      # 又はレベル５大雨特別警報
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "高潮特別警報",      # 又はレベル５高潮特別警報
    "39": "土砂災害特別警報",  # レベル５土砂災害特別警報（令和6年度追加）
    # 危険警報（令和6年度追加）
    "43": "大雨危険警報",      # レベル４大雨危険警報
    "48": "高潮危険警報",      # レベル４高潮危険警報
    "49": "土砂災害危険警報",  # レベル４土砂災害危険警報
}

# 警報ステータスの優先度（表示順ソート用）
WARNING_STATUS_ORDER = {"発表": 0, "継続": 1, "更新": 2, "解除": 3}

# 2週間気温予報・1ヶ月予報 地域番号マップ
# 出典: https://www.data.jma.go.jp/risk/probability/info/number.html
LONGFCST_REGION_MAP = {
    "11": "北海道地方",       "12": "北海道日本海側",       "13": "北海道オホーツク海側",
    "14": "北海道太平洋側",   "15": "東北地方",             "16": "東北日本海側",
    "17": "東北太平洋側",     "18": "東北北部",              "19": "東北南部",
    "20": "関東甲信地方",     "21": "北陸地方",              "22": "東海地方",
    "23": "近畿地方",         "24": "近畿日本海側",          "25": "近畿太平洋側",
    "26": "中国地方",         "27": "山陰",                  "28": "山陽",
    "29": "四国地方",         "30": "九州北部地方",          "31": "九州南部・奄美地方",
    "32": "九州南部",         "33": "奄美地方",              "34": "沖縄地方",
}

# 気温平年差 → 定性カテゴリ変換（アンサンブル平均値を使用した近似）
def _anomaly_to_category(anomaly: float) -> str:
    """気温平年差（℃）をJMA定性カテゴリに変換"""
    if anomaly >= 1.5:
        return "かなり高い"
    elif anomaly >= 0.5:
        return "高い"
    elif anomaly > -0.5:
        return "平年並み"
    elif anomaly > -1.5:
        return "低い"
    else:
        return "かなり低い"


def _find_longfcst_region_num(query: str) -> str | None:
    """地域名の部分一致で2桁地域番号を返す"""
    # 数字2桁そのものを指定された場合はそのまま返す
    if query.isdigit() and len(query) == 2:
        if query in LONGFCST_REGION_MAP:
            return query
    # 名前検索
    for num, name in LONGFCST_REGION_MAP.items():
        if query in name or name in query:
            return num
    return None

# 警報・注意報エリアコード → 地域名（class10s / class15s）
WARNING_AREA_NAME_MAP = {
    # 沖縄本島地方
    "471010": "本島中南部", "471020": "本島北部", "471030": "久米島",
    # 大東島地方
    "472010": "南大東島", "472020": "北大東島",
    # 宮古島地方
    "473010": "宮古島", "473020": "多良間島",
    # 八重山地方
    "474010": "石垣島", "474020": "西表島・竹富島・小浜島・黒島・新城島・波照間島",
    "474030": "与那国島",
    # 北海道
    "011010": "石狩地方北部", "011020": "石狩地方南部",
    "012010": "渡島地方北部", "012020": "渡島地方南部",
    # 東北
    "040010": "宮城県北部", "040020": "宮城県南部・仙台",
    # 関東
    "130010": "東京地方", "130020": "伊豆諸島北部", "130030": "伊豆諸島南部",
    "130040": "小笠原諸島",
    # その他主要地方（class10s）
}

# HTTPリクエスト共通ヘッダー（JMA利用規約対応）
HEADERS = {"User-Agent": "jma_mcp/1.0 (educational use)"}

# 天気コード → テキストマッピング（気象庁TELOPS準拠）
WEATHER_CODE_MAP = {
    "100": "晴", "101": "晴時々曇", "102": "晴一時雨", "103": "晴時々雨",
    "104": "晴一時雪", "105": "晴時々雪", "106": "晴一時雨か雪",
    "107": "晴時々雨か雪", "108": "晴一時雨か雷雨", "110": "晴後時々曇",
    "111": "晴後曇", "112": "晴後一時雨", "113": "晴後時々雨", "114": "晴後雨",
    "115": "晴後一時雪", "116": "晴後時々雪", "117": "晴後雪",
    "118": "晴後雨か雪", "119": "晴後雨か雷雨", "120": "晴朝夕一時雨",
    "121": "晴朝の内一時雨", "122": "晴夕方一時雨", "123": "晴山沿い雷雨",
    "124": "晴山沿い雪", "125": "晴午後は雷雨", "126": "晴昼頃から雨",
    "127": "晴夕方から雨", "128": "晴夜は雨", "130": "朝の内霧後晴",
    "131": "晴明け方霧", "132": "晴朝夕曇", "140": "晴時々曇一時雨",
    "160": "晴一時雪か雨", "170": "晴時々雪か雨", "181": "晴後雪か雨",
    "200": "曇", "201": "曇時々晴", "202": "曇一時雨", "203": "曇時々雨",
    "204": "曇一時雪", "205": "曇時々雪", "206": "曇一時雨か雪",
    "207": "曇時々雨か雪", "208": "曇一時雨か雷雨", "209": "霧",
    "210": "曇後時々晴", "211": "曇後晴", "212": "曇後一時雨",
    "213": "曇後時々雨", "214": "曇後雨", "215": "曇後一時雪",
    "216": "曇後時々雪", "217": "曇後雪", "218": "曇後雨か雪",
    "219": "曇後雨か雷雨", "220": "曇朝夕一時雨", "221": "曇朝の内一時雨",
    "222": "曇夕方一時雨", "223": "曇山沿い雷雨", "224": "曇山沿い雪",
    "225": "曇午後は雷雨", "226": "曇昼頃から雨", "227": "曇夕方から雨",
    "228": "曇夜は雨", "229": "曇夜は雪", "230": "曇夜半後晴",
    "231": "曇海上海岸は霧か霧雨", "240": "曇時々曇一時雨", "250": "曇時々雪",
    "260": "曇一時雪か雨", "270": "曇時々雪か雨", "281": "曇後雪か雨",
    "300": "雨", "301": "雨時々晴", "302": "雨時々止む", "303": "雨時々雪",
    "304": "雨か雪", "306": "大雨", "308": "雨で暴風を伴う", "309": "雨一時雪",
    "311": "雨後時々晴", "313": "雨後時々曇", "314": "雨後時々雪",
    "315": "雨後雪", "316": "雨後晴", "317": "雨後曇", "320": "朝の内雨後晴",
    "321": "朝の内雨後曇", "322": "雨朝晩一時雪", "323": "雨昼頃から晴",
    "324": "雨夕方から晴", "325": "雨夜半から晴", "326": "雨夕方から雪",
    "327": "雨夜半から雪", "328": "雨一時強く降る", "329": "雨一時みぞれ",
    "340": "雪か雨", "350": "雨で雷を伴う", "361": "雪か雨後晴",
    "371": "雪か雨後曇", "400": "雪", "401": "雪時々晴", "402": "雪時々止む",
    "403": "雪時々雨", "405": "大雪", "406": "風雪強い", "407": "暴風雪",
    "409": "雪一時雨", "411": "雪後時々晴", "413": "雪後時々曇",
    "414": "雪後雨", "420": "朝の内雪後晴", "421": "朝の内雪後曇",
    "422": "雪昼頃から雨", "423": "雪夕方から雨", "424": "雪夜半から雨",
    "425": "雪一時強く降る", "426": "雪後みぞれ", "427": "雪一時みぞれ",
    "450": "雪で雷を伴う",
}

WEATHER_EMOJI_MAP = {"1": "☀️", "2": "☁️", "3": "🌧️", "4": "🌨️"}


def weather_code_to_text(code: str) -> str:
    """天気コードを説明テキストに変換"""
    return WEATHER_CODE_MAP.get(str(code), f"不明({code})")


def weather_code_to_emoji(code: str) -> str:
    """天気コードを絵文字に変換"""
    code_str = str(code)
    if not code_str:
        return "❓"
    return WEATHER_EMOJI_MAP.get(code_str[0], "🌤️")


def fetch_json(url: str) -> dict:
    """指定URLからJSONを取得する"""
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def format_date_jp(iso_str: str) -> str:
    """ISO 8601文字列を日本語日付に変換（例: 4月14日(月)）"""
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    dt = datetime.fromisoformat(iso_str).astimezone(JST)
    wd = weekdays[dt.weekday()]
    return f"{dt.month}月{dt.day}日({wd})"


# MCPサーバーのインスタンス作成
server = Server("jma-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """利用可能なツール一覧を返す"""
    return [
        Tool(
            name="get_forecast",
            description="エリアコードを指定して3日間の短期天気予報を取得する",
            inputSchema={
                "type": "object",
                "properties": {
                    "area_code": {
                        "anyOf": [{"type": "string"}, {"type": "integer"}],
                        "description": "気象庁エリアコード（例: 471000 = 沖縄本島地方）",
                    }
                },
                "required": ["area_code"],
            },
        ),
        Tool(
            name="get_weekly_forecast",
            description="エリアコードを指定して週間天気予報を取得する",
            inputSchema={
                "type": "object",
                "properties": {
                    "area_code": {
                        "anyOf": [{"type": "string"}, {"type": "integer"}],
                        "description": "気象庁エリアコード（例: 471000 = 沖縄本島地方）",
                    }
                },
                "required": ["area_code"],
            },
        ),
        Tool(
            name="get_overview",
            description="エリアコードを指定して天気概況テキストを取得する",
            inputSchema={
                "type": "object",
                "properties": {
                    "area_code": {
                        "anyOf": [{"type": "string"}, {"type": "integer"}],
                        "description": "気象庁エリアコード（例: 471000 = 沖縄本島地方）",
                    }
                },
                "required": ["area_code"],
            },
        ),
        Tool(
            name="search_area",
            description="エリア名（部分一致）からエリアコードを検索する",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "検索キーワード（例: '沖縄', '東京', '福岡'）",
                    }
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="get_warning",
            description="エリアコードを指定して警報・注意報の発表状況を取得する",
            inputSchema={
                "type": "object",
                "properties": {
                    "area_code": {
                        "anyOf": [{"type": "string"}, {"type": "integer"}],
                        "description": "気象庁エリアコード（例: 471000 = 沖縄本島地方）",
                    }
                },
                "required": ["area_code"],
            },
        ),
        Tool(
            name="get_early_warning",
            description="エリアコードを指定して早期注意情報（警報級の可能性）を取得する。今日・明日・明後日以降の大雨・暴風・大雪・波浪・高潮などの警報級現象の可能性（高・中・なし）を確認できる",
            inputSchema={
                "type": "object",
                "properties": {
                    "area_code": {
                        "anyOf": [{"type": "string"}, {"type": "integer"}],
                        "description": "気象庁エリアコード（例: 471000 = 沖縄本島地方）",
                    }
                },
                "required": ["area_code"],
            },
        ),
        Tool(
            name="get_mdrr_data",
            description=(
                "特定の都道府県や地域の気象観測値を取得する。"
                "「沖縄の最高気温」「北海道の降雪量」のように地域を絞って調べるときに使う。"
                "element(必須): mxtem=最高気温, mntem=最低気温, pre24h=日降水量, "
                "mxwsp=最大風速, gust=最大瞬間風速, snc=積雪, "
                "pre1h/pre3h/pre6h/pre12h/pre48h/pre72h=降水量, predaily=日降水量, "
                "mxsnc=最深積雪, snd3h/snd6h/snd12h/snd24h/snd48h/snd72h=降雪量。"
                "prefecture: 都道府県名（例: '沖縄', '北海道'）で絞り込み。"
                "top_n: 上位N件（デフォルト20）。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "element": {
                        "type": "string",
                        "description": "取得する気象要素のキー（例: 'pre24h', 'mxtem', 'snc'）",
                    },
                    "prefecture": {
                        "type": "string",
                        "description": "都道府県名でフィルタ（部分一致、例: '沖縄', '北海道'）。省略時は全国",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "上位N件を返す（デフォルト20、0で全件）",
                    },
                },
                "required": ["element"],
            },
        ),
        Tool(
            name="get_daily_ranking",
            description=(
                "全国の観測値ランキング上位5地点を取得する。"
                "「全国で一番暑い場所」「全国の最高気温ランキング」など全国比較に使う。"
                "特定の都道府県を調べるなら get_mdrr_data を使うこと。"
                "今日から過去7日分を参照可能。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "対象日付（MM/DD形式、例: '04/14'）。省略時は今日",
                    },
                    "element": {
                        "type": "string",
                        "description": (
                            "取得する要素（省略時は全要素）。"
                            "指定例: '最高気温', '最低気温', '降水量', '風速', '積雪', '降雪'"
                        ),
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_record_update",
            description=(
                "観測史上1位の値 更新状況を取得する。"
                "その日に観測史上1位（タイ記録含む）を更新した地点・観測値・従来記録を表示。"
                "今日から過去7日分を参照可能。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "対象日付（MM/DD形式、例: '04/13'）。省略時は今日",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_forecaster_comment",
            description=(
                "気象台からのコメントを取得する。"
                "「<<警報等の見込み>>」と「<<特記事項>>」を含む予報官コメント。"
                "台風・大雨・うねりなど特別な現象への注意喚起が記載される。"
                "天気予報・警報だけでは分からない気象台の総合的な見解を確認できる。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "area_code": {
                        "anyOf": [{"type": "string"}, {"type": "integer"}],
                        "description": "気象庁エリアコード（例: 471000 = 沖縄本島地方）",
                    }
                },
                "required": ["area_code"],
            },
        ),
        Tool(
            name="get_information",
            description=(
                "気象情報（府県気象情報・地方気象情報・全般気象情報など）の発表内容を取得する。"
                "大雨・暴風・高波・台風など気象現象に関する詳細な解説文（見出し＋本文）を確認できる。"
                "area_code を指定すると該当都道府県の情報に絞り込む。省略時は全国の最新情報を表示。"
                "info_type で「府県気象情報」「地方気象情報」「全般気象情報」等に絞り込み可能。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "area_code": {
                        "anyOf": [{"type": "string"}, {"type": "integer"}],
                        "description": "気象庁エリアコード（例: 471000 = 沖縄本島地方、400000 = 福岡県）。省略時は全国",
                    },
                    "info_type": {
                        "type": "string",
                        "description": (
                            "情報種別でフィルタ（部分一致）。"
                            "例: '府県気象情報', '地方気象情報', '全般気象情報', '潮位情報', '天候情報'"
                        ),
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_twoweek_forecast",
            description=(
                "2週間気温予報（8〜12日先の5日間平均気温）を地域別に取得する。"
                "「来週末ごろの気温は？」「2週間後は高温になる？」など短期〜2週間先の気温傾向を確認できる。"
                "region_num（地域番号）: 11=北海道地方, 15=東北地方, 20=関東甲信地方, "
                "22=東海地方, 23=近畿地方, 26=中国地方, 29=四国地方, "
                "30=九州北部地方, 31=九州南部・奄美地方, 34=沖縄地方。"
                "毎日9時30分頃更新。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "region_num": {
                        "type": "string",
                        "description": (
                            "地域番号（11〜34）または地域名（例: '沖縄地方', '関東甲信地方'）。"
                            "省略時は関東甲信地方（20）。"
                            "地域番号一覧: https://www.data.jma.go.jp/risk/probability/info/number.html"
                        ),
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="get_monthly_forecast",
            description=(
                "1ヶ月予報（向こう7日間・14日間・28日間の気温傾向）を地域別に取得する。"
                "「今月の気温は平年より高い？」「来月にかけての気温の見通しは？」など確認できる。"
                "region_num（地域番号）: 11=北海道地方, 15=東北地方, 20=関東甲信地方, "
                "22=東海地方, 23=近畿地方, 26=中国地方, 29=四国地方, "
                "30=九州北部地方, 31=九州南部・奄美地方, 34=沖縄地方。"
                "毎週木曜日9時30分頃更新。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "region_num": {
                        "type": "string",
                        "description": (
                            "地域番号（11〜34）または地域名（例: '沖縄地方', '関東甲信地方'）。"
                            "省略時は関東甲信地方（20）。"
                        ),
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="get_3month_forecast",
            description=(
                "3ヶ月予報の解説資料URLと概要を取得する。"
                "「夏の気温は？」「この先3ヶ月の降水量は？」など季節規模の見通しを知りたい場合に使う。"
                "気温・降水量・日照時間の各地域別「高い/平年並み/低い」確率が掲載される。"
                "毎月下旬発表（詳細な本文はブラウザでURL参照）。"
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_6month_forecast",
            description=(
                "暖候期予報・寒候期予報（6ヶ月見通し）の解説資料URLと概要を取得する。"
                "「今年の夏（3〜8月）は暑い？」「この冬（9〜3月）の寒さは？」などの長期見通しに使う。"
                "暖候期予報は2月下旬、寒候期予報は9月下旬に発表。"
                "詳細な本文はブラウザでURL参照。"
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_early_weather_info",
            description=(
                "早期天候情報（2週間先の顕著な高温・低温・多雨・少雨・多雪の可能性）のURLと概要を取得する。"
                "「2週間後に異常な高温になる？」「来週末は大雨になりそう？」などに使う。"
                "毎週月曜・木曜に更新（顕著な天候が予想される場合のみ発表）。"
                "region_num（地域番号）: 0=全国, 11=北海道地方, 15=東北地方, 20=関東甲信地方, "
                "22=東海地方, 23=近畿地方, 26=中国地方, 29=四国地方, "
                "30=九州北部地方, 31=九州南部・奄美地方, 34=沖縄地方。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "region_num": {
                        "type": "string",
                        "description": (
                            "地域番号（11〜34）または地域名（例: '沖縄地方', '関東甲信地方'）。"
                            "省略または '0' 指定で全国。"
                        ),
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="get_elnino_monitor",
            description=(
                "エルニーニョ監視速報のURLと概要を取得する。"
                "エルニーニョ/ラニーニャ現象の現況・予測、熱帯太平洋の海面水温状況を確認できる。"
                "毎月10日頃発表。日本の季節予報（高温・冷夏・暖冬等）に直結する情報。"
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_earthquake_info",
            description=(
                "最近の地震情報を取得する。"
                "震央地名・規模（マグニチュード）・最大震度・発生日時を一覧表示する。"
                "min_intensity を指定すると指定震度以上の地震に絞り込める。"
                "count で取得件数を指定（デフォルト10、最大50）。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "min_intensity": {
                        "type": "integer",
                        "description": "最小震度（1〜7）。省略時は全件表示",
                    },
                    "count": {
                        "type": "integer",
                        "description": "取得件数（デフォルト10、最大50）",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_tsunami_info",
            description=(
                "最近の津波情報・津波予報を取得する。"
                "発表中の津波警報・注意報・予報の一覧と対象地域を表示する。"
                "現在発表中の津波情報がない場合はその旨を返す。"
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """ツール呼び出しのディスパッチャー"""
    # ローカルLLMが整数で渡すケースに対応するため str() で正規化
    area_code = str(arguments["area_code"]) if "area_code" in arguments else None

    if name == "get_forecast":
        result = await _get_forecast(area_code)
    elif name == "get_weekly_forecast":
        result = await _get_weekly_forecast(area_code)
    elif name == "get_overview":
        result = await _get_overview(area_code)
    elif name == "search_area":
        result = await _search_area(arguments["name"])
    elif name == "get_warning":
        result = await _get_warning(area_code)
    elif name == "get_early_warning":
        result = await _get_early_warning(area_code)
    elif name == "get_mdrr_data":
        result = await _get_mdrr_data(
            arguments["element"],
            arguments.get("prefecture", ""),
            int(arguments.get("top_n", 20)),
        )
    elif name == "get_daily_ranking":
        result = await _get_daily_ranking(
            arguments.get("date", ""),
            arguments.get("element", ""),
        )
    elif name == "get_record_update":
        result = await _get_record_update(arguments.get("date", ""))
    elif name == "get_forecaster_comment":
        result = await _get_forecaster_comment(area_code)
    elif name == "get_information":
        result = await _get_information(
            area_code or "",
            arguments.get("info_type", ""),
        )
    elif name == "get_twoweek_forecast":
        result = await _get_twoweek_forecast(arguments.get("region_num", "20"))
    elif name == "get_monthly_forecast":
        result = await _get_monthly_forecast(arguments.get("region_num", "20"))
    elif name == "get_3month_forecast":
        result = await _get_3month_forecast()
    elif name == "get_6month_forecast":
        result = await _get_6month_forecast()
    elif name == "get_early_weather_info":
        result = await _get_early_weather_info(arguments.get("region_num", "0"))
    elif name == "get_elnino_monitor":
        result = await _get_elnino_monitor()
    elif name == "get_earthquake_info":
        result = await _get_earthquake_info(
            int(arguments.get("min_intensity", 0)),
            int(arguments.get("count", 10)),
        )
    elif name == "get_tsunami_info":
        result = await _get_tsunami_info()
    else:
        result = f"エラー: 未知のツール '{name}'"

    return [TextContent(type="text", text=result)]


async def _get_forecast(area_code: str) -> str:
    """3日間短期天気予報を取得して整形する"""
    area_name = AREA_CODE_MAP.get(area_code, area_code)
    url = FORECAST_URL.format(area_code=area_code)

    try:
        data = fetch_json(url)
    except requests.exceptions.RequestException as e:
        return f"エラー: 予報データの取得に失敗しました。\n詳細: {e}"

    # 短期予報（data[0]）を使用
    if not data or len(data) == 0:
        return "エラー: 予報データが空です。"

    short_term = data[0]
    publishing_office = short_term.get("publishingOffice", "")
    header = f"【{area_name} 短期天気予報】"
    if publishing_office:
        header += f"（{publishing_office} 発表）"
    lines = [header, ""]

    for time_series in short_term.get("timeSeries", []):
        time_defines = time_series.get("timeDefines", [])
        areas = time_series.get("areas", [])
        if not areas:
            continue

        area = areas[0]

        # 天気情報
        if "weathers" in area:
            lines.append("■ 天気")
            for i, weather in enumerate(area["weathers"]):
                if i < len(time_defines):
                    date_str = format_date_jp(time_defines[i])
                    lines.append(f"  {date_str}: {weather}")
            lines.append("")

        # 風
        if "winds" in area:
            lines.append("■ 風")
            for i, wind in enumerate(area["winds"]):
                if i < len(time_defines):
                    date_str = format_date_jp(time_defines[i])
                    lines.append(f"  {date_str}: {wind}")
            lines.append("")

        # 波（沿岸地域のみ）
        if "waves" in area:
            lines.append("■ 波")
            for i, wave in enumerate(area["waves"]):
                if i < len(time_defines):
                    date_str = format_date_jp(time_defines[i])
                    lines.append(f"  {date_str}: {wave}")
            lines.append("")

        # 降水確率（時刻を時間帯ラベルに変換して日付ごとに集約）
        if "pops" in area:
            lines.append("■ 降水確率")
            pop_by_date: dict = {}
            pop_order: list = []
            wdays_p = ["月", "火", "水", "木", "金", "土", "日"]
            for i, pop in enumerate(area["pops"]):
                if i >= len(time_defines):
                    continue
                dt = datetime.fromisoformat(time_defines[i]).astimezone(JST)
                date_key = f"{dt.month}月{dt.day}日({wdays_p[dt.weekday()]})"
                end_h = (dt.hour + 6) % 24
                slot = f"{dt.hour}-{end_h if end_h != 0 else 24}h"
                if date_key not in pop_by_date:
                    pop_by_date[date_key] = []
                    pop_order.append(date_key)
                pop_by_date[date_key].append(f"{slot}:{pop}%")
            for date_key in pop_order:
                lines.append(f"  {date_key}: {' '.join(pop_by_date[date_key])}")
            lines.append("")

        # 気温（日付ごとの最初のエントリ時刻で当日/翌日以降を判定）
        # 当日発表: [今日09:00(日中最高), 今日00:00(全日最高), 明日00:00(最低), 明日09:00(最高)]
        # 夜間発表: [明日00:00(最低), 明日09:00(最高)]
        # → 日付内の最初エントリが6時以降なら当日扱い(すべて最高)、0時なら翌日扱い(00:00=最低)
        if "temps" in area:
            lines.append("■ 気温")
            temp_by_date: dict = {}
            temp_order: list = []
            date_first_hour: dict = {}
            wdays = ["月", "火", "水", "木", "金", "土", "日"]
            for i, temp in enumerate(area["temps"]):
                if i >= len(time_defines) or not temp:
                    continue
                dt = datetime.fromisoformat(time_defines[i]).astimezone(JST)
                date_key = f"{dt.month}月{dt.day}日({wdays[dt.weekday()]})"
                if date_key not in date_first_hour:
                    date_first_hour[date_key] = dt.hour
            for i, temp in enumerate(area["temps"]):
                if i >= len(time_defines) or not temp:
                    continue
                dt = datetime.fromisoformat(time_defines[i]).astimezone(JST)
                date_key = f"{dt.month}月{dt.day}日({wdays[dt.weekday()]})"
                if date_first_hour[date_key] >= 6:
                    kind = "max"
                else:
                    kind = "max" if 6 <= dt.hour < 18 else "min"
                if date_key not in temp_by_date:
                    temp_by_date[date_key] = {}
                    temp_order.append(date_key)
                temp_by_date[date_key][kind] = temp
            for date_key in temp_order:
                t = temp_by_date[date_key]
                parts = []
                if "max" in t:
                    parts.append(f"最高{t['max']}°C")
                if "min" in t:
                    parts.append(f"最低{t['min']}°C")
                lines.append(f"  {date_key}: {' / '.join(parts)}")
            lines.append("")

    lines.append(f"出典: 気象庁 https://www.jma.go.jp/bosai/forecast/#area_type=offices&area_code={area_code}")
    return "\n".join(lines).rstrip()


async def _get_weekly_forecast(area_code: str) -> str:
    """週間天気予報を取得して整形する"""
    area_name = AREA_CODE_MAP.get(area_code, area_code)
    url = FORECAST_URL.format(area_code=area_code)

    try:
        data = fetch_json(url)
    except requests.exceptions.RequestException as e:
        return f"エラー: 予報データの取得に失敗しました。\n詳細: {e}"

    # 週間予報（data[1]）を使用
    if not data or len(data) < 2:
        return "エラー: 週間予報データがありません。"

    weekly = data[1]
    lines = [f"【{area_name} 週間天気予報】", ""]

    for time_series in weekly.get("timeSeries", []):
        time_defines = time_series.get("timeDefines", [])
        areas = time_series.get("areas", [])
        if not areas:
            continue

        area = areas[0]

        # 天気コード → テキスト変換
        if "weatherCodes" in area:
            lines.append("■ 天気")
            for i, code in enumerate(area["weatherCodes"]):
                if i < len(time_defines):
                    date_str = format_date_jp(time_defines[i])
                    emoji = weather_code_to_emoji(code)
                    text = weather_code_to_text(code)
                    lines.append(f"  {date_str}: {emoji} {text}")
            lines.append("")

        # 降水確率
        if "pops" in area:
            lines.append("■ 降水確率")
            for i, pop in enumerate(area["pops"]):
                if i < len(time_defines) and pop:
                    date_str = format_date_jp(time_defines[i])
                    lines.append(f"  {date_str}: {pop}%")
            lines.append("")

        # 信頼度（A=高・B=中・C=低）
        if "reliabilities" in area:
            lines.append("■ 信頼度")
            for i, rel in enumerate(area["reliabilities"]):
                if i < len(time_defines) and rel:
                    date_str = format_date_jp(time_defines[i])
                    lines.append(f"  {date_str}: {rel}")
            lines.append("")

        # 最高・最低気温
        if "tempsMin" in area or "tempsMax" in area:
            lines.append("■ 気温（最低 / 最高）")
            temps_min = area.get("tempsMin", [])
            temps_max = area.get("tempsMax", [])
            for i in range(max(len(temps_min), len(temps_max))):
                if i < len(time_defines):
                    date_str = format_date_jp(time_defines[i])
                    t_min = temps_min[i] if i < len(temps_min) and temps_min[i] else "—"
                    t_max = temps_max[i] if i < len(temps_max) and temps_max[i] else "—"
                    lines.append(f"  {date_str}: {t_min}°C / {t_max}°C")
            lines.append("")

    lines.append(f"出典: 気象庁 https://www.jma.go.jp/bosai/forecast/#area_type=offices&area_code={area_code}")
    return "\n".join(lines).rstrip()


async def _get_overview(area_code: str) -> str:
    """天気概況テキストを取得する"""
    area_name = AREA_CODE_MAP.get(area_code, area_code)
    url = OVERVIEW_URL.format(area_code=area_code)

    try:
        data = fetch_json(url)
    except requests.exceptions.RequestException as e:
        return f"エラー: 概況データの取得に失敗しました。\n詳細: {e}"

    lines = [f"【{area_name} 天気概況】", ""]

    # 発表時刻
    published_at = data.get("publishingOffice", "")
    report_datetime = data.get("reportDatetime", "")
    if report_datetime:
        lines.append(f"発表: {format_date_jp(report_datetime)}")
    if published_at:
        lines.append(f"発表機関: {published_at}")
    lines.append("")

    # 概況テキスト
    text = data.get("text", "")
    if text:
        lines.append(text)
    else:
        lines.append("概況テキストがありません。")

    lines.append("")
    lines.append(f"出典: 気象庁 https://www.jma.go.jp/bosai/forecast/#area_type=offices&area_code={area_code}")
    return "\n".join(lines)


async def _get_warning(area_code: str) -> str:
    """警報・注意報の発表状況を取得して整形する"""
    area_name = AREA_CODE_MAP.get(area_code, area_code)
    url = WARNING_URL.format(area_code=area_code)

    try:
        data = fetch_json(url)
    except requests.exceptions.RequestException as e:
        return f"エラー: 警報データの取得に失敗しました。\n詳細: {e}"

    report_datetime = data.get("reportDatetime", "")
    publishing_office = data.get("publishingOffice", "")
    headline = data.get("headlineText", "")

    lines = [f"【{area_name} 警報・注意報】", ""]
    if report_datetime:
        lines.append(f"発表: {format_date_jp(report_datetime)}")
    if publishing_office:
        lines.append(f"発表機関: {publishing_office}")
    if headline:
        lines.append(f"見出し: {headline}")
    lines.append("")

    # areaTypes[0]: 地域区分（class10）レベルで集計
    area_types = data.get("areaTypes", [])
    if not area_types:
        lines.append("警報・注意報データがありません。")
        return "\n".join(lines)

    # 発表中・解除以外を先に、解除を後にまとめる
    active_entries = []
    cleared_entries = []

    for area_info in area_types[0].get("areas", []):
        code = area_info.get("code", "")
        name_str = WARNING_AREA_NAME_MAP.get(code, code)
        warnings = area_info.get("warnings", [])

        active_warnings = []
        cleared_warnings = []

        for w in warnings:
            w_code = str(w.get("code", ""))
            status = w.get("status", "")
            w_name = WARNING_CODE_MAP.get(w_code, f"不明({w_code})")
            if status == "解除":
                cleared_warnings.append(f"{w_name}（{status}）")
            elif status:
                active_warnings.append(f"{w_name}（{status}）")

        if active_warnings:
            active_entries.append((name_str, active_warnings))
        if cleared_warnings:
            cleared_entries.append((name_str, cleared_warnings))

    if active_entries:
        lines.append("■ 発表中")
        for name_str, ws in active_entries:
            lines.append(f"  {name_str}: {' / '.join(ws)}")
        lines.append("")

    if cleared_entries:
        lines.append("■ 解除")
        for name_str, ws in cleared_entries:
            lines.append(f"  {name_str}: {' / '.join(ws)}")
        lines.append("")

    if not active_entries and not cleared_entries:
        lines.append("現在、発表中の警報・注意報はありません。")

    lines.append("")
    lines.append(f"出典: 気象庁 https://www.jma.go.jp/bosai/map.html#contents=warning&areaCode={area_code}")
    return "\n".join(lines).rstrip()


async def _get_early_warning(area_code: str) -> str:
    """早期注意情報（警報級の可能性）を取得して整形する"""
    area_name = AREA_CODE_MAP.get(area_code, area_code)
    url = PROBABILITY_URL.format(area_code=area_code)

    try:
        data = fetch_json(url)
    except requests.exceptions.RequestException as e:
        return f"エラー: 早期注意情報の取得に失敗しました。\n詳細: {e}"

    if not data:
        return "エラー: 早期注意情報データが空です。"

    # 可能性ラベルの表示変換（空文字は「低い」または「情報なし」）
    def fmt_prob(val: str) -> str:
        if val in ("高", "中"):
            return val
        if val == "なし":
            return "なし"
        return "—"

    # 警報級の可能性を持つプロパティのみ抽出するヘルパー
    EARLY_TYPES = {
        "雨の警報級の可能性",
        "雪の警報級の可能性",
        "風（風雪）の警報級の可能性",
        "波の警報級の可能性",
        "潮位の警報級の可能性",
    }

    lines = [f"【{area_name} 早期注意情報（警報級の可能性）】", ""]

    # 発表情報（data[0] から取得）
    first = data[0]
    report_datetime = first.get("reportDatetime", "")
    publishing_office = first.get("publishingOffice", "")
    if report_datetime:
        lines.append(f"発表: {format_date_jp(report_datetime)}")
    if publishing_office:
        lines.append(f"発表機関: {publishing_office}")
    lines.append("")

    # 短期（今日夜・明日）の警報級の可能性 — data[0] の timeSeries から抽出
    short_ts = first.get("timeSeries", [])
    short_early_ts = None
    for ts in short_ts:
        areas = ts.get("areas", [])
        if areas and "properties" in areas[0]:
            props = areas[0]["properties"]
            if any(p.get("type") in EARLY_TYPES for p in props):
                short_early_ts = ts
                break

    if short_early_ts:
        time_defines = short_early_ts.get("timeDefines", [])
        # 時刻ラベルを作成（例: 15日夜、16日昼）
        time_labels = []
        for td in time_defines:
            dt = datetime.fromisoformat(td).astimezone(JST)
            hour = dt.hour
            period = "夜" if hour >= 18 or hour < 6 else "昼前後"
            time_labels.append(f"{dt.month}/{dt.day}({['月','火','水','木','金','土','日'][dt.weekday()]}){period}")

        lines.append("■ 短期（今日夜～明日）")
        header = "  地域" + "".join(f"  {lbl}" for lbl in time_labels)
        lines.append(header)

        comment_lines = []  # 気象台コメントを別途収集
        for area_info in short_early_ts.get("areas", []):
            code = area_info.get("code", "")
            area_label = WARNING_AREA_NAME_MAP.get(code, code)
            text = area_info.get("text", "")
            props = area_info.get("properties", [])

            # 警報級の可能性プロパティのみ表示
            printed_props = []
            for prop in props:
                ptype = prop.get("type", "")
                if ptype not in EARLY_TYPES:
                    continue
                probs = prop.get("probabilities", [])
                prob_strs = [fmt_prob(p) for p in probs]
                # 全て「—」なら省略
                if all(p == "—" for p in prob_strs):
                    continue
                printed_props.append(f"  [{area_label}] {ptype}: {' / '.join(prob_strs)}")

            if printed_props:
                lines.extend(printed_props)

            # コメントは常に収集（確率表示の有無に関わらず）
            if text:
                comment_lines.append(f"  {area_label}: {text}")

        lines.append("")

        # 気象台コメントセクション
        if comment_lines:
            lines.append("■ 気象台コメント（短期）")
            lines.extend(comment_lines)
            lines.append("")

    # 週間（明後日以降）の警報級の可能性 — data[1]
    if len(data) > 1:
        weekly = data[1]
        weekly_ts = weekly.get("timeSeries", [])
        for ts in weekly_ts:
            time_defines = ts.get("timeDefines", [])
            areas = ts.get("areas", [])
            if not areas:
                continue
            props_sample = areas[0].get("properties", [])
            if not any(p.get("type") in EARLY_TYPES for p in props_sample):
                continue

            time_labels = [
                f"{datetime.fromisoformat(td).astimezone(JST).strftime('%m/%d')}"
                for td in time_defines
            ]

            lines.append("■ 週間（明後日以降）")
            lines.append("  地域: " + " / ".join(time_labels))

            for area_info in areas:
                code = area_info.get("code", "")
                area_label = WARNING_AREA_NAME_MAP.get(code, AREA_CODE_MAP.get(code, code))
                for prop in area_info.get("properties", []):
                    ptype = prop.get("type", "")
                    if ptype not in EARLY_TYPES:
                        continue
                    probs = prop.get("probabilities", [])
                    prob_strs = [fmt_prob(p) for p in probs]
                    if all(p == "—" for p in prob_strs):
                        continue
                    lines.append(f"  [{area_label}] {ptype}: {' / '.join(prob_strs)}")
            lines.append("")

    # 短期・週間ともに出力なし
    if len(lines) <= 4:
        lines.append("現在、警報級の可能性が高い・中程度の現象はありません。")

    lines.append("")
    lines.append(f"出典: 気象庁 https://www.jma.go.jp/bosai/probability/#area_type=offices&area_code={area_code}&lang=ja")
    return "\n".join(lines).rstrip()


async def _get_mdrr_data(element: str, prefecture: str = "", top_n: int = 20) -> str:
    """気象の状況CSVを取得して整形する"""
    if element not in MDRR_ELEMENTS:
        keys = ", ".join(MDRR_ELEMENTS.keys())
        return f"エラー: 不明な要素 '{element}'。\n使用可能なキー: {keys}"

    label, csv_path, unit, sort_order = MDRR_ELEMENTS[element]
    url = f"{MDRR_BASE_URL}/{csv_path}"

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        text = response.content.decode("shift_jis", errors="replace")
    except requests.exceptions.RequestException as e:
        return f"エラー: データ取得に失敗しました。\n詳細: {e}"

    lines = text.strip().splitlines()
    if len(lines) < 2:
        return "エラー: データが空です。"

    header = lines[0].split(",")
    # 列インデックス（共通）
    # 0:観測所番号, 1:都道府県, 2:地点, 4-8:現在時刻, 9:主要値
    IDX_PREF  = 1
    IDX_NAME  = 2
    IDX_YEAR  = 4
    IDX_MON   = 5
    IDX_DAY   = 6
    IDX_HOUR  = 7
    IDX_MIN   = 8
    IDX_VALUE = 9

    value_col_name = header[IDX_VALUE] if len(header) > IDX_VALUE else "値"

    # データ行をパース
    records = []
    for line in lines[1:]:
        cols = line.split(",")
        if len(cols) <= IDX_VALUE:
            continue
        pref  = cols[IDX_PREF].strip()
        name  = cols[IDX_NAME].strip()
        val_s = cols[IDX_VALUE].strip()

        # 都道府県フィルタ
        if prefecture and prefecture not in pref:
            continue

        # 値を数値変換（空・非数値はスキップ）
        try:
            val = float(val_s)
        except (ValueError, TypeError):
            continue

        # 観測時刻
        try:
            obs_time = f"{cols[IDX_YEAR]}/{cols[IDX_MON]}/{cols[IDX_DAY]} {cols[IDX_HOUR]}:{cols[IDX_MIN]}"
        except IndexError:
            obs_time = ""

        records.append({"pref": pref, "name": name, "value": val, "time": obs_time})

    if not records:
        pref_msg = f"（{prefecture}）" if prefecture else ""
        return f"該当データがありませんでした{pref_msg}。"

    # ソート
    reverse = (sort_order == "desc")
    records.sort(key=lambda x: x["value"], reverse=reverse)

    # 上位N件
    if top_n > 0:
        records = records[:top_n]

    # ヘッダー構築
    pref_label = f"（{prefecture}）" if prefecture else "（全国）"
    obs_time_sample = records[0]["time"] if records else ""
    lines_out = [
        f"【{label}{pref_label} 最新値】",
        "",
        f"観測時刻: {obs_time_sample}",
        f"ランキング基準: {value_col_name}",
        "",
    ]

    rank_label = "上位" if reverse else "下位"
    lines_out.append(f"{'順位':<4} {'都道府県':<14} {'地点':<22} {value_col_name}")
    lines_out.append("─" * 65)

    for i, rec in enumerate(records, 1):
        lines_out.append(
            f"{i:<4} {rec['pref']:<14} {rec['name']:<22} {rec['value']}"
        )

    total = len(records)
    lines_out.append(f"\n表示: {total}件")

    lines_out.append(f"\n出典: 気象庁 {MDRR_BASE_URL}/")
    return "\n".join(lines_out)


def _parse_html_tables(html: str) -> list[dict]:
    """HTML から <table> を解析して [{caption, rows}] のリストを返す。
    閉じタグなしの <tr> にも対応するため、<tr> で分割してパースする。"""
    result = []
    for table_html in re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE):
        cap_m = re.findall(r'<caption[^>]*>(.*?)</caption>', table_html, re.DOTALL | re.IGNORECASE)
        caption = re.sub(r'<[^>]+>', '', cap_m[0]).strip() if cap_m else ""

        # <tr> で分割（閉じタグがなくても対応）
        rows = []
        tr_blocks = re.split(r'<tr[^>]*>', table_html, flags=re.IGNORECASE)
        for tr in tr_blocks[1:]:  # 最初のブロックは <tr> の前なのでスキップ
            cells = re.findall(r'<t[dh][^>]*>(.*?)(?:</t[dh]>|(?=<t[dh][^>]*>)|(?=</tr>)|$)',
                               tr, re.DOTALL | re.IGNORECASE)
            clean = []
            for c in cells:
                text = re.sub(r'<[^>]+>', '', c).strip()
                # 観測値末尾の "]" を除去（"30.3 ]"・"13:45]" → "30.3"・"13:45"）
                # ただし "[タイ記録]" のような前置 "[" がある場合は除去しない
                if not text.startswith('['):
                    text = re.sub(r'\s*\]$', '', text)
                if text:
                    clean.append(text)
            if clean:
                rows.append(clean)

        result.append({"caption": caption, "rows": rows})
    return result


def _mmdd_from_arg(date_str: str) -> str:
    """'MM/DD' または 'MMDD' 形式の文字列を 'MMDD' に正規化。省略時は今日の JST 日付"""
    if date_str:
        normalized = date_str.replace("/", "").replace("-", "").strip()
        if len(normalized) == 4:
            return normalized
    now = datetime.now(JST)
    return now.strftime("%m%d")


async def _get_daily_ranking(date_str: str = "", element_filter: str = "") -> str:
    """全国観測値ランキング（上位10地点）を取得して整形する"""
    mmdd = _mmdd_from_arg(date_str)
    url = MDRR_RANKING_URL.format(mmdd=mmdd)

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        html = response.content.decode("utf-8", errors="replace")
    except requests.exceptions.RequestException as e:
        return f"エラー: データ取得に失敗しました。\n詳細: {e}"

    # 日付ラベルを HTML から取得
    date_label_m = re.search(r'<span id\s*=\s*["\']data_n["\'][^>]*>([^<]+)</span>', html)
    date_label = date_label_m.group(1).strip() if date_label_m else f"{mmdd[:2]}月{mmdd[2:]}日"

    time_label_m = re.search(r'<span[^>]*class=["\']ex2["\'][^>]*>([^<]+)</span>', html)
    time_label = time_label_m.group(1).strip() if time_label_m else ""

    tables = _parse_html_tables(html)

    # 要素フィルタキーワードのマッピング
    ELEMENT_KEYWORDS = {
        "最高気温": ["最高気温"],
        "最低気温": ["最低気温"],
        "気温": ["気温"],
        "降水量": ["降水量", "降水"],
        "風速": ["風速"],
        "積雪": ["積雪"],
        "降雪": ["降雪量", "降雪"],
    }

    filter_keywords = []
    for key, kws in ELEMENT_KEYWORDS.items():
        if key in element_filter:
            filter_keywords = kws
            break

    lines = [f"【全国観測値ランキング（{date_label}）{time_label}】", ""]

    written = 0
    for tbl in tables:
        caption = tbl["caption"]
        rows = tbl["rows"]
        if not caption or len(rows) < 3:
            continue

        # 要素フィルタ
        if filter_keywords and not any(kw in caption for kw in filter_keywords):
            continue

        lines.append(f"■ {caption}")

        # ヘッダー行（1行目）
        header = rows[0]
        # データ行（2行目以降、ただし「単位行」は2行目の場合がある）
        # 2行目が数値データでなければ単位行としてスキップ
        data_start = 1
        if len(rows) > 1:
            second_row = rows[1]
            # 数値が1つも含まれないなら単位行
            if not any(re.match(r'^-?\d', c) for c in second_row):
                data_start = 2

        # 上位5件に絞る（コンテキスト節約のため）
        for row in rows[data_start:data_start + 5]:
            if not row or not any(row):
                continue
            # 順位・都道府県・地点・値の列のみ抽出
            line_parts = [c for c in row[:6] if c]
            lines.append("  " + "  ".join(line_parts))

        lines.append("")
        written += 1

    if written == 0:
        lines.append("該当するランキングデータがありませんでした。")

    lines.append("")
    lines.append(f"出典: 気象庁 {url}")
    return "\n".join(lines).rstrip()


async def _get_record_update(date_str: str = "") -> str:
    """観測史上1位の値 更新状況を取得して整形する"""
    mmdd = _mmdd_from_arg(date_str)
    url = MDRR_RECORD_UPD_URL.format(mmdd=mmdd)

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        html = response.content.decode("utf-8", errors="replace")
    except requests.exceptions.RequestException as e:
        return f"エラー: データ取得に失敗しました。\n詳細: {e}"

    date_label = f"{mmdd[:2]}月{mmdd[2:]}日"

    tables = _parse_html_tables(html)
    lines = [f"【観測史上1位の値 更新状況（{date_label}）】", ""]

    # サマリテーブル（地点数）を最初に表示
    for tbl in tables:
        if "地点数" in tbl["caption"] and "昨冬" not in tbl["caption"]:
            lines.append("■ 更新地点数サマリ")
            for row in tbl["rows"]:
                if not row or not any(row):
                    continue
                lines.append("  " + " | ".join(c for c in row if c))
            lines.append("")
            break

    # 更新があった要素テーブル（地点数 > 0）を表示
    updated_count = 0
    for tbl in tables:
        caption = tbl["caption"]
        rows = tbl["rows"]
        # 地点数 > 0 のテーブルを対象とする
        m = re.search(r'(\d+)地点', caption)
        if not m or int(m.group(1)) == 0:
            continue
        if "地点数" in caption or "昨冬" in caption:
            continue
        if len(rows) < 2:
            continue

        lines.append(f"■ {caption}")

        # 2行目以降をデータとして出力
        data_start = 1
        if len(rows) > 1:
            if not any(re.match(r'^-?\d|^[^\d\s]{2,}', c) for c in rows[1]):
                data_start = 2

        for row in rows[data_start:]:
            if not row or not any(row):
                continue
            parts = [c for c in row[:9] if c]
            lines.append("  " + "  ".join(parts))

        lines.append("")
        updated_count += 1

    if updated_count == 0:
        lines.append("この日に観測史上1位を更新した地点はありませんでした。")

    lines.append("")
    lines.append(f"出典: 気象庁 {url}")
    return "\n".join(lines).rstrip()


async def _get_forecaster_comment(area_code: str) -> str:
    """気象台からのコメント（警報等の見込み・特記事項）を取得して整形する"""
    area_name = AREA_CODE_MAP.get(area_code, area_code)
    url = FORECASTER_COMMENT_URL.format(area_code=area_code)

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.encoding = "utf-8"
        response.raise_for_status()
        html = response.text
    except requests.exceptions.RequestException as e:
        return f"エラー: 気象台コメントの取得に失敗しました。\n詳細: {e}"

    # 発表時刻を抽出
    pub_date = ""
    m = re.search(r'class="ycomment_pub_date"[^>]*>([^<]+)<', html)
    if m:
        pub_date = m.group(1).strip()

    # <p> を段落区切り、<br> を改行に変換してからタグ除去
    text = re.sub(r'</p>', '\n\n', html, flags=re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    # リンク（<a>〜</a>）は丸ごと除去
    text = re.sub(r'<a [^>]+>.*?</a>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    # 矢印記号（リンク前後の装飾）を除去
    text = re.sub(r'[→←▶]', '', text)
    # 「背景色の説明」以降は不要なので除去
    text = re.sub(r'背景色の説明.*', '', text, flags=re.DOTALL)

    lines_raw = [l.strip() for l in text.splitlines() if l.strip()]

    lines = [f"【{area_name} 気象台からのコメント】", ""]
    if pub_date:
        lines.append(f"発表: {pub_date}")
        lines.append("")

    # 不要行のフィルタキーワード
    SKIP_KEYWORDS = ['で詳細を確認', '★', '警報・注意報のページ']

    for line in lines_raw:
        # 発表時刻の重複行はスキップ
        if pub_date and line == pub_date:
            continue
        # リンク残骸などの不要行はスキップ
        if any(kw in line for kw in SKIP_KEYWORDS):
            continue
        # セクションヘッダーを強調
        if '＜＜' in line and '＞＞' in line:
            lines.append("")
            lines.append(f"■ {line.strip()}")
        elif line.startswith('・'):
            lines.append(f"  {line}")
        elif line:
            lines.append(f"  {line}")

    lines.append("")
    lines.append("出典: 気象庁")
    return "\n".join(lines).rstrip()


async def _get_information(area_code: str = "", info_type: str = "") -> str:
    """気象情報（府県気象情報・地方気象情報・全般気象情報等）を取得して整形する"""
    try:
        items = fetch_json(INFORMATION_LIST_URL)
    except requests.exceptions.RequestException as e:
        return f"エラー: 気象情報一覧の取得に失敗しました。\n詳細: {e}"

    if not items:
        return "エラー: 気象情報データが空です。"

    # 台風全般情報は typhoon.json から別途取得してマージ
    try:
        typhoon_items = fetch_json(TYPHOON_LIST_URL)
        for item in typhoon_items:
            item["_typhoon"] = True  # 本文取得エンドポイント区別用
        items = items + typhoon_items
    except requests.exceptions.RequestException:
        pass  # 台風情報取得失敗は無視して続行

    # エリアコードフィルタ: areaCode（都道府県レベル）で前方一致
    # 例: area_code="471000" → areaCode="471000" に一致
    # area_code が指定されない場合は全件対象
    if area_code:
        # 上位コード（例: 47xxxx → 470000）でも一致させるため
        # items の areaCodes リスト内に area_code が含まれるものを選択
        filtered = [
            d for d in items
            if area_code in d.get("areaCodes", []) or d.get("areaCode") == area_code
        ]
        # 一致しない場合は都道府県コード先頭2桁で緩やかにマッチ
        if not filtered:
            prefix = area_code[:2]
            filtered = [
                d for d in items
                if any(c.startswith(prefix) for c in d.get("areaCodes", []))
            ]
    else:
        filtered = items

    # 情報種別フィルタ（部分一致）
    if info_type:
        filtered = [d for d in filtered if info_type in d.get("controlTitle", "")]

    if not filtered:
        area_label = AREA_CODE_MAP.get(area_code, area_code) if area_code else "全国"
        type_label = f"（種別: {info_type}）" if info_type else ""
        return f"現在、{area_label}の気象情報{type_label}は発表されていません。"

    # 発表日時の新しい順にソート
    filtered.sort(key=lambda d: d.get("reportDatetime", ""), reverse=True)

    # 本文取得は上位5件まで
    MAX_FULL_TEXT = 5
    area_label = AREA_CODE_MAP.get(area_code, area_code) if area_code else "全国"
    lines = [f"【{area_label} 気象情報】", f"該当件数: {len(filtered)}件", ""]

    for i, item in enumerate(filtered):
        control_title   = item.get("controlTitle", "")
        head_title      = item.get("headTitle", "")
        publishing      = item.get("publishingOffice", "")
        report_dt       = item.get("reportDatetime", "")
        info_type_label = item.get("infoType", "")
        # typhoon.json 由来は fileName フィールド、それ以外は jsonName フィールド
        is_typhoon = item.get("_typhoon", False)
        if is_typhoon:
            json_name = item.get("fileName", "")
        else:
            json_name = item.get("jsonName", "")

        date_str = format_date_jp(report_dt) if report_dt else ""

        lines.append(f"■ {control_title}（{publishing}）")
        lines.append(f"  発表: {date_str}　{info_type_label}")
        lines.append(f"  見出し: {head_title}")

        # 本文取得（上位 MAX_FULL_TEXT 件のみ）
        if i < MAX_FULL_TEXT and json_name:
            if is_typhoon:
                denbun_url = TYPHOON_DENBUN_URL.format(json_name=json_name)
            else:
                denbun_url = INFORMATION_DENBUN_URL.format(json_name=json_name)
            try:
                denbun = fetch_json(denbun_url)
                headline = denbun.get("headlineText", "").strip()
                comment  = denbun.get("commentText", "").strip()
                if headline:
                    lines.append(f"  概要: {headline}")
                if comment:
                    # 長い本文は改行を保持しつつ先頭に空白を付けて整形
                    for cline in comment.splitlines():
                        lines.append(f"    {cline}" if cline.strip() else "")
            except requests.exceptions.RequestException:
                pass  # 本文取得失敗は無視して続行

        lines.append("")

    if area_code:
        lines.append(f"出典: 気象庁 https://www.jma.go.jp/bosai/information/#area_type=offices&area_code={area_code}&format=table")
    else:
        lines.append("出典: 気象庁 https://www.jma.go.jp/bosai/information/")
    return "\n".join(lines).rstrip()


async def _search_area(name: str) -> str:
    """エリア名の部分一致でエリアコードを検索する"""
    results = search_area_by_name(name)

    if not results:
        return f"「{name}」に一致するエリアが見つかりませんでした。"

    lines = [f"「{name}」の検索結果 ({len(results)}件)", ""]
    for item in results:
        lines.append(f"  {item['name']}: {item['code']}")

    return "\n".join(lines)


async def _get_twoweek_forecast(region_input: str = "20") -> str:
    """2週間気温予報CSVを取得して整形する"""
    # 地域名 → 番号に変換
    region_num = _find_longfcst_region_num(region_input) or region_input
    if region_num not in LONGFCST_REGION_MAP:
        valid = ", ".join(f"{k}={v}" for k, v in LONGFCST_REGION_MAP.items())
        return f"エラー: 地域番号 '{region_input}' が不正です。\n有効な番号: {valid}"

    region_name = LONGFCST_REGION_MAP[region_num]
    url = TWOWEEK_CSV_URL.format(num=region_num)

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        text = response.content.decode("utf-8", errors="replace")
    except requests.exceptions.RequestException as e:
        return f"エラー: 2週間気温予報データの取得に失敗しました。\n詳細: {e}"

    lines = text.strip().splitlines()
    if len(lines) < 2:
        return "エラー: CSVデータが空です。"

    # ヘッダー行: 初期値年,月,日,[空白×8],{-10.0,…,+10.0}
    header = lines[0].split(",")
    try:
        init_year = header[0].strip()
        init_mon  = header[1].strip()
        init_day  = header[2].strip()
    except IndexError:
        return "エラー: CSVフォーマットが予期した形式ではありません。"

    out = [
        f"【{region_name} 2週間気温予報】",
        f"初期値日: {init_year}年{init_mon}月{init_day}日（毎日9:30頃更新）",
        ""
    ]

    # ヘッダーから確率列の0°C列インデックスを計算
    # 範囲は -10.0 to +10.0（0.1℃刻み、201値）、確率列は col[11] 開始
    # 0°C = index 11 + 100 = 111
    PROB_ZERO_IDX_2W = 111  # P(anomaly ≤ 0°C) の列インデックス（2週間CSV）

    ELEM_NAMES = {"1": "日平均気温", "2": "日最高気温", "3": "日最低気温"}
    prev_elem = None

    for line in lines[1:]:
        cols = line.split(",")
        if len(cols) < 12:
            continue
        try:
            sy, sm, sd = cols[0].strip(), cols[1].strip(), cols[2].strip()
            ey, em, ed = cols[3].strip(), cols[4].strip(), cols[5].strip()
            period    = int(cols[6].strip())
            reg_code  = cols[7].strip()
            elem      = cols[8].strip()
            # col[10]: アンサンブル平均平年差（単位: 0.1℃）→ ÷10 で℃変換
            mean_anom = int(cols[10].strip()) / 10.0
        except (ValueError, IndexError):
            continue

        # 地点番号（5桁）はスキップ → 地域番号（2桁）のみ表示
        if len(reg_code) > 2:
            continue

        # P(anomaly ≤ 0°C) を取得して高温/低温確率を計算
        prob_below = None
        if len(cols) > PROB_ZERO_IDX_2W:
            try:
                prob_below = int(cols[PROB_ZERO_IDX_2W].strip())
            except (ValueError, IndexError):
                pass
        prob_above = (100 - prob_below) if prob_below is not None else None

        if elem != prev_elem:
            if prev_elem is not None:
                out.append("")
            out.append(f"■ {ELEM_NAMES.get(elem, f'要素{elem}')}")
            prev_elem = elem

        period_str = f"{int(sm)}/{int(sd)}〜{int(em)}/{int(ed)}（{period}日間平均）"
        cat  = _anomaly_to_category(mean_anom)
        sign = "+" if mean_anom >= 0 else ""
        prob_str = ""
        if prob_above is not None:
            prob_str = f"  高い確率 {prob_above}% / 低い確率 {prob_below}%"
        out.append(f"  {period_str}: 平年差 {sign}{mean_anom:.1f}℃ [{cat}]{prob_str}")

    out.append("")
    out.append("※ 平年差はアンサンブル予報の平均値（目安）、確率はP(平年以上/以下)")
    out.append(f"詳細グラフ（全国）: {LONGFCST_TWOWEEK_PAGE}")
    out.append(f"詳細グラフ（地域別）: {LONGFCST_TWOWEEK_PAGE}?reg_no={region_num}")
    out.append(f"早期天候情報: {SOUTEN_URL.format(reg_no=region_num, elem='temp')}")
    return "\n".join(out).rstrip()


async def _get_monthly_forecast(region_input: str = "20") -> str:
    """1ヶ月予報CSVを取得して整形する"""
    region_num = _find_longfcst_region_num(region_input) or region_input
    if region_num not in LONGFCST_REGION_MAP:
        valid = ", ".join(f"{k}={v}" for k, v in LONGFCST_REGION_MAP.items())
        return f"エラー: 地域番号 '{region_input}' が不正です。\n有効な番号: {valid}"

    region_name = LONGFCST_REGION_MAP[region_num]
    url = MONTHLY_CSV_URL.format(num=region_num)

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        text = response.content.decode("utf-8", errors="replace")
    except requests.exceptions.RequestException as e:
        return f"エラー: 1ヶ月予報データの取得に失敗しました。\n詳細: {e}"

    lines = text.strip().splitlines()
    if len(lines) < 2:
        return "エラー: CSVデータが空です。"

    # ヘッダー行: 初期値年,月,日,[空白×8],{-5.0,...,+5.0}
    header = lines[0].split(",")
    try:
        init_year = header[0].strip()
        init_mon  = header[1].strip()
        init_day  = header[2].strip()
    except IndexError:
        return "エラー: CSVフォーマットが予期した形式ではありません。"

    out = [
        f"【{region_name} 1ヶ月予報】",
        f"初期値日: {init_year}年{init_mon}月{init_day}日（毎週木曜9:30頃更新）",
        ""
    ]

    # 1ヶ月CSV: 範囲 -5.0 to +5.0（0.1℃刻み、101値）
    # 0°C は index 11 + 50 = 61
    PROB_ZERO_IDX_1M = 61  # P(anomaly ≤ 0°C) の列インデックス（1ヶ月CSV）

    ELEM_NAMES = {"1": "日平均気温", "2": "日最高気温", "3": "日最低気温"}
    prev_elem = None

    for line in lines[1:]:
        cols = line.split(",")
        if len(cols) < 12:
            continue
        try:
            sy, sm, sd = cols[0].strip(), cols[1].strip(), cols[2].strip()
            ey, em, ed = cols[3].strip(), cols[4].strip(), cols[5].strip()
            period    = int(cols[6].strip())
            reg_code  = cols[7].strip()
            elem      = cols[8].strip()
            # col[10]: アンサンブル平均平年差（単位: 0.1℃）→ ÷10 で℃変換
            mean_anom = int(cols[10].strip()) / 10.0
        except (ValueError, IndexError):
            continue

        # 地点番号（5桁）はスキップ
        if len(reg_code) > 2:
            continue

        # P(anomaly ≤ 0°C) を取得して確率を計算
        prob_below = None
        if len(cols) > PROB_ZERO_IDX_1M:
            try:
                prob_below = int(cols[PROB_ZERO_IDX_1M].strip())
            except (ValueError, IndexError):
                pass
        prob_above = (100 - prob_below) if prob_below is not None else None

        if elem != prev_elem:
            if prev_elem is not None:
                out.append("")
            out.append(f"■ {ELEM_NAMES.get(elem, f'要素{elem}')}")
            prev_elem = elem

        period_str = f"{int(sm)}/{int(sd)}〜{int(em)}/{int(ed)}（{period}日間平均）"
        cat  = _anomaly_to_category(mean_anom)
        sign = "+" if mean_anom >= 0 else ""
        prob_str = ""
        if prob_above is not None:
            prob_str = f"  高い確率 {prob_above}% / 低い確率 {prob_below}%"
        out.append(f"  {period_str}: 平年差 {sign}{mean_anom:.1f}℃ [{cat}]{prob_str}")

    out.append("")
    out.append("※ 平年差はアンサンブル予報の平均値（目安）、確率はP(平年以上/以下)")
    out.append(f"詳細（全国）: https://www.data.jma.go.jp/cpd/longfcst/kaisetsu/?term=P1M")
    out.append(f"早期天候情報（地域別）: {SOUTEN_URL.format(reg_no=region_num, elem='temp')}")
    return "\n".join(out).rstrip()


async def _get_3month_forecast() -> str:
    """3ヶ月予報の解説資料URLと概要を返す"""
    url = LONGFCST_KAISETSU_URL.format(term="P3M")

    # ページ存在確認
    page_ok = False
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            page_ok = True
    except requests.exceptions.RequestException:
        pass

    status = "（ページ確認OK）" if page_ok else "（取得失敗）"
    out = [
        "【3ヶ月予報 解説資料】",
        "",
        "気象庁が毎月下旬に発表する「3ヶ月予報」です。",
        "向こう3ヶ月間の気温・降水量・日照時間について、",
        "各地域別に「高い/平年並み/低い」の確率が掲載されます。",
        "",
        "■ 掲載内容",
        "  ・気温の見通し（各地方・地域別）",
        "  ・降水量の見通し（各地方・地域別）",
        "  ・日照時間の見通し（各地方・地域別）",
        "  ・確率表（高い/平年並み/低い）",
        "  ・特徴的な天候の解説文",
        "",
        "■ 発表時期",
        "  毎月下旬（木曜日）に更新",
        "",
        f"■ 解説資料URL {status}",
        f"  {url}",
        "",
        "※ 解説資料はJavaScriptで動的に描画されるため、",
        "  全文を読むにはブラウザでURLを開いてください。",
    ]
    return "\n".join(out)


async def _get_6month_forecast() -> str:
    """暖候期予報・寒候期予報（6ヶ月見通し）の解説資料URLと概要を返す"""
    url = LONGFCST_KAISETSU_URL.format(term="P6M")

    # ページ存在確認
    page_ok = False
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            page_ok = True
    except requests.exceptions.RequestException:
        pass

    now_jst = datetime.now(JST)
    month = now_jst.month
    # 暖候期（3〜8月）は2月下旬発表、寒候期（9〜3月）は9月下旬発表
    if 3 <= month <= 8:
        season_type = "暖候期（3〜8月）"
        publish_info = "2月下旬発表"
    else:
        season_type = "寒候期（9〜翌3月）"
        publish_info = "9月下旬発表"

    status = "（ページ確認OK）" if page_ok else "（取得失敗）"
    out = [
        "【暖候期予報・寒候期予報（6ヶ月見通し）】",
        "",
        f"現在の対象シーズン: {season_type}（{publish_info}）",
        "",
        "気象庁が年2回（2月下旬・9月下旬）発表する「6ヶ月見通し」です。",
        "半年先までの気温・降水量・日照時間の傾向が掲載されます。",
        "",
        "■ 掲載内容",
        "  ・気温の見通し（各地方・地域別）",
        "  ・降水量の見通し（各地方・地域別）",
        "  ・日照時間の見通し（各地方・地域別）",
        "  ・エルニーニョ/ラニーニャの影響評価",
        "  ・特徴的な天候の解説文",
        "",
        "■ 発表時期",
        "  ・暖候期予報: 毎年2月下旬（対象期間3〜8月）",
        "  ・寒候期予報: 毎年9月下旬（対象期間9〜翌3月）",
        "",
        f"■ 解説資料URL {status}",
        f"  {url}",
        "",
        "※ 解説資料はJavaScriptで動的に描画されるため、",
        "  全文を読むにはブラウザでURLを開いてください。",
    ]
    return "\n".join(out)


async def _get_early_weather_info(region_input: str = "0") -> str:
    """早期天候情報の発表内容を取得して返す"""
    # 地域番号を解決（0=全国）
    if region_input in ("0", "全国", ""):
        reg_no = 0
        region_name = "全国"
    else:
        longfcst_num = _find_longfcst_region_num(region_input) or region_input
        reg_no = int(longfcst_num)
        region_name = LONGFCST_REGION_MAP.get(longfcst_num, region_input)

    page_url = SOUTEN_URL.format(reg_no=reg_no, elem="temp")

    # 全国指定の場合はflg.jsonで発表種別を確認してURL案内
    if reg_no == 0:
        flg = {}
        try:
            resp = requests.get(SOUTEN_FLG_URL, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                flg = resp.json()
        except requests.exceptions.RequestException:
            pass

        out = [f"【早期天候情報 — 全国】", ""]
        if flg.get("temp") == 1:
            out.append("■ 現在発表中: 気温に関する早期天候情報（高温・低温）")
        if flg.get("snow", -9) >= 0:
            out.append("■ 現在発表中: 降雪量に関する早期天候情報")
        if not (flg.get("temp") == 1 or flg.get("snow", -9) >= 0):
            out.append("■ 現在、早期天候情報の発表はありません。")
        out += [
            "",
            "地域を指定すると発表内容の詳細を確認できます。",
            "例: 「九州北部地方の早期天候情報」",
            "",
            f"■ 全国マップURL",
            f"  {SOUTEN_BASE_URL}",
        ]
        return "\n".join(out)

    # 地域指定の場合はJSONデータを直接取得
    data = []
    try:
        resp = requests.get(
            SOUTEN_DATA_URL.format(reg_no=reg_no),
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
    except requests.exceptions.RequestException:
        pass

    out = [f"【早期天候情報 — {region_name}】", ""]

    if not data:
        out += [
            "現在、この地域の早期天候情報の発表はありません。",
            "",
            "早期天候情報は2週間先に顕著な高温・低温・多雪などが予想される",
            "場合にのみ発表されます（毎週月・木曜日）。",
            "",
            f"出典: 気象庁 {page_url}",
        ]
        return "\n".join(out)

    # 発表あり: titleフィールドが存在するレコードが概要、type=="本文" が詳細テキスト
    summary = [d for d in data if d.get("title") and d.get("type") != "本文"]
    honbun  = [d for d in data if d.get("type") == "本文"]

    # titleが存在しない場合は発表なし
    if not summary and not honbun:
        out += [
            "現在、この地域の早期天候情報の発表はありません。",
            "",
            "早期天候情報は2週間先に顕著な高温・低温・多雪などが予想される",
            "場合にのみ発表されます（毎週月・木曜日）。",
            "",
            f"出典: 気象庁 {page_url}",
        ]
        return "\n".join(out)

    if summary:
        s = summary[0]
        out.append(f"■ タイトル: {s.get('title', '')}")
        out.append(f"  発表: {s.get('reportDate_W', '')} {s.get('reportTime_W', '')}  {s.get('publishOffice', '')}")
        out.append(f"  対象地域: {s.get('reg_ch_text', region_name)}")
        out.append(f"  種別: {s.get('type', '')}")
        out.append(f"  条件: {s.get('condition', '')}")

    if honbun:
        out.append("")
        out.append("■ 本文")
        out.append(honbun[0].get("text", "").strip())

    out += [
        "",
        f"出典: 気象庁 {page_url}",
    ]
    return "\n".join(out)


async def _get_elnino_monitor() -> str:
    """エルニーニョ監視速報のURLと概要を返す"""
    # ページ存在確認
    page_ok = False
    try:
        resp = requests.get(ELNINO_URL, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            page_ok = True
    except requests.exceptions.RequestException:
        pass

    status = "（ページ確認OK）" if page_ok else "（取得失敗）"
    out = [
        "【エルニーニョ監視速報】",
        "",
        "気象庁が毎月発表する「エルニーニョ監視速報」です。",
        "太平洋赤道域の海面水温・大気循環の状況と、",
        "エルニーニョ/ラニーニャ現象の監視・予測が掲載されます。",
        "",
        "■ 掲載内容",
        "  ・エルニーニョ/ラニーニャ現象の現況と今後の見通し",
        "  ・熱帯太平洋の海面水温平年差分布図",
        "  ・各種気候指標の時系列グラフ",
        "  ・アンサンブル予報モデルによる今後6ヶ月の予測",
        "",
        "■ 発表時期",
        "  毎月10日頃（月1回）",
        "",
        f"■ URL {status}",
        f"  {ELNINO_URL}",
        "",
        "※ エルニーニョ/ラニーニャは日本の季節予報（気温・降水量）に",
        "  大きく影響するため、長期予報との併読を推奨します。",
    ]
    return "\n".join(out)


def _parse_intensity(maxi: str) -> float:
    """震度文字列（'5-', '5+', '6-', '6+' 等）を数値に変換する"""
    if not maxi:
        return 0
    maxi = str(maxi).strip()
    if maxi.endswith("-"):
        return float(maxi[:-1]) - 0.1
    if maxi.endswith("+"):
        return float(maxi[:-1]) + 0.1
    try:
        return float(maxi)
    except ValueError:
        return 0


async def _get_earthquake_info(min_intensity: int = 0, count: int = 10) -> str:
    """最近の地震情報を取得して整形する"""
    try:
        items = fetch_json(QUAKE_LIST_URL)
    except requests.exceptions.RequestException as e:
        return f"エラー: 地震情報の取得に失敗しました。\n詳細: {e}"

    if not items:
        return "エラー: 地震情報データが空です。"

    # 震度フィルタ
    if min_intensity > 0:
        items = [d for d in items if _parse_intensity(d.get("maxi", "")) >= min_intensity]
        if not items:
            return f"震度{min_intensity}以上の地震情報は見つかりませんでした。"

    count = min(max(1, count), 50)
    items = items[:count]

    intensity_label = f"（震度{min_intensity}以上）" if min_intensity > 0 else ""
    lines = [f"【最近の地震情報{intensity_label} 最新{len(items)}件】", ""]

    for item in items:
        at       = format_date_jp(item.get("at", ""))
        anm      = item.get("anm", "不明")
        mag      = item.get("mag", "—")
        maxi     = item.get("maxi", "—")
        ttl      = item.get("ttl", "")

        maxi_str = f"震度{maxi}" if maxi and maxi != "—" else "震度情報なし"
        mag_str  = f"M{mag}" if mag and mag != "—" else "規模不明"

        lines.append(f"■ {at}")
        lines.append(f"  震央: {anm}　{mag_str}　最大{maxi_str}")
        if ttl:
            lines.append(f"  種別: {ttl}")
        lines.append("")

    lines.append("出典: 気象庁 https://www.jma.go.jp/bosai/quake/")
    return "\n".join(lines).rstrip()


async def _get_tsunami_info() -> str:
    """津波情報・津波予報を取得して整形する"""
    try:
        items = fetch_json(TSUNAMI_LIST_URL)
    except requests.exceptions.RequestException as e:
        return f"エラー: 津波情報の取得に失敗しました。\n詳細: {e}"

    if not items:
        return "現在、発表中の津波情報はありません。\n\n出典: 気象庁 https://www.jma.go.jp/bosai/map.html#5/38.411/143.987/&elem=info&contents=tsunami"

    lines = [f"【津波情報 最新{len(items)}件】", ""]

    for item in items:
        rdt  = format_date_jp(item.get("rdt", ""))
        at   = format_date_jp(item.get("at", ""))
        anm  = item.get("anm", "不明")
        mag  = item.get("mag", "—")
        ttl  = item.get("ttl", "")
        ift  = item.get("ift", "")

        lines.append(f"■ {ttl}（{ift}）　発表: {rdt}")
        lines.append(f"  震源: {anm}　M{mag}　地震発生: {at}")

        # 津波予報の種別一覧
        kinds = item.get("kind", [])
        unique_kinds = list(dict.fromkeys(k.get("kind", "") for k in kinds if k.get("kind")))
        if unique_kinds:
            lines.append(f"  予報種別: {' / '.join(unique_kinds[:3])}")

        lines.append("")

    lines.append("出典: 気象庁 https://www.jma.go.jp/bosai/map.html#5/38.411/143.987/&elem=info&contents=tsunami")
    return "\n".join(lines).rstrip()


def create_app() -> Starlette:
    """SSE ベースの Starlette アプリを生成する"""
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )
        return Response()

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(create_app(), host="0.0.0.0", port=port)
