from __future__ import annotations
import base64
import json
import math
import os
import random
import time
import threading
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import streamlit as st

# =========================
# Game constants
# =========================
END_POS = 47
MIN_PLAYERS = 2
MAX_PLAYERS = 6

PAIR: Dict[int, int] = {
    1: 10, 10: 1,      # 兔
    2: 14, 14: 2,      # 驢
    3: 12, 12: 3,      # 葫蘆
    4: 15, 15: 4,      # 乞丐
    5: 20, 20: 5,      # 雞
    6: 18, 18: 6,      # 虎
    7: 23, 23: 7,      # 賓
    8: 22, 22: 8,      # 鯉魚
    9: 37, 37: 9,      # 肥
    11: 34, 34: 11,    # 吉
    13: 28, 28: 13,    # 王桑
    16: 42, 42: 16,    # 鐘
    17: 26, 26: 17,    # 掃
    19: 30, 30: 19,    # 仙姑
    21: 32, 32: 21,    # 咬木
    24: 35, 35: 24,    # 鳥
    25: 46, 46: 25,    # 銅錢
    27: 36, 36: 27,    # 韭菜
    29: 40, 40: 29,    # 鹿
    31: 45, 45: 31,    # 龍
    33: 41, 41: 33,    # 龜
    38: 43, 43: 38,    # 馬
    39: 44, 44: 39,    # 花
}

# 圖案（你可以隨時換成更貼近年畫的圖示）
# 兩兩對應的兩格會顯示同一個 icon
SYMBOL_NAME = {
    0: "起點",
    47: "南極仙翁",
    1: "兔", 2: "驢", 3: "葫蘆", 4: "乞丐", 5: "雞", 6: "虎",
    7: "賓", 8: "鯉魚", 9: "肥", 11: "吉", 13: "王桑", 16: "鐘",
    17: "掃", 19: "仙姑", 21: "咬木", 24: "鳥", 25: "銅錢",
    27: "韭菜", 29: "鹿", 31: "龍", 33: "龜", 38: "馬", 39: "花",
}
SYMBOL_ICON = {
    0: "🏁",
    47: "🧙‍♂️",
    1: "🐰",
    2: "🫏",
    3: "🫙",
    4: "🧓",
    5: "🐔",
    6: "🐯",
    7: "🎭",
    8: "🐟",
    9: "💪",
    11: "🧧",
    13: "👴",
    16: "🔔",
    17: "🧹",
    19: "🧝‍♀️",
    21: "🪵",
    24: "🐦",
    25: "🪙",
    27: "🥬",
    29: "🦌",
    31: "🐲",
    33: "🐢",
    38: "🐴",
    39: "🌸",
}
def icon_for_pos(i: int) -> str:
    if i in (0, END_POS):
        return SYMBOL_ICON[i]
    # paired positions share the same icon/name: use the smaller index as "canonical"
    if i in PAIR:
        a = min(i, PAIR[i])
        return SYMBOL_ICON.get(a, "•")
    return "•"

# 可愛棋子（玩家選）
TOKENS = ["🐼", "🐸", "🦊", "🐯", "🐵", "🦄", "🐙", "🦁", "🐰", "🐲"]

# =========================
# Models
# =========================
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

# =========================
# In-memory "online" room store (Streamlit server memory)
# =========================
@st.cache_resource
def get_store():
    return {"rooms": {}, "lock": threading.Lock()}

def now_ts() -> float:
    return time.time()

def room_get(room_id: str) -> Optional[RoomState]:
    store = get_store()
    with store["lock"]:
        raw = store["rooms"].get(room_id)
        if raw is None:
            return None
        return deserialize_state(raw)

def room_set(state: RoomState) -> None:
    state.updated_at = now_ts()
    store = get_store()
    with store["lock"]:
        store["rooms"][state.room] = serialize_state(state)

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

