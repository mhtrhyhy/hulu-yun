from __future__ import annotations
import base64
import json
import math
import os
import random
import sqlite3
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import streamlit as st

# -------------------------
# CONFIG
# -------------------------
END_POS = 47
MIN_PLAYERS = 2
MAX_PLAYERS = 6
DB_PATH = "rooms.sqlite3"

PAIR: Dict[int, int] = {
    1: 10, 10: 1, 2: 14, 14: 2, 3: 12, 12: 3, 4: 15, 15: 4, 5: 20, 20: 5,
    6: 18, 18: 6, 7: 23, 23: 7, 8: 22, 22: 8, 9: 37, 37: 9, 11: 34, 34: 11,
    13: 28, 28: 13, 16: 42, 42: 16, 17: 26, 26: 17, 19: 30, 30: 19, 21: 32, 32: 21,
    24: 35, 35: 24, 25: 46, 46: 25, 27: 36, 36: 27, 29: 40, 40: 29, 31: 45, 45: 31,
    33: 41, 41: 33, 38: 43, 43: 38, 39: 44, 44: 39
}

SYMBOL_ICON = {
    0: "🏁", 47: "🧙‍♂️",
    1: "🐰", 2: "🫏", 3: "🫙", 4: "🧓", 5: "🐔", 6: "🐯",
    7: "🎭", 8: "🐟", 9: "💪", 11: "🧧", 13: "👴", 16: "🔔",
    17: "🧹", 19: "🧝‍♀️", 21: "🪵", 24: "🐦", 25: "🪙",
    27: "🥬", 29: "🦌", 31: "🐲", 33: "🐢", 38: "🐴", 39: "🌸",
}

TOKENS = ["🐼", "🐸", "🦊", "🐯", "🐵", "🦄", "🐙", "🦁", "🐰", "🐲"]


def icon_for_pos(i: int) -> str:
    if i in (0, END_POS):
        return SYMBOL_ICON[i]
    if i in PAIR:
        a = min(i, PAIR[i])
        return SYMBOL_ICON.get(a, "•")
    return "•"


# -------------------------
# MODELS
# -------------------------
@dataclass
class Player:
    pid: str
    name: str
    token: str
    pos: int = 0
    score: int = 0


@dataclass
class RoomState:
    room: str
    players: List[Player]
    turn: int = 0
    log: List[str] = None
    ended: bool = False
    winner_pid: Optional[str] = None
    draws: int = 0
    last_roll: Optional[Tuple[int, int, int]] = None  # d1,d2,sum
    updated_at: float = 0.0

    def __post_init__(self):
        if self.log is None:
            self.log = []


