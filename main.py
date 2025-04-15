import pymem
import pymem.process
import time
import os
import sys
import win32gui
import win32con
import win32api
import win32ui
import requests
import dearpygui.dearpygui as dpg
import json
import math
import ctypes
import threading
from typing import Dict, List, Tuple
from pynput import mouse

gdi32 = ctypes.windll.gdi32

WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 1080
UPDATE_INTERVAL = 1

CONFIG_DIR = os.path.join(os.environ['SYSTEMDRIVE'], '\\ColoramaHack_Configs')
if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)

DEFAULT_CONFIG = {
    'esp_enabled': True,
    'show_teammates': False,
    'team_color': [0, 255, 0],
    'enemy_color': [255, 0, 0],
    'name_health_color': [255, 255, 255],
    'line_thickness': 2,
    'draw_bottom_line': False,
    'draw_box': True,
    'box_type': 'corner',
    'smoothing': 1,
    'aimbot_enabled': False,
    'aim_key': 'left_mouse',
    'aim_fov': 15,
    'aim_smooth': 7,
    'aim_teammates': False,
    'aim_targets': {'head': False, 'chest': True, 'legs': False},
    'show_fov': True,
    'fov_color': [255, 0, 0],
    'show_names': True,
    'show_health_text': True,
    'show_health_bar': True,
    'health_bar_position': 'left',
    'show_bones': True,
    'bone_color': [255, 255, 255]
}

config = DEFAULT_CONFIG.copy()
menu_visible = True
player_positions: Dict[str, Tuple[float, float, float, float]] = {}
pm = None
client = None
left_mouse_pressed = False
aim_key_pressed = False
hdc = None
hWnd = None
buffer_hdc = None
buffer_bmp = None
update_thread = None
mouse_listener = None
running = True

def load_offsets_from_github():
    try:
        offsets_url = 'https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json'
        client_dll_url = 'https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json'

        response_offsets = requests.get(offsets_url, timeout=5)
        response_offsets.raise_for_status()
        offsets = response_offsets.json()

        response_client_dll = requests.get(client_dll_url, timeout=5)
        response_client_dll.raise_for_status()
        client_dll = response_client_dll.json()

        return offsets, client_dll

    except requests.exceptions.RequestException as e:
        sys.exit(1)
    except json.JSONDecodeError as e:
        sys.exit(1)
    except Exception as e:
        sys.exit(1)

try:
    offsets, client_dll = load_offsets_from_github()
except SystemExit:
    raise
except Exception as e:
    sys.exit(1)

if 'client.dll' not in offsets or 'client.dll' not in client_dll:
    sys.exit(1)

dwEntityList = offsets['client.dll'].get('dwEntityList', 0)
dwLocalPlayerPawn = offsets['client.dll'].get('dwLocalPlayerPawn', 0)
dwViewMatrix = offsets['client.dll'].get('dwViewMatrix', 0)
dwViewAngles = offsets['client.dll'].get('dwViewAngles', 0)

try:
    m_iTeamNum = client_dll['client.dll']['classes']['C_BaseEntity']['fields'].get('m_iTeamNum', 0)
    m_lifeState = client_dll['client.dll']['classes']['C_BaseEntity']['fields'].get('m_lifeState', 0)
    m_pGameSceneNode = client_dll['client.dll']['classes']['C_BaseEntity']['fields'].get('m_pGameSceneNode', 0)
    m_iHealth = client_dll['client.dll']['classes']['C_BaseEntity']['fields'].get('m_iHealth', 0)
    m_modelState = client_dll['client.dll']['classes']['CSkeletonInstance']['fields'].get('m_modelState', 0)
    m_hPlayerPawn = client_dll['client.dll']['classes']['CCSPlayerController']['fields'].get('m_hPlayerPawn', 0)
    m_sSanitizedPlayerName = client_dll['client.dll']['classes']['CCSPlayerController']['fields'].get('m_sSanitizedPlayerName', 0)
except KeyError as e:
    sys.exit(1)

required_offsets = [
    dwEntityList, dwLocalPlayerPawn, dwViewMatrix, dwViewAngles,
    m_iTeamNum, m_lifeState, m_pGameSceneNode, m_iHealth,
    m_modelState, m_hPlayerPawn, m_sSanitizedPlayerName
]
if any(offset == 0 for offset in required_offsets):
    sys.exit(1)

def create_window():
    global hWnd, hdc, buffer_hdc, buffer_bmp
    wc = win32gui.WNDCLASS()
    wc.lpszClassName = "ESPOverlay"
    wc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
    wc.lpfnWndProc = lambda hwnd, msg, wp, lp: win32gui.DefWindowProc(hwnd, msg, wp, lp)
    win32gui.RegisterClass(wc)

    hWnd = win32gui.CreateWindowEx(
        win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST,
        wc.lpszClassName,
        "Overlay",
        win32con.WS_POPUP,
        0, 0, WINDOW_WIDTH, WINDOW_HEIGHT,
        0, 0, 0, None
    )
    
    win32gui.SetLayeredWindowAttributes(hWnd, win32api.RGB(0, 0, 0), 0, win32con.LWA_COLORKEY)
    win32gui.ShowWindow(hWnd, win32con.SW_SHOW)
    hdc = win32gui.GetDC(hWnd)
    if not hWnd or not hdc:
        raise RuntimeError
    
    buffer_hdc = win32gui.CreateCompatibleDC(hdc)
    buffer_bmp = win32gui.CreateCompatibleBitmap(hdc, WINDOW_WIDTH, WINDOW_HEIGHT)
    win32gui.SelectObject(buffer_hdc, buffer_bmp)

