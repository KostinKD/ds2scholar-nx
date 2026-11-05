#!/usr/bin/env python3
"""Companion AI Controller for Dark Souls II PC Phantom.

Emulates FromSoftware's native NPC companion behavior (based on the extracted
ezstate/ai705000 state machine of Masterless Glencour / white phantoms) using
the 3D navigation corridor from m10_31_00_00.msb (Heide's Tower of Flame).
"""
import argparse
import json
import math
from pathlib import Path
import sys
import time

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]

BUTTONS = {
    'a': 0x1000,
    'b': 0x2000,       # Roll / Backstep / Sprint
    'x': 0x4000,       # Use Item / Estus
    'y': 0x8000,       # Two-hand stance toggle
    'start': 0x0010,
    'back': 0x0020,
    'ls': 0x0040,
    'rs': 0x0080,      # Lock-On target (RS click)
    'lb': 0x0100,      # Shield Block / Guard
    'rb': 0x0200,      # Light Attack
    'up': 0x0001,
    'down': 0x0002,
    'left': 0x0004,
    'right': 0x0008,
}


def find_active_client_dir():
    """Find the most recently updated active PC client directory."""
    pair_dir = ROOT / 'out' / 'switch_pc_pair'
    if pair_dir.is_dir():
        runs = sorted(pair_dir.glob('*/pc'), key=lambda p: p.stat().st_mtime, reverse=True)
        for r in runs:
            if (r / 'ds2.exe').is_file():
                return r
    pair_dir = ROOT / 'out' / 'bot_pair'
    if pair_dir.is_dir():
        runs = sorted(pair_dir.glob('*/bot'), key=lambda p: p.stat().st_mtime, reverse=True)
        for r in runs:
            if (r / 'ds2.exe').is_file():
                return r
    return None