# =========================
# Sound (beep)
# =========================
def beep_wav_base64(freq=880, ms=130, volume=0.25, sample_rate=22050) -> str:
    import struct
    n = int(sample_rate * ms / 1000)
    data = bytearray()
    for i in range(n):
        t = i / sample_rate
        v = int(volume * 32767 * math.sin(2 * math.pi * freq * t))
        data += struct.pack("<h", v)

    sub2 = len(data)
    chunk = 36 + sub2
    header = b"RIFF" + struct.pack("<I", chunk) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    dat = b"data" + struct.pack("<I", sub2)
    wav = header + fmt + dat + bytes(data)
    return base64.b64encode(wav).decode("ascii")

BEEP_POS = beep_wav_base64(freq=990)
BEEP_NEG = beep_wav_base64(freq=440)

def play_beep(base64_wav: str):
    st.components.v1.html(
        f"""
        <audio autoplay>
          <source src="data:audio/wav;base64,{base64_wav}" type="audio/wav">
        </audio>
        """,
        height=0,
    )

# =========================
# Game rules
# =========================
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
    """
    起點可多人。
    非起點：若落點有人 -> 推對方到對應格（只推一次，不連鎖）。
    若落點與其對應格都有人，第三人進入其中任一格 -> 流局重開。
    """
    if target_pos == 0:
        return True, ""

    occ = occupant_pid_at(state.players, target_pos)
    if occ is None or occ == mover_pid:
        return True, ""

    if target_pos == END_POS:
        return False, "終點已有玩家（理論上不該發生），判定流局。"

    pair_pos = PAIR.get(target_pos)
    if pair_pos is None:
        return False, f"{target_pos} 無對應格，推人無解，判定流局。"

    occ_at_pair = occupant_pid_at(state.players, pair_pos)
    if occ_at_pair is not None and occ_at_pair != occ:
        return False, f"目標格({target_pos})與對應格({pair_pos})皆有人，第三人進入 → 流局。"

    pushed = find_player(state, occ)
    pushed.pos = pair_pos
    mover = find_player(state, mover_pid)
    return True, f"碰撞：{mover.name} 到達 {target_pos}，把 {pushed.name} 推到對應格 {pair_pos}（三沖：不連鎖推）。"

def apply_scoring_after_move(state: RoomState, mover_pid: str) -> Dict[str, int]:
    """
    A 移動後：
    - A 在 B 前方 1~5 格：A +10..50, B -10..50
    - A 在 B 後方 1~5 格：A -10..50, B +10..50
    """
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
    return deltas

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

# =========================
# Spiral board rendering (SVG)
# =========================
def spiral_xy(i: int, size: int = 520) -> Tuple[float, float]:
    """
    螺旋：外圈(0) -> 中心(47)
    你可以調 turns / radii 讓它更像年畫
    """
    cx = cy = size / 2
    t = i / END_POS  # 0..1
    turns = 2.6  # 螺旋圈數（越大越繞）
    angle = -math.pi / 2 + (2 * math.pi) * turns * t
    r0 = size * 0.44
    r1 = size * 0.08
    r = r0 * (1 - t) + r1 * t
    x = cx + r * math.cos(angle)
    y = cy + r * math.sin(angle)
    return x, y

def render_spiral_svg(state: RoomState, size: int = 520, show_numbers: bool = False) -> str:
    # base path dots + icons
    elems = []
    # background frame
    elems.append(f'<rect x="1" y="1" width="{size-2}" height="{size-2}" rx="18" fill="white" stroke="rgba(0,0,0,0.15)"/>')

    for i in range(0, END_POS + 1):
        x, y = spiral_xy(i, size=size)
        # tiny dot
        elems.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" opacity="0.25"/>')
        # icon / label
        ico = icon_for_pos(i)
        fs = 16 if i not in (0, END_POS) else 18
        elems.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{fs}" text-anchor="middle" dominant-baseline="middle">{ico}</text>')
        if show_numbers and (i % 4 == 0 or i in (0, END_POS)):
            elems.append(f'<text x="{x+18:.1f}" y="{y-10:.1f}" font-size="10" opacity="0.55">{i}</text>')

    # players tokens
    # 起點可多人 -> 稍微擺開
    start_stack = 0
    for p in state.players:
        x, y = spiral_xy(p.pos, size=size)
        if p.pos == 0:
            x += 18 * math.cos(start_stack * 1.1)
            y += 18 * math.sin(start_stack * 1.1)
            start_stack += 1
        elems.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="24" text-anchor="middle" dominant-baseline="middle">{p.token}</text>')

    title = "葫蘆運"
    return f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">' + "".join(elems) + f'<text x="{size/2:.1f}" y="30" font-size="16" text-anchor="middle" opacity="0.65">{title}</text></svg>'

