import pymem
import pymem.process
import time
import os
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
from pynput import mouse
import keyboard
import signal
import sys
from uuid import uuid4

gdi32 = ctypes.windll.gdi32
user32 = ctypes.windll.user32

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("mi", MOUSEINPUT),
    ]

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001

UPDATE_INTERVAL = 0.01
CONFIG_DIR = os.path.join(os.environ['SYSTEMDRIVE'], '\\ColoramaHack_Configs')
os.makedirs(CONFIG_DIR, exist_ok=True)

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
    'aim_smooth': 2,
    'aim_teammates': False,
    'aim_targets': {'head': False, 'chest': True, 'legs': False},
    'show_fov': False,
    'fov_color': [255, 0, 0],
    'show_names': True,
    'show_health_text': False,
    'show_health_bar': True,
    'health_bar_position': 'left',
    'show_bones': False,
    'bone_color': [255, 255, 255],
    'no_flash_enabled': False,
    'bhop_enabled': False,
    'fov_enabled': False,
    'fov_value': 0.0,
    'kill_delay': 0.5,
}

class State:
    def __init__(self):
        self.window_width = 1920
        self.window_height = 1080
        self.config = DEFAULT_CONFIG.copy()
        self.player_positions = {}
        self.pm = None
        self.client = None
        self.aim_key_pressed = False
        self.hdc = None
        self.hWnd = None
        self.buffer_hdc = None
        self.buffer_bmp = None
        self.running = True
        self.game_window = None
        self.last_kill_time = 0
        self.original_flash_alpha = 255.0
        self.current_ids = []

state = State()

def get_game_window():
    hwnd = win32gui.FindWindow(None, "Counter-Strike 2")
    if hwnd:
        rect = win32gui.GetClientRect(hwnd)
        state.window_width = rect[2] - rect[0]
        state.window_height = rect[3] - rect[1]
        return hwnd
    return None

def load_offsets_from_github():
    offsets_url = 'https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json'
    client_dll_url = 'https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json'
    try:
        response_offsets = requests.get(offsets_url, timeout=5)
        response_offsets.raise_for_status()
        offsets = response_offsets.json()
        response_client_dll = requests.get(client_dll_url, timeout=5)
        response_client_dll.raise_for_status()
        client_dll = response_client_dll.json()
        return offsets, client_dll
    except requests.RequestException:
        raise Exception("Failed to load offsets from GitHub")

def validate_offsets(offsets, client_dll):
    return {
        'dwEntityList': offsets['client.dll'].get('dwEntityList', 0),
        'dwLocalPlayerPawn': offsets['client.dll'].get('dwLocalPlayerPawn', 0),
        'dwViewMatrix': offsets['client.dll'].get('dwViewMatrix', 0),
        'dwViewAngles': offsets['client.dll'].get('dwViewAngles', 0),
        'm_iTeamNum': client_dll['client.dll']['classes']['C_BaseEntity']['fields'].get('m_iTeamNum', 0),
        'm_lifeState': client_dll['client.dll']['classes']['C_BaseEntity']['fields'].get('m_lifeState', 0),
        'm_pGameSceneNode': client_dll['client.dll']['classes']['C_BaseEntity']['fields'].get('m_pGameSceneNode', 0),
        'm_iHealth': client_dll['client.dll']['classes']['C_BaseEntity']['fields'].get('m_iHealth', 0),
        'm_modelState': client_dll['client.dll']['classes']['CSkeletonInstance']['fields'].get('m_modelState', 0),
        'm_hPlayerPawn': client_dll['client.dll']['classes']['CCSPlayerController']['fields'].get('m_hPlayerPawn', 0),
        'm_sSanitizedPlayerName': client_dll['client.dll']['classes']['CCSPlayerController']['fields'].get('m_sSanitizedPlayerName', 0),
        'm_flFlashMaxAlpha': client_dll['client.dll']['classes']['C_CSPlayerPawnBase']['fields'].get('m_flFlashMaxAlpha', 0),
        'm_fFlags': client_dll['client.dll']['classes']['C_CSPlayerPawn']['fields'].get('m_fFlags', 0)
    }

offsets, client_dll = load_offsets_from_github()
offset_values = validate_offsets(offsets, client_dll)

dwEntityList = offset_values['dwEntityList']
dwLocalPlayerPawn = offset_values['dwLocalPlayerPawn']
dwViewMatrix = offset_values['dwViewMatrix']
dwViewAngles = offset_values['dwViewAngles']
m_iTeamNum = offset_values['m_iTeamNum']
m_lifeState = offset_values['m_lifeState']
m_pGameSceneNode = offset_values['m_pGameSceneNode']
m_iHealth = offset_values['m_iHealth']
m_modelState = offset_values['m_modelState']
m_hPlayerPawn = offset_values['m_hPlayerPawn']
m_sSanitizedPlayerName = offset_values['m_sSanitizedPlayerName']
m_flFlashMaxAlpha = offset_values['m_flFlashMaxAlpha']
m_fFlags = offset_values['m_fFlags']

def cleanup_resources():
    state.running = False
    try:
        mouse_listener.stop()
    except Exception:
        pass
    try:
        if state.hdc and state.hWnd:
            win32gui.ReleaseDC(state.hWnd, state.hdc)
    except Exception:
        pass
    try:
        if state.buffer_hdc:
            win32gui.DeleteDC(state.buffer_hdc)
    except Exception:
        pass
    try:
        if state.buffer_bmp:
            win32gui.DeleteObject(state.buffer_bmp)
    except Exception:
        pass
    try:
        if state.hWnd:
            win32gui.DestroyWindow(state.hWnd)
            win32gui.UnregisterClass(state.hWnd, None)
    except Exception:
        pass
    try:
        if state.pm:
            state.pm.close_process()
    except Exception:
        pass
    try:
        dpg.destroy_context()
    except Exception:
        pass
    os._exit(0)  # Force exit the program