dpg.create_context()
viewport = dpg.create_viewport(title='ColoramaHack', width=625, height=310, resizable=False, decorated=False, clear_color=[40, 40, 40, 200])

def on_click(x, y, button, pressed):
    global left_mouse_pressed, aim_key_pressed
    if button == mouse.Button.left:
        left_mouse_pressed = pressed
        if config['aim_key'] == 'left_mouse':
            aim_key_pressed = pressed
    elif button == mouse.Button.right and config['aim_key'] == 'right_mouse':
        aim_key_pressed = pressed

mouse_listener = mouse.Listener(on_click=on_click)
mouse_listener.start()

def rgb_to_hex(rgb: List[int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)

def close_program():
    global hdc, hWnd, buffer_hdc, buffer_bmp, pm, update_thread, mouse_listener, running
    config['esp_enabled'] = False
    running = False
    try:
        if mouse_listener:
            mouse_listener.stop()
            mouse_listener = None
        if update_thread and update_thread.is_alive():
            update_thread.cancel()
            update_thread = None
        if hdc and hWnd:
            win32gui.ReleaseDC(hWnd, hdc)
            hdc = None
        if buffer_hdc:
            win32gui.DeleteDC(buffer_hdc)
            buffer_hdc = None
        if buffer_bmp:
            win32gui.DeleteObject(buffer_bmp)
            buffer_bmp = None
        if hWnd:
            win32gui.DestroyWindow(hWnd)
            hWnd = None
        if pm:
            pm.close_process()
            pm = None
        dpg.destroy_context()
    except:
        pass
    finally:
        os._exit(0)

def update_color(sender, app_data, user_data):
    if app_data is not None and isinstance(app_data, (list, tuple)) and len(app_data) >= 3:
        config[user_data] = [int(c * 255) for c in app_data[:3]]

def toggle_esp(sender, app_data): config['esp_enabled'] = app_data
def toggle_teammates(sender, app_data): config['show_teammates'] = app_data
def set_line_thickness(sender, app_data): config['line_thickness'] = int(app_data)
def set_smoothing(sender, app_data): config['smoothing'] = app_data
def toggle_aimbot(sender, app_data): config['aimbot_enabled'] = app_data
def set_aim_fov(sender, app_data): config['aim_fov'] = app_data
def set_aim_smooth(sender, app_data): config['aim_smooth'] = app_data
def toggle_aim_target(sender, app_data, user_data): config['aim_targets'][user_data] = app_data
def toggle_aim_teammates(sender, app_data): config['aim_teammates'] = app_data
def toggle_show_fov(sender, app_data): config['show_fov'] = app_data
def toggle_bottom_line(sender, app_data): config['draw_bottom_line'] = app_data
def toggle_names(sender, app_data): config['show_names'] = app_data
def toggle_health_text(sender, app_data): config['show_health_text'] = app_data
def toggle_health_bar(sender, app_data): config['show_health_bar'] = app_data
def set_health_bar_position(sender, app_data): config['health_bar_position'] = app_data.lower()
def toggle_bones(sender, app_data): config['show_bones'] = app_data

def save_config(sender, app_data):
    config_name = dpg.get_value("##config_name")
    if config_name:
        with open(os.path.join(CONFIG_DIR, f"{config_name}.json"), 'w') as f:
            json.dump(config, f)
        update_config_list()

def load_config(sender, app_data, user_data):
    config_path = os.path.join(CONFIG_DIR, f"{user_data}.json")
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            loaded_config = json.load(f)
            config.update(loaded_config)
            for color_key in ['team_color', 'enemy_color', 'name_health_color', 'fov_color', 'bone_color']:
                if color_key not in config or not isinstance(config[color_key], list) or len(config[color_key]) != 3:
                    config[color_key] = DEFAULT_CONFIG[color_key]
                else:
                    config[color_key] = [max(0, min(255, int(c))) for c in config[color_key]]

            dpg.set_value("esp_enabled", config['esp_enabled'])
            dpg.set_value("show_teammates", config['show_teammates'])
            dpg.set_value("draw_bottom_line", config['draw_bottom_line'])
            dpg.set_value("draw_box", config['draw_box'])
            dpg.set_value("line_thickness", config['line_thickness'])
            dpg.set_value("box_type_selector", config['box_type'].capitalize())
            dpg.set_value("aimbot_enabled", config['aimbot_enabled'])
            dpg.set_value("aim_fov", config['aim_fov'])
            dpg.set_value("aim_smooth", config['aim_smooth'])
            dpg.set_value("aim_teammates", config['aim_teammates'])
            dpg.set_value("aim_head", config['aim_targets']['head'])
            dpg.set_value("aim_chest", config['aim_targets']['chest'])
            dpg.set_value("aim_legs", config['aim_targets']['legs'])
            dpg.set_value("show_fov", config['show_fov'])
            dpg.set_value("show_names", config['show_names'])
            dpg.set_value("show_health_text", config['show_health_text'])
            dpg.set_value("show_health_bar", config['show_health_bar'])
            dpg.set_value("health_bar_position", config['health_bar_position'].capitalize())
            dpg.set_value("show_bones", config['show_bones'])
            dpg.set_value("aim_key_selector", "Left" if config['aim_key'] == 'left_mouse' else "Right")
            dpg.set_value("team_color", [x / 255.0 for x in config['team_color']] + [1.0])
            dpg.set_value("enemy_color", [x / 255.0 for x in config['enemy_color']] + [1.0])
            dpg.set_value("name_health_color", [x / 255.0 for x in config['name_health_color']] + [1.0])
            dpg.set_value("fov_color", [x / 255.0 for x in config['fov_color']] + [1.0])
            dpg.set_value("bone_color", [x / 255.0 for x in config['bone_color']] + [1.0])

def delete_config(sender, app_data, user_data):
    config_path = os.path.join(CONFIG_DIR, f"{user_data}.json")
    if os.path.exists(config_path):
        os.remove(config_path)
        update_config_list()

def update_config_list():
    configs = [f.replace('.json', '') for f in os.listdir(CONFIG_DIR) if f.endswith('.json')]
    dpg.delete_item("config_list", children_only=True)
    for cfg in configs:
        with dpg.group(horizontal=True, parent="config_list"):
            dpg.add_button(label=cfg, callback=load_config, user_data=cfg, width=150)
            dpg.add_button(label="X", callback=delete_config, user_data=cfg, width=30)

with dpg.window(label="ColoramaHack", width=625, height=310, no_title_bar=True, no_move=True, no_resize=True, pos=[0, 0]) as menu_window:
    with dpg.theme() as globalTheme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (21, 19, 21, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TitleBg, (21, 19, 21, 255))
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, (255, 255, 255, 255))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (225, 225, 225, 255))
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
    dpg.bind_theme(globalTheme)

    dpg.add_text("ColoramaHack")
    with dpg.tab_bar():
        with dpg.tab(label="Esp"):
            with dpg.group(horizontal=True):
                with dpg.group():
                    dpg.add_spacer(height=10)
                    dpg.add_checkbox(label="ESP", default_value=config['esp_enabled'], callback=toggle_esp, tag="esp_enabled")
                    dpg.add_checkbox(label="Teammates", default_value=config['show_teammates'], callback=toggle_teammates, tag="show_teammates")
                    dpg.add_checkbox(label="Box", default_value=config['draw_box'], callback=lambda s, a: config.update({'draw_box': a}), tag="draw_box")
                    dpg.add_checkbox(label="Line", default_value=config['draw_bottom_line'], callback=toggle_bottom_line, tag="draw_bottom_line")
                    dpg.add_checkbox(label="Names", default_value=config['show_names'], callback=toggle_names, tag="show_names")
                    dpg.add_checkbox(label="Health Text", default_value=config['show_health_text'], callback=toggle_health_text, tag="show_health_text")
                    dpg.add_checkbox(label="Health Bar", default_value=config['show_health_bar'], callback=toggle_health_bar, tag="show_health_bar")
                    dpg.add_checkbox(label="Bones", default_value=config['show_bones'], callback=toggle_bones, tag="show_bones")
                    dpg.add_spacer(height=10)
                with dpg.group():
                    dpg.add_text("Bar Pos:")
                    dpg.add_radio_button(items=["Left", "Right"], default_value=config['health_bar_position'].capitalize(), callback=set_health_bar_position, tag="health_bar_position")
                    dpg.add_slider_int(label="Thickness", min_value=1, max_value=5, default_value=config['line_thickness'], callback=set_line_thickness, tag="line_thickness", width=200)
                    dpg.add_text("Box Type:")
                    dpg.add_radio_button(items=["Full", "Corner", "Bottom"], default_value=config['box_type'].capitalize(), callback=lambda s, a: config.update({'box_type': a.lower()}), tag="box_type_selector")
                    dpg.add_spacer(height=15)
                with dpg.group():
                    dpg.add_text("Enemy:")
                    dpg.add_color_edit(default_value=config['enemy_color'], callback=update_color, user_data="enemy_color", width=200, tag="enemy_color", alpha_bar=False)
                    dpg.add_text("Team:")
                    dpg.add_color_edit(default_value=config['team_color'], callback=update_color, user_data="team_color", width=200, tag="team_color", alpha_bar=False)
                    dpg.add_text("Name/Health:")
                    dpg.add_color_edit(default_value=config['name_health_color'], callback=update_color, user_data="name_health_color", width=200, tag="name_health_color", alpha_bar=False)
                    dpg.add_text("Bone:")
                    dpg.add_color_edit(default_value=config['bone_color'], callback=update_color, user_data="bone_color", width=200, tag="bone_color", alpha_bar=False)

        with dpg.tab(label="Aimbot"):
            with dpg.group(horizontal=True):
                with dpg.group():
                    dpg.add_spacer(height=15)
                    dpg.add_checkbox(label="Aimbot", default_value=config['aimbot_enabled'], callback=toggle_aimbot, tag="aimbot_enabled")
                    dpg.add_checkbox(label="Aim Teammates", default_value=config['aim_teammates'], callback=toggle_aim_teammates, tag="aim_teammates")
                    dpg.add_text("Aim Key:")
                    dpg.add_radio_button(
                        items=["Left", "Right"],
                        default_value="Left" if config['aim_key'] == 'left_mouse' else "Right",
                        callback=lambda s, a: config.update({'aim_key': 'left_mouse' if a == "Left" else 'right_mouse'}),
                        tag="aim_key_selector"
                    )
                    dpg.add_text("Targets:")
                    with dpg.group(horizontal=True):
                        dpg.add_checkbox(label="Head", default_value=config['aim_targets']['head'], callback=toggle_aim_target, user_data="head", tag="aim_head")
                        dpg.add_checkbox(label="Chest", default_value=config['aim_targets']['chest'], callback=toggle_aim_target, user_data="chest", tag="aim_chest")
                        dpg.add_checkbox(label="Legs", default_value=config['aim_targets']['legs'], callback=toggle_aim_target, user_data="legs", tag="aim_legs")
                    dpg.add_spacer(height=20)
                with dpg.group():
                    dpg.add_slider_int(label="FOV", min_value=1.0, max_value=180.0, default_value=config['aim_fov'], callback=set_aim_fov, tag="aim_fov", width=200, pos=[330, 75])
                    dpg.add_slider_int(label="Smooth", min_value=1.0, max_value=10.0, default_value=config['aim_smooth'], callback=set_aim_smooth, tag="aim_smooth", width=200, pos=[330, 105])

        with dpg.tab(label="Misc"):
            with dpg.group(horizontal=True):
                with dpg.group():
                    dpg.add_spacer(height=20)
                    dpg.add_checkbox(label="Show FOV", default_value=config['show_fov'], callback=toggle_show_fov, tag="show_fov")
                    dpg.add_spacer(height=20)
                with dpg.group():
                    dpg.add_text("FOV Color:")
                    dpg.add_color_edit(default_value=config['fov_color'], callback=update_color, user_data="fov_color", width=150, tag="fov_color", alpha_bar=False)
                    dpg.add_button(label="Exit", callback=close_program, width=150)
                    dpg.add_spacer(height=20)
                with dpg.group():
                    dpg.add_text("Made By SA1DEN", pos=[12, 260])
                    dpg.add_text("Version 1.0.1", pos=[12, 280])

        with dpg.tab(label="Config"):
            with dpg.group(horizontal=True):
                with dpg.group():
                    dpg.add_spacer(height=20)
                    dpg.add_input_text(hint="Config name", width=200, tag="##config_name")
                    dpg.add_button(label="Save", callback=save_config, width=150)
                    dpg.add_spacer(height=20)
                with dpg.group():
                    with dpg.child_window(height=245, tag="config_list"):
                        update_config_list()

