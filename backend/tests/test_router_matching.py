"""T1: word-boundary matching — token nguyên tử không lọt vào từ khác.

Bug cũ: 'earn' ⊂ 'learn', 'wo' ⊂ 'word', 'phone' ⊂ 'iphone' → refuse oan.
"""
from app.agent.contracts import IntentType, RefusalCode
from app.agent.breakdown import BreakdownPlanner
from app.agent.router import RuleRouter
import pytest

R = RuleRouter()


def _decide(q):
    return R.route(q)[1]


# --- False-positive cũ: KHÔNG được refuse/clarify sai vì substring ---
def test_learn_not_refused_as_cross():
    d = _decide("How many customers learn to use the app")
    assert d.refusal_code != RefusalCode.cross_pnl

def test_burnout_not_refused_as_cross():
    d = _decide("customer burnout rate report")
    assert d.refusal_code != RefusalCode.cross_pnl

def test_iphone_not_refused_as_pii():
    d = _decide("Khách hàng mua iphone tháng này")
    assert d.refusal_code != RefusalCode.raw_or_pii
    assert d.intent != IntentType.out_of_scope

def test_word_not_flagged_needs_review():
    d = _decide("báo cáo word count theo tháng")
    assert d.refusal_code != RefusalCode.needs_review


# --- True-positive: vẫn phải fire đúng ---
def test_earn_still_refused():
    assert _decide("Khách earn điểm ở GSM").refusal_code == RefusalCode.cross_pnl

def test_burn_still_refused():
    assert _decide("khách burn điểm nhiều nhất").refusal_code == RefusalCode.cross_pnl

def test_raw_still_refused():
    assert _decide("cho tôi raw customers").refusal_code == RefusalCode.raw_or_pii

def test_phone_still_refused():
    assert _decide("số điện thoại của khách VIP").refusal_code == RefusalCode.raw_or_pii

def test_nvso_still_needs_review():
    assert _decide("đếm nvso completed l12m").refusal_code == RefusalCode.needs_review

def test_owner_routes_to_vinfast():
    d = _decide("Đã có bao nhiêu khách nhận xe trong tháng trước")
    assert d.intent != IntentType.out_of_scope
    assert d.business_unit == "VINFAST"

def test_window_compare_intent_via_vs():
    d = _decide("GSM số chuyến l1m vs l3m")
    assert d.intent == IntentType.window_compare


def test_per_customer_list_does_not_trigger_breakdown_clarification():
    assert not BreakdownPlanner().needs_dimension_choice(
        "Mức chi tiêu GSM gần đây đang thay đổi thế nào theo từng khách", []
    )


# --- T2: lọc câu lạc đề (off-domain) → out_of_scope, không clarify BU ---
def test_weather_is_out_of_scope():
    d = _decide("thời tiết hôm nay thế nào")
    assert d.intent == IntentType.out_of_scope
    assert d.refusal_code == RefusalCode.irrelevant

def test_math_is_out_of_scope():
    d = _decide("1 cộng 1 bằng mấy")
    assert d.intent == IntentType.out_of_scope

def test_chitchat_is_out_of_scope():
    d = _decide("kể cho tôi một câu chuyện cười")
    assert d.intent == IntentType.out_of_scope

def test_in_domain_no_bu_still_clarifies():
    # có tín hiệu domain ("chi tiêu") nhưng chưa rõ BU → clarify, KHÔNG out_of_scope
    d = _decide("tổng chi tiêu của khách")
    assert d.intent != IntentType.out_of_scope

def test_valid_bu_question_not_filtered():
    d = _decide("GSM có bao nhiêu chuyến hoàn thành l1m")
    assert d.intent != IntentType.out_of_scope
    assert d.business_unit == "GSM"


@pytest.mark.parametrize("question, business_unit", [
    ("Số giao dịch GSM không hoàn thành trong 1 tháng", "GSM"),
    ("Số giao dịch VinFast chưa hoàn thành trong 1 tháng", "VINFAST"),
])
def test_unfinished_status_keeps_business_unit_and_only_requests_canceled(question, business_unit):
    d = _decide(question)
    assert d.intent == IntentType.clarify
    assert d.business_unit == business_unit
    assert d.known_slots == {"business_unit": business_unit}
    assert d.missing_slots == ["order_status"]
    assert "đã hủy" in (d.clarifying_question or "").lower()
    assert "bàn giao" not in (d.clarifying_question or "").lower()


def test_unfinished_cross_bu_is_not_silently_merged():
    d = _decide("Số giao dịch GSM và VinFast không hoàn thành trong 1 tháng")
    assert d.intent == IntentType.out_of_scope


@pytest.mark.parametrize("question, intent", [
    ("Ghép mọi snapshot GSM với mọi snapshot VinFast theo customer_id", IntentType.out_of_scope),
    ("Ghép GSM, VinFast và bảng khách hàng để xem chi tiêu", IntentType.out_of_scope),
    ("Bao nhiêu khách đã trả xe VinFast", IntentType.out_of_scope),
    ("Tháng sau dự đoán bao nhiêu khách sẽ nhận xe VinFast", IntentType.out_of_scope),
    ("Bao nhiêu khách đã đặt xe VinFast nhưng chưa hoàn tất đơn", IntentType.clarify),
])
def test_router_handles_eval_guardrail_cases(question, intent):
    assert _decide(question).intent == intent
