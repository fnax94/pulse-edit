"""License activation dialog."""

import customtkinter as ctk
from app.licensing import lemon, storage
from app.i18n import t


class LicenseDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title(t("activation_title"))
        self.geometry("400x280")
        self.resizable(False, False)
        self.licensed = False

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 400) // 2
        y = (self.winfo_screenheight() - 280) // 2
        self.geometry(f"400x280+{x}+{y}")

        self.grab_set()

        ctk.CTkLabel(self, text=t("app_title"), font=("", 22, "bold")).pack(pady=(20, 5))
        ctk.CTkLabel(self, text=t("enter_key")).pack(pady=(0, 15))

        self.key_entry = ctk.CTkEntry(self, width=320,
                                       placeholder_text="XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX")
        self.key_entry.pack(pady=5)

        self.activate_btn = ctk.CTkButton(self, text=t("activate_btn"),
                                           command=self._activate, width=200)
        self.activate_btn.pack(pady=15)

        self.status_label = ctk.CTkLabel(self, text="", text_color="gray")
        self.status_label.pack(pady=5)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _activate(self):
        key = self.key_entry.get().strip()
        if not key:
            self.status_label.configure(text=t("please_enter_key"), text_color="orange")
            return

        self.activate_btn.configure(state="disabled", text=t("verifying"))
        self.status_label.configure(text="", text_color="gray")
        self.update()

        valid, message = lemon.verify_license(key)

        if valid:
            storage.save_license(key)
            self.status_label.configure(text=t("license_activated"), text_color="green")
            self.licensed = True
            self.after(800, self.destroy)
        else:
            self.status_label.configure(text=message, text_color="red")
            self.activate_btn.configure(state="normal", text=t("activate_btn"))

    def _on_close(self):
        self.destroy()