dpg.setup_dearpygui()
dpg.set_viewport_always_top(False)
dpg.show_viewport()

def w2s(mtx: List[float], posx: float, posy: float, posz: float, width: int, height: int) -> List[float]:
    screenW = (mtx[12] * posx) + (mtx[13] * posy) + (mtx[14] * posz) + mtx[15]
    if screenW > 0.001:
        screenX = (mtx[0] * posx) + (mtx[1] * posy) + (mtx[2] * posz) + mtx[3]
        screenY = (mtx[4] * posx) + (mtx[5] * posy) + (mtx[6] * posz) + mtx[7]
        camX, camY = width / 2, height / 2
        x = camX + (camX * screenX / screenW)
        y = camY - (camY * screenY / screenW)
        return [x, y]
    return [-999, -999]

def connect_to_game() -> bool:
    global pm, client
    try:
        pm = pymem.Pymem("cs2.exe")
        client = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
        return True
    except:
        return False

def calc_angle(src: List[float], dst: List[float]) -> List[float]:
    delta = [dst[0] - src[0], dst[1] - src[1], dst[2] - src[2]]
    hyp = math.sqrt(delta[0]**2 + delta[1]**2 + delta[2]**2)
    if hyp == 0:
        return [0, 0]
    pitch = math.degrees(math.asin(-delta[2] / hyp))
    yaw = math.degrees(math.atan2(delta[1], delta[0]))
    return [pitch, yaw]