def close_program():
    cleanup_resources()
    sys.exit(0)

def signal_handler(sig, frame):
    close_program()

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def wnd_proc(hwnd, msg, wp, lp):
    if msg == win32con.WM_DESTROY:
        cleanup_resources()
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wp, lp)

def create_window():
    try:
        wc = win32gui.WNDCLASS()
        wc.lpszClassName = f"ESPOverlay_{uuid4()}"
        wc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        wc.lpfnWndProc = wnd_proc
        win32gui.RegisterClass(wc)
    except win32gui.error as e:
        print(f"Error registering window class: {e}")
        cleanup_resources()
        sys.exit(1)

    state.hWnd = win32gui.CreateWindowEx(
        win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST,
        wc.lpszClassName,
        "Overlay",
        win32con.WS_POPUP,
        0, 0, state.window_width, state.window_height,
        0, 0, 0, None
    )
    
    win32gui.SetLayeredWindowAttributes(state.hWnd, win32api.RGB(0, 0, 0), 0, win32con.LWA_COLORKEY)
    win32gui.ShowWindow(state.hWnd, win32con.SW_SHOW)
    state.hdc = win32gui.GetDC(state.hWnd)
    state.buffer_hdc = win32gui.CreateCompatibleDC(state.hdc)
    state.buffer_bmp = win32gui.CreateCompatibleBitmap(state.hdc, state.window_width, state.window_height)
    win32gui.SelectObject(state.buffer_hdc, state.buffer_bmp)

# GUI Setup
dpg.create_context()
viewport = dpg.create_viewport(title='ColoramaHack', width=900, height=400, resizable=False, decorated=False, clear_color=[0, 0, 0, 0])

def on_click(x, y, button, pressed):
    if button == mouse.Button.right:
        state.aim_key_pressed = pressed

mouse_listener = mouse.Listener(on_click=on_click)
mouse_listener.start()

# GUI Callbacks
def update_color(sender, app_data, user_data):
    state.config[user_data] = [int(c * 255) for c in app_data[:3]]

def toggle_esp(sender, app_data):
    state.config['esp_enabled'] = app_data
    if not app_data and not state.config['aimbot_enabled']:
        win32gui.FillRect(state.buffer_hdc, (0, 0, state.window_width, state.window_height), win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0)))

def toggle_teammates(sender, app_data): state.config['show_teammates'] = app_data
def set_line_thickness(sender, app_data): state.config['line_thickness'] = int(app_data)
def set_smoothing(sender, app_data): state.config['smoothing'] = app_data
def toggle_aimbot(sender, app_data): state.config['aimbot_enabled'] = app_data
def set_aim_fov(sender, app_data): state.config['aim_fov'] = app_data
def set_aim_smooth(sender, app_data): state.config['aim_smooth'] = app_data
def toggle_aim_target(sender, app_data, user_data): state.config['aim_targets'][user_data] = app_data
def toggle_aim_teammates(sender, app_data): state.config['aim_teammates'] = app_data
def toggle_show_fov(sender, app_data): state.config['show_fov'] = app_data
def toggle_bottom_line(sender, app_data): state.config['draw_bottom_line'] = app_data
def toggle_names(sender, app_data): state.config['show_names'] = app_data
def toggle_health_text(sender, app_data): state.config['show_health_text'] = app_data
def toggle_health_bar(sender, app_data): state.config['show_health_bar'] = app_data
def set_health_bar_position(sender, app_data): state.config['health_bar_position'] = app_data.lower()
def toggle_bones(sender, app_data): state.config['show_bones'] = app_data
def toggle_no_flash(sender, app_data): state.config['no_flash_enabled'] = app_data
def toggle_bhop(sender, app_data): state.config['bhop_enabled'] = app_data
def toggle_fov(sender, app_data): state.config['fov_enabled'] = app_data
def set_fov_value(sender, app_data): state.config['fov_value'] = app_data
def set_kill_delay(sender, app_data): state.config['kill_delay'] = app_data

def save_config(sender, app_data):
    config_name = dpg.get_value("##config_name")
    if config_name:
        with open(os.path.join(CONFIG_DIR, f"{config_name}.json"), 'w') as f:
            json.dump(state.config, f)
        update_config_list()

def load_config(sender, app_data, user_data):
    config_path = os.path.join(CONFIG_DIR, f"{user_data}.json")
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            loaded_config = json.load(f)
            state.config.update(loaded_config)
            for color_key in ['team_color', 'enemy_color', 'name_health_color', 'fov_color', 'bone_color']:
                state.config[color_key] = [max(0, min(255, int(c))) for c in state.config[color_key]]
            update_gui_from_config()

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