def render_minimap_svg(state: RoomState, size: int = 260) -> str:
    # 簡化版：圓形小地圖（右上角看位置）
    cx = cy = size / 2
    r = size * 0.36
    dots = []
    labels = []
    tokens = []

    def ang(i: int) -> float:
        return -math.pi/2 + 2*math.pi*(i/(END_POS+1))

    for i in range(END_POS + 1):
        a = ang(i)
        x = cx + r * math.cos(a)
        y = cy + r * math.sin(a)
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" opacity="0.25" />')
        if i in (0, END_POS) or i % 6 == 0:
            labels.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="9" text-anchor="middle" dominant-baseline="middle" opacity="0.55">{i}</text>')

    for p in state.players:
        a = ang(p.pos)
        x = cx + r * math.cos(a)
        y = cy + r * math.sin(a)
        tokens.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="18" text-anchor="middle" dominant-baseline="middle">{p.token}</text>')

    svg = f"""
    <svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">
      <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="rgba(0,0,0,0.18)" stroke-width="2"/>
      {''.join(dots)}
      {''.join(labels)}
      {''.join(tokens)}
      <text x="{cx}" y="{cy}" font-size="12" text-anchor="middle" dominant-baseline="middle" opacity="0.7">位置</text>
    </svg>
    """
    return svg

# =========================
# UI helpers
# =========================
def ensure_pid() -> str:
    if "pid" not in st.session_state:
        st.session_state.pid = base64.urlsafe_b64encode(os.urandom(9)).decode("ascii").rstrip("=")
    return st.session_state.pid

def current_turn_player(state: RoomState) -> Player:
    return state.players[state.turn % len(state.players)]

def compact_players_table(state: RoomState):
    rows = []
    for p in state.players:
        rows.append({"棋子": p.token, "名字": p.name, "格": p.pos, "分數": p.score})
    st.dataframe(rows, use_container_width=True, hide_index=True, height=220)

def try_autorefresh(interval_ms: int = 1200):
    # 某些環境 st_autorefresh 可能不存在，這裡保守處理
    if hasattr(st, "autorefresh"):
        st.autorefresh(interval=interval_ms, key="auto_refresh_key")
    elif hasattr(st, "st_autorefresh"):
        st.st_autorefresh(interval=interval_ms, key="auto_refresh_key")

# =========================
# App
# =========================
st.set_page_config(page_title="葫蘆運 Online", layout="wide")
pid = ensure_pid()

st.title("🎲 葫蘆運（最終線上完整版：房間制 / 螺旋棋盤 / 圖案 / 音效 / 慢速移動）")

with st.sidebar:
    st.header("加入房間")
    room_id = st.text_input("房號（大家輸入同一組）", value=st.session_state.get("room_id", "8888")).strip()
    my_name = st.text_input("你的暱稱", value=st.session_state.get("my_name", f"玩家{random.randint(1,99)}")).strip()
    my_token = st.selectbox("選棋子", TOKENS, index=0)
    st.session_state.room_id = room_id
    st.session_state.my_name = my_name

    c1, c2 = st.columns(2)
    create_room = c1.button("建立房間", type="primary", use_container_width=True)
    join_room = c2.button("加入房間", use_container_width=True)

    st.divider()
    st.subheader("同步/速度")
    auto_sync = st.toggle("自動同步（建議開）", value=True)
    move_speed = st.slider("移動速度（秒/格）", 0.12, 0.70, 0.28, 0.02)
    show_numbers = st.toggle("棋盤顯示格號（小字）", value=False)

    st.caption("規則：起點可多人；推人不連鎖（符合三沖）；若一格與對應格都有人，第三人進入 → 流局重開。")