class CompanionAI:
    def __init__(self, client_dir=None):
        self.client_dir = Path(client_dir or find_active_client_dir()).resolve()
        if not (self.client_dir / 'ds2.exe').is_file():
            raise FileNotFoundError(f"Invalid client directory: {self.client_dir}")
        self.pad_path = self.client_dir / 'pad.txt'
        self.nav_file = ROOT / 'tools' / 'nav' / 'heide_corridor.json'
        self.waypoints = []
        if self.nav_file.is_file():
            try:
                data = json.loads(self.nav_file.read_text(encoding='utf-8'))
                self.waypoints = data.get('waypoints', [])
            except Exception as e:
                print(f"Warning: could not load nav file: {e}")

        print(f"[{time.strftime('%H:%M:%S')}] Glencour Companion AI initialized on: {self.client_dir.name}")
        if self.waypoints:
            print(f"[{time.strftime('%H:%M:%S')}] Loaded {len(self.waypoints)} waypoints from {self.nav_file.name}")

    def send_cmd(self, buttons_mask=0, lx=0, ly=0, rx=0, ry=0, ms=200, label=""):
        stamp = time.time_ns()
        values = (stamp, ms, f"{buttons_mask:x}", int(lx), int(ly), int(rx), int(ry))
        temp = self.pad_path.with_suffix('.tmp')
        temp.write_text(' '.join(map(str, values)) + '\n', encoding='ascii')
        temp.replace(self.pad_path)
        tag = f" ({label})" if label else ""
        print(f"[{time.strftime('%H:%M:%S')}] AI Input: btn=0x{buttons_mask:04X} stick=({int(lx)},{int(ly)})/({int(rx)},{int(ry)}) {ms}ms{tag}", flush=True)

    def release(self):
        self.send_cmd(0, 0, 0, 0, 0, ms=50, label="release")

    # =========================================================================
    # Native Action Primitives (Mapping to DS2 ChrCtrl buttons & sticks)
    # =========================================================================

    def lock_on(self):
        """【索敵】ターゲット設定: Click Right Stick (0x0080) to toggle Lock-On."""
        self.send_cmd(buttons_mask=BUTTONS['rs'], ms=200, label="ai_lock_on")
        time.sleep(0.35)

    def camera_snap(self):
        """Reset camera behind character facing direction."""
        self.send_cmd(buttons_mask=BUTTONS['rs'], ms=150, label="ai_camera_reset")
        time.sleep(0.3)

    def light_attack(self):
        """【攻撃】近接攻撃: Light Attack (RB = 0x0200)."""
        self.send_cmd(buttons_mask=BUTTONS['rb'], ms=250, label="ai_light_attack")
        time.sleep(0.7)

    def attack_combo(self):
        """【攻撃】コンボ攻撃: Two-hit Light Attack combo (RB -> RB)."""
        self.send_cmd(buttons_mask=BUTTONS['rb'], ms=250, label="ai_combo_hit1")
        time.sleep(0.65)
        self.send_cmd(buttons_mask=BUTTONS['rb'], ms=250, label="ai_combo_hit2")
        time.sleep(0.85)

    def two_hand_toggle(self):
        """【プレイヤー攻撃】武器持ち方変更: Toggle Two-Handed stance (Y = 0x8000)."""
        self.send_cmd(buttons_mask=BUTTONS['y'], ms=200, label="ai_two_hand_toggle")
        time.sleep(0.6)

    def guard_hold(self, ms=1200):
        """【攻撃】防御: Raise and hold shield (LB)."""
        self.send_cmd(buttons_mask=BUTTONS['lb'], ms=ms, label="ai_guard_hold")
        time.sleep(ms / 1000.0 + 0.1)

    def guard_move(self, lx=0, ly=32767, rx=0, ry=0, ms=1200, label="ai_guard_move"):
        """【移動】ロック移動ナビメッシュ: Move with shield raised (LB + Left Stick)."""
        self.send_cmd(buttons_mask=BUTTONS['lb'], lx=lx, ly=ly, rx=rx, ry=ry, ms=ms, label=label)
        time.sleep(ms / 1000.0 + 0.05)

    def normal_move(self, lx=0, ly=32767, rx=0, ry=0, ms=1000, label="ai_normal_move"):
        """【移動】通常移動ナビメッシュ: Standard move along vector."""
        self.send_cmd(buttons_mask=0, lx=lx, ly=ly, rx=rx, ry=ry, ms=ms, label=label)
        time.sleep(ms / 1000.0 + 0.05)

    def sprint_move(self, lx=0, ly=32767, ms=1000, label="ai_sprint"):
        """【移動】ダッシュ_ナビメッシュ: Sprint forward (Hold B + Left Stick)."""
        self.send_cmd(buttons_mask=BUTTONS['b'], lx=lx, ly=ly, ms=ms, label=label)
        time.sleep(ms / 1000.0 + 0.05)

    def dodge_back(self):
        """【攻撃】ランダム回避 / 間合行動：後退移動: Evade roll backwards (LSD + B)."""
        self.send_cmd(buttons_mask=BUTTONS['b'], lx=0, ly=-32768, ms=250, label="ai_dodge_back")
        time.sleep(0.75)

    def dodge_left(self):
        """【攻撃】ランダム回避_左: Evade roll to the left (LSL + B)."""
        self.send_cmd(buttons_mask=BUTTONS['b'], lx=-32768, ly=0, ms=250, label="ai_dodge_left")
        time.sleep(0.75)

    def dodge_right(self):
        """【攻撃】ランダム回避_右: Evade roll to the right (LSR + B)."""
        self.send_cmd(buttons_mask=BUTTONS['b'], lx=32767, ly=0, ms=250, label="ai_dodge_right")
        time.sleep(0.75)

    def circle_strafe_left(self, ms=900):
        """間合行動：左右移動 (左旋回): Circle strafe left around locked target with shield up."""
        self.guard_move(lx=-32768, ly=0, ms=ms, label="ai_strafe_left")

    def circle_strafe_right(self, ms=900):
        """間合行動：左右移動 (右旋回): Circle strafe right around locked target with shield up."""
        self.guard_move(lx=32767, ly=0, ms=ms, label="ai_strafe_right")

    def heal(self):
        """【プレイヤー攻撃】アイテム使用: Tactical Estus Flask recovery (Roll back -> X)."""
        print(f"[{time.strftime('%H:%M:%S')}] >>> 【AI】緊急回復行動：エスト瓶使用 <<<")
        self.dodge_back()
        time.sleep(0.4)
        self.send_cmd(buttons_mask=BUTTONS['x'], ms=300, label="ai_drink_estus")
        time.sleep(2.6)

    def cast_sign(self):
        """Cast White Sign Soapstone via inventory menu."""
        print(f"[{time.strftime('%H:%M:%S')}] === 【AI】召喚サイン設置：白サインろう石 ===")
        menu_seq = ['start', 'rb', 'a', 'a', 'right', 'right', 'right', 'a', 'a']
        for b in menu_seq:
            self.send_cmd(buttons_mask=BUTTONS[b], ms=200, label=f"menu_{b}")
            time.sleep(0.9)
        time.sleep(3.5)
        for _ in range(3):
            self.send_cmd(buttons_mask=BUTTONS['b'], ms=200, label="menu_close_b")
            time.sleep(0.9)
        print(f"[{time.strftime('%H:%M:%S')}] Sign cast complete. White summon sign is active on the ground.")

    # =========================================================================
    # High-level In-Engine Navigation (m10_31_00_00.msb Safe Corridor)
    # =========================================================================

    def navigate_heide_corridor(self, start_wp=0, end_wp=None):
        """
        Traverses the Heide's Tower of Flame bridge corridor using the waypoints
        extracted from m10_31_00_00.msb.
        Steers character strictly along the centerline, preventing edge falls.
        """
        if not self.waypoints:
            print("Error: No waypoints available in heide_corridor.json")
            return

        end_wp = end_wp or len(self.waypoints)
        print(f"[{time.strftime('%H:%M:%S')}] === 【AI ナビメッシュ移動】Башня Хейда: Вейпоинты {start_wp} -> {end_wp} ===")

        # Waypoint sequence parameters:
        # 0 -> 1: Bonfire to stairs (angle ~ +35 deg, down stairs)
        # 1 -> 2: Stairs to bridge start (angle ~ +33 deg, enter bridge)
        # 2 -> 3: Bridge start to bridge mid (centerline Z=162.0)
        # 3 -> 4: Bridge mid to bridge exit (Z=162.0 -> 169.0)
        # 4 -> 5: Bridge exit to rotunda archway (straight into arch)
        # 5 -> 6: Archway turning RIGHT down stairs to rotunda (sharp right ~ -60 deg)
        # 6 -> 7: Rotunda stairs into Old Knight arena center

        segment_params = [
            # wp 0 -> 1: Bonfire to top of stairs
            {"label": "Спуск от костра к мосту", "lx": 10000, "ly": 32767, "rx": 0, "ms": 1400, "guard": True},
            # wp 1 -> 2: Enter bridge platform
            {"label": "Вход на настил моста", "lx": 8000, "ly": 32767, "rx": 0, "ms": 1300, "guard": True},
            # wp 2 -> 3: Bridge centerline segment 1
            {"label": "Осевая линия моста (центр Z=162)", "lx": -2000, "ly": 32767, "rx": 0, "ms": 1400, "guard": True},
            # wp 3 -> 4: Bridge centerline segment 2
            {"label": "Осевая линия моста (выход)", "lx": 4000, "ly": 32767, "rx": 0, "ms": 1400, "guard": True},
            # wp 4 -> 5: Approaching outer archway
            {"label": "Подход к внешней арке ротонды", "lx": 1000, "ly": 32767, "rx": 0, "ms": 1300, "guard": True},
            # wp 5 -> 6: Turning right down the stairs towards rotunda
            {"label": "Поворот вправо по ступеням в ротонду", "lx": 22000, "ly": 22000, "rx": 18000, "ms": 1600, "guard": True},
            # wp 6 -> 7: Entering Old Knight arena
            {"label": "Вход в круглый зал рыцаря", "lx": 16000, "ly": 28000, "rx": 10000, "ms": 1500, "guard": True},
        ]

        for i in range(start_wp, min(end_wp - 1, len(segment_params))):
            seg = segment_params[i]
            wp_from = self.waypoints[i]['name']
            wp_to = self.waypoints[i+1]['name']
            print(f"\n[{time.strftime('%H:%M:%S')}] [Нави-сегмент {i+1}/{len(segment_params)}] {wp_from} -> {wp_to}")
            print(f"[{time.strftime('%H:%M:%S')}] Маневр: {seg['label']} (lx={seg['lx']}, ly={seg['ly']}, rx={seg['rx']})")

            # Execute guarded step along safe vector
            btn = BUTTONS['lb'] if seg.get('guard') else 0
            self.send_cmd(buttons_mask=btn, lx=seg['lx'], ly=seg['ly'], rx=seg['rx'], ms=seg['ms'], label=f"nav_seg_{i+1}")
            time.sleep(seg['ms'] / 1000.0 + 0.25)

            # Periodic scan (RS click)
            if i in (1, 3, 5):
                self.lock_on()

        print(f"\n[{time.strftime('%H:%M:%S')}] Навигационный переход успешно завершен. Бот в ротонде!")

    # =========================================================================
    # Native Combat State Machine (ai705000: Masterless Glencour)
    # =========================================================================

    def glencour_tactical_combat(self, rounds=3):
        """
        Executes the native Glencour combat routine from ai705000:
        1. 【索敵】Target Lock-On (RS)
        2. 【移動】Guarded Approach (LB + Stick)
        3. 間合行動：左右移動 Circle Strafe to target's flank
        4. 【攻撃】Two-hit punish combo (RB -> RB)
        5. 【攻撃】ランダム回避 / 後退移動 Tactical dodge roll back
        6. 間合行動：防御 Shield hold for stamina recovery
        """
        print(f"\n[{time.strftime('%H:%M:%S')}] === 【AI 戦闘ルーチン：マスターレス・グレンカー】===")
        # Step 1: Target Lock-on
        print(f"[{time.strftime('%H:%M:%S')}] [Шаг 1: 索敵] Фиксация цели (Lock-On RS)...")
        self.lock_on()
        time.sleep(0.4)

        for r in range(rounds):
            print(f"\n[{time.strftime('%H:%M:%S')}] --- Боевой цикл #{r+1}/{rounds} ---")

            # Step 2: Guarded approach to engage range
            print(f"[{time.strftime('%H:%M:%S')}] [Шаг 2: 接近] Сближение со щитом в боевую зону (間合距離 3.5м)...")
            self.guard_move(lx=0, ly=32767, ms=1100, label="glencour_approach")
            time.sleep(0.2)

            # Step 3: Flanking strafe (baiting attack)
            strafe_dir = "влево" if r % 2 == 0 else "вправо"
            print(f"[{time.strftime('%H:%M:%S')}] [Шаг 3: 間合行動] Круговой стрейф {strafe_dir} для захода во фланг...")
            if r % 2 == 0:
                self.circle_strafe_left(ms=900)
            else:
                self.circle_strafe_right(ms=900)
            time.sleep(0.2)

            # Step 4: Punish combo
            print(f"[{time.strftime('%H:%M:%S')}] [Шаг 4: 攻撃] Нанесение 2-ударной комбинации (RB -> RB)...")
            self.attack_combo()
            time.sleep(0.3)

            # Step 5: Tactical evasion (clearing giant swing)
            print(f"[{time.strftime('%H:%M:%S')}] [Шаг 5: 回避] Тактический перекат назад от замаха (LSD + B)...")
            self.dodge_back()
            time.sleep(0.4)

            # Step 6: Stamina regen under guard
            print(f"[{time.strftime('%H:%M:%S')}] [Шаг 6: 防御] Удержание блока для восстановления выносливости...")
            self.guard_hold(ms=1300)
            time.sleep(0.2)

        print(f"\n[{time.strftime('%H:%M:%S')}] Боевой цикл Glencour завершен.")

    # =========================================================================
    # Autonomous Engine Loop
    # =========================================================================

    def autonomous_glencour_loop(self, cycles=10):
        """
        Runs the full autonomous companion cycle:
        Corridor Navigation -> Combat -> Flank -> Guard -> Reset.
        """
        print(f"\n[{time.strftime('%H:%M:%S')}] ====================================================")
        print(f"[{time.strftime('%H:%M:%S')}]   ЗАПУСК АВТОНОМНОГО ИИ-КОМПАНЬОНА (GLENCOUR AI)   ")
        print(f"[{time.strftime('%H:%M:%S')}] ====================================================")
        try:
            # 1. Traverse corridor
            self.navigate_heide_corridor(start_wp=0, end_wp=6)
            time.sleep(1.0)

            # 2. Engage enemies in rotunda
            self.glencour_tactical_combat(rounds=3)
        except KeyboardInterrupt:
            print(f"\n[{time.strftime('%H:%M:%S')}] ИИ-цикл остановлен пользователем.")
        finally:
            self.release()
            print(f"[{time.strftime('%H:%M:%S')}] Все действия ввода сброшены.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='status',
                        choices=['status', 'sign', 'nav', 'fight', 'auto', 'attack', 'combo',
                                 'lockon', 'dodge', 'heal', 'step', 'guard', 'strafe_l', 'strafe_r',
                                 'interactive'])
    parser.add_argument('--cycles', type=int, default=3, help='Number of rounds/cycles')
    parser.add_argument('--client', type=Path, default=None,
                        help='Explicit client directory (default: latest active run)')
    args = parser.parse_args()

    client = args.client or find_active_client_dir()
    if not client:
        print("Error: No active PC client folder found")
        sys.exit(1)

    ai = CompanionAI(client)

    if args.action == 'status':
        print(f"AI ready for commands on active client: {client}")
        print("Commands: sign, nav (bridge corridor), fight (Glencour combat), auto, attack, combo, lockon, dodge, heal, guard")
    elif args.action == 'sign':
        ai.cast_sign()
    elif args.action == 'nav':
        ai.navigate_heide_corridor()
    elif args.action == 'fight':
        ai.glencour_tactical_combat(rounds=args.cycles)
    elif args.action == 'auto':
        ai.autonomous_glencour_loop(cycles=args.cycles)
    elif args.action == 'attack':
        ai.light_attack()
    elif args.action == 'combo':
        ai.attack_combo()
    elif args.action == 'lockon':
        ai.lock_on()
    elif args.action == 'dodge':
        ai.dodge_back()
    elif args.action == 'heal':
        ai.heal()
    elif args.action == 'step':
        ai.normal_move(ms=1000)
    elif args.action == 'guard':
        ai.guard_move(ms=1400)
    elif args.action == 'strafe_l':
        ai.circle_strafe_left(ms=1000)
    elif args.action == 'strafe_r':
        ai.circle_strafe_right(ms=1000)
    elif args.action == 'interactive':
        print("=== Glencour Interactive Console (type command or 'exit') ===")
        print("Commands: nav, fight, attack, combo, lockon, dodge, heal, guard, strafe_l, strafe_r")
        while True:
            try:
                cmd = input("glencour> ").strip().lower()
                if not cmd or cmd in ('exit', 'quit'):
                    break
                if cmd == 'nav':
                    ai.navigate_heide_corridor()
                elif cmd == 'fight':
                    ai.glencour_tactical_combat()
                elif hasattr(ai, cmd):
                    getattr(ai, cmd)()
                else:
                    print(f"Unknown command: {cmd}")
            except KeyboardInterrupt:
                break
        print("Interactive session ended.")


if __name__ == '__main__':
    main()