def update_gui_from_config():
    dpg.set_value("esp_enabled", state.config['esp_enabled'])
    dpg.set_value("show_teammates", state.config['show_teammates'])
    dpg.set_value("draw_bottom_line", state.config['draw_bottom_line'])
    dpg.set_value("draw_box", state.config['draw_box'])
    dpg.set_value("line_thickness", state.config['line_thickness'])
    dpg.set_value("box_type_selector", state.config['box_type'].capitalize())
    dpg.set_value("aimbot_enabled", state.config['aimbot_enabled'])
    dpg.set_value("aim_fov", state.config['aim_fov'])
    dpg.set_value("aim_smooth", state.config['aim_smooth'])
    dpg.set_value("aim_teammates", state.config['aim_teammates'])
    dpg.set_value("aim_head", state.config['aim_targets']['head'])
    dpg.set_value("aim_chest", state.config['aim_targets']['chest'])
    dpg.set_value("aim_legs", state.config['aim_targets']['legs'])
    dpg.set_value("show_fov", state.config['show_fov'])
    dpg.set_value("show_names", state.config['show_names'])
    dpg.set_value("show_health_text", state.config['show_health_text'])
    dpg.set_value("show_health_bar", state.config['show_health_bar'])
    dpg.set_value("health_bar_position", state.config['health_bar_position'].capitalize())
    dpg.set_value("show_bones", state.config['show_bones'])
    dpg.set_value("no_flash_enabled", state.config['no_flash_enabled'])
    dpg.set_value("bhop_enabled", state.config['bhop_enabled'])
    dpg.set_value("fov_enabled", state.config['fov_enabled'])
    dpg.set_value("fov_value", state.config['fov_value'])
    dpg.set_value("kill_delay", state.config['kill_delay'])
    dpg.set_value("team_color", [x / 255.0 for x in state.config['team_color']] + [1.0])
    dpg.set_value("enemy_color", [x / 255.0 for x in state.config['enemy_color']] + [1.0])
    dpg.set_value("name_health_color", [x / 255.0 for x in state.config['name_health_color']] + [1.0])
    dpg.set_value("fov_color", [x / 255.0 for x in state.config['fov_color']] + [1.0])
    dpg.set_value("bone_color", [x / 255.0 for x in state.config['bone_color']] + [1.0])

# Theme definitions
THEMES = {
    "Default": {
        "WindowBg": (20, 20, 25, 255),
        "Text": (220, 220, 230, 255),
        "Button": (60, 60, 70, 255),
        "ButtonHovered": (80, 80, 100, 255),
        "ButtonActive": (100, 100, 120, 255),
        "FrameBg": (50, 50, 60, 255),
        "FrameBgHovered": (70, 70, 90, 255),
        "FrameBgActive": (90, 90, 110, 255),
        "CheckMark": (0, 255, 255, 255),
        "SliderGrab": (0, 255, 255, 255),
        "SliderGrabActive": (0, 200, 200, 255),
        "Tab": (50, 50, 60, 255),
        "TabHovered": (80, 80, 100, 255),
        "TabActive": (100, 100, 120, 255),
        "ChildBg": (40, 40, 50, 255)
    },
    "Purple": {
        "WindowBg": (25, 20, 35, 255),
        "Text": (200, 180, 255, 255),
        "Button": (80, 60, 120, 255),
        "ButtonHovered": (100, 80, 140, 255),
        "ButtonActive": (120, 100, 160, 255),
        "FrameBg": (45, 40, 55, 255),
        "FrameBgHovered": (65, 60, 75, 255),
        "FrameBgActive": (85, 80, 95, 255),
        "CheckMark": (180, 140, 255, 255),
        "SliderGrab": (180, 140, 255, 255),
        "SliderGrabActive": (160, 120, 235, 255),
        "Tab": (80, 60, 120, 255),
        "TabHovered": (100, 80, 140, 255),
        "TabActive": (120, 100, 160, 255),
        "ChildBg": (35, 30, 45, 255)
    },
    "Neon": {
        "WindowBg": (15, 15, 30, 255),
        "Text": (100, 200, 255, 255),
        "Button": (30, 60, 100, 255),
        "ButtonHovered": (40, 80, 120, 255),
        "ButtonActive": (50, 100, 140, 255),
        "FrameBg": (25, 40, 60, 255),
        "FrameBgHovered": (35, 60, 80, 255),
        "FrameBgActive": (45, 80, 100, 255),
        "CheckMark": (0, 200, 255, 255),
        "SliderGrab": (0, 200, 255, 255),
        "SliderGrabActive": (0, 180, 235, 255),
        "Tab": (30, 60, 100, 255),
        "TabHovered": (40, 80, 120, 255),
        "TabActive": (50, 100, 140, 255),
        "ChildBg": (20, 30, 45, 255)
    },
    "Yellow": {
        "WindowBg": (30, 25, 10, 255),
        "Text": (255, 215, 0, 255),
        "Button": (80, 70, 20, 255),
        "ButtonHovered": (100, 90, 30, 255),
        "ButtonActive": (120, 110, 40, 255),
        "FrameBg": (50, 45, 15, 255),
        "FrameBgHovered": (70, 65, 25, 255),
        "FrameBgActive": (90, 85, 35, 255),
        "CheckMark": (255, 215, 0, 255),
        "SliderGrab": (255, 215, 0, 255),
        "SliderGrabActive": (235, 195, 0, 255),
        "Tab": (80, 70, 20, 255),
        "TabHovered": (100, 90, 30, 255),
        "TabActive": (120, 110, 40, 255),
        "ChildBg": (40, 35, 10, 255)
    },
    "Matrix": {
        "WindowBg": (0, 20, 0, 255),
        "Text": (0, 255, 0, 255),
        "Button": (0, 40, 0, 255),
        "ButtonHovered": (0, 60, 0, 255),
        "ButtonActive": (0, 80, 0, 255),
        "FrameBg": (0, 30, 0, 255),
        "FrameBgHovered": (0, 50, 0, 255),
        "FrameBgActive": (0, 70, 0, 255),
        "CheckMark": (0, 255, 0, 255),
        "SliderGrab": (0, 255, 0, 255),
        "SliderGrabActive": (0, 235, 0, 255),
        "Tab": (0, 40, 0, 255),
        "TabHovered": (0, 60, 0, 255),
        "TabActive": (0, 80, 0, 255),
        "ChildBg": (0, 25, 0, 255)
    }
}