# -------------------------
# DB (SQLite)
# -------------------------
def db_init():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS rooms(
        room TEXT PRIMARY KEY,
        state_json TEXT NOT NULL,
        updated_at REAL NOT NULL
      )
    """)
    conn.commit()
    conn.close()


def serialize_state(state: RoomState) -> str:
    d = asdict(state)
    d["players"] = [asdict(p) for p in state.players]
    return json.dumps(d, ensure_ascii=False)


def deserialize_state(s: str) -> RoomState:
    d = json.loads(s)
    players = [Player(**p) for p in d["players"]]
    return RoomState(
        room=d["room"],
        players=players,
        turn=d.get("turn", 0),
        log=d.get("log", []),
        ended=d.get("ended", False),
        winner_pid=d.get("winner_pid"),
        draws=d.get("draws", 0),
        last_roll=tuple(d["last_roll"]) if d.get("last_roll") else None,
        updated_at=d.get("updated_at", 0.0),
    )


def room_load(room: str) -> Optional[RoomState]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT state_json FROM rooms WHERE room=?", (room,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return deserialize_state(row[0])


def room_save(state: RoomState) -> None:
    state.updated_at = time.time()
    payload = serialize_state(state)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO rooms(room, state_json, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(room) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at",
        (state.room, payload, state.updated_at),
    )
    conn.commit()
    conn.close()


# -------------------------
# GAME LOGIC
# -------------------------
def ensure_pid() -> str:
    if "pid" not in st.session_state:
        st.session_state.pid = base64.urlsafe_b64encode(os.urandom(9)).decode("ascii").rstrip("=")
    return st.session_state.pid


def roll_two_dice() -> Tuple[int, int, int]:
    d1 = random.randint(1, 6)
    d2 = random.randint(1, 6)
    return d1, d2, d1 + d2


def bounce_move(start_pos: int, steps: int) -> int:
    raw = start_pos + steps
    if raw <= END_POS:
        return raw
    exceed = raw - END_POS
    return END_POS - exceed


def jump_if_needed(pos: int) -> int:
    if pos in (0, END_POS):
        return pos
    return PAIR.get(pos, pos)


def find_player(state: RoomState, pid: str) -> Player:
    for p in state.players:
        if p.pid == pid:
            return p
    raise KeyError("player not found")


def occupant_pid_at(players: List[Player], pos: int) -> Optional[str]:
    for p in players:
        if p.pos == pos:
            return p.pid
    return None


def try_resolve_collision_no_chain(state: RoomState, mover_pid: str, target_pos: int) -> Tuple[bool, str]:
    # 起點可多人
    if target_pos == 0:
        return True, ""

    occ = occupant_pid_at(state.players, target_pos)
    if occ is None or occ == mover_pid:
        return True, ""

    # 兩邊都有人，第三人進入 -> 流局
    pair_pos = PAIR.get(target_pos)
    if pair_pos is None:
        return False, f"{target_pos} 無對應格，判定流局。"

    occ_at_pair = occupant_pid_at(state.players, pair_pos)
    if occ_at_pair is not None and occ_at_pair != occ:
        return False, f"目標格({target_pos})與對應格({pair_pos})皆有人，第三人進入 → 流局。"

    pushed = find_player(state, occ)
    pushed.pos = pair_pos
    mover = find_player(state, mover_pid)
    return True, f"碰撞：{mover.name} 到達 {target_pos}，把 {pushed.name} 推到對應格 {pair_pos}（三沖：不連鎖推）。"


def apply_scoring_after_move(state: RoomState, mover_pid: str) -> int:
    # 回傳 mover 的淨分變化（用來決定音效）
    deltas: Dict[str, int] = {}
    A = find_player(state, mover_pid)
    for B in state.players:
        if B.pid == mover_pid:
            continue
        diff = A.pos - B.pos
        if 1 <= diff <= 5:
            d = 10 * diff
            deltas[mover_pid] = deltas.get(mover_pid, 0) + d
            deltas[B.pid] = deltas.get(B.pid, 0) - d
            state.log.append(f"計分：{A.name} 在 {B.name} 前 {diff} 格 → {A.name}+{d}, {B.name}-{d}")
        elif -5 <= diff <= -1:
            d = 10 * abs(diff)
            deltas[mover_pid] = deltas.get(mover_pid, 0) - d
            deltas[B.pid] = deltas.get(B.pid, 0) + d
            state.log.append(f"計分：{A.name} 在 {B.name} 後 {abs(diff)} 格 → {A.name}-{d}, {B.name}+{d}")

    for p in state.players:
        if p.pid in deltas:
            p.score += deltas[p.pid]
    return deltas.get(mover_pid, 0)


def finalize_win(state: RoomState, winner_pid: str) -> None:
    winner = find_player(state, winner_pid)
    total = 0
    for p in state.players:
        if p.pid == winner_pid:
            continue
        p.score -= 100
        total += 100
    winner.score += total
    state.ended = True
    state.winner_pid = winner_pid
    state.log.append(f"終局：{winner.name} 抵達南極仙翁(47)。其他玩家各 -100，共 {total} 分加到 {winner.name}。")


def reset_positions_keep_scores(state: RoomState) -> None:
    for p in state.players:
        p.pos = 0
    state.turn = 0
    state.ended = False
    state.winner_pid = None
    state.draws += 1
    state.last_roll = None
    state.log.append(f"流局第 {state.draws} 次：全員回到起點，重新開始（分數保留）。")


# -------------------------
# SVG (spiral + minimap)
# -------------------------
def spiral_xy(i: int, size: int = 560) -> Tuple[float, float]:
    cx = cy = size / 2
    t = i / END_POS
    turns = 2.6
    angle = -math.pi / 2 + (2 * math.pi) * turns * t
    r0 = size * 0.44
    r1 = size * 0.09
    r = r0 * (1 - t) + r1 * t
    x = cx + r * math.cos(angle)
    y = cy + r * math.sin(angle)
    return x, y


def render_spiral_svg(state: RoomState, size: int = 560) -> str:
    elems = [f'<rect x="1" y="1" width="{size-2}" height="{size-2}" rx="18" fill="white" stroke="rgba(0,0,0,0.15)"/>' ]
    for i in range(END_POS + 1):
        x, y = spiral_xy(i, size=size)
        elems.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" opacity="0.22"/>')
        ico = icon_for_pos(i)
        fs = 16 if i not in (0, END_POS) else 18
        elems.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{fs}" text-anchor="middle" dominant-baseline="middle">{ico}</text>')

    start_stack = 0
    for p in state.players:
        x, y = spiral_xy(p.pos, size=size)
        if p.pos == 0:
            x += 18 * math.cos(start_stack * 1.1)
            y += 18 * math.sin(start_stack * 1.1)
            start_stack += 1
        elems.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="24" text-anchor="middle" dominant-baseline="middle">{p.token}</text>')

    return f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">' + "".join(elems) + f'<text x="{size/2:.1f}" y="30" font-size="16" text-anchor="middle" opacity="0.65">葫蘆運</text></svg>'


def render_minimap_svg(state: RoomState, size: int = 260) -> str:
    cx = cy = size / 2
    r = size * 0.36

    def ang(i: int) -> float:
        return -math.pi/2 + 2*math.pi*(i/(END_POS+1))

    dots, labels, tokens = [], [], []
    for i in range(END_POS + 1):
        a = ang(i)
        x = cx + r * math.cos(a)
        y = cy + r * math.sin(a)
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" opacity="0.22" />')
        if i in (0, END_POS) or i % 6 == 0:
            labels.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="9" text-anchor="middle" dominant-baseline="middle" opacity="0.55">{i}</text>')

    for p in state.players:
        a = ang(p.pos)
        x = cx + r * math.cos(a)
        y = cy + r * math.sin(a)
        tokens.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="18" text-anchor="middle" dominant-baseline="middle">{p.token}</text>')

    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">
      <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="rgba(0,0,0,0.18)" stroke-width="2"/>
      {''.join(dots)}
      {''.join(labels)}
      {''.join(tokens)}
      <text x="{cx}" y="{cy}" font-size="12" text-anchor="middle" dominant-baseline="middle" opacity="0.7">位置</text>
    </svg>
    """


