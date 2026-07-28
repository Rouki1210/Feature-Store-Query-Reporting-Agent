"""T1: word-boundary matching — token nguyên tử không lọt vào từ khác.

Bug cũ: 'earn' ⊂ 'learn', 'wo' ⊂ 'word', 'phone' ⊂ 'iphone' → refuse oan.
"""
from app.agent.contracts import IntentType, RefusalCode
from app.agent.router import RuleRouter

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
