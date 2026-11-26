from ai_pool import build_prompt


def test_prediction_schema_has_no_fixed_home_score_and_includes_draw():
    prompt = build_prompt('Ev', 'Deplasman', {}, {}, {})
    schema = prompt.split('SADECE JSON:', 1)[1]
    assert '"score":"2-1"' not in schema
    assert 'EV_GOL-DEPLASMAN_GOL' in schema
    assert 'HOME, DRAW ve AWAY' in prompt
    assert 'beraberlik' in prompt.lower()
