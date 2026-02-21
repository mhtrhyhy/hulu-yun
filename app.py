from __future__ import annotations
import base64
import json
import math
import os
import random
import sqlite3
import time
from dataclasses import dataclass
from typing import List, Optional

import streamlit as st

# -------------------------
# 基本設定
# -------------------------
END_POS = 47
DB_PATH = "rooms.sqlite3"

PAIR = {
    1: 10, 10: 1, 2: 14, 14: 2, 3: 12, 12: 3, 4: 15, 15: 4, 5: 20, 20: 5,
    6: 18, 18: 6, 7: 23, 23: 7, 8: 22, 22: 8, 9: 37, 37: 9,
    11: 34, 34: 11, 13: 28, 28: 13, 16: 42, 42: 16, 17: 26, 26: 17,
    19: 30, 30: 19, 21: 32, 32: 21, 24: 35, 35: 24, 25: 46, 46: 25,
    27: 36, 36: 27, 29: 40, 40: 29, 31: 45, 45: 31, 33: 41, 41: 33,
    38: 43, 43: 38, 39: 44, 44: 39
}

TOKENS = ["🐼","🐸","🦊","🐯","🐵","🦄","🐙","🦁","🐰","🐲"]

# -------------------------
# 資料模型
# -------------------------
@dataclass
class Player:
    pid: str
    name: str
    token: str
    pos: int
    score: int

@dataclass
class RoomState:
    room: str
    players: List[Player]
    turn: int
    log: List[str]
    ended: bool


# -------------------------
# SQLite
# -------------------------
def db_init():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS rooms(
        room TEXT PRIMARY KEY,
        state_json TEXT
    )
    """)
    conn.commit()
    conn.close()

def room_save(state: RoomState):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO rooms(room, state_json) VALUES(?,?) "
        "ON CONFLICT(room) DO UPDATE SET state_json=excluded.state_json",
        (state.room, json.dumps(state, default=lambda o: o.__dict__, ensure_ascii=False))
    )
    conn.commit()
    conn.close()

def room_load(room: str) -> Optional[RoomState]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT state_json FROM rooms WHERE room=?", (room,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    d = json.loads(row[0])
    players = [Player(**p) for p in d["players"]]
    return RoomState(
        room=d["room"],
        players=players,
        turn=d["turn"],
        log=d["log"],
        ended=d["ended"]
    )

# -------------------------
# 遊戲邏輯
# -------------------------
def ensure_pid():
    if "pid" not in st.session_state:
        st.session_state.pid = base64.urlsafe_b64encode(os.urandom(6)).decode()
    return st.session_state.pid

def roll_dice():
    return random.randint(1,6) + random.randint(1,6)

def bounce(pos, steps):
    raw = pos + steps
    if raw <= END_POS:
        return raw
    return END_POS - (raw - END_POS)

def jump(pos):
    if pos in (0, END_POS):
        return pos
    return PAIR.get(pos, pos)

def occupant(players, pos):
    for p in players:
        if p.pos == pos:
            return p
    return None

def resolve_collision(state, mover, target):
    if target == 0:
        return True
    occ = occupant(state.players, target)
    if not occ or occ.pid == mover.pid:
        return True
    pair = PAIR.get(target)
    if not pair:
        return False
    occ2 = occupant(state.players, pair)
    if occ2 and occ2.pid != occ.pid:
        return False
    occ.pos = pair
    return True

# -------------------------
# 畫螺旋盤
# -------------------------
def spiral_xy(i, size=520):
    cx = cy = size/2
    t = i/END_POS
    angle = -math.pi/2 + 2*math.pi*2.6*t
    r = size*0.42*(1-t) + size*0.1*t
    return cx + r*math.cos(angle), cy + r*math.sin(angle)

def render_board(state):
    size=520
    elems=[]
    for i in range(END_POS+1):
        x,y=spiral_xy(i,size)
        elems.append(f'<text x="{x}" y="{y}" font-size="14" text-anchor="middle" dominant-baseline="middle">{i}</text>')
    for p in state.players:
        x,y=spiral_xy(p.pos,size)
        elems.append(f'<text x="{x}" y="{y}" font-size="22" text-anchor="middle" dominant-baseline="middle">{p.token}</text>')
    return f'<svg width="{size}" height="{size}">{"".join(elems)}</svg>'

# -------------------------
# UI
# -------------------------
st.set_page_config(layout="wide")
db_init()
pid = ensure_pid()

st.title("🎲 葫蘆運 Online 穩定核心版")

room = st.sidebar.text_input("房號","8888")
name = st.sidebar.text_input("暱稱",f"玩家{random.randint(1,99)}")
token = st.sidebar.selectbox("棋子",TOKENS)

if st.sidebar.button("建立房間"):
    state = RoomState(room,[Player(pid,name,token,0,0)],0,[],False)
    room_save(state)

if st.sidebar.button("加入房間"):
    state = room_load(room)
    if state and not any(p.pid==pid for p in state.players):
        state.players.append(Player(pid,name,token,0,0))
        room_save(state)

state = room_load(room)
if not state:
    st.stop()

col1,col2 = st.columns([1.2,0.8])

with col2:
    st.subheader("玩家")
    st.write([(p.name,p.pos,p.score) for p in state.players])
    if st.button("🔄 同步"):
        st.rerun()

with col1:
    st.markdown(render_board(state), unsafe_allow_html=True)

    if len(state.players)>=2 and state.players[0].pid==pid and not state.ended:
        if st.button("🎲 擲骰並走"):
            mover = state.players[state.turn % len(state.players)]
            steps = roll_dice()
            pos1 = bounce(mover.pos,steps)
            pos2 = jump(pos1)
            ok = resolve_collision(state,mover,pos2)
            if not ok:
                for p in state.players:
                    p.pos=0
                state.turn=0
            else:
                mover.pos=pos2
                state.turn+=1
            room_save(state)
            st.rerun()