# -------------------------
# App UI
# -------------------------
st.set_page_config(page_title="葫蘆運 Online", layout="wide")
db_init()

pid = ensure_pid()
st.title("🎲 葫蘆運（線上房間版：SQLite 同步更穩）")

with st.sidebar:
    st.header("房間")
    room = st.text_input("房號（大家輸入同一組）", value=st.session_state.get("room", "8888")).strip()
    name = st.text_input("你的暱稱", value=st.session_state.get("name", f"玩家{random.randint(1,99)}")).strip()
    token = st.selectbox("棋子", TOKENS, index=0)
    st.session_state.room = room
    st.session_state.name = name

    c1, c2 = st.columns(2)
    btn_create = c1.button("建立房間", type="primary", use_container_width=True)
    btn_join = c2.button("加入房間", use_container_width=True)

    st.divider()
    move_speed = st.slider("移動速度（秒/格）", 0.12, 0.70, 0.28, 0.02)
    st.caption("開始：至少 2 人加入後，主持人會看到「🎲 擲骰並走」按鈕。")

if not room:
    st.info("請先輸入房號。")
    st.stop()

state = room_load(room)

if btn_create:
    state = RoomState(room=room, players=[Player(pid=pid, name=name or "主持人", token=token)], log=[], turn=0)
    state.log.append(f"房間 {room} 建立：{state.players[0].name} 是主持人。")
    room_save(state)
    st.success("房間已建立，請叫朋友用同房號加入。")

if btn_join:
    if state is None:
        st.error("找不到房間，請先建立房間。")
        st.stop()
    if not any(p.pid == pid for p in state.players):
        if len(state.players) >= MAX_PLAYERS:
            st.error("房間已滿（最多 6 人）。")
            st.stop()
        used = {p.token for p in state.players}
        tk = token if token not in used else random.choice([t for t in TOKENS if t not in used] or TOKENS)
        nm = name or f"玩家{random.randint(1,99)}"
        state.players.append(Player(pid=pid, name=nm, token=tk))
        state.log.append(f"✅ {nm} 加入房間（{tk}）")
        room_save(state)
    st.success("加入成功！")

# reload fresh
state = room_load(room)
if state is None:
    st.info("尚未建立房間。")
    st.stop()

