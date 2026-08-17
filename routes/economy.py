import time
from flask import Blueprint, jsonify, request
from db import db
from auth import require_auth, current_user

bp = Blueprint("economy", __name__, url_prefix="/api/economy")

FREE_COINS = 100_000
COOLDOWN_MS = 30 * 60 * 1000  # 30 minutes

@bp.get("/balance")
@require_auth
def balance():
    user = current_user()
    return jsonify(coins=user["coins"])

@bp.post("/free")
@require_auth
def free_coins():
    user = current_user()
    now = int(time.time() * 1000)
    last = user["last_free_claim"] or 0
    wait_ms = COOLDOWN_MS - (now - last)
    if wait_ms > 0:
        wait_s = int(wait_ms / 1000)
        mins = wait_s // 60
        secs = wait_s % 60
        return jsonify(error=f"Cooldown active. Try again in {mins}m {secs}s."), 429
    with db() as conn:
        conn.execute(
            "UPDATE users SET coins=coins+?, last_free_claim=? WHERE id=?",
            (FREE_COINS, now, user["id"])
        )
    return jsonify(ok=True, coins_added=FREE_COINS)

@bp.post("/gamble")
@require_auth
def gamble():
    import random
    user = current_user()
    data = request.get_json(silent=True) or {}
    game = data.get("game")  # slots | coinflip | blackjack | roulette | dice
    bet = int(data.get("bet", 0))

    if bet <= 0:
        return jsonify(error="Bet must be greater than 0."), 400
    if bet > user["coins"]:
        return jsonify(error="You don't have enough coins."), 400

    result = 0
    detail = {}

    if game == "slots":
        symbols = ["🍒","🍋","🍊","🍇","⭐","💎"]
        weights = [30, 25, 20, 15, 7, 3]
        reels = random.choices(symbols, weights=weights, k=3)
        detail["reels"] = reels
        if reels[0] == reels[1] == reels[2]:
            mult = {"💎": 50, "⭐": 20, "🍇": 10, "🍊": 5, "🍋": 3, "🍒": 2}.get(reels[0], 2)
            result = bet * mult - bet
            detail["win"] = True
            detail["multiplier"] = mult
        elif reels[0] == reels[1] or reels[1] == reels[2]:
            result = int(bet * 0.5) - bet
            detail["win"] = False
            detail["partial"] = True
        else:
            result = -bet
            detail["win"] = False

    elif game == "coinflip":
        choice = data.get("choice", "heads")
        flip = random.choice(["heads", "tails"])
        detail["flip"] = flip
        detail["choice"] = choice
        result = bet if flip == choice else -bet
        detail["win"] = result > 0

    elif game == "blackjack":
        # Quick serverside blackjack resolution
        def draw(): return min(random.randint(1, 13), 10)
        def hand_val(cards):
            val = sum(cards)
            if 1 in cards and val + 10 <= 21: val += 10
            return val
        player = [draw(), draw()]
        dealer = [draw(), draw()]
        # Player strategy: hit under 17
        while hand_val(player) < 17:
            player.append(draw())
        while hand_val(dealer) < 17:
            dealer.append(draw())
        pv, dv = hand_val(player), hand_val(dealer)
        detail["player_hand"] = player
        detail["dealer_hand"] = dealer
        detail["player_val"] = pv
        detail["dealer_val"] = dv
        if pv > 21:
            result = -bet; detail["win"] = False; detail["reason"] = "bust"
        elif dv > 21 or pv > dv:
            result = bet; detail["win"] = True
        elif pv == dv:
            result = 0; detail["win"] = None; detail["reason"] = "push"
        else:
            result = -bet; detail["win"] = False

    elif game == "roulette":
        pick = data.get("pick", "red")  # red|black|green|0-36
        spin = random.randint(0, 36)
        reds = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
        detail["spin"] = spin
        detail["pick"] = pick
        if pick == "green":
            win = spin == 0
            mult = 35
        elif pick == "red":
            win = spin in reds
            mult = 2
        elif pick == "black":
            win = spin != 0 and spin not in reds
            mult = 2
        else:
            try:
                win = spin == int(pick)
                mult = 35
            except:
                win = False; mult = 1
        result = bet * (mult - 1) if win else -bet
        detail["win"] = win

    elif game == "dice":
        target = int(data.get("target", 7))  # guess sum of 2d6
        d1, d2 = random.randint(1,6), random.randint(1,6)
        roll = d1 + d2
        detail["dice"] = [d1, d2]
        detail["roll"] = roll
        detail["target"] = target
        if target == roll:
            # payout based on probability
            payouts = {2:35, 3:17, 4:11, 5:8, 6:6, 7:5, 8:6, 9:8, 10:11, 11:17, 12:35}
            mult = payouts.get(target, 5)
            result = bet * mult - bet
            detail["win"] = True
            detail["multiplier"] = mult
        else:
            result = -bet
            detail["win"] = False
    else:
        return jsonify(error="Unknown game."), 400

    new_coins = max(0, user["coins"] + result)
    with db() as conn:
        conn.execute("UPDATE users SET coins=? WHERE id=?", (new_coins, user["id"]))
        conn.execute(
            "INSERT INTO gambling_log (user_id, game, bet, result) VALUES (?,?,?,?)",
            (user["id"], game, bet, result)
        )

    return jsonify(ok=True, result=result, new_balance=new_coins, detail=detail)
