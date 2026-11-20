"""命令列：挑哪幾家店。"""

from softgoods.cli import build_parser, pick_sites
from softgoods.models import SiteConfig


def _sites():
    return {
        "lampclub": SiteConfig(site_id="lampclub", name="燈迷", base_url="https://l.test", baseline=True),
        "a": SiteConfig(site_id="a", name="A", base_url="https://a.test"),
        "b": SiteConfig(site_id="b", name="B", base_url="https://b.test"),
    }


def test_several_stores_at_once():
    args = build_parser().parse_args(["crawl", "a", "b"])
    assert [s.site_id for s in pick_sites(_sites(), args.site)] == ["a", "b"]


def test_all_leaves_out_the_baseline():
    # lampclub 現在只拿來對照「抓齊了沒」；更新全部不要再去抓它（不靠它，也省它的伺服器）
    args = build_parser().parse_args(["crawl", "all"])
    assert [s.site_id for s in pick_sites(_sites(), args.site)] == ["a", "b"]


def test_the_baseline_can_still_be_crawled_by_name():
    args = build_parser().parse_args(["crawl", "lampclub"])
    assert [s.site_id for s in pick_sites(_sites(), args.site)] == ["lampclub"]


def test_the_same_store_twice_runs_once():
    # 同一家跑兩個工人，會超過它的速度限制（Codex 審查 2026-11-20）
    args = build_parser().parse_args(["crawl", "a", "b", "a"])
    assert [s.site_id for s in pick_sites(_sites(), args.site)] == ["a", "b"]


def test_fresh_flag():
    assert build_parser().parse_args(["crawl", "all", "--fresh"]).fresh is True
    assert build_parser().parse_args(["crawl", "all"]).fresh is False