def apply_theme(theme_name):
    theme = THEMES.get(theme_name, THEMES["Default"])
    with dpg.theme() as new_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, theme["WindowBg"])
            dpg.add_theme_color(dpg.mvThemeCol_Text, theme["Text"])
            dpg.add_theme_color(dpg.mvThemeCol_Button, theme["Button"])
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, theme["ButtonHovered"])
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, theme["ButtonActive"])
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, theme["FrameBg"])
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, theme["FrameBgHovered"])
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, theme["FrameBgActive"])
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, theme["CheckMark"])
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, theme["SliderGrab"])
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive, theme["SliderGrabActive"])
            dpg.add_theme_color(dpg.mvThemeCol_Tab, theme["Tab"])
            dpg.add_theme_color(dpg.mvThemeCol_TabHovered, theme["TabHovered"])
            dpg.add_theme_color(dpg.mvThemeCol_TabActive, theme["TabActive"])
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, theme["ChildBg"])
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_ScrollbarSize, 12)
            dpg.add_theme_style(dpg.mvStyleVar_ScrollbarRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_TabRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 12, 12)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 6)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 10, 10)
    dpg.bind_theme(new_theme)

def on_theme_change(sender, app_data):
    apply_theme(app_data)

with dpg.window(label="ColoramaHack", width=900, height=400, no_title_bar=True, no_move=True, no_resize=True, pos=[0, 0]):
    with dpg.tab_bar():
        with dpg.tab(label="ESP"):
            with dpg.group(horizontal=True):
                with dpg.group():
                    dpg.add_checkbox(label="Enable ESP", default_value=state.config['esp_enabled'], callback=toggle_esp, tag="esp_enabled")
                    dpg.add_checkbox(label="Show Teammates", default_value=state.config['show_teammates'], callback=toggle_teammates, tag="show_teammates")
                    dpg.add_checkbox(label="Draw Box", default_value=state.config['draw_box'], callback=lambda s, a: state.config.update({'draw_box': a}), tag="draw_box")
                    dpg.add_checkbox(label="Draw Bottom Line", default_value=state.config['draw_bottom_line'], callback=toggle_bottom_line, tag="draw_bottom_line")
                    dpg.add_checkbox(label="Show Names", default_value=state.config['show_names'], callback=toggle_names, tag="show_names")
                    dpg.add_checkbox(label="Show Health Text", default_value=state.config['show_health_text'], callback=toggle_health_text, tag="show_health_text")
                    dpg.add_checkbox(label="Show Health Bar", default_value=state.config['show_health_bar'], callback=toggle_health_bar, tag="show_health_bar")
                    dpg.add_checkbox(label="Show Bones", default_value=state.config['show_bones'], callback=toggle_bones, tag="show_bones")
                with dpg.group():
                    dpg.add_text("Health Bar Position:")
                    dpg.add_radio_button(items=["Left", "Right"], default_value=state.config['health_bar_position'].capitalize(), callback=set_health_bar_position, tag="health_bar_position")
                    dpg.add_slider_int(label="Line Thickness", min_value=1, max_value=5, default_value=state.config['line_thickness'], callback=set_line_thickness, tag="line_thickness", width=200)
                    dpg.add_text("Box Type:")
                    dpg.add_radio_button(items=["Full", "Corner", "Bottom"], default_value=state.config['box_type'].capitalize(), callback=lambda s, a: state.config.update({'box_type': a.lower()}), tag="box_type_selector")
                with dpg.group():
                    dpg.add_text("Colors:")
                    dpg.add_color_edit(label="Enemy Color", default_value=state.config['enemy_color'], callback=update_color, user_data="enemy_color", width=200, tag="enemy_color")
                    dpg.add_color_edit(label="Team Color", default_value=state.config['team_color'], callback=update_color, user_data="team_color", width=200, tag="team_color")
                    dpg.add_color_edit(label="Name/Health Color", default_value=state.config['name_health_color'], callback=update_color, user_data="name_health_color", width=200, tag="name_health_color")
                    dpg.add_color_edit(label="Bone Color", default_value=state.config['bone_color'], callback=update_color, user_data="bone_color", width=200, tag="bone_color")

        with dpg.tab(label="Aimbot"):
            with dpg.group(horizontal=True):
                with dpg.group():
                    dpg.add_checkbox(label="Enable Aimbot", default_value=state.config['aimbot_enabled'], callback=toggle_aimbot, tag="aimbot_enabled")
                    dpg.add_checkbox(label="Aim at Teammates", default_value=state.config['aim_teammates'], callback=toggle_aim_teammates, tag="aim_teammates")
                    dpg.add_text("Aim Targets:")
                    with dpg.group(horizontal=True):
                        dpg.add_checkbox(label="Head", default_value=state.config['aim_targets']['head'], callback=toggle_aim_target, user_data="head", tag="aim_head")
                        dpg.add_checkbox(label="Chest", default_value=state.config['aim_targets']['chest'], callback=toggle_aim_target, user_data="chest", tag="aim_chest")
                        dpg.add_checkbox(label="Legs", default_value=state.config['aim_targets']['legs'], callback=toggle_aim_target, user_data="legs", tag="aim_legs")
                with dpg.group():
                    dpg.add_slider_int(label="FOV", min_value=1, max_value=180, default_value=state.config['aim_fov'], callback=set_aim_fov, tag="aim_fov", width=200)
                    dpg.add_slider_int(label="Smoothness", min_value=0, max_value=10, default_value=state.config['aim_smooth'], callback=set_aim_smooth, tag="aim_smooth", width=200)
                    dpg.add_slider_float(label="Delay After Kill", min_value=0.0, max_value=2.0, default_value=state.config['kill_delay'], callback=set_kill_delay, tag="kill_delay", width=200)

        with dpg.tab(label="Misc"):
            with dpg.group(horizontal=True):
                with dpg.group():
                    dpg.add_text("Theme Selection")
                    dpg.add_combo(list(THEMES.keys()), default_value="Default", callback=on_theme_change, width=200)
                    apply_theme("Default")  # Apply default theme on startup
                    dpg.add_separator()
                    dpg.add_checkbox(label="No Flash", default_value=state.config['no_flash_enabled'], callback=toggle_no_flash, tag="no_flash_enabled")
                    dpg.add_checkbox(label="Bunny Hop", default_value=state.config['bhop_enabled'], callback=toggle_bhop, tag="bhop_enabled")
                    dpg.add_checkbox(label="Custom FOV", default_value=state.config['fov_enabled'], callback=toggle_fov, tag="fov_enabled")
                    dpg.add_slider_float(label="FOV Value", min_value=50.0, max_value=160.0, default_value=state.config['fov_value'], callback=set_fov_value, tag="fov_value", width=150)
                    dpg.add_checkbox(label="Show FOV Circle", default_value=state.config['show_fov'], callback=toggle_show_fov, tag="show_fov", pos=[10, 300])
                    dpg.add_color_edit(label="FOV Circle Color", default_value=state.config['fov_color'], callback=update_color, user_data="fov_color", width=150, tag="fov_color")
            dpg.add_text("Made By SA1DEN | Version 1.0.3", color=(150, 150, 150, 255), pos=[10, 360])

        with dpg.tab(label="Config"):
            with dpg.group(horizontal=True):
                with dpg.group():
                    dpg.add_input_text(hint="Enter config name", width=200, tag="##config_name")
                    dpg.add_button(label="Save Config", callback=save_config, width=150)
                with dpg.group():
                    with dpg.child_window(height=295, tag="config_list"):
                        update_config_list()

dpg.setup_dearpygui()
dpg.show_viewport()

def w2s(mtx, posx, posy, posz, width, height):
    screenW = (mtx[12] * posx) + (mtx[13] * posy) + (mtx[14] * posz) + mtx[15]
    if screenW > 0.001:
        screenX = (mtx[0] * posx) + (mtx[1] * posy) + (mtx[2] * posz) + mtx[3]
        screenY = (mtx[4] * posx) + (mtx[5] * posy) + (mtx[6] * posz) + mtx[7]
        camX, camY = width / 2, height / 2
        x = camX + (camX * screenX / screenW)
        y = camY - (camY * screenY / screenW)
        return [x, y]
    return [-999, -999]

def connect_to_game():
    try:
        state.pm = pymem.Pymem("cs2.exe")
        state.client = pymem.process.module_from_name(state.pm.process_handle, "client.dll").lpBaseOfDll
        state.game_window = get_game_window()
        return True
    except pymem.exception.PymemError:
        return False

def send_mouse_input(dx, dy):
    input_struct = INPUT()
    input_struct.type = INPUT_MOUSE
    input_struct.mi.dx = dx
    input_struct.mi.dy = dy
    input_struct.mi.dwFlags = MOUSEEVENTF_MOVE
    user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(input_struct))

def draw_line(hdc, x1, y1, x2, y2, color, thickness):
    if not hdc:
        return
    # Ensure coordinates are within valid bounds
    max_coord = 32767  # Maximum value for 32-bit signed integer
    x1 = max(-max_coord, min(max_coord, int(x1)))
    y1 = max(-max_coord, min(max_coord, int(y1)))
    x2 = max(-max_coord, min(max_coord, int(x2)))
    y2 = max(-max_coord, min(max_coord, int(y2)))
    
    try:
        pen = win32gui.CreatePen(win32con.PS_SOLID, thickness, win32api.RGB(*color))
        old_pen = win32gui.SelectObject(hdc, pen)
        win32gui.MoveToEx(hdc, x1, y1)
        win32gui.LineTo(hdc, x2, y2)
        win32gui.SelectObject(hdc, old_pen)
        win32gui.DeleteObject(pen)
    except Exception:
        pass

def draw_rect(hdc, x, y, width, height, color, thickness, filled=False):
    if not hdc:
        return
    pen = win32gui.CreatePen(win32con.PS_SOLID, thickness, win32api.RGB(*color))
    old_pen = win32gui.SelectObject(hdc, pen)
    brush = win32gui.CreateSolidBrush(win32api.RGB(*color) if filled else win32api.RGB(0, 0, 0))
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
        draw_rect(hdc, x, y + i, width, 1, [r, g, b], 1, filled=True)

def draw_text(hdc, x, y, text, color, scale=1.0):
    if not hdc:
        return
    font = win32ui.CreateFont({"name": "Arial Black", "height": int(20 * scale), "weight": 700})
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
    return min(1.0, max(0.6, height / 200))