def move_mouse(dx: float, dy: float):
    ctypes.windll.user32.mouse_event(0x0001, int(dx), int(dy), 0, 0)

def get_closest_enemy_target(local_pos):
    closest_dist = float('inf')
    target_angles = None
    target_screen = None
    try:
        view_matrix = [pm.read_float(client + dwViewMatrix + i * 4) for i in range(16)]
        local_game_scene = pm.read_longlong(local_pos + m_pGameSceneNode)
        local_bone_matrix = pm.read_longlong(local_game_scene + m_modelState + 0x80)
        local_head = [
            pm.read_float(local_bone_matrix + 6 * 0x20),
            pm.read_float(local_bone_matrix + 6 * 0x20 + 0x4),
            pm.read_float(local_bone_matrix + 6 * 0x20 + 0x8) + 8
        ]
    except:
        return None, None

    for i in range(64):
        try:
            entity = pm.read_longlong(client + dwEntityList)
            if not entity:
                continue
            list_entry = pm.read_longlong(entity + ((8 * (i & 0x7FFF) >> 9) + 16))
            if not list_entry:
                continue
            entity_controller = pm.read_longlong(list_entry + 120 * (i & 0x1FF))
            if not entity_controller:
                continue
            entity_controller_pawn = pm.read_longlong(entity_controller + m_hPlayerPawn)
            if not entity_controller_pawn:
                continue
            list_entry = pm.read_longlong(entity + (0x8 * ((entity_controller_pawn & 0x7FFF) >> 9) + 16))
            if not list_entry:
                continue
            entity_pawn_addr = pm.read_longlong(list_entry + 120 * (entity_controller_pawn & 0x1FF))
            if not entity_pawn_addr or entity_pawn_addr == local_pos:
                continue
            entity_alive = pm.read_int(entity_pawn_addr + m_lifeState)
            if entity_alive != 256:
                continue
            entity_team = pm.read_int(entity_pawn_addr + m_iTeamNum)
            local_team = pm.read_int(local_pos + m_iTeamNum)
            if entity_team == local_team and not config['aim_teammates']:
                continue
            game_scene = pm.read_longlong(entity_pawn_addr + m_pGameSceneNode)
            bone_matrix = pm.read_longlong(game_scene + m_modelState + 0x80)
            target_positions = []
            if config['aim_targets']['head']:
                target_positions.append([pm.read_float(bone_matrix + 6 * 0x20), pm.read_float(bone_matrix + 6 * 0x20 + 0x4), pm.read_float(bone_matrix + 6 * 0x20 + 0x8) + 8])
            if config['aim_targets']['chest']:
                target_positions.append([pm.read_float(bone_matrix + 5 * 0x20), pm.read_float(bone_matrix + 5 * 0x20 + 0x4), pm.read_float(bone_matrix + 5 * 0x20 + 0x8)])
            if config['aim_targets']['legs']:
                target_positions.append([pm.read_float(bone_matrix + 28 * 0x20), pm.read_float(bone_matrix + 28 * 0x20 + 0x4), pm.read_float(bone_matrix + 28 * 0x20 + 0x8)])
            if not target_positions:
                continue
            for target_pos in target_positions:
                angles = calc_angle(local_head, target_pos)
                screen_pos = w2s(view_matrix, target_pos[0], target_pos[1], target_pos[2], WINDOW_WIDTH, WINDOW_HEIGHT)
                if screen_pos[0] == -999:
                    continue
                current_angles = [pm.read_float(client + dwViewAngles), pm.read_float(client + dwViewAngles + 0x4)]
                delta_pitch = (angles[0] - current_angles[0] + 180) % 360 - 180
                delta_yaw = (angles[1] - current_angles[1] + 180) % 360 - 180
                dist = math.sqrt(delta_pitch**2 + delta_yaw**2)
                if dist < closest_dist and dist < config['aim_fov']:
                    closest_dist = dist
                    target_angles = angles
                    target_screen = screen_pos
        except:
            continue
    return target_angles, target_screen

