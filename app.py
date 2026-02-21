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
    last_roll: Optional[Tuple[int, int, int]] = None

    def __post_init__(self):
        if self.log is None:
            self.log = []


# -------------------------
# DB
# -------------------------
def db_init():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS rooms(
        room TEXT PRIMARY KEY,
        state_json TEXT NOT NULL
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
    return RoomState(**{k: d[k] for k in d if k != "players"}, players=players)


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
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO rooms(room, state_json) VALUES(?,?) "
        "ON CONFLICT(room) DO UPDATE SET state_json=excluded.state_json",
        (state.room, serialize_state(state)),
    )
    conn.commit()
    conn.close()


# -------------------------
# GAME LOGIC
# -------------------------
def ensure_pid():
    if "pid" not in st.session_state:
        st.session_state.pid = base64.urlsafe_b64encode(os.urandom(9)).decode()
    return st.session_state.pid


def roll_two_dice():
    d1 = random.randint(1, 6)
    d2 = random.randint(1, 6)
    return d1, d2, d1 + d2


def bounce_move(pos, steps):
    raw = pos + steps
    if raw <= END_POS:
        return raw
    return END_POS - (raw - END_POS)


def jump_if_needed(pos):
    if pos in (0, END_POS):
        return pos
    return PAIR.get(pos, pos)


def find_player(state, pid):
    return next(p for p in state.players if p.pid == pid)


def occupant_pid_at(players, pos):
    for p in players:
        if p.pos == pos:
            return p.pid
    return None


def try_resolve_collision_no_chain(state, mover_pid, target_pos):
    if target_pos == 0:
        return True, ""

    occ = occupant_pid_at(state.players, target_pos)
    if occ is None or occ == mover_pid:
        return True, ""

    pair_pos = PAIR.get(target_pos)
    if pair_pos is None:
        return False, "無對應格，流局。"

    occ_at_pair = occupant_pid_at(state.players, pair_pos)
    if occ_at_pair is not None and occ_at_pair != occ:
        return False, "兩格皆有人，流局。"

    find_player(state, occ).pos = pair_pos
    return True, "推人成功（三沖不連鎖）"


# -------------------------
# SVG
# -------------------------
def spiral_xy(i, size=560):
    cx = cy = size / 2
    t = i / END_POS
    angle = -math.pi/2 + 2*math.pi*2.6*t
    r = size*0.44*(1-t) + size*0.09*t
    return cx + r*math.cos(angle), cy + r*math.sin(angle)


def render_board(state):
    size = 560
    elems = []
    for i in range(END_POS+1):
        x,y = spiral_xy(i,size)
        elems.append(f'<text x="{x}" y="{y}" font-size="16" text-anchor="middle" dominant-baseline="middle">{icon_for_pos(i)}</text>')
    for p in state.players:
        x,y = spiral_xy(p.pos,size)
        elems.append(f'<text x="{x}" y="{y}" font-size="24" text-anchor="middle" dominant-baseline="middle">{p.token}</text>')
    return f'<svg width="{size}" height="{size}">{"".join(elems)}</svg>'


# -------------------------
# UI
# -------------------------
st.set_page_config(page_title="葫蘆運 Online", layout="wide")
db_init()

pid = ensure_pid()
st.title("🎲 葫蘆運 Online（穩定版）")

room = st.sidebar.text_input("房號", "8888")
name = st.sidebar.text_input("暱稱", f"玩家{random.randint(1,99)}")
token = st.sidebar.selectbox("棋子", TOKENS)

if st.sidebar.button("建立房間"):
    state = RoomState(room=room, players=[Player(pid,name,token)])
    room_save(state)

if st.sidebar.button("加入房間"):
    state = room_load(room)
    if state and not any(p.pid==pid for p in state.players):
        state.players.append(Player(pid,name,token))
        room_save(state)

state = room_load(room)
if not state:
    st.stop()

left,right = st.columns([1.25,0.75])

with right:
    st.subheader("玩家")
    st.write([(p.name,p.pos,p.score) for p in state.players])

with left:
    st.markdown(render_board(state), unsafe_allow_html=True)

    if len(state.players)>=2 and state.players[0].pid==pid:
        if st.button("🎲 擲骰並走"):
            mover = state.players[state.turn%len(state.players)]
            d1,d2,steps = roll_two_dice()
            pos1 = bounce_move(mover.pos,steps)
            pos2 = jump_if_needed(pos1)
            ok,_ = try_resolve_collision_no_chain(state,mover.pid,pos2)
            if not ok:
                for p in state.players:
                    p.pos=0
                state.turn=0
            else:
                mover.pos=pos2
                state.turn+=1
            room_save(state)
            st.rerun()
