"""No-token Poisson baseline; never mixed into AI consensus or AI rankings."""
from math import exp, factorial, isfinite


def predict(context):
    home = (context.get("home") or {}).get("last_5") or {}
    away = (context.get("away") or {}).get("last_5") or {}
    if any(len(form.get("matches", [])) < 3 for form in (home, away)):
        return None
    numbers = [home.get("avg_goals_for"), home.get("avg_goals_against"),
               away.get("avg_goals_for"), away.get("avg_goals_against")]
    if any(not isinstance(x, (int, float)) or not isfinite(x) or x < 0 for x in numbers):
        return None
    lh = max(.15, min(5., (numbers[0] + numbers[3]) / 2))
    la = max(.15, min(5., (numbers[2] + numbers[1]) / 2))
    rows = [(exp(-lh-la) * lh**h * la**a / factorial(h) / factorial(a), h, a)
            for h in range(11) for a in range(11)]
    _, h, a = max(rows)
    return {"score": f"{h}-{a}", "outcome": "HOME" if h > a else "AWAY" if h < a else "DRAW",
            "method": "poisson_form_v1", "expected_goals": [round(lh, 3), round(la, 3)],
            "limitations": "Küçük form örneklemi; rakip gücü ve kadro etkisi modellenmez."}