def draw_line(hdc, x1, y1, x2, y2, color, thickness):
    if not hdc:
        return
    pen = win32gui.CreatePen(win32con.PS_SOLID, thickness, win32api.RGB(*color))
    old_pen = win32gui.SelectObject(hdc, pen)
    win32gui.MoveToEx(hdc, int(x1), int(y1))
    win32gui.LineTo(hdc, int(x2), int(y2))
    win32gui.SelectObject(hdc, old_pen)
    win32gui.DeleteObject(pen)

def draw_rect(hdc, x, y, width, height, color, thickness, filled=False):
    if not hdc:
        return
    pen = win32gui.CreatePen(win32con.PS_SOLID, thickness, win32api.RGB(*color))
    old_pen = win32gui.SelectObject(hdc, pen)
    if filled:
        brush = win32gui.CreateSolidBrush(win32api.RGB(*color))
    else:
        brush = win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0))
    old_brush = win32gui.SelectObject(hdc, brush)
    win32gui.Rectangle(hdc, int(x), int(y), int(x + width), int(y + height))
    win32gui.SelectObject(hdc, old_pen)
    win32gui.SelectObject(hdc, old_brush)
    win32gui.DeleteObject(pen)
    win32gui.DeleteObject(brush)

def draw_gradient_rect(hdc, x, y, width, height, health):
    if not hdc:
        return
    steps = int(height)
    for i in range(steps):
        ratio = i / height
        adjusted_ratio = (1 - health / 100) + (health / 100 * (1 - ratio))
        r = int(255 * adjusted_ratio)
        g = int(255 * (1 - adjusted_ratio))
        b = 0
        color = [r, g, b]
        draw_rect(hdc, x, y + i, width, 1, color, 1, filled=True)

def draw_text(hdc, x, y, text, color, scale=1.0):
    if not hdc:
        return
    font = win32ui.CreateFont({
        "name": "arial black",
        "height": int(20 * scale),
        "weight": 700,
    })
    old_font = win32gui.SelectObject(hdc, font.GetSafeHandle())
    gdi32.SetTextColor(hdc, win32api.RGB(*color))
    gdi32.SetBkMode(hdc, win32con.TRANSPARENT)
    text_w = text.encode('utf-16le') + b'\0\0'
    gdi32.TextOutW(hdc, int(x), int(y), text_w, len(text))
    win32gui.SelectObject(hdc, old_font)
    win32gui.DeleteObject(font.GetSafeHandle())

def draw_oval(hdc, x1, y1, x2, y2, color, thickness):
    if not hdc:
        return
    pen = win32gui.CreatePen(win32con.PS_SOLID, thickness, win32api.RGB(*color))
    old_pen = win32gui.SelectObject(hdc, pen)
    brush = win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0))
    old_brush = win32gui.SelectObject(hdc, brush)
    win32gui.Ellipse(hdc, int(x1), int(y1), int(x2), int(y2))
    win32gui.SelectObject(hdc, old_pen)
    win32gui.SelectObject(hdc, old_brush)
    win32gui.DeleteObject(pen)
    win32gui.DeleteObject(brush)

def calculate_scale(head_pos, leg_pos):
    height = abs(head_pos[1] - leg_pos[1])
    base_scale = min(1.0, max(0.6, height / 200))
    return base_scale

