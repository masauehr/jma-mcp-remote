"""2026-05-28 の防災気象情報の新体系への対応のテスト（通信はダミー。実通信なし）

実行（mcp が入っている Python で）:
  /opt/homebrew/bin/python3 -m unittest discover -s tests -v
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

AREA_MASTER = {
    "class10s": {"120010": {"name": "北西部"}, "120020": {"name": "南部"}},
    "class20s": {"1220500": {"name": "館山市"}, "1222300": {"name": "鴨川市"}, "1222700": {"name": "佐倉市"}},
    "offices": {},
}


def report(code, at, items10=None, items20=None, head="", notice=""):
    r = {"dataTypeCode": code, "reportDatetime": at, "headlineText": head,
         "warning": {"class10Items": items10 or [], "class20Items": items20 or []}}
    if notice:
        r["notice"] = notice
    return r


def kinds(code=None, status="継続"):
    return [{"code": code, "status": status}] if code else [{"status": "発表警報・注意報はなし"}]


def run(coro):
    return asyncio.run(coro)


class UrlTest(unittest.TestCase):
    def test_new_paths_and_no_old_paths(self):
        for u in (server.WARNING_URL, server.PROBABILITY_URL, server.INFORMATION_LIST_URL, server.INFORMATION_DENBUN_URL):
            self.assertIn("/r8/", u)
        self.assertIn("warning_timeline/data/", server.WARNING_TIMELINE_URL)
        self.assertNotIn("/r8/", server.WARNING_TIMELINE_URL)          # 時系列情報は版の番号なし
        self.assertIn("typhoon/data/", server.TYPHOON_TARGET_URL)
        self.assertFalse(hasattr(server, "TYPHOON_LIST_URL"))          # 旧 typhoon.json（5/27 で停止）は使わない

    def test_new_tools_are_registered(self):
        names = [t.name for t in run(server.list_tools())]
        self.assertIn("get_warning_timeline", names)
        self.assertIn("get_typhoon", names)
        self.assertEqual(len(names), len(set(names)))

    def test_dispatch_new_tools(self):
        with mock.patch.object(server, "_get_warning_timeline", new=mock.AsyncMock(return_value="T")) as m1, \
             mock.patch.object(server, "_get_typhoon", new=mock.AsyncMock(return_value="Y")) as m2:
            out1 = run(server.call_tool("get_warning_timeline", {"area_code": 120000, "municipality": "佐倉"}))
            out2 = run(server.call_tool("get_typhoon", {"typhoon_number": "26"}))
        m1.assert_awaited_with("120000", "佐倉")                          # 整数で渡されても文字列に正規化
        m2.assert_awaited_with("26")
        self.assertEqual((out1[0].text, out2[0].text), ("T", "Y"))


class WarningCodeTest(unittest.TestCase):
    def test_normalization_and_levels(self):
        self.assertEqual(server.warning_name("03"), "レベル３大雨警報")      # JSON 上は2桁文字列
        self.assertEqual(server.warning_name("3"), "レベル３大雨警報")
        self.assertEqual(server.warning_name("09"), "レベル３土砂災害警報")
        self.assertEqual(server.warning_name(43), "レベル４大雨危険警報")
        self.assertEqual(server.warning_name("49"), "レベル４土砂災害危険警報")
        self.assertEqual(server.warning_name("48"), "レベル４高潮危険警報")
        self.assertEqual(server.warning_name("33"), "レベル５大雨特別警報")
        self.assertEqual(server.warning_name("29"), "レベル２土砂災害注意報")
        self.assertEqual(server.warning_name("14"), "雷注意報")
        self.assertTrue(server.warning_name("99").startswith("不明"))
        self.assertTrue(server.warning_name("xx").startswith("不明"))


class WarningFormatTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(server, "get_area_master", return_value=AREA_MASTER)
        p.start()
        self.addCleanup(p.stop)

    def test_only_latest_report_per_type(self):
        old = report("VPWW55", "2026-09-22T10:00:00+09:00", items20=[{"areaCode": "1222700", "kinds": kinds("03", "発表")}])
        new = report("VPWW55", "2026-09-24T10:00:00+09:00", items20=[{"areaCode": "1222700", "kinds": kinds("03", "解除")}])
        text = server.format_warning("千葉県", "120000", [old, new])
        self.assertNotIn("発表中（市町村）", text)
        self.assertIn("現在、発表中の警報・注意報はありません", text)

    def test_active_levels_notice_and_cleared_grouping(self):
        slide = report("VPWW56", "2026-09-24T10:41:00+09:00", head="南部では、土砂災害に注意してください。",
                       items10=[{"areaCode": "120020", "kinds": kinds("29")}],
                       items20=[{"areaCode": "1220500", "kinds": kinds("29")}, {"areaCode": "1222300", "kinds": kinds("29")},
                                {"areaCode": "1222700", "kinds": kinds("29", "解除")}], notice="令和８年８月千葉豪雨による…暫定基準")
        rain = report("VPWW55", "2026-09-24T10:41:00+09:00", head="注意報を解除します。",
                      items20=[{"areaCode": "1222700", "kinds": kinds("10", "解除")}])
        text = server.format_warning("千葉県", "120000", [slide, rain])
        self.assertIn("南部: レベル２土砂災害注意報（継続）", text)
        self.assertIn("館山市: レベル２土砂災害注意報（継続）", text)
        self.assertIn("特記事項", text)
        self.assertIn("暫定基準", text)
        self.assertIn("土砂災害（9月24日(木) 10:41発表）", text)
        self.assertIn("レベル２土砂災害注意報: 佐倉市", text)          # 解除は名称ごとにまとめて表示
        self.assertIn("レベル２大雨注意報: 佐倉市", text)
        self.assertIn("map.html#contents=warning&areaCode=120000", text)   # 出典URL

    def test_stale_system_is_flagged(self):
        r = report("VPWW55", "2026-09-24T10:00:00+09:00", items20=[{"areaCode": "1222700", "kinds": kinds("03")}])
        old = "2020-01-01T00:00:00Z"
        self.assertIn("更新が止まっている疑い", server.format_warning("千葉県", "120000", [r], old))
        from datetime import datetime, timezone
        fresh = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertNotIn("更新が止まっている疑い", server.format_warning("千葉県", "120000", [r], fresh))

    def test_legacy_dict_or_empty_is_reported_as_error(self):
        for bad in ({"reportDatetime": "2026-05-28T11:10:00+09:00", "areaTypes": []}, [], None):
            self.assertTrue(server.format_warning("千葉県", "120000", bad).startswith("エラー"))

    def test_get_warning_reads_r8_url(self):
        seen = []

        def fake(url):
            seen.append(url)
            if url.endswith("map_time.json"):
                return {"latestControlDatetime": "2026-09-24T02:35:07Z"}
            return [report("VPWW55", "2026-09-24T10:00:00+09:00", items20=[{"areaCode": "1222700", "kinds": kinds("03")}])]
        with mock.patch.object(server, "fetch_json", side_effect=fake):
            text = run(server._get_warning("120000"))
        self.assertTrue(any("/warning/data/r8/120000.json" in u for u in seen))
        self.assertIn("レベル３大雨警報", text)

    def test_network_error_message(self):
        with mock.patch.object(server, "fetch_json", side_effect=requests.exceptions.ConnectionError("x")):
            self.assertTrue(run(server._get_warning("120000")).startswith("エラー"))


class VersionDiscoveryTest(unittest.TestCase):
    def test_404_triggers_discovery_and_follows_new_version(self):
        server._JMA_VERSION["v"] = "r8"
        err = requests.exceptions.HTTPError(response=mock.Mock(status_code=404))

        def fake(url):
            if "/r8/" in url:
                raise err
            return {"ok": url}
        try:
            with mock.patch.object(server, "fetch_json", side_effect=fake), \
                 mock.patch.object(server, "_discover_jma_version", return_value="r9"):
                self.assertEqual(server.fetch_json_versioned("https://x/bosai/warning/data/r8/a.json")["ok"],
                                 "https://x/bosai/warning/data/r9/a.json")
            self.assertEqual(server._JMA_VERSION["v"], "r9")
        finally:
            server._JMA_VERSION["v"] = "r8"

    def test_non_404_errors_are_not_swallowed(self):
        err = requests.exceptions.HTTPError(response=mock.Mock(status_code=500))
        with mock.patch.object(server, "fetch_json", side_effect=err), \
             mock.patch.object(server, "_discover_jma_version") as d:
            with self.assertRaises(requests.exceptions.HTTPError):
                server.fetch_json_versioned("https://x/r8/a.json")
            d.assert_not_called()


class TimelineFormatTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(server, "get_area_master", return_value=AREA_MASTER)
        p.start()
        self.addCleanup(p.stop)

    def doc(self):
        def part(t, codes):
            return {"type": t, "locals": [{"codes": codes}]}
        blocks = [{"dateTime": f"2026-09-24T{h:02d}:00:00+09:00", "duration": "PT3H"} for h in (12, 15, 18)]
        return {"reportDatetime": "2026-09-24T11:00:00+09:00", "timeSeries": [
            {"timeDefines": blocks, "class20Items": [
                {"areaCode": "1220500", "kinds": [{"significancyParts": [part("土砂災害危険度", ["21", "31", "11"])]},
                                                  {"significancyParts": [part("風危険度", ["01", "01", "01"])]}]},
                {"areaCode": "1222700", "kinds": [{"significancyParts": [part("大雨浸水危険度", ["11", "11", "11"])]}]}]},
            {"timeDefines": [{"dateTime": "2026-09-24T12:00:00+09:00", "duration": "PT24H"}], "class20Items": []}]}

    def test_levels_from_tens_digit_and_filtering(self):
        text = server.format_warning_timeline("千葉県", "120000", self.doc())
        self.assertIn("館山市・土砂災害", text)
        self.assertNotIn("佐倉市", text)                              # すべてレベル1（なし）の市町村は出さない
        self.assertNotIn("・風", text)                               # レベル0の風は出さない
        row = next(line for line in text.splitlines() if line.startswith("館山市・土砂災害"))
        self.assertEqual(row.split()[-3:], ["注", "警", "・"])         # 21→注意 31→警戒 11→なし
        self.assertIn("予測情報", text)
        self.assertIn("5時・11時・17時・23時", text)

    def test_municipality_filter_and_empty(self):
        self.assertIn("注意以上の見通し", server.format_warning_timeline("千葉県", "120000", self.doc(), "佐倉"))
        self.assertIn("現在、（佐倉）注意以上", server.format_warning_timeline("千葉県", "120000", self.doc(), "佐倉"))
        self.assertIn("館山市", server.format_warning_timeline("千葉県", "120000", self.doc(), "館山"))

    def test_broken_documents(self):
        for bad in ({}, None, {"timeSeries": [{"timeDefines": [{"dateTime": "2026-09-24T12:00:00+09:00", "duration": "PT24H"}]}]}):
            self.assertTrue(server.format_warning_timeline("千葉県", "120000", bad).startswith("エラー"))


class InformationTest(unittest.TestCase):
    def test_r8_urls_br_conversion_and_missing_fields(self):
        items = [
            {"controlTitle": "府県気象解説情報", "headTitle": "千葉県気象解説情報（大雨）", "publishingOffice": "銚子地方気象台",
             "reportDatetime": "2026-09-23T06:38:00+09:00", "infoType": "発表", "areaCode": "120000", "areaCodes": ["120000"],
             "jsonName": "n1"},
            {"areaType": "offices", "areaCode": "120000", "areaCodes": ["120000"], "dataType": "pdf", "pdfName": "p",
             "reportDatetime": "2026-09-22T00:00:00+09:00"},                   # controlTitle・jsonName なし（PDF）
        ]
        seen = []

        def fake(url):
            seen.append(url)
            if url.endswith("information.json"):
                return items
            return {"headlineText": "大雨に注意", "commentText": "［気象概況］<br>降水量が多い<br /><br>［防災事項］"}
        with mock.patch.object(server, "fetch_json", side_effect=fake):
            text = run(server._get_information("120000"))
        self.assertTrue(any("/information/data/r8/information.json" in u for u in seen))
        self.assertTrue(any("/information/data/r8/denbun/n1.json" in u for u in seen))
        self.assertFalse(any("typhoon" in u for u in seen))            # 旧 typhoon.json は取得しない
        self.assertIn("降水量が多い", text)
        self.assertNotIn("<br", text)
        self.assertIn("（PDF資料）", text)


class EarlyWarningTest(unittest.TestCase):
    def test_new_hazard_types_and_6h_labels(self):
        def props(**kw):
            return [{"type": t, "probabilities": p} for t, p in kw.items()]
        data = [{"reportDatetime": "2026-09-24T11:00:00+09:00", "publishingOffice": "銚子地方気象台", "timeSeries": [
            {"timeDefines": ["2026-09-24T12:00:00+09:00", "2026-09-24T18:00:00+09:00"],
             "areas": [{"code": "120010", "text": "北西部では大雨に注意",
                        "properties": props(**{"大雨の警報級の可能性": ["中", ""], "土砂災害の警報級の可能性": ["", "高"]})}]}]},
            {"timeSeries": [{"timeDefines": ["2026-09-26T00:00:00+09:00"], "areas": [
                {"code": "120000", "properties": props(**{"雨の警報級の可能性": ["中"]})}]}]}]
        seen = []

        def fake(url):
            seen.append(url)
            return data
        with mock.patch.object(server, "fetch_json", side_effect=fake):
            text = run(server._get_early_warning("120000"))
        self.assertTrue(any("/probability/data/probability/r8/120000.json" in u for u in seen))
        self.assertIn("大雨の警報級の可能性: 中 / —", text)
        self.assertIn("土砂災害の警報級の可能性: — / 高", text)
        self.assertIn("9/24(木)12時〜", text)
        self.assertIn("明後日まで・6時間ごと", text)
        self.assertIn("雨の警報級の可能性: 中", text)                    # 週間（従来の種別名）も表示
        self.assertIn("発表: 9月24日(木) 11:00", text)


class TyphoonTest(unittest.TestCase):
    SPEC = [
        {"part": "title", "issue": {"UTC": "2026-09-24T03:45:00Z"}, "typhoonNumber": "2626", "name": {"jp": "スリゲ", "en": "Surigae"}},
        {"part": {"jp": "実況"}, "advancedHours": 0, "category": {"jp": "台風"}, "scale": "-", "intensity": "-",
         "position": {"deg": [18.5, 133.5]}, "location": "フィリピンの東", "course": "西北西", "speed": {"km/h": "25"},
         "pressure": "1000", "maximumWind": {"sustained": {"m/s": "20"}, "gust": {"m/s": "30"}},
         "galeWarning": [{"area": "北", "range": {"km": 280}}, {"area": "南", "range": {"km": 110}}],
         "validtime": {"UTC": "2026-09-24T03:00:00Z"}},
        {"part": {"jp": "予報 69時間後"}, "advancedHours": 69, "category": {"jp": "台風"}, "intensity": "強い",
         "position": {"deg": [22.8, 126.6]}, "pressure": "975", "maximumWind": {"sustained": {"m/s": "35"}, "gust": {"m/s": "50"}},
         "probabilityCircleRadius": {"km": 220}, "stormWarning": [{"area": {"jp": "全域"}, "range": {"km": 310}}]},
    ]
    FC = [{"part": "title"}, {"part": {"jp": "予報 69時間後"}, "advancedHours": 69, "validtime": {"UTC": "2026-09-27T00:00:00Z"}}]

    def fake(self, url):
        if url.endswith("targetTc.json"):
            return [{"tropicalCyclone": "TC2632", "typhoonNumber": "2626"}]
        return self.SPEC if url.endswith("specifications.json") else self.FC

    def test_format_and_number_filter(self):
        with mock.patch.object(server, "fetch_json", side_effect=self.fake):
            text = run(server._get_typhoon(""))
            self.assertIn("台風26号（スリゲ Surigae）", text)
            self.assertIn("北緯18.5度 東経133.5度（フィリピンの東）", text)
            self.assertIn("強風域（風速15m/s以上）: 北側280km・南側110km", text)
            self.assertIn("69時間後（9月27日(日) 09:00）", text)
            self.assertIn("暴風警戒域全域310km（強い）", text)
            self.assertIn("typhoon.html#", text)                        # 出典URL
            self.assertIn("台風26号", run(server._get_typhoon("2626")))   # 4桁でも絞り込める
            self.assertIn("台風26号", run(server._get_typhoon("26")))
            self.assertIn("見つかりませんでした", run(server._get_typhoon("5")))

    def test_no_typhoon(self):
        with mock.patch.object(server, "fetch_json", return_value=[]):
            self.assertIn("現在、発表中の台風情報はありません", run(server._get_typhoon("")))

    def test_detail_failure_does_not_crash(self):
        def fake(url):
            if url.endswith("targetTc.json"):
                return [{"tropicalCyclone": "TC2632", "typhoonNumber": "2626"}]
            raise requests.exceptions.ConnectionError("x")
        with mock.patch.object(server, "fetch_json", side_effect=fake):
            self.assertIn("詳細の取得に失敗", run(server._get_typhoon("")))


if __name__ == "__main__":
    unittest.main()