def get_closest_enemy_target(local_pos):
    closest_dist = float('inf')
    target_screen = None
    target_pos = None
    try:
        view_matrix = [state.pm.read_float(state.client + dwViewMatrix + i * 4) for i in range(16)]
        local_game_scene = state.pm.read_longlong(local_pos + m_pGameSceneNode)
        local_bone_matrix = state.pm.read_longlong(local_game_scene + m_modelState + 0x80)
        local_head = [
            state.pm.read_float(local_bone_matrix + 6 * 0x20),
            state.pm.read_float(local_bone_matrix + 6 * 0x20 + 0x4),
            state.pm.read_float(local_bone_matrix + 6 * 0x20 + 0x8)
        ]
    except pymem.exception.PymemError:
        return None, None

    target_bones = []
    if state.config['aim_targets']['head']:
        target_bones.append(('head', 6))
    if state.config['aim_targets']['chest']:
        target_bones.append(('chest', 4))
    if state.config['aim_targets']['legs']:
        target_bones.append(('legs', 23))

    if not target_bones:
        return None, None

    for i in range(64):
        try:
            entity = state.pm.read_longlong(state.client + dwEntityList)
            if not entity:
                continue
            list_entry = state.pm.read_longlong(entity + ((8 * (i & 0x7FFF) >> 9) + 16))
            if not list_entry:
                continue
            entity_controller = state.pm.read_longlong(list_entry + 120 * (i & 0x1FF))
            if not entity_controller:
                continue
            entity_controller_pawn = state.pm.read_longlong(entity_controller + m_hPlayerPawn)
            if not entity_controller_pawn:
                continue
            list_entry = state.pm.read_longlong(entity + (0x8 * ((entity_controller_pawn & 0x7FFF) >> 9) + 16))
            if not list_entry:
                continue
            entity_pawn_addr = state.pm.read_longlong(list_entry + 120 * (entity_controller_pawn & 0x1FF))
            if not entity_pawn_addr or entity_pawn_addr == local_pos:
                continue
            entity_alive = state.pm.read_int(entity_pawn_addr + m_lifeState)
            if entity_alive != 256:
                entity_id = f"{entity_pawn_addr}_{i}"
                if entity_id in state.player_positions:
                    state.last_kill_time = time.time()
                continue
            entity_team = state.pm.read_int(entity_pawn_addr + m_iTeamNum)
            local_team = state.pm.read_int(local_pos + m_iTeamNum)
            if entity_team == local_team and not state.config['aim_teammates']:
                continue
            game_scene = state.pm.read_longlong(entity_pawn_addr + m_pGameSceneNode)
            bone_matrix = state.pm.read_longlong(game_scene + m_modelState + 0x80)

            for bone_name, bone_id in target_bones:
                pos = [
                    state.pm.read_float(bone_matrix + bone_id * 0x20),
                    state.pm.read_float(bone_matrix + bone_id * 0x20 + 0x4),
                    state.pm.read_float(bone_matrix + bone_id * 0x20 + 0x8)
                ]
                screen_pos = w2s(view_matrix, pos[0], pos[1], pos[2], state.window_width, state.window_height)
                if screen_pos[0] == -999:
                    continue
                center_x, center_y = state.window_width // 2, state.window_height // 2
                delta_x = screen_pos[0] - center_x
                delta_y = screen_pos[1] - center_y
                dist = math.sqrt(delta_x**2 + delta_y**2)
                if dist < closest_dist and dist < (state.config['aim_fov'] / 180.0 * state.window_width / 2):
                    closest_dist = dist
                    target_screen = screen_pos
                    target_pos = pos
        except pymem.exception.PymemError:
            continue
    return target_screen, target_pos

def draw_player_esp(hdc, view_matrix, local_player_team, entity_pawn_addr, entity_controller, index):
    try:
        entity_alive = state.pm.read_int(entity_pawn_addr + m_lifeState)
        if entity_alive != 256:
            return
        entity_team = state.pm.read_int(entity_pawn_addr + m_iTeamNum)
        if entity_team == local_player_team and not state.config['show_teammates']:
            return

        health = min(max(state.pm.read_int(entity_pawn_addr + m_iHealth), 0), 100)
        name_ptr = state.pm.read_longlong(entity_controller + m_sSanitizedPlayerName)
        player_name = state.pm.read_string(name_ptr, 32) if name_ptr else f"Player_{index}"
        if not player_name.strip():
            player_name = f"Player_{index}"

        color = state.config['team_color'] if entity_team == local_player_team else state.config['enemy_color']
        game_scene = state.pm.read_longlong(entity_pawn_addr + m_pGameSceneNode)
        bone_matrix = state.pm.read_longlong(game_scene + m_modelState + 0x80)

        bone_indices = {
            'head': 6, 'neck': 5, 'chest': 4, 'stomach': 3,
            'left_shoulder': 8, 'left_elbow': 9, 'left_hand': 10,
            'right_shoulder': 13, 'right_elbow': 14, 'right_hand': 15,
            'left_hip': 22, 'left_knee': 23, 'left_foot': 24,
            'right_hip': 25, 'right_knee': 26, 'right_foot': 27
        }

        bone_positions = {}
        for bone_name, bone_id in bone_indices.items():
            boneX = state.pm.read_float(bone_matrix + bone_id * 0x20)
            boneY = state.pm.read_float(bone_matrix + bone_id * 0x20 + 0x4)
            boneZ = state.pm.read_float(bone_matrix + bone_id * 0x20 + 0x8)
            pos = w2s(view_matrix, boneX, boneY, boneZ, state.window_width, state.window_height)
            if pos[0] != -999:
                bone_positions[bone_name] = pos

        head_pos = bone_positions.get('head', [-999, -999])
        leg_pos = bone_positions.get('right_foot', [-999, -999])
        if head_pos[0] == -999 or leg_pos[0] == -999:
            return

        player_id = f"{entity_pawn_addr}_{index}"
        smoothing_factor = state.config['smoothing']
        state.current_ids.append(player_id)
        if player_id in state.player_positions:
            old_head_x, old_head_y, old_leg_x, old_leg_y = state.player_positions[player_id]
            head_pos[0] = old_head_x * (1 - smoothing_factor) + head_pos[0] * smoothing_factor
            head_pos[1] = old_head_y * (1 - smoothing_factor) + head_pos[1] * smoothing_factor
            leg_pos[0] = old_leg_x * (1 - smoothing_factor) + leg_pos[0] * smoothing_factor
            leg_pos[1] = old_leg_y * (1 - smoothing_factor) + leg_pos[1] * smoothing_factor
        state.player_positions[player_id] = (head_pos[0], head_pos[1], leg_pos[0], leg_pos[1])

        deltaZ = abs(head_pos[1] - leg_pos[1]) * 1.3
        box_width = deltaZ // 3
        leftX = head_pos[0] - box_width
        rightX = head_pos[0] + box_width
        topY = head_pos[1] - deltaZ * 0.15
        bottomY = leg_pos[1] + deltaZ * 0.15

        if state.config['draw_box']:
            if state.config['box_type'] == 'full':
                draw_line(hdc, leftX, bottomY, rightX, bottomY, color, state.config['line_thickness'])
                draw_line(hdc, leftX, bottomY, leftX, topY, color, state.config['line_thickness'])
                draw_line(hdc, rightX, bottomY, rightX, topY, color, state.config['line_thickness'])
                draw_line(hdc, leftX, topY, rightX, topY, color, state.config['line_thickness'])
            elif state.config['box_type'] == 'corner':
                corner_size = box_width // 2
                draw_line(hdc, leftX, topY, leftX + corner_size, topY, color, state.config['line_thickness'])
                draw_line(hdc, leftX, topY, leftX, topY + corner_size, color, state.config['line_thickness'])
                draw_line(hdc, rightX, topY, rightX - corner_size, topY, color, state.config['line_thickness'])
                draw_line(hdc, rightX, topY, rightX, topY + corner_size, color, state.config['line_thickness'])
                draw_line(hdc, leftX, bottomY, leftX + corner_size, bottomY, color, state.config['line_thickness'])
                draw_line(hdc, leftX, bottomY, leftX, bottomY - corner_size, color, state.config['line_thickness'])
                draw_line(hdc, rightX, bottomY, rightX - corner_size, bottomY, color, state.config['line_thickness'])
                draw_line(hdc, rightX, bottomY, rightX, bottomY - corner_size, color, state.config['line_thickness'])
            elif state.config['box_type'] == 'bottom':
                draw_line(hdc, leftX, bottomY, rightX, bottomY, color, state.config['line_thickness'])
                draw_line(hdc, leftX, bottomY, leftX, bottomY - deltaZ//2, color, state.config['line_thickness'])
                draw_line(hdc, rightX, bottomY, rightX, bottomY - deltaZ//2, color, state.config['line_thickness'])

        if state.config['draw_bottom_line']:
            bottom_center_x = (leftX + rightX) / 2
            draw_line(hdc, state.window_width//2, state.window_height, bottom_center_x, bottomY, color, state.config['line_thickness'])

        if state.config['show_bones']:
            skeleton_color = state.config['bone_color']
            bone_thickness = 2
            bone_pairs = [
                ('head', 'neck'), ('neck', 'chest'), ('chest', 'stomach'),
                ('chest', 'left_shoulder'), ('left_shoulder', 'left_elbow'), ('left_elbow', 'left_hand'),
                ('chest', 'right_shoulder'), ('right_shoulder', 'right_elbow'), ('right_elbow', 'right_hand'),
                ('stomach', 'left_hip'), ('left_hip', 'left_knee'), ('left_knee', 'left_foot'),
                ('stomach', 'right_hip'), ('right_hip', 'right_knee'), ('right_knee', 'right_foot')
            ]
            for start, end in bone_pairs:
                if start in bone_positions and end in bone_positions:
                    draw_line(hdc, bone_positions[start][0], bone_positions[start][1], 
                             bone_positions[end][0], bone_positions[end][1], skeleton_color, bone_thickness)

        scale = calculate_scale(head_pos, leg_pos)
        
        if state.config['show_names'] or state.config['show_health_text'] or state.config['show_health_bar']:
            bar_width = 5 * scale
            bar_height = deltaZ
            bar_y_top = topY
            bar_y_bottom = bottomY
            bar_x = leftX - bar_width - 5 * scale if state.config['health_bar_position'] == 'left' else rightX + 5 * scale

            if state.config['show_names']:
                name_width = len(player_name) * 8 * scale
                name_x = head_pos[0] - (name_width / 2)
                name_y = topY - 20 * scale
                draw_text(hdc, name_x, name_y, player_name[:16], state.config['name_health_color'], scale)

            if state.config['show_health_bar']:
                draw_rect(hdc, bar_x, bar_y_top, bar_width, bar_height, [85, 85, 85], 1, filled=True)
                health_height = (health / 100.0) * bar_height
                draw_gradient_rect(hdc, bar_x, bar_y_bottom - health_height, bar_width, health_height, health)

            if state.config['show_health_text']:
                health_pos_x = leftX - bar_width - 40 * scale if state.config['health_bar_position'] == 'left' else rightX + bar_width + 15 * scale
                health_pos_y = (topY + bottomY) / 2 - 10 * scale
                draw_text(hdc, health_pos_x, health_pos_y, f"{health}", state.config['name_health_color'], scale)
    except pymem.exception.PymemError:
        pass

def draw_esp_and_aim():
    if not state.running or state.pm is None or state.client is None or state.hdc is None or state.hWnd is None or state.buffer_hdc is None:
        return

    if not state.game_window:
        state.game_window = get_game_window()

    is_minimized = state.game_window and win32gui.IsIconic(state.game_window)
    if is_minimized and not state.config['esp_enabled'] and not state.config['aimbot_enabled']:
        return

    try:
        win32gui.FillRect(state.buffer_hdc, (0, 0, state.window_width, state.window_height), win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0)))
    except Exception:
        return

    try:
        view_matrix = [state.pm.read_float(state.client + dwViewMatrix + i * 4) for i in range(16)]
        local_player_pawn_addr = state.pm.read_longlong(state.client + dwLocalPlayerPawn)
        if not local_player_pawn_addr:
            return
        local_player_team = state.pm.read_int(local_player_pawn_addr + m_iTeamNum)
    except pymem.exception.PymemError:
        return

    state.current_ids = []
    fov_radius = (state.config['aim_fov'] / 180.0) * state.window_width / 2

    if state.config['show_fov'] and state.config['esp_enabled'] and not is_minimized:
        draw_oval(state.buffer_hdc, 
                  state.window_width//2 - fov_radius, state.window_height//2 - fov_radius,
                  state.window_width//2 + fov_radius, state.window_height//2 + fov_radius,
                  state.config['fov_color'], 2)

    if state.config['esp_enabled']:
        entity_list = state.pm.read_longlong(state.client + dwEntityList)
        if not entity_list:
            return

        for i in range(64):
            try:
                list_entry = state.pm.read_longlong(entity_list + ((8 * (i & 0x7FFF) >> 9) + 16))
                if not list_entry:
                    continue
                entity_controller = state.pm.read_longlong(list_entry + 120 * (i & 0x1FF))
                if not entity_controller:
                    continue
                entity_controller_pawn = state.pm.read_longlong(entity_controller + m_hPlayerPawn)
                if not entity_controller_pawn:
                    continue
                list_entry_pawn = state.pm.read_longlong(entity_list + (0x8 * ((entity_controller_pawn & 0x7FFF) >> 9) + 16))
                if not list_entry_pawn:
                    continue
                entity_pawn_addr = state.pm.read_longlong(list_entry_pawn + 120 * (entity_controller_pawn & 0x1FF))
                if not entity_pawn_addr or entity_pawn_addr == local_player_pawn_addr:
                    continue
                if not is_minimized:
                    draw_player_esp(state.buffer_hdc, view_matrix, local_player_team, entity_pawn_addr, entity_controller, i)
                else:
                    # Update player positions even when minimized
                    draw_player_esp(None, view_matrix, local_player_team, entity_pawn_addr, entity_controller, i)
            except pymem.exception.PymemError:
                continue

    if state.config['aimbot_enabled'] and state.aim_key_pressed:
        if time.time() - state.last_kill_time < state.config['kill_delay']:
            pass
        else:
            target_screen, target_pos = get_closest_enemy_target(local_player_pawn_addr)
            if target_screen and target_pos:
                try:
                    center_x, center_y = state.window_width // 2, state.window_height // 2
                    dx = int(target_screen[0] - center_x)
                    dy = int(target_screen[1] - center_y)
                    if abs(dx) < state.window_width and abs(dy) < state.window_height:
                        if state.config['aim_smooth'] == 0:
                            send_mouse_input(dx, dy)
                        else:
                            smooth_factor = 1.0 + state.config['aim_smooth'] * 0.5
                            dx = int(dx / smooth_factor)
                            dy = int(dy / smooth_factor)
                            send_mouse_input(dx, dy)
                except pymem.exception.PymemError:
                    pass

    for player_id in list(state.player_positions.keys()):
        if player_id not in state.current_ids:
            del state.player_positions[player_id]

    if not is_minimized:
        try:
            win32gui.BitBlt(state.hdc, 0, 0, state.window_width, state.window_height, state.buffer_hdc, 0, 0, win32con.SRCCOPY)
        except Exception:
            pass

def bhop_thread():
    last_space_time = 0
    debounce_interval = 0.04
    while state.running:
        current_time = time.perf_counter()
        if (state.config['bhop_enabled'] and state.game_window and 
            win32gui.GetForegroundWindow() == state.game_window and 
            not win32gui.IsIconic(state.game_window)):
            if keyboard.is_pressed('space') and (current_time - last_space_time) > debounce_interval:
                keyboard.press('space')
                time.sleep(0.01)
                keyboard.release('space')
                last_space_time = current_time
        else:
            keyboard.release('space')
        time.sleep(0.005)

def update():
    while state.running:
        start_time = time.perf_counter()
        try:
            if state.pm is None or state.client is None:
                if not connect_to_game():
                    time.sleep(1)
                    continue
            if state.hdc is None or state.hWnd is None or state.buffer_hdc is None or not win32gui.IsWindow(state.hWnd):
                create_window()

            if state.config['no_flash_enabled']:
                local_player_pawn_addr = state.pm.read_longlong(state.client + dwLocalPlayerPawn)
                if local_player_pawn_addr:
                    state.pm.write_float(local_player_pawn_addr + m_flFlashMaxAlpha, 0.0)
            else:
                local_player_pawn_addr = state.pm.read_longlong(state.client + dwLocalPlayerPawn)
                if local_player_pawn_addr:
                    state.pm.write_float(local_player_pawn_addr + m_flFlashMaxAlpha, state.original_flash_alpha)

            pointer_base = state.client + 0x01A4B378
            intermediate_address = state.pm.read_longlong(pointer_base)
            if intermediate_address:
                fov_address = intermediate_address + 0x130
                try:
                    if state.config['fov_enabled']:
                        state.pm.write_float(fov_address, float(state.config['fov_value']))
                    else:
                        state.pm.write_float(fov_address, 0.0)
                except pymem.exception.PymemError:
                    pass

            draw_esp_and_aim()
            dpg.render_dearpygui_frame()
            if state.hWnd and win32gui.IsWindow(state.hWnd):
                win32gui.UpdateWindow(state.hWnd)
            else:
                create_window()
        except pymem.exception.PymemError:
            connect_to_game()
        except Exception as e:
            print(f"Error in update loop: {e}")
            cleanup_resources()
            sys.exit(1)

        elapsed = time.perf_counter() - start_time
        time.sleep(max(0, UPDATE_INTERVAL - elapsed))

if __name__ == "__main__":
    try:
        create_window()
        update_thread = threading.Thread(target=update, daemon=True)
        update_thread.start()
        bhop_thread = threading.Thread(target=bhop_thread, daemon=True)
        bhop_thread.start()
        while state.running:
            try:
                win32gui.PumpMessages()
            except Exception as e:
                print(f"Error in PumpMessages: {e}")
                cleanup_resources()
                sys.exit(1)
    except KeyboardInterrupt:
        close_program()
    except Exception as e:
        print(f"Error: {e}")
        close_program()