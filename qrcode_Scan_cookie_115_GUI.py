#!/usr/bin/env python3
# encoding: utf-8

"扫码获取 115 cookie (GUI Version)"

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 5) # Version updated for GUI layout fix
__all__ = [
    "AppEnum", "get_qrcode_token", "get_qrcode_status", "post_qrcode_result",
    "get_qrcode", "login_with_qrcode",
]

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from enum import Enum
from json import loads
from urllib.parse import urlencode
from urllib.request import urlopen, Request, URLError
from urllib.error import HTTPError
import io
import threading
import time
from PIL import Image, ImageTk # Requires Pillow: pip install Pillow

# --- Core 115 API Functions (Mostly unchanged) ---

# Define AppEnum globally so it's accessible everywhere
AppEnum = Enum("AppEnum", "web, android, ios, linux, mac, windows, tv, alipaymini, wechatmini, qandroid")

def get_enum_name(val, cls):
    if isinstance(val, cls):
        return val.name
    try:
        if isinstance(val, str):
            return cls[val].name
    except KeyError:
        pass
    # Attempt to get name by value if string lookup fails
    try:
        return cls(val).name
    except ValueError:
        # Handle cases where val might not be a valid enum member (name or value)
        raise ValueError(f"'{val}' is not a valid member or name in {cls.__name__}") from None