if not room_id:
    st.info("請先在左側輸入房號。")
    st.stop()

# Load/create room
state = room_get(room_id)

if create_room:
    # create fresh room with host = creator
    state = RoomState(room=room_id, players=[Player(pid=pid, name=my_name or "主持人", token=my_token)], log=[], turn=0)
    state.log.append(f"房間 {room_id} 建立：{state.players[0].name} 是主持人。")
    room_set(state)
    st.success("房間已建立！把房號告訴朋友加入。")

if join_room:
    if state is None:
        st.error("找不到房間，請先建立。")
        st.stop()
    if not any(p.pid == pid for p in state.players):
        if len(state.players) >= MAX_PLAYERS:
            st.error("房間已滿（最多 6 人）。")
            st.stop()
        used = {p.token for p in state.players}
        token = my_token if my_token not in used else random.choice([t for t in TOKENS if t not in used] or TOKENS)
        nm = my_name or f"玩家{random.randint(1,99)}"
        state.players.append(Player(pid=pid, name=nm, token=token))
        state.log.append(f"✅ {nm} 加入房間（{token}）")
        room_set(state)
    st.success("加入成功！")

# Always reload for freshness
state = room_get(room_id)
if state is None:
    st.info("房間尚未建立：請按左側「建立房間」。")
    st.stop()

host_pid = state.players[0].pid
is_host = (pid == host_pid)

# Auto refresh for non-host (and host too)
if auto_sync:
    try_autorefresh(1200)

# Layout
left, right = st.columns([1.25, 0.75], vertical_alignment="start")

with right:
    st.subheader("右上角小地圖（看所有棋子位置）")
    st.markdown(render_minimap_svg(state), unsafe_allow_html=True)
    st.subheader("玩家（小字）")
    compact_players_table(state)