def draw_esp_and_aim():
    global hdc, hWnd, buffer_hdc
    if not running or (not config['esp_enabled'] and not config['aimbot_enabled']) or pm is None or client is None or hdc is None or hWnd is None or buffer_hdc is None:
        return
    
    win32gui.FillRect(buffer_hdc, (0, 0, WINDOW_WIDTH, WINDOW_HEIGHT), win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0)))
    
    try:
        view_matrix = [pm.read_float(client + dwViewMatrix + i * 4) for i in range(16)]
        local_player_pawn_addr = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_player_pawn_addr:
            return
        local_player_team = pm.read_int(local_player_pawn_addr + m_iTeamNum)
    except:
        return

    current_ids = []
    smoothing_factor = config['smoothing']
    fov_radius = (config['aim_fov'] / 180.0) * WINDOW_WIDTH / 2

    if config['show_fov']:
        draw_oval(buffer_hdc, 
                  WINDOW_WIDTH//2 - fov_radius, WINDOW_HEIGHT//2 - fov_radius,
                  WINDOW_WIDTH//2 + fov_radius, WINDOW_HEIGHT//2 + fov_radius,
                  config['fov_color'], 2)

    if config['esp_enabled']:
        entity_list = pm.read_longlong(client + dwEntityList)
        if not entity_list:
            return

        for i in range(64):
            try:
                list_entry = pm.read_longlong(entity_list + ((8 * (i & 0x7FFF) >> 9) + 16))
                if not list_entry:
                    continue
                entity_controller = pm.read_longlong(list_entry + 120 * (i & 0x1FF))
                if not entity_controller:
                    continue
                entity_controller_pawn = pm.read_longlong(entity_controller + m_hPlayerPawn)
                if not entity_controller_pawn:
                    continue
                list_entry_pawn = pm.read_longlong(entity_list + (0x8 * ((entity_controller_pawn & 0x7FFF) >> 9) + 16))
                if not list_entry_pawn:
                    continue
                entity_pawn_addr = pm.read_longlong(list_entry_pawn + 120 * (entity_controller_pawn & 0x1FF))
                if not entity_pawn_addr or entity_pawn_addr == local_player_pawn_addr:
                    continue
                entity_alive = pm.read_int(entity_pawn_addr + m_lifeState)
                if entity_alive != 256:
                    continue
                entity_team = pm.read_int(entity_pawn_addr + m_iTeamNum)
                if entity_team == local_player_team and not config['show_teammates']:
                    continue

                health = pm.read_int(entity_pawn_addr + m_iHealth)
                if health < 0 or health > 100:
                    health = 100
                name_ptr = pm.read_longlong(entity_controller + m_sSanitizedPlayerName)
                player_name = pm.read_string(name_ptr, 32) if name_ptr else f"Player_{i}"
                if not player_name.strip():
                    player_name = f"Player_{i}"

                color = config['team_color'] if entity_team == local_player_team else config['enemy_color']
                game_scene = pm.read_longlong(entity_pawn_addr + m_pGameSceneNode)
                bone_matrix = pm.read_longlong(game_scene + m_modelState + 0x80)
                
                selected_bone = 6
                if config['aim_targets']['chest']:
                    selected_bone = 5
                elif config['aim_targets']['legs']:
                    selected_bone = 28

                bone_indices = {
                    'head': 6, 'neck': 5, 'chest': 4, 'stomach': 3,
                    'left_shoulder': 8, 'left_elbow': 9, 'left_hand': 10,
                    'right_shoulder': 13, 'right_elbow': 14, 'right_hand': 15,
                    'left_hip': 22, 'left_knee': 23, 'left_foot': 24,
                    'right_hip': 25, 'right_knee': 26, 'right_foot': 27
                }

                bone_positions = {}
                for bone_name, bone_id in bone_indices.items():
                    boneX = pm.read_float(bone_matrix + bone_id * 0x20)
                    boneY = pm.read_float(bone_matrix + bone_id * 0x20 + 0x4)
                    boneZ = pm.read_float(bone_matrix + bone_id * 0x20 + 0x8)
                    if bone_name == 'head':
                        boneZ += 4
                    pos = w2s(view_matrix, boneX, boneY, boneZ, WINDOW_WIDTH, WINDOW_HEIGHT)
                    if pos[0] != -999:
                        bone_positions[bone_name] = pos

                head_pos = bone_positions.get('head', [-999, -999])
                leg_pos = bone_positions.get('right_foot', [-999, -999])
                if head_pos[0] == -999 or leg_pos[0] == -999:
                    continue

                player_id = f"{entity_pawn_addr}_{i}"
                current_ids.append(player_id)
                if player_id in player_positions:
                    old_head_x, old_head_y, old_leg_x, old_leg_y = player_positions[player_id]
                    head_pos[0] = old_head_x * (1 - smoothing_factor) + head_pos[0] * smoothing_factor
                    head_pos[1] = old_head_y * (1 - smoothing_factor) + head_pos[1] * smoothing_factor
                    leg_pos[0] = old_leg_x * (1 - smoothing_factor) + leg_pos[0] * smoothing_factor
                    leg_pos[1] = old_leg_y * (1 - smoothing_factor) + leg_pos[1] * smoothing_factor
                player_positions[player_id] = (head_pos[0], head_pos[1], leg_pos[0], leg_pos[1])

                deltaZ = abs(head_pos[1] - leg_pos[1])
                box_width = deltaZ // 3
                leftX = head_pos[0] - box_width
                rightX = head_pos[0] + box_width

                if config['draw_box']:
                    if config['box_type'] == 'full':
                        draw_line(buffer_hdc, leftX, leg_pos[1], rightX, leg_pos[1], color, config['line_thickness'])
                        draw_line(buffer_hdc, leftX, leg_pos[1], leftX, head_pos[1], color, config['line_thickness'])
                        draw_line(buffer_hdc, rightX, leg_pos[1], rightX, head_pos[1], color, config['line_thickness'])
                        draw_line(buffer_hdc, leftX, head_pos[1], rightX, head_pos[1], color, config['line_thickness'])
                    elif config['box_type'] == 'corner':
                        corner_size = box_width // 2
                        draw_line(buffer_hdc, leftX, head_pos[1], leftX + corner_size, head_pos[1], color, config['line_thickness'])
                        draw_line(buffer_hdc, leftX, head_pos[1], leftX, head_pos[1] + corner_size, color, config['line_thickness'])
                        draw_line(buffer_hdc, rightX, head_pos[1], rightX - corner_size, head_pos[1], color, config['line_thickness'])
                        draw_line(buffer_hdc, rightX, head_pos[1], rightX, head_pos[1] + corner_size, color, config['line_thickness'])
                        draw_line(buffer_hdc, leftX, leg_pos[1], leftX + corner_size, leg_pos[1], color, config['line_thickness'])
                        draw_line(buffer_hdc, leftX, leg_pos[1], leftX, leg_pos[1] - corner_size, color, config['line_thickness'])
                        draw_line(buffer_hdc, rightX, leg_pos[1], rightX - corner_size, leg_pos[1], color, config['line_thickness'])
                        draw_line(buffer_hdc, rightX, leg_pos[1], rightX, leg_pos[1] - corner_size, color, config['line_thickness'])
                    elif config['box_type'] == 'bottom':
                        draw_line(buffer_hdc, leftX, leg_pos[1], rightX, leg_pos[1], color, config['line_thickness'])
                        draw_line(buffer_hdc, leftX, leg_pos[1], leftX, leg_pos[1] - deltaZ//2, color, config['line_thickness'])
                        draw_line(buffer_hdc, rightX, leg_pos[1], rightX, leg_pos[1] - deltaZ//2, color, config['line_thickness'])

                if config['draw_bottom_line']:
                    bottom_center_x = (leftX + rightX) / 2
                    draw_line(buffer_hdc, WINDOW_WIDTH//2, WINDOW_HEIGHT, bottom_center_x, leg_pos[1], color, config['line_thickness'])

                if config['show_bones']:
                    skeleton_color = config['bone_color']
                    bone_thickness = 2
                    if 'head' in bone_positions and 'neck' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['head'][0], bone_positions['head'][1], 
                                 bone_positions['neck'][0], bone_positions['neck'][1], skeleton_color, bone_thickness)
                    if 'neck' in bone_positions and 'chest' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['neck'][0], bone_positions['neck'][1], 
                                 bone_positions['chest'][0], bone_positions['chest'][1], skeleton_color, bone_thickness)
                    if 'chest' in bone_positions and 'stomach' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['chest'][0], bone_positions['chest'][1], 
                                 bone_positions['stomach'][0], bone_positions['stomach'][1], skeleton_color, bone_thickness)
                    if 'chest' in bone_positions and 'left_shoulder' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['chest'][0], bone_positions['chest'][1], 
                                 bone_positions['left_shoulder'][0], bone_positions['left_shoulder'][1], skeleton_color, bone_thickness)
                    if 'left_shoulder' in bone_positions and 'left_elbow' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['left_shoulder'][0], bone_positions['left_shoulder'][1], 
                                 bone_positions['left_elbow'][0], bone_positions['left_elbow'][1], skeleton_color, bone_thickness)
                    if 'left_elbow' in bone_positions and 'left_hand' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['left_elbow'][0], bone_positions['left_elbow'][1], 
                                 bone_positions['left_hand'][0], bone_positions['left_hand'][1], skeleton_color, bone_thickness)
                    if 'chest' in bone_positions and 'right_shoulder' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['chest'][0], bone_positions['chest'][1], 
                                 bone_positions['right_shoulder'][0], bone_positions['right_shoulder'][1], skeleton_color, bone_thickness)
                    if 'right_shoulder' in bone_positions and 'right_elbow' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['right_shoulder'][0], bone_positions['right_shoulder'][1], 
                                 bone_positions['right_elbow'][0], bone_positions['right_elbow'][1], skeleton_color, bone_thickness)
                    if 'right_elbow' in bone_positions and 'right_hand' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['right_elbow'][0], bone_positions['right_elbow'][1], 
                                 bone_positions['right_hand'][0], bone_positions['right_hand'][1], skeleton_color, bone_thickness)
                    if 'stomach' in bone_positions and 'left_hip' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['stomach'][0], bone_positions['stomach'][1], 
                                 bone_positions['left_hip'][0], bone_positions['left_hip'][1], skeleton_color, bone_thickness)
                    if 'left_hip' in bone_positions and 'left_knee' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['left_hip'][0], bone_positions['left_hip'][1], 
                                 bone_positions['left_knee'][0], bone_positions['left_knee'][1], skeleton_color, bone_thickness)
                    if 'left_knee' in bone_positions and 'left_foot' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['left_knee'][0], bone_positions['left_knee'][1], 
                                 bone_positions['left_foot'][0], bone_positions['left_foot'][1], skeleton_color, bone_thickness)
                    if 'stomach' in bone_positions and 'right_hip' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['stomach'][0], bone_positions['stomach'][1], 
                                 bone_positions['right_hip'][0], bone_positions['right_hip'][1], skeleton_color, bone_thickness)
                    if 'right_hip' in bone_positions and 'right_knee' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['right_hip'][0], bone_positions['right_hip'][1], 
                                 bone_positions['right_knee'][0], bone_positions['right_knee'][1], skeleton_color, bone_thickness)
                    if 'right_knee' in bone_positions and 'right_foot' in bone_positions:
                        draw_line(buffer_hdc, bone_positions['right_knee'][0], bone_positions['right_knee'][1], 
                                 bone_positions['right_foot'][0], bone_positions['right_foot'][1], skeleton_color, bone_thickness)

                scale = calculate_scale(head_pos, leg_pos)
                
                if config['show_names'] or config['show_health_text'] or config['show_health_bar']:
                    bar_width = 5 * scale
                    bar_height = deltaZ
                    bar_y_top = head_pos[1]
                    bar_y_bottom = leg_pos[1]
                    bar_x = leftX - bar_width - 5 * scale if config['health_bar_position'] == 'left' else rightX + 5 * scale

                    if config['show_names']:
                        name_width = len(player_name) * 8 * scale
                        name_x = head_pos[0] - (name_width / 2)
                        name_y = head_pos[1] - 20 * scale
                        draw_text(buffer_hdc, name_x, name_y, player_name[:16], config['name_health_color'], scale)

                    if config['show_health_bar']:
                        draw_rect(buffer_hdc, bar_x, bar_y_top, bar_width, bar_height, [85, 85, 85], 1, filled=True)
                        health_height = (health / 100.0) * bar_height
                        draw_gradient_rect(buffer_hdc, bar_x, bar_y_bottom - health_height, bar_width, health_height, health)

                    if config['show_health_text']:
                        health_pos_x = leftX - bar_width - 40 * scale if config['health_bar_position'] == 'left' else rightX + bar_width + 15 * scale
                        health_pos_y = (head_pos[1] + leg_pos[1]) / 2 - 10 * scale
                        draw_text(buffer_hdc, health_pos_x, health_pos_y, f"{health}", config['name_health_color'], scale)

            except:
                continue

    if config['aimbot_enabled'] and aim_key_pressed:
        target_angles, target_screen = get_closest_enemy_target(local_player_pawn_addr)
        if target_angles and target_screen:
            try:
                current_angles = [pm.read_float(client + dwViewAngles), pm.read_float(client + dwViewAngles + 0x4)]
                smooth = config['aim_smooth']
                delta_pitch = target_angles[0] - current_angles[0]
                delta_yaw = target_angles[1] - current_angles[1]
                while delta_pitch > 180: delta_pitch -= 360
                while delta_pitch < -180: delta_pitch += 360
                while delta_yaw > 180: delta_yaw -= 360
                while delta_yaw < -180: delta_yaw += 360
                new_pitch = current_angles[0] + delta_pitch / smooth
                new_yaw = current_angles[1] + delta_yaw / smooth
                new_pitch = max(-89.0, min(89.0, new_pitch))
                pm.write_float(client + dwViewAngles, float(new_pitch))
                pm.write_float(client + dwViewAngles + 0x4, float(new_yaw))
                verify_angles = [pm.read_float(client + dwViewAngles), pm.read_float(client + dwViewAngles + 0x4)]
                if abs(verify_angles[0] - new_pitch) > 0.1 or abs(verify_angles[1] - new_yaw) > 0.1:
                    center_x, center_y = WINDOW_WIDTH//2, WINDOW_HEIGHT//2
                    dx = (target_screen[0] - center_x) / smooth
                    dy = (target_screen[1] - center_y) / smooth
                    move_mouse(dx, dy)
            except:
                center_x, center_y = WINDOW_WIDTH//2, WINDOW_HEIGHT//2
                dx = (target_screen[0] - center_x) / config['aim_smooth']
                dy = (target_screen[1] - center_y) / config['aim_smooth']
                move_mouse(dx, dy)

    for player_id in list(player_positions.keys()):
        if player_id not in current_ids:
            del player_positions[player_id]

    win32gui.BitBlt(hdc, 0, 0, WINDOW_WIDTH, WINDOW_HEIGHT, buffer_hdc, 0, 0, win32con.SRCCOPY)

def update():
    global hdc, hWnd, buffer_hdc, update_thread, running
    if not running:
        return
    try:
        if pm is None or client is None:
            if not connect_to_game():
                update_thread = threading.Timer(UPDATE_INTERVAL / 1000, update)
                update_thread.start()
                return
        if hdc is None or hWnd is None or buffer_hdc is None or not win32gui.IsWindow(hWnd):
            create_window()
        draw_esp_and_aim()
        dpg.render_dearpygui_frame()
        if hWnd and win32gui.IsWindow(hWnd):
            win32gui.UpdateWindow(hWnd)
        else:
            create_window()
    except:
        close_program()
    else:
        update_thread = threading.Timer(UPDATE_INTERVAL / 1000, update)
        update_thread.start()

try:
    create_window()
    update_thread = threading.Timer(UPDATE_INTERVAL / 1000, update)
    update_thread.start()
    while running:
        win32gui.PumpMessages()
except:
    close_program()
finally:
    close_program()