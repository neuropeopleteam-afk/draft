"""learn-v1 «Учитывать решения компании»: выключено по умолчанию, ограничено, объяснимо, откатывается выключением."""
from app.modules.matching import learn, ranking
from tests.test_day2_rules import H, employer
from tests.test_employer_matching import NEED, _seeded_need

W = ranking.WEIGHTS


def row(**kw):
    return {k: kw.get(k, 0.5) for k in learn.KEYS}


def test_adjust_bounded_and_needs_data():
    few = learn.adjust(W, [row()] * 2, [row()] * 5)
    assert few["status"] == "few" and few["after"] == W
    # компания одобряет сильных по ФСП и отклоняет без ФСП — вес ФСП растёт, сумма весов прежняя, сдвиг ограничен
    pos = [row(fsp=0.9)] * 40
    neg = [row(fsp=0.0)] * 40
    r = learn.adjust(W, pos, neg)
    assert r["status"] == "ok" and r["after"]["fsp"] > W["fsp"]
    assert abs(sum(r["after"].values()) - sum(W.values())) < 1e-3
    assert r["after"]["fsp"] <= W["fsp"] * (1 + learn.MAX_SHIFT) / (1 - 0.05) + 1e-6
    for k in learn.KEYS:
        assert W[k] * (1 - learn.MAX_SHIFT) * 0.9 <= r["after"][k] <= W[k] * (1 + learn.MAX_SHIFT) * 1.1 + 1e-9
    # без разницы между «плюсами» и «минусами» — веса прежние
    same = learn.adjust(W, [row()] * 5, [row()] * 5)
    assert all(abs(same["after"][k] - W[k]) < 1e-4 for k in learn.KEYS)


def test_end_to_end_off_by_default_on_explained_off_again(client):
    te = employer(client)
    need = _seeded_need(client, te, NEED)
    v1 = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(te)).json()
    assert v1["learning"] is None and v1["weights"] == W
    res = v1["results"]
    assert len(res) >= 8
    # одобряем кандидатов с бо́льшей силой ФСП, отклоняем с меньшей (по компонентам, которые видит HR)
    by_fsp = sorted(res, key=lambda r: -r["components"]["fsp"])
    for r in by_fsp[:4]:
        assert client.put(f"/api/employer/needs/{need['id']}/feedback", json={
            "version": 1, "ref": r["ref"], "verdict": "fit"}, headers=H(te)).status_code == 200
    for r in by_fsp[-4:]:
        assert client.put(f"/api/employer/needs/{need['id']}/feedback", json={
            "version": 1, "ref": r["ref"], "verdict": "unfit", "reason": "other"}, headers=H(te)).status_code == 200
    on = client.post(f"/api/employer/needs/{need['id']}/selections", json={
        "parent_version": 1, "filters": {"learn_from_company": True}}, headers=H(te))
    assert on.status_code == 201, on.text
    on = on.json()
    lr = on["learning"]
    assert lr["status"] == "ok" and lr["decisions"]["plus"] == 4 and lr["decisions"]["minus"] == 4
    assert lr["weights_after"]["fsp"] >= W["fsp"] and on["weights"] == lr["weights_after"]
    assert "вес «достижения ФСП»" in lr["text"] or "заметной разницы нет" in lr["text"]
    off = client.post(f"/api/employer/needs/{need['id']}/selections", json={
        "parent_version": 2, "filters": {}}, headers=H(te)).json()
    assert off["learning"] is None and off["weights"] == W
