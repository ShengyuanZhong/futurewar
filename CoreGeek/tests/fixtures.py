import json
from pathlib import Path
from app.config import Settings


def unit(uid, kind, x, y, **extra):
    result = {"id": uid, "roleType": kind, "pos": {"x": x, "y": y},
              "health": 1500 if kind == "station" else 220 if kind == "worker" else 200,
              "level": 1 if kind not in ("worker", "pioneer") else 0,
              "cooldown": 0, "attackRange": 0,
              "backPackCapability": 100 if kind == "worker" else 40 if kind == "pioneer" else 0,
              "backpack": []}
    result.update(extra)
    return result


def robot(uid, x, y, health=40, **extra):
    result = unit(uid, "smallRobot", x, y, health=health)
    result.update(targetTeam="challenger", abnormalState="")
    result.update(extra)
    return result


def request(round_no=1):
    raw = json.loads((Path(__file__).resolve().parents[2] / "request.txt").read_text(encoding="utf-8"))
    raw.update(roundNo=round_no, phaseTask="", llmResp="", lastCmdResult="", errors=[],
               worldNews={"officialNews": "", "folkLegends": ""}, lastRoundRoleActionResults={})
    raw["teamOur"]["roles"] = [unit(503, "station", 10, 24), unit(501, "worker", 8, 23),
                                   unit(502, "pioneer", 14, 13), unit(504, "worker", 12, 23)]
    raw["teamOur"]["goldNum"] = 75
    raw["teamEnemy"]["roles"] = []
    raw["robot"]["roles"] = []
    raw["mapInfo"]["zones"] = [
        {"neutralType": name, "pos": {"x": x, "y": y}}
        for name, x, y in (("vendor", 7, 23), ("weaponShop", 13, 23),
                           ("stone", 7, 22), ("iron", 6, 20), ("copper", 13, 22),
                           ("challengerTaskPoint1", 14, 14), ("challengerTaskPoint2", 17, 17),
                           ("challengerTaskPoint2", 16, 17))]
    for task in raw["teamOur"]["playerTasks"]:
        task["timeoutRounds"] = 12
    return raw


def layout_settings(**kwargs):
    # Synthetic coordinates used solely for exercising the configured-zone gate.
    return Settings(layouts={"challenger": {"verified": True, "source": "synthetic test fixture; not official geography",
        "weapons": [{"x": -1, "y": 0}, {"x": 0, "y": 1}, {"x": 2, "y": 0}],
        "walls": [{"x": -2, "y": -2}, {"x": 3, "y": -2}]}}, enable_news=False, **kwargs)