host_pid = state.players[0].pid
is_host = (pid == host_pid)

left, right = st.columns([1.25, 0.75], vertical_alignment="start")

with right:
    st.subheader("右上角小地圖")
    st.markdown(render_minimap_svg(state), unsafe_allow_html=True)
    st.subheader("玩家（小字）")
    st.dataframe([{"棋子": p.token, "名字": p.name, "格": p.pos, "分數": p.score} for p in state.players],
                 use_container_width=True, hide_index=True, height=220)
    st.button("🔄 同步一下", use_container_width=True, on_click=lambda: None)

with left:
    st.subheader("螺旋棋盤")
    st.markdown(render_spiral_svg(state), unsafe_allow_html=True)

    turn_player = state.players[state.turn % len(state.players)]
    st.write(f"房號：**{room}** ｜ 主持人：**{state.players[0].name}** ｜ 流局：**{state.draws}**")
    st.write(f"輪到：**{turn_player.name} {turn_player.token}**")

    if state.last_roll:
        d1, d2, ssum = state.last_roll
        st.info(f"上一次骰子：{d1}+{d2}={ssum}")

    if state.ended:
        winner = find_player(state, state.winner_pid).name if state.winner_pid else "未知"
        st.success(f"🏆 遊戲結束！勝者：**{winner}**")
    else:
        if not is_host:
            st.info("你不是主持人：等待主持人擲骰。你可以按右側「同步一下」或重新整理頁面。")
        else:
            if len(state.players) < MIN_PLAYERS:
                st.warning("至少 2 人加入後才能開始。")
            else:
                if st.button("🎲 擲骰並走（先出點數→慢慢移動）", type="primary", use_container_width=True):
                    state = room_load(room)  # latest
                    mover = state.players[state.turn % len(state.players)]
                    from_pos = mover.pos

                    d1, d2, ssum = roll_two_dice()
                    state.last_roll = (d1, d2, ssum)
                    state.log.append(f"🎲 {mover.name} 擲骰：{d1}+{d2}={ssum}")
                    room_save(state)

                    st.info(f"骰子：{d1}+{d2}={ssum}")
                    time.sleep(0.45)

                    pos1 = bounce_move(from_pos, ssum)
                    pos2 = jump_if_needed(pos1)

                    # visual-only animation
                    ph_board = st.empty()
                    ph_msg = st.empty()

                    step = 1 if pos1 >= from_pos else -1
                    for cur in range(from_pos, pos1 + step, step):
                        tmp = room_load(room)
                        for p in tmp.players:
                            if p.pid == mover.pid:
                                p.pos = cur
                        ph_board.markdown(render_spiral_svg(tmp), unsafe_allow_html=True)
                        ph_msg.info(f"{mover.name} 移動中… {cur}")
                        time.sleep(move_speed)

                    if pos2 != pos1:
                        ph_msg.warning(f"落在圖案格 {pos1} {icon_for_pos(pos1)} → 跳到 {pos2} {icon_for_pos(pos2)}")
                        time.sleep(0.35)

                    # apply to shared state
                    state = room_load(room)
                    mover = state.players[state.turn % len(state.players)]
                    mover_from = mover.pos

                    pos1 = bounce_move(mover_from, ssum)
                    state.log.append(f"移動：{mover.name} {mover_from}→{pos1}")
                    pos2 = jump_if_needed(pos1)
                    if pos2 != pos1:
                        state.log.append(f"跳躍：{pos1}→{pos2}")

                    ok, msg = try_resolve_collision_no_chain(state, mover.pid, pos2)
                    if not ok:
                        state.log.append(f"❌ {msg}")
                        reset_positions_keep_scores(state)
                        state.turn += 1
                        room_save(state)
                        st.rerun()
                    if msg:
                        state.log.append(msg)

                    mover.pos = pos2
                    net = apply_scoring_after_move(state, mover.pid)

                    # sound cue (simple)
                    if net != 0:
                        # minimalist: use emoji cue (cloud autoplay audio often blocked)
                        st.toast("🔔 得分變化" if net > 0 else "🔕 扣分變化")

                    if mover.pos == END_POS:
                        finalize_win(state, mover.pid)

                    state.turn += 1
                    room_save(state)
                    st.rerun()

    st.subheader("事件紀錄（最新 50）")
    st.write("\n".join((state.log or [])[-50:]) if state.log else "（尚無）")
