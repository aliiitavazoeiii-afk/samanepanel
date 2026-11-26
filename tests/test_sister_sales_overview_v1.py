"""Regression coverage for unified read-only sister sales aggregation."""
from unittest.mock import patch

from daily_sales_service.sister_sales_overview_v1 import sales_overview


def _line(day,source,gross,fee,cost,packs=1,units=1,identifier="1"):
    return {"sale_date":day,"source":source,"gross":gross,"fees":fee,
            "cogs":cost,"packs":packs,"units":units,"sale_id":identifier}


def test_sums_channels_and_days_without_extra_entries():
    entries=[
        _line("2026-11-26","digikala",360000,90000,178000,2,2,"dk"),
        _line("2026-11-26","site",200000,0,120000,1,2,"site"),
        _line("2026-11-25","mold",500000,0,350000,1,1,"invoice"),
    ]
    with patch("daily_sales_service.sister_sales_overview_v1.sale_lines",return_value=entries) as sale_mock:
        result=sales_overview(None,"2026-11-25","2026-11-26")
    assert sale_mock.call_count==1
    assert result["total"]["gross"]==1060000
    assert result["total"]["fees"]==90000
    assert result["total"]["cogs_known"]==648000
    assert result["total"]["profit"]==322000
    assert result["total"]["orders"]==3
    assert result["total"]["packs"]==4
    assert result["total"]["units"]==5
    assert len(result["channels"])==3
    assert len(result["days"])==2
    assert len(result["day_channels"])==3
    assert result["day_channels"][0]["jalali"].count("/")==2


def test_unknown_cost_does_not_report_false_zero_profit():
    entries=[_line("2026-11-26","digikala",100000,25000,None)]
    with patch("daily_sales_service.sister_sales_overview_v1.sale_lines",return_value=entries):
        result=sales_overview(None,"2026-11-26","2026-11-26")
    assert result["total"]["profit"] is None
    assert result["total"]["unknown_cost_lines"]==1
    assert result["channels"][0]["profit"] is None
    assert result["days"][0]["profit"] is None


def test_zero_sales_and_channel_filter():
    with patch("daily_sales_service.sister_sales_overview_v1.sale_lines",return_value=[]) as call:
        result=sales_overview(None,"2026-11-26","2026-11-26","basalam")
    assert call.call_args.kwargs["channel"]=="basalam"
    assert result["total"]["gross"]==0
    assert result["total"]["profit"]==0
    assert result["day_channels"]==[]