with left:
    st.subheader("螺旋棋盤（外圈 → 中心）")
    st.markdown(render_spiral_svg(state, size=560, show_numbers=show_numbers), unsafe_allow_html=True)

    st.caption(f"房號：**{room_id}**　｜　主持人：**{find_player(state, host_pid).name}**　｜　流局：**{state.draws}**")
    turn_player = current_turn_player(state)
    st.write(f"輪到：**{turn_player.name} {turn_player.token}**")

    if state.last_roll:
        d1, d2, ssum = state.last_roll
        st.info(f"上一次骰子：{d1} + {d2} = {ssum}")

    c1, c2, c3 = st.columns([1, 1, 1])
    manual_sync = c1.button("🔄 同步一下", use_container_width=True)
    reset_keep = c2.button("流局重開（分數保留）", use_container_width=True, disabled=not is_host)
    reset_all = c3.button("重新開新局（分數清零）", use_container_width=True, disabled=not is_host)

    if manual_sync:
        st.rerun()

    if reset_keep and is_host:
        state.log.append("主持人手動：流局重開。")
        reset_positions_keep_scores(state)
        room_set(state)
        st.rerun()

    if reset_all and is_host:
        # keep players but reset scores/positions/log
        players_copy = [Player(pid=p.pid, name=p.name, token=p.token, pos=0, score=0) for p in state.players]
        state = RoomState(room=room_id, players=players_copy, log=[f"主持人重開新局（分數清零）。"], turn=0)
        room_set(state)
        st.rerun()

    st.divider()

    if state.ended:
        winner = find_player(state, state.winner_pid).name if state.winner_pid else "未知"
        st.success(f"🏆 遊戲結束！勝者：**{winner}**")
    else:
        if not is_host:
            st.info("你不是主持人：等待主持人按「擲骰並走」。你可開自動同步或按同步。")
        else:
            if len(state.players) < MIN_PLAYERS:
                st.warning("至少 2 人才能開始。")
            else:
                if st.button("🎲 擲骰並走（先出點數 → 慢慢移動）", type="primary", use_container_width=True):
                    # Reload latest right before action
                    state = room_get(room_id)
                    if state is None:
                        st.error("房間讀取失敗。")
                        st.stop()

                    mover = current_turn_player(state)
                    from_pos = mover.pos

                    # 1) roll and show
                    d1, d2, ssum = roll_two_dice()
                    state.last_roll = (d1, d2, ssum)
                    state.log.append(f"🎲 {mover.name} 擲骰：{d1}+{d2}={ssum}")
                    room_set(state)

                    st.info(f"骰子：{d1} + {d2} = {ssum}")
                    time.sleep(0.55)

                    # 2) compute destination (bounce, then possible jump)
                    pos1 = bounce_move(from_pos, ssum)
                    pos2 = jump_if_needed(pos1)

                    # 3) UI-only slow move animation to pos1
                    ph_board = st.empty()
                    ph_msg = st.empty()

                    def render_temp(temp_pos: int, msg: str):
                        # render temporary position (host only)
                        tmp = room_get(room_id)
                        if tmp is None:
                            return
                        for p in tmp.players:
                            if p.pid == mover.pid:
                                p.pos = temp_pos
                        ph_board.markdown(render_spiral_svg(tmp, size=560, show_numbers=show_numbers), unsafe_allow_html=True)
                        ph_msg.info(msg)

                    step = 1 if pos1 >= from_pos else -1
                    for cur in range(from_pos, pos1 + step, step):
                        render_temp(cur, f"{mover.name} 移動中… {cur}")
                        time.sleep(move_speed)

                    if pos2 != pos1:
                        ph_msg.warning(f"落在圖案格 {pos1} {icon_for_pos(pos1)} → 跳到對應格 {pos2} {icon_for_pos(pos2)}")
                        time.sleep(0.45)

                    # 4) apply official move to shared state
                    state = room_get(room_id)
                    if state is None:
                        st.error("房間讀取失敗。")
                        st.stop()
                    mover = current_turn_player(state)
                    mover_from = mover.pos

                    # must match the displayed roll
                    pos1 = bounce_move(mover_from, ssum)
                    state.log.append(f"移動：{mover.name} {mover_from}→{pos1}（超過47反彈）")
                    pos2 = jump_if_needed(pos1)
                    if pos2 != pos1:
                        state.log.append(f"跳躍：{pos1}→{pos2}")

                    ok, msg = try_resolve_collision_no_chain(state, mover.pid, pos2)
                    if not ok:
                        state.log.append(f"❌ {msg}")
                        reset_positions_keep_scores(state)
                        state.turn += 1
                        room_set(state)
                        st.rerun()

                    if msg:
                        state.log.append(msg)

                    mover.pos = pos2

                    deltas = apply_scoring_after_move(state, mover.pid)
                    # sound cue
                    if deltas:
                        net = deltas.get(mover.pid, 0)
                        play_beep(BEEP_POS if net >= 0 else BEEP_NEG)

                    if mover.pos == END_POS:
                        finalize_win(state, mover.pid)

                    state.turn += 1
                    room_set(state)
                    st.rerun()

    st.subheader("事件紀錄（最新 50 條）")
    logs = (state.log or [])[-50:]
    st.write("\n".join(logs) if logs else "（尚無紀錄）")

with st.expander("圖案對應表（你定義的）"):
    lines = []
    lines.append("起點(0)")
    # list canonical pairs once
    seen = set()
    for a, b in sorted((min(k, v), max(k, v)) for k, v in PAIR.items() if k < v):
        if (a, b) in seen:
            continue
        seen.add((a, b))
        nm = SYMBOL_NAME.get(a, "")
        ico = SYMBOL_ICON.get(a, "")
        lines.append(f"{ico} {nm} ({a}) ↔ ({b})")
    lines.append("南極仙翁(47)=終點")
    st.text("\n".join(lines))