def get_qrcode_token():
    """获取登录二维码，扫码可用
    GET https://qrcodeapi.115.com/api/1.0/web/1.0/token/
    :return: dict
    """
    api = "https://qrcodeapi.115.com/api/1.0/web/1.0/token/"
    try:
        # Added User-Agent as some APIs might require it
        req = Request(api, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as response:
            return loads(response.read())
    except (URLError, HTTPError, TimeoutError) as e:
        raise ConnectionError(f"Failed to get QR code token: {e}")
    except Exception as e:
        raise RuntimeError(f"An unexpected error occurred getting token: {e}")


def get_qrcode_status(payload):
    """获取二维码的状态（未扫描、已扫描、已登录、已取消、已过期等）
    GET https://qrcodeapi.115.com/get/status/
    :param payload: 请求的查询参数，取自 `login_qrcode_token` 接口响应，有 3 个
        - uid:  str
        - time: int
        - sign: str
    :return: dict
    """
    api = "https://qrcodeapi.115.com/get/status/?" + urlencode(payload)
    try:
        req = Request(api, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=5) as response: # Shorter timeout for status checks
            return loads(response.read())
    except TimeoutError:
        return {"state": True, "data": {"status": 0}} # Mimic a 'waiting' response
    except (URLError, HTTPError) as e:
        print(f"Warning: Failed to get QR code status: {e}")
        return {"state": False, "error": str(e), "data": {"status": -99}} # Custom status for network error
    except Exception as e:
        print(f"Warning: Unexpected error during status check: {e}")
        return {"state": False, "error": str(e), "data": {"status": -99}}

def post_qrcode_result(uid, app="windows"):
    """获取扫码登录的结果，并且绑定设备，包含 cookie
    POST https://passportapi.115.com/app/1.0/{app}/1.0/login/qrcode/
    :param uid: 二维码的 uid，取自 `login_qrcode_token` 接口响应
    :param app: 扫码绑定的设备 (string name like 'windows', 'web', etc.)
    :return: dict，包含 cookie
    """
    try:
        app_name = get_enum_name(app, AppEnum)
    except ValueError as e:
        raise ValueError(f"Invalid app type provided: {app}") from e

    payload = {"app": app_name, "account": uid}
    api = f"https://passportapi.115.com/app/1.0/{app_name}/1.0/login/qrcode/"
    req = Request(
        api,
        data=urlencode(payload).encode("utf-8"),
        method="POST",
        headers={"User-Agent": "Mozilla/5.0"} # Add User-Agent
    )
    try:
        with urlopen(req, timeout=10) as response:
            return loads(response.read())
    except (URLError, HTTPError, TimeoutError) as e:
        raise ConnectionError(f"Failed to post QR code result for app '{app_name}': {e}")
    except Exception as e:
        raise RuntimeError(f"An unexpected error occurred posting result for app '{app_name}': {e}")

def get_qrcode(uid):
    """获取二维码图片数据
    :return: bytes containing the image data
    """
    url = f"https://qrcodeapi.115.com/api/1.0/mac/1.0/qrcode?uid={uid}"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as response:
            return response.read()
    except (URLError, HTTPError, TimeoutError) as e:
        raise ConnectionError(f"Failed to download QR code image: {e}")
    except Exception as e:
        raise RuntimeError(f"An unexpected error occurred downloading QR image: {e}")

# --- GUI Application Class ---

class QRCodeLoginApp:
    def __init__(self, master):
        self.master = master
        master.title("115 扫码登录")
        # Adjusted height slightly, might need fine-tuning
        master.geometry("450x680")
        master.resizable(False, False)

        self.qrcode_token = None
        self.polling_active = False
        self.poll_thread = None
        self._stop_event = threading.Event()

        # Style
        self.style = ttk.Style()
        self.style.configure("TLabel", padding=5)
        self.style.configure("TButton", padding=5)
        self.style.configure("TCombobox", padding=5)

        # --- App Type Selection ---
        self.app_selection_frame = ttk.Frame(master)
        self.app_selection_frame.pack(fill=tk.X, padx=10, pady=(10, 0))

        self.app_type_label = ttk.Label(self.app_selection_frame, text="选择 App 类型:")
        self.app_type_label.pack(side=tk.LEFT, padx=(0, 5))

        app_names = [app.name for app in AppEnum]
        self.selected_app_type_var = tk.StringVar()
        self.app_type_combo = ttk.Combobox(
            self.app_selection_frame,
            textvariable=self.selected_app_type_var,
            values=app_names,
            state="readonly",
            width=15
        )
        self.app_type_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.app_type_combo.set("windows")

        # --- QR Code Area (Using a Frame for fixed size) ---
        qr_frame_width = 270 # Desired width for the QR code area (adjust as needed)
        qr_frame_height = 270 # Desired height for the QR code area (adjust as needed)

        self.qr_frame = ttk.Frame(
            master,
            width=qr_frame_width,
            height=qr_frame_height,
            relief=tk.GROOVE, # Add a border to visualize the frame
            borderwidth=2
        )
        self.qr_frame.pack(pady=10, padx=10)
        # Prevent the frame from shrinking to fit its contents
        self.qr_frame.pack_propagate(False)

        # QR Code Image Label (placed inside the frame)
        self.qr_image_label = ttk.Label(self.qr_frame, text="点击 '获取二维码' 开始", anchor=tk.CENTER)
        self.qr_photo_image = None # Keep reference
        # Pack the label inside the frame, allowing it to center
        self.qr_image_label.pack(expand=True, fill=tk.BOTH)

        # --- Status Label ---
        self.status_label = ttk.Label(master, text="状态: 未开始", anchor=tk.W, relief=tk.SUNKEN)
        self.status_label.pack(fill=tk.X, padx=10, pady=5)

        # --- Cookie Text Area ---
        self.cookie_label = ttk.Label(master, text="获取到的 Cookie:", anchor=tk.W)
        self.cookie_label.pack(fill=tk.X, padx=10, pady=(5, 0))
        self.cookie_text = scrolledtext.ScrolledText(master, height=8, wrap=tk.WORD, state=tk.DISABLED) # Reduced height slightly
        self.cookie_text.pack(pady=(0, 10), padx=10, fill=tk.BOTH, expand=True)

        # --- Buttons Frame ---
        self.buttons_frame = ttk.Frame(master)
        self.buttons_frame.pack(fill=tk.X, padx=10, pady=5)

        self.get_qr_button = ttk.Button(self.buttons_frame, text="获取二维码", command=self.start_login_process)
        self.get_qr_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = ttk.Button(self.buttons_frame, text="停止", command=self.stop_polling, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        self.close_button = ttk.Button(self.buttons_frame, text="关闭", command=self.close_app)
        self.close_button.pack(side=tk.RIGHT, padx=5)

        master.protocol("WM_DELETE_WINDOW", self.close_app)

    def update_status(self, message):
        current_message = message
        self.master.after(0, lambda: self.status_label.config(text=f"状态: {current_message}"))

    def display_qr_code(self, image_data):
        try:
            img = Image.open(io.BytesIO(image_data))
            # Resize image to fit the frame nicely, maintaining aspect ratio
            img.thumbnail((self.qr_frame.winfo_reqwidth() - 10, self.qr_frame.winfo_reqheight() - 10), Image.Resampling.LANCZOS) # Use frame size, leave some padding

            self.qr_photo_image = ImageTk.PhotoImage(img)
            current_photo = self.qr_photo_image
            # Update the label inside the frame
            self.master.after(0, lambda: self.qr_image_label.config(image=current_photo, text="")) # Remove placeholder text
        except Exception as e:
            self.show_error(f"无法显示二维码: {e}")
            # Reset label text in case of error
            self.master.after(0, lambda: self.qr_image_label.config(image=None, text="无法显示二维码"))

    def display_cookies(self, cookie_dict):
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
        def _update_text():
            self.cookie_text.config(state=tk.NORMAL)
            self.cookie_text.delete(1.0, tk.END)
            self.cookie_text.insert(tk.END, cookie_str)
            self.cookie_text.config(state=tk.DISABLED)
        self.master.after(0, _update_text)

    def show_error(self, message):
        current_message = message
        self.master.after(0, lambda: messagebox.showerror("错误", current_message))
        self.update_status(f"错误: {current_message.splitlines()[0]}")

    def show_info(self, message):
        current_message = message
        self.master.after(0, lambda: messagebox.showinfo("信息", current_message))

    def set_ui_state(self, state):
        if state == 'running':
            self.get_qr_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.app_type_combo.config(state=tk.DISABLED)
        elif state == 'finished' or state == 'idle':
            self.get_qr_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.app_type_combo.config(state="readonly")
            self.polling_active = False

    def start_login_process(self):
        if self.polling_active:
            self.show_info("登录流程已在进行中。")
            return

        self.current_app_type = self.selected_app_type_var.get()
        if not self.current_app_type:
             self.show_error("请先选择一个 App 类型！")
             return

        self.set_ui_state('running')
        self.update_status("正在获取二维码...")
        self.cookie_text.config(state=tk.NORMAL)
        self.cookie_text.delete(1.0, tk.END)
        self.cookie_text.config(state=tk.DISABLED)
        # Reset QR image label text
        self.master.after(0, lambda: self.qr_image_label.config(image=None, text="正在加载..."))
        self._stop_event.clear()

        self.poll_thread = threading.Thread(target=self._login_thread_func, daemon=True)
        self.poll_thread.start()

    def _login_thread_func(self):
        self.polling_active = True
        selected_app = self.current_app_type
        try:
            # 1. Get QR Code Token
            self.update_status("获取 Token...")
            token_resp = get_qrcode_token()
            if not token_resp or not token_resp.get("state"):
                err_msg = token_resp.get('msg') or token_resp.get('error', '未知错误')
                raise RuntimeError(f"获取 Token 失败: {err_msg}")
            self.qrcode_token = token_resp["data"]
            if "qrcode" not in self.qrcode_token or "uid" not in self.qrcode_token:
                 raise RuntimeError(f"Token 响应格式不正确: {self.qrcode_token}")
            qrcode_content = self.qrcode_token.pop("qrcode")
            uid = self.qrcode_token["uid"]

            # 2. Get QR Code Image
            self.update_status("下载二维码图片...")
            qr_image_data = get_qrcode(uid)
            self.display_qr_code(qr_image_data) # Update GUI

            # 3. Poll for Status
            self.update_status("等待扫码...")
            start_time = time.monotonic()
            timeout_seconds = 180 # 3 minutes timeout

            while self.polling_active and not self._stop_event.is_set():
                if time.monotonic() - start_time > timeout_seconds:
                    raise RuntimeError("扫码超时，请重新获取二维码。")

                time.sleep(2)
                if self._stop_event.is_set(): break

                try:
                    status_resp = get_qrcode_status(self.qrcode_token)
                except Exception as poll_err:
                    self.update_status(f"轮询错误: {poll_err}")
                    time.sleep(3)
                    continue

                if self._stop_event.is_set(): break

                if not status_resp:
                    self.update_status("错误: 轮询状态收到空响应")
                    continue

                if not status_resp.get("state"):
                    err_msg = status_resp.get('msg') or status_resp.get('error', '轮询状态失败')
                    self.update_status(f"错误: {err_msg}")
                    # Potentially check for specific fatal errors here
                    continue

                status_data = status_resp.get("data", {})
                status = status_data.get("status")
                status_msg = status_data.get("msg", "")

                if status == 0:
                    self.update_status("等待扫码...")
                elif status == 1:
                    self.update_status("已扫描，请在手机上确认登录...")
                elif status == 2:
                    self.update_status("已确认登录! 获取 Cookie...")
                    # 4. Get Login Result (Cookies)
                    login_result = post_qrcode_result(uid, selected_app)
                    if login_result and login_result.get("state"):
                        cookies = login_result.get("data", {}).get("cookie", {})
                        if not cookies:
                             raise RuntimeError(f"获取 Cookie 成功，但 Cookie 为空。响应: {login_result}")
                        self.display_cookies(cookies)
                        self.update_status("登录成功!")
                        self.show_info(f"登录成功！({selected_app} App) Cookie 已显示。")
                    else:
                        err_msg = login_result.get('msg') or login_result.get('error', '未知错误')
                        raise RuntimeError(f"获取 Cookie 失败 ({selected_app} App): {err_msg}")
                    break # Exit polling loop on success
                elif status == -1:
                    raise RuntimeError(f"二维码已过期 ({status_msg})，请重新获取。")
                elif status == -2:
                    raise RuntimeError(f"已取消登录 ({status_msg})。")
                elif status == -99:
                    self.update_status(f"网络错误，重试中... ({status_resp.get('error')})")
                else:
                    self.update_status(f"未知状态: {status}, data: {status_data}")
                    print(f"Warning: Unknown QR status encountered: {status_resp}")


            if self._stop_event.is_set():
                 self.update_status("操作已停止。")

        except (ConnectionError, RuntimeError, ValueError, Exception) as e:
            self.show_error(f"登录过程中发生错误:\n{e}")
        finally:
            self.polling_active = False
            self.master.after(0, lambda: self.set_ui_state('finished'))

    def stop_polling(self):
        if self.poll_thread and self.poll_thread.is_alive():
            self._stop_event.set()
            self.update_status("正在停止...")
        else:
             self.update_status("没有活动进程可以停止。")
        self.master.after(0, lambda: self.set_ui_state('finished'))


    def close_app(self):
        self.stop_polling()
        if self.poll_thread and self.poll_thread.is_alive():
             time.sleep(0.1)
        self.master.destroy()


# --- Main Execution Block ---

if __name__ == "__main__":
    root = tk.Tk()
    app = QRCodeLoginApp(root)
    root.mainloop()
