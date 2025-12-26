import flet as ft
import sqlite3
import requests
import bcrypt
import os
import re
import threading
import time
from datetime import datetime

# ================= CONFIG =================
API_KEY = os.environ.get("FOOTBALL_API_KEY", "4b281685a4934c939b278db91318f62b")
HEADERS = {"X-Auth-Token": API_KEY}
BASE_URL = "https://api.football-data.org/v4"

MAX_PLAYERS = 12
SESSION_FILE = "session.txt"
UPDATE_INTERVAL = 300

PRIMARY = "#00d4ff"
SECONDARY = "#7c3aed"
SUCCESS = "#10b981"
DANGER = "#ef4444"
CARD_BG = "#1a1f3a"

# ================= DATABASE =================
conn = sqlite3.connect("serie_a_predictor.db", check_same_thread=False)
cur = conn.cursor()

cur.executescript("""
CREATE TABLE IF NOT EXISTS users(
    email TEXT PRIMARY KEY,
    password TEXT,
    team TEXT,
    credits INTEGER
);

CREATE TABLE IF NOT EXISTS leagues(
    name TEXT PRIMARY KEY,
    password TEXT
);

CREATE TABLE IF NOT EXISTS standings(
    email TEXT,
    league TEXT,
    points INTEGER DEFAULT 0,
    PRIMARY KEY(email, league)
);

CREATE TABLE IF NOT EXISTS bets(
    email TEXT,
    league TEXT,
    match_id INTEGER,
    winner TEXT,
    result TEXT,
    amount INTEGER DEFAULT 0,
    evaluated INTEGER DEFAULT 0
);
""")

conn.commit()

# ================= API =================
def get_matches(status="SCHEDULED"):
    try:
        r = requests.get(
            f"{BASE_URL}/competitions/SA/matches?status={status}",
            headers=HEADERS,
            timeout=5
        )
        r.raise_for_status()
        return r.json().get("matches", [])
    except requests.RequestException as e:
        print("Errore API:", e)
        return []

# ================= EVALUATION =================
def evaluate_matches():
    finished = get_matches("FINISHED")
    updated = 0
    
    for m in finished:
        mid = m["id"]
        h = m["score"]["fullTime"]["home"]
        a = m["score"]["fullTime"]["away"]
        result = "1" if h > a else "2" if a > h else "X"
        score = f"{h}-{a}"

        cur.execute("""
            SELECT rowid,email,league,winner,result,amount
            FROM bets
            WHERE match_id=? AND evaluated=0
        """, (mid,))

        for rid, email, league, w, r, amount in cur.fetchall():
            if w == result:
                gain = amount
                if r == score:
                    gain *= 2
            else:
                gain = -amount * 2

            points = 0
            if w == result:
                points = 3
                if r == score:
                    points += 2

            try:
                cur.execute("UPDATE users SET credits=credits + ? WHERE email=?", (gain, email))
                cur.execute("INSERT OR IGNORE INTO standings(email, league, points) VALUES(?,?,0)", (email, league))
                cur.execute("UPDATE standings SET points=points+? WHERE email=? AND league=?", (points, email, league))
                cur.execute("UPDATE bets SET evaluated=1 WHERE rowid=?", (rid,))
                updated += 1
            except Exception as e:
                print(f"Errore valutazione: {e}")
                
    conn.commit()
    return updated

# ================= SESSION =================
def save_session(email, league):
    with open(SESSION_FILE, "w") as f:
        f.write(f"{email}\n{league}")

def load_session():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as f:
            lines = f.read().splitlines()
            if len(lines) == 2:
                return lines[0], lines[1]
    return None, None

def clear_session():
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)

# ================= APP =================
user_logged = None
current_league = None
auto_update_thread = None
stop_update = False

def main(page: ft.Page):
    global user_logged, current_league, auto_update_thread, stop_update
    
    page.title = "⚽ Serie A Predictor"
    page.theme_mode = ft.ThemeMode.DARK
    page.window_width = 450
    page.window_height = 850
    page.padding = 0
    page.bgcolor = "#0a0e27"
    
    evaluate_matches()
    saved_email, saved_league = load_session()

    def auto_update_loop():
        global stop_update
        while not stop_update:
            time.sleep(UPDATE_INTERVAL)
            if not stop_update:
                updated = evaluate_matches()
                if updated > 0:
                    print(f"✅ Aggiornate {updated} scommesse")

    def start_auto_update():
        global auto_update_thread, stop_update
        stop_update = False
        if auto_update_thread is None or not auto_update_thread.is_alive():
            auto_update_thread = threading.Thread(target=auto_update_loop, daemon=True)
            auto_update_thread.start()

    def stop_auto_update():
        global stop_update
        stop_update = True

    def show_snackbar(message, color=SUCCESS):
        page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color="white", weight="bold"),
            bgcolor=color,
            duration=3000
        )
        page.snack_bar.open = True
        page.update()

    def login_view():
        page.clean()
        
        email = ft.TextField(
            label="Email",
            prefix_icon="email",
            border_radius=10,
            bgcolor=CARD_BG,
            border_color=PRIMARY
        )
        pwd = ft.TextField(
            label="Password",
            prefix_icon="lock",
            password=True,
            can_reveal_password=True,
            border_radius=10,
            bgcolor=CARD_BG,
            border_color=PRIMARY
        )
        team = ft.TextField(
            label="Nome Squadra (solo nuovi utenti)",
            prefix_icon="sports_soccer",
            border_radius=10,
            bgcolor=CARD_BG,
            border_color=PRIMARY
        )

        def enter(e):
            global user_logged
            
            if not email.value or not pwd.value:
                show_snackbar("⚠️ Compila email e password", DANGER)
                return
                
            cur.execute("SELECT password FROM users WHERE email=?", (email.value,))
            row = cur.fetchone()
            
            try:
                if row:
                    if not bcrypt.checkpw(pwd.value.encode(), row[0].encode()):
                        show_snackbar("❌ Password errata", DANGER)
                        return
                    show_snackbar("✅ Bentornato!", SUCCESS)
                else:
                    if not team.value:
                        show_snackbar("⚠️ Inserisci nome squadra", DANGER)
                        return
                    hashed = bcrypt.hashpw(pwd.value.encode(), bcrypt.gensalt()).decode()
                    cur.execute("INSERT INTO users VALUES(?,?,?,?)", (email.value, hashed, team.value, 1000))
                    conn.commit()
                    show_snackbar("🎉 Benvenuto! 1000 crediti!", SUCCESS)
            except Exception as ex:
                show_snackbar(f"❌ Errore: {ex}", DANGER)
                return
                
            user_logged = email.value
            go("league")

        page.add(
            ft.Container(
                content=ft.Column([
                    ft.Container(height=50),
                    ft.Container(
                        content=ft.Icon("sports_soccer", size=80, color=PRIMARY),
                        alignment=ft.alignment.center
                    ),
                    ft.Text(
                        "SERIE A PREDICTOR",
                        size=32,
                        weight="bold",
                        color=PRIMARY,
                        text_align="center"
                    ),
                    ft.Text(
                        "Pronostica, Scommetti, Vinci!",
                        size=16,
                        color="grey",
                        text_align="center"
                    ),
                    ft.Container(height=30),
                    email, pwd, team,
                    ft.Container(height=20),
                    ft.ElevatedButton(
                        "ENTRA",
                        on_click=enter,
                        width=300,
                        height=50,
                        style=ft.ButtonStyle(
                            bgcolor=PRIMARY,
                            color="black",
                            shape=ft.RoundedRectangleBorder(radius=10)
                        )
                    )
                ], horizontal_alignment="center", spacing=15),
                padding=30,
                expand=True
            )
        )

    def league_view():
        page.clean()
        global current_league
        
        name = ft.TextField(
            label="Nome Lega",
            prefix_icon="group",
            border_radius=10,
            bgcolor=CARD_BG,
            border_color=PRIMARY
        )
        pwd = ft.TextField(
            label="Password Lega",
            prefix_icon="key",
            password=True,
            can_reveal_password=True,
            border_radius=10,
            bgcolor=CARD_BG,
            border_color=PRIMARY
        )

        def create_league(e):
            if not name.value or not pwd.value:
                show_snackbar("⚠️ Compila tutti i campi", DANGER)
                return
                
            cur.execute("SELECT name FROM leagues WHERE name=?", (name.value,))
            if cur.fetchone():
                show_snackbar("❌ Lega già esistente", DANGER)
                return
                
            try:
                hashed = bcrypt.hashpw(pwd.value.encode(), bcrypt.gensalt()).decode()
                cur.execute("INSERT INTO leagues VALUES(?,?)", (name.value, hashed))
                cur.execute("INSERT INTO standings VALUES(?,?,0)", (user_logged, name.value))
                conn.commit()
                current_league = name.value
                save_session(user_logged, current_league)
                show_snackbar(f"🎉 Lega '{name.value}' creata!", SUCCESS)
                start_auto_update()
                go("game")
            except Exception as ex:
                show_snackbar(f"❌ Errore: {ex}", DANGER)

        def join_league(e):
            if not name.value or not pwd.value:
                show_snackbar("⚠️ Compila tutti i campi", DANGER)
                return
                
            cur.execute("SELECT password FROM leagues WHERE name=?", (name.value,))
            row = cur.fetchone()
            if not row or not bcrypt.checkpw(pwd.value.encode(), row[0].encode()):
                show_snackbar("❌ Credenziali errate", DANGER)
                return
                
            cur.execute("SELECT COUNT(*) FROM standings WHERE league=?", (name.value,))
            if cur.fetchone()[0] >= MAX_PLAYERS:
                show_snackbar("❌ Lega piena", DANGER)
                return
                
            try:
                cur.execute("SELECT 1 FROM standings WHERE email=? AND league=?", (user_logged, name.value))
                if not cur.fetchone():
                    cur.execute("INSERT INTO standings VALUES(?,?,0)", (user_logged, name.value))
                    conn.commit()
                current_league = name.value
                save_session(user_logged, current_league)
                show_snackbar(f"✅ Entrato in '{name.value}'!", SUCCESS)
                start_auto_update()
                go("game")
            except Exception as ex:
                show_snackbar(f"❌ Errore: {ex}", DANGER)

        def logout(e):
            global user_logged, current_league
            user_logged = None
            current_league = None
            clear_session()
            stop_auto_update()
            go("login")

        page.add(
            ft.Container(
                content=ft.Column([
                    ft.AppBar(
                        title=ft.Text("Seleziona Lega", weight="bold"),
                        bgcolor=CARD_BG,
                        actions=[
                            ft.IconButton(
                                "logout",
                                on_click=logout,
                                tooltip="Logout",
                                icon_color=DANGER
                            )
                        ]
                    ),
                    ft.Container(
                        content=ft.Column([
                            ft.Icon("emoji_events", size=60, color=PRIMARY),
                            ft.Text(
                                "Crea o Unisciti a una Lega",
                                size=24,
                                weight="bold",
                                text_align="center"
                            ),
                            ft.Container(height=20),
                            name, pwd,
                            ft.Container(height=20),
                            ft.Row([
                                ft.ElevatedButton(
                                    "➕ CREA",
                                    on_click=create_league,
                                    expand=1,
                                    height=50,
                                    style=ft.ButtonStyle(
                                        bgcolor=SUCCESS,
                                        color="white",
                                        shape=ft.RoundedRectangleBorder(radius=10)
                                    )
                                ),
                                ft.ElevatedButton(
                                    "🔑 UNISCITI",
                                    on_click=join_league,
                                    expand=1,
                                    height=50,
                                    style=ft.ButtonStyle(
                                        bgcolor=SECONDARY,
                                        color="white",
                                        shape=ft.RoundedRectangleBorder(radius=10)
                                    )
                                ),
                            ], spacing=10)
                        ], horizontal_alignment="center", spacing=15),
                        padding=30
                    )
                ], spacing=0),
                expand=True
            )
        )

    def game_view():
        page.clean()
        cur.execute("SELECT team,credits FROM users WHERE email=?", (user_logged,))
        result = cur.fetchone()
        
        if not result:
            go("login")
            return
            
        team, credits = result

        def manual_update(e):
            updated = evaluate_matches()
            if updated > 0:
                show_snackbar(f"✅ {updated} scommesse aggiornate!", SUCCESS)
                game_view()
            else:
                show_snackbar("ℹ️ Nessun aggiornamento", PRIMARY)

        header = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Column([
                        ft.Text("Squadra", size=12, color="grey"),
                        ft.Text(team, size=18, weight="bold", color=PRIMARY)
                    ], spacing=0),
                    ft.Column([
                        ft.Text("Crediti", size=12, color="grey"),
                        ft.Text(f"💰 {credits}", size=18, weight="bold", color=SUCCESS)
                    ], spacing=0, horizontal_alignment="end"),
                ], alignment="spaceBetween"),
                ft.Row([
                    ft.Text(f"Lega: {current_league}", size=12, color="grey"),
                    ft.IconButton(
                        "refresh",
                        on_click=manual_update,
                        tooltip="Aggiorna",
                        icon_size=20,
                        icon_color=PRIMARY
                    )
                ], alignment="spaceBetween")
            ], spacing=5),
            bgcolor=CARD_BG,
            padding=15,
            border_radius=10
        )

        matches = get_matches()[:8]
        
        if not matches:
            col = ft.Column([
                ft.Container(
                    content=ft.Column([
                        ft.Icon("event_busy", size=60, color="grey"),
                        ft.Text("Nessuna partita disponibile", size=16, color="grey")
                    ], horizontal_alignment="center", spacing=10),
                    padding=50
                )
            ])
        else:
            col = ft.Column(scroll="always", expand=True, spacing=10)

            for m in matches:
                match_date = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
                date_str = match_date.strftime("%d/%m %H:%M")
                
                w = ft.Dropdown(
                    label="Pronostico",
                    options=[
                        ft.dropdown.Option("1", "🏠 Casa"),
                        ft.dropdown.Option("X", "🤝 Pareggio"),
                        ft.dropdown.Option("2", "✈️ Trasferta")
                    ],
                    border_radius=10,
                    bgcolor=CARD_BG,
                    border_color=PRIMARY
                )
                r = ft.TextField(
                    label="Risultato esatto (es. 2-1)",
                    border_radius=10,
                    bgcolor=CARD_BG,
                    border_color=PRIMARY
                )
                bet_amount = ft.TextField(
                    label="Crediti",
                    value="10",
                    keyboard_type=ft.KeyboardType.NUMBER,
                    border_radius=10,
                    bgcolor=CARD_BG,
                    border_color=PRIMARY,
                    width=120
                )

                cur.execute("SELECT winner,result,amount FROM bets WHERE email=? AND match_id=? AND league=?", 
                           (user_logged, m["id"], current_league))
                existing = cur.fetchone()

                if existing:
                    col.controls.append(ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text(m['homeTeam']['name'], size=14, weight="bold", expand=1),
                                ft.Text("VS", size=12, color=PRIMARY),
                                ft.Text(m['awayTeam']['name'], size=14, weight="bold", expand=1, text_align="right"),
                            ]),
                            ft.Text(date_str, size=11, color="grey"),
                            ft.Divider(height=1, color="grey"),
                            ft.Container(
                                content=ft.Row([
                                    ft.Icon("check_circle", color=SUCCESS, size=20),
                                    ft.Column([
                                        ft.Text("Scommessa piazzata", size=12, weight="bold", color=SUCCESS),
                                        ft.Text(f"Pronostico: {existing[0]} | Risultato: {existing[1]}", size=11),
                                        ft.Text(f"Importo: {existing[2]} CR", size=11, weight="bold")
                                    ], spacing=2, expand=1)
                                ], spacing=10),
                                bgcolor="#10b98120",
                                padding=10,
                                border_radius=8
                            )
                        ], spacing=8),
                        bgcolor=CARD_BG,
                        padding=15,
                        border_radius=10,
                        border=ft.border.all(1, SUCCESS)
                    ))
                    continue

                def bet(e, match=m, winner=w, result=r, amount_field=bet_amount):
                    try:
                        amount = int(amount_field.value)
                        if amount <= 0:
                            raise ValueError("Importo deve essere positivo")
                        if amount > credits:
                            raise ValueError("Crediti insufficienti")
                    except ValueError as ex:
                        show_snackbar(f"⚠️ {ex}", DANGER)
                        return

                    if not winner.value:
                        show_snackbar("⚠️ Seleziona pronostico", DANGER)
                        return

                    if not result.value or not re.match(r'^\d+-\d+$', result.value):
                        show_snackbar("⚠️ Formato: 2-1", DANGER)
                        return

                    try:
                        cur.execute("""
                            INSERT INTO bets (email, league, match_id, winner, result, amount, evaluated) 
                            VALUES (?, ?, ?, ?, ?, ?, 0)
                        """, (user_logged, current_league, match["id"], winner.value, result.value, amount))
                        
                        cur.execute("UPDATE users SET credits=credits-? WHERE email=?", (amount, user_logged))
                        conn.commit()
                        
                        show_snackbar(f"✅ Scommessa di {amount} CR piazzata!", SUCCESS)
                        game_view()
                        
                    except Exception as ex:
                        show_snackbar(f"❌ Errore: {ex}", DANGER)

                col.controls.append(ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text(m['homeTeam']['name'], size=14, weight="bold", expand=1),
                            ft.Text("VS", size=12, color=PRIMARY, weight="bold"),
                            ft.Text(m['awayTeam']['name'], size=14, weight="bold", expand=1, text_align="right"),
                        ]),
                        ft.Text(date_str, size=11, color="grey"),
                        ft.Divider(height=1, color="grey"),
                        w, ft.Row([r, bet_amount], spacing=10),
                        ft.ElevatedButton(
                            "⚽ PUNTA",
                            on_click=bet,
                            width=200,
                            height=45,
                            style=ft.ButtonStyle(
                                bgcolor=PRIMARY,
                                color="black",
                                shape=ft.RoundedRectangleBorder(radius=10)
                            )
                        )
                    ], spacing=10, horizontal_alignment="center"),
                    bgcolor=CARD_BG,
                    padding=15,
                    border_radius=10
                ))

        nav = ft.NavigationBar(
            selected_index=0,
            on_change=lambda e: [game_view, ranking_view, my_bets_view][e.control.selected_index](),
            destinations=[
                ft.NavigationBarDestination(icon="sports_soccer", label="Partite"),
                ft.NavigationBarDestination(icon="leaderboard", label="Classifica"),
                ft.NavigationBarDestination(icon="history", label="Le mie"),
            ],
            bgcolor=CARD_BG
        )

        page.add(
            ft.Column([
                header,
                ft.Container(content=col, expand=True, padding=ft.padding.only(left=10, right=10)),
                nav
            ], spacing=10, expand=True)
        )

    def ranking_view():
        page.clean()
        
        cur.execute("""
            SELECT u.team, s.points, u.credits
            FROM standings s
            JOIN users u ON u.email=s.email
            WHERE s.league=?
            ORDER BY s.points DESC, u.credits DESC
        """, (current_league,))

        results = cur.fetchall()
        col = ft.Column(scroll="always", expand=True, spacing=10)
        
        if not results:
            col.controls.append(ft.Container(
                content=ft.Column([
                    ft.Icon("groups", size=60, color="grey"),
                    ft.Text("Nessun giocatore", size=16, color="grey")
                ], horizontal_alignment="center", spacing=10),
                padding=50
            ))
        else:
            for idx, (team_name, points, creds) in enumerate(results, 1):
                if idx == 1:
                    icon = "🥇"
                    color = "#ffd700"
                elif idx == 2:
                    icon = "🥈"
                    color = "#c0c0c0"
                elif idx == 3:
                    icon = "🥉"
                    color = "#cd7f32"
                else:
                    icon = f"{idx}"
                    color = "grey"
                    
                col.controls.append(ft.Container(
                    content=ft.Row([
                        ft.Container(
                            content=ft.Text(icon, size=24, weight="bold"),
                            width=50,
                            alignment=ft.alignment.center
                        ),
                        ft.Column([
                            ft.Text(team_name, size=16, weight="bold"),
                            ft.Text(f"💰 {creds} CR", size=12, color="grey")
                        ], spacing=2, expand=1),
                        ft.Container(
                            content=ft.Text(f"{points}", size=20, weight="bold", color=PRIMARY),
                            bgcolor="#00d4ff20",
                            padding=10,
                            border_radius=8
                        )
                    ], alignment="spaceBetween"),
                    bgcolor=CARD_BG,
                    padding=15,
                    border_radius=10,
                    border=ft.border.all(2, color) if idx <= 3 else None
                ))

        nav = ft.NavigationBar(
            selected_index=1,
            on_change=lambda e: [game_view, ranking_view, my_bets_view][e.control.selected_index](),
            destinations=[
                ft.NavigationBarDestination(icon="sports_soccer", label="Partite"),
                ft.NavigationBarDestination(icon="leaderboard", label="Classifica"),
                ft.NavigationBarDestination(icon="history", label="Le mie"),
            ],
            bgcolor=CARD_BG
        )

        page.add(
            ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Icon("emoji_events", color=PRIMARY),
                        ft.Text(f"Classifica - {current_league}", size=20, weight="bold"),
                        ft.IconButton(
                            "logout",
                            on_click=lambda _: go("league"),
                            tooltip="Cambia lega",
                            icon_color=DANGER
                        )
                    ], alignment="spaceBetween"),
                    bgcolor=CARD_BG,
                    padding=15,
                    border_radius=10
                ),
                ft.Container(content=col, expand=True, padding=ft.padding.only(left=10, right=10)),
                nav
            ], spacing=10, expand=True)
        )

    def my_bets_view():
        page.clean()
        
        cur.execute("""
            SELECT match_id, winner, result, amount, evaluated
            FROM bets
            WHERE email=? AND league=?
            ORDER BY evaluated ASC, match_id DESC
        """, (user_logged, current_league))

        bets = cur.fetchall()
        col = ft.Column(scroll="always", expand=True, spacing=10)
        
        if not bets:
            col.controls.append(ft.Container(
                content=ft.Column([
                    ft.Icon("receipt_long", size=60, color="grey"),
                    ft.Text("Nessuna scommessa", size=16, color="grey")
                ], horizontal_alignment="center", spacing=10),
                padding=50
            ))
        else:
            pending = [b for b in bets if not b[4]]
            evaluated = [b for b in bets if b[4]]
            
            if pending:
                col.controls.append(ft.Text("⏳ In attesa", size=18, weight="bold", color=PRIMARY))
                for match_id, winner, result, amount, _ in pending:
                    col.controls.append(ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text(f"Match #{match_id}", size=12, color="grey"),
                                ft.Container(
                                    content=ft.Text("IN ATTESA", size=10, weight="bold"),
                                    bgcolor="#f59e0b20",
                                    padding=5,
                                    border_radius=5
                                )
                            ], alignment="spaceBetween"),
                            ft.Text(f"Pronostico: {winner} | Risultato: {result}", size=14),
                            ft.Text(f"Importo: {amount} CR", size=14, weight="bold", color=PRIMARY)
                        ], spacing=5),
                        bgcolor=CARD_BG,
                        padding=15,
                        border_radius=10,
                        border=ft.border.all(1, "#f59e0b")
                    ))
            
            if evaluated:
                col.controls.append(ft.Container(height=10))
                col.controls.append(ft.Text("✅ Valutate", size=18, weight="bold", color=SUCCESS))
                for match_id, winner, result, amount, _ in evaluated:
                    col.controls.append(ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text(f"Match #{match_id}", size=12, color="grey"),
                                ft.Container(
                                    content=ft.Text("VALUTATA", size=10, weight="bold"),
                                    bgcolor="#10b98120",
                                    padding=5,
                                    border_radius=5
                                )
                            ], alignment="spaceBetween"),
                            ft.Text(f"Pronostico: {winner} | Risultato: {result}", size=14),
                            ft.Text(f"Importo: {amount} CR", size=14, weight="bold")
                        ], spacing=5),
                        bgcolor=CARD_BG,
                        padding=15,
                        border_radius=10
                    ))

        nav = ft.NavigationBar(
            selected_index=2,
            on_change=lambda e: [game_view, ranking_view, my_bets_view][e.control.selected_index](),
            destinations=[
                ft.NavigationBarDestination(icon="sports_soccer", label="Partite"),
                ft.NavigationBarDestination(icon="leaderboard", label="Classifica"),
                ft.NavigationBarDestination(icon="history", label="Le mie"),
            ],
            bgcolor=CARD_BG
        )

        page.add(
            ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Icon("receipt_long", color=PRIMARY),
                        ft.Text("Le mie scommesse", size=20, weight="bold"),
                        ft.IconButton(
                            "logout",
                            on_click=lambda _: go("league"),
                            tooltip="Cambia lega",
                            icon_color=DANGER
                        )
                    ], alignment="spaceBetween"),
                    bgcolor=CARD_BG,
                    padding=15,
                    border_radius=10
                ),
                ft.Container(content=col, expand=True, padding=ft.padding.only(left=10, right=10)),
                nav
            ], spacing=10, expand=True)
        )

    def go(view):
        page.clean()
        {
            "login": login_view,
            "league": league_view,
            "game": game_view,
            "ranking": ranking_view
        }[view]()
        page.update()

    if saved_email and saved_league:
        user_logged = saved_email
        current_league = saved_league
        start_auto_update()
        game_view()
    else:
        go("login")

ft.app(target=main, view=ft.WEB_BROWSER)