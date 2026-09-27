from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional, Set

import rag_core as core

# ============================================================
# VEXA LOCAL — Paleta Premium (Azul Medianoche y Oro)
# ============================================================

BG = "#0F141E"          
BG_2 = "#151B29"        
PANEL = "#1C2436"       
CARD = "#242E45"        
CARD_2 = "#2D3956"      
INPUT = "#0A0D14"       
BORDER = "#354261"      
ACCENT = "#D4AF37"      
ACCENT_HOVER = "#F5D670"
ACCENT_DIM = "#4A3E1B"  
TEXT = "#F8F9FA"        
TEXT_2 = "#B3BCCD"      
MUTED = "#73809C"       
FAINT = "#425070"       
DANGER = "#E57373"      
SUCCESS = "#81C784"     

F_TITLE = ("Georgia", 22, "bold")
F_SUBTITLE = ("Georgia", 11, "italic")
F_SECTION = ("Segoe UI", 10, "bold")
F_LABEL = ("Segoe UI", 10)
F_LABEL_B = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)
F_SMALL_B = ("Segoe UI", 9, "bold")
F_CHAT = ("Segoe UI", 11)


# ============================================================
# INSERCIÓN DE TEXTO (Preparado para HTML)
# ============================================================

def insertar_texto_en_chat(widget: tk.Text, texto: str, es_usuario: bool):
    widget.config(state="normal")
    widget.delete("1.0", "end")

    base_font = F_CHAT
    widget.tag_configure("normal", font=base_font, foreground=TEXT)
    
    widget.insert("end", texto, ("normal",))
    widget.config(state="disabled")

    widget.update_idletasks()
    try:
        dlines = widget.count("1.0", "end", "displaylines")
        num_filas = dlines[0] if dlines else 1
    except Exception:
        num_filas = int(widget.index("end-1c").split(".")[0])

    widget.config(height=max(1, num_filas))


# ============================================================
# SEGURIDAD Y PIN
# ============================================================

CARPETA_CONFIG = Path.home() / ".vexa_local"
ARCHIVO_CONFIG = CARPETA_CONFIG / "config.json"


def existe_pin_configurado() -> bool:
    return ARCHIVO_CONFIG.exists()


def guardar_pin(pin: str) -> None:
    CARPETA_CONFIG.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_hex(16)
    ARCHIVO_CONFIG.write_text(
        json.dumps({"salt": salt, "pin_hash": hashlib.sha256((salt + pin).encode("utf-8")).hexdigest()}),
        encoding="utf-8",
    )


def verificar_pin(pin: str) -> bool:
    if not ARCHIVO_CONFIG.exists():
        return False
    datos = json.loads(ARCHIVO_CONFIG.read_text(encoding="utf-8"))
    return hashlib.sha256((datos["salt"] + pin).encode("utf-8")).hexdigest() == datos["pin_hash"]


class PinInput(tk.Frame):
    def __init__(self, parent, digits=4, on_submit=None, **kwargs):
        super().__init__(parent, bg=PANEL, **kwargs)
        self.digits = digits
        self.on_submit = on_submit
        self.entries: List[tk.Entry] = []
        self.vars: List[tk.StringVar] = []

        for i in range(digits):
            var = tk.StringVar()
            box = tk.Frame(self, bg=PANEL, width=48, height=48)
            box.pack_propagate(False)
            box.pack(side="left", padx=5)

            canvas = tk.Canvas(box, bg=PANEL, highlightthickness=0, bd=0)
            canvas.pack(fill="both", expand=True)

            canvas.create_oval(2, 2, 46, 46, outline=ACCENT, width=1.5, fill=INPUT)

            entry = tk.Entry(
                canvas, textvariable=var, show="●", font=("Segoe UI", 16, "bold"),
                bg=INPUT, fg=TEXT, bd=0, justify="center",
                highlightthickness=0, insertbackground=ACCENT
            )
            entry.place(x=9, y=8, width=30, height=30)

            self.entries.append(entry)
            self.vars.append(var)

            entry.bind("", lambda e, idx=i: self._on_key(e, idx))
            entry.bind("", lambda e, idx=i: self._on_keypress(e, idx))

    def _on_keypress(self, event, idx):
        if event.keysym == "BackSpace" and not self.vars[idx].get() and idx > 0:
            self.entries[idx - 1].focus()
            self.vars[idx - 1].set("")

    def _on_key(self, event, idx):
        val = self.vars[idx].get().strip()

        if len(val) > 1:
            self.vars[idx].set(val[-1])
            val = val[-1]

        if val and not val.isdigit():
            self.vars[idx].set("")
            return

        if val and idx < self.digits - 1:
            self.entries[idx + 1].focus()

        if event.keysym == "Return" and self.on_submit:
            self.on_submit()

    def get(self) -> str:
        return "".join(v.get().strip() for v in self.vars)

    def clear(self):
        for v in self.vars:
            v.set("")
        if self.entries:
            self.entries[0].focus()

    def focus(self):
        if self.entries:
            self.entries[0].focus()


# ============================================================
# HELPERS VISUALES
# ============================================================

def pill_button(parent, text, command, bg=CARD_2, fg=TEXT, hover=BORDER,
                font=F_SMALL_B, padx=14, pady=7):
    btn = tk.Label(
        parent, text=text, bg=bg, fg=fg, font=font,
        padx=padx, pady=pady, cursor="hand2",
    )
    btn._normal_bg = bg
    btn._hover_bg = hover
    btn._enabled = True

    def enter(_):
        if btn._enabled:
            btn.configure(bg=btn._hover_bg)

    def leave(_):
        if btn._enabled:
            btn.configure(bg=btn._normal_bg)

    def click(_):
        if btn._enabled:
            command()

    btn.bind("", enter)
    btn.bind("", leave)
    btn.bind("", click)
    return btn


def set_enabled(btn, enabled: bool):
    btn._enabled = enabled
    if enabled:
        btn.configure(bg=btn._normal_bg, fg=btn.cget("fg"), cursor="hand2")
    else:
        btn.configure(bg=BORDER, fg=FAINT, cursor="arrow")


def make_pill_dropdown(parent, variable, values):
    shell = tk.Frame(
        parent, bg=BORDER, height=42,
        highlightthickness=0, cursor="hand2",
    )
    shell.pack_propagate(False)

    inner = tk.Frame(shell, bg=INPUT)
    inner.place(x=1, y=1, relwidth=1, relheight=1, width=-2, height=-2)

    label = tk.Label(
        inner, textvariable=variable,
        bg=INPUT, fg=TEXT, font=F_SMALL_B,
        anchor="w", padx=15, cursor="hand2",
    )
    label.pack(side="left", fill="both", expand=True)

    arrow = tk.Label(
        inner, text="⌄", bg=INPUT, fg=ACCENT,
        font=("Segoe UI Symbol", 15, "bold"),
        width=3, cursor="hand2",
    )
    arrow.pack(side="right", fill="y")

    menu = tk.Menu(
        parent, tearoff=False, bg=CARD, fg=TEXT,
        activebackground=CARD_2, activeforeground=TEXT,
        bd=0, relief="flat", font=F_SMALL,
    )

    for value in values:
        menu.add_command(label=value, command=lambda v=value: variable.set(v))

    def open_menu(_=None):
        x = shell.winfo_rootx()
        y = shell.winfo_rooty() + shell.winfo_height() + 5
        menu.tk_popup(x, y)

    for widget in (shell, inner, label, arrow):
        widget.bind("", open_menu)

    return shell


def separator(parent):
    return tk.Frame(parent, bg=BORDER, height=1)


# ============================================================
# SCROLL DEL CHAT
# ============================================================

class ChatScrollable(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview,
            style="Vexa.Vertical.TScrollbar",
        )
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("", self._update_region)
        self.canvas.bind("", self._resize_inner)
        self.canvas.bind("", self._bind_mousewheel)
        self.canvas.bind("", self._unbind_mousewheel)

    def _update_region(self, _=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_inner(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _bind_mousewheel(self, _=None):
        self.canvas.bind_all("", self._wheel)

    def _unbind_mousewheel(self, _=None):
        self.canvas.unbind_all("")

    def _wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120) * 2, "units")

    def bottom(self):
        self.update_idletasks()
        self._update_region()
        self.canvas.yview_moveto(1.0)

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self.canvas.yview_moveto(0)


# ============================================================
# DRAG & DROP
# ============================================================

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

BaseTk = TkinterDnD.Tk if DND_AVAILABLE else tk.Tk


# ============================================================
# APLICACIÓN PRINCIPAL
# ============================================================

class VexaLocalApp(BaseTk):
    def __init__(self):
        super().__init__()
        self.title("Vexa - Asistente Profesional")
        self.geometry("1280x780")
        self.minsize(980, 620)
        self.configure(bg=BG)

        self._setup_styles()

        self.indice = core.IndiceDocumental()
        self.rutas_documentos: List[str] = []
        self.documentos_seleccionados: Set[str] = set()
        self.modelo_var = tk.StringVar(value=core.MODELOS_DISPONIBLES[0])
        self.burbuja_escribiendo = None
        self.pills_frame = None
        self.doc_cards_frame = None
        self.drop_zone = None

        self._mostrar_login()

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Vexa.Vertical.TScrollbar",
            background=CARD, troughcolor=BG,
            bordercolor=BG, arrowcolor=BG, relief="flat",
        )
        style.map("Vexa.Vertical.TScrollbar", background=[("active", ACCENT_DIM)])

    # --------------------------------------------------------
    # Login y Seguridad
    # --------------------------------------------------------

    def _mostrar_login(self):
        self.login = tk.Frame(self, bg=BG)
        self.login.place(relx=0.5, rely=0.5, anchor="center")

        card = tk.Frame(self.login, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, padx=2, pady=2)
        card.pack()

        inner = tk.Frame(card, bg=PANEL, padx=58, pady=46)
        inner.pack()

        tk.Label(inner, text="VEXA", font=("Georgia", 28, "bold"), bg=PANEL, fg=ACCENT).pack(pady=(2, 3))
        tk.Label(inner, text="ENTORNO EJECUTIVO", font=F_SUBTITLE, bg=PANEL, fg=TEXT_2).pack(pady=(0, 26))

        separator(inner).pack(fill="x", pady=(0, 25))

        first = not existe_pin_configurado()

        if first:
            tk.Label(
                inner, text="Bienvenido. Configure un PIN de seguridad de 4 dígitos para resguardar su información.",
                font=F_SMALL, bg=PANEL, fg=TEXT_2, wraplength=300, justify="center",
            ).pack(pady=(0, 18))

            tk.Label(inner, text="NUEVO PIN", font=F_SECTION, bg=PANEL, fg=TEXT).pack(anchor="w")
            self.pin_input1 = PinInput(inner, digits=4)
            self.pin_input1.pack(pady=(8, 14))

            tk.Label(inner, text="CONFIRMAR PIN", font=F_SECTION, bg=PANEL, fg=TEXT).pack(anchor="w")
            self.pin_input2 = PinInput(inner, digits=4, on_submit=self._crear_pin)
            self.pin_input2.pack(pady=(8, 20))

            self.login_btn = pill_button(
                inner, "Configurar y Entrar  ➔", self._crear_pin,
                bg=ACCENT, fg="#111", hover=ACCENT_HOVER,
                font=F_LABEL_B, padx=28, pady=11,
            )
            self.login_btn.pack(fill="x")
        else:
            tk.Label(inner, text="INGRESE SU PIN", font=F_SECTION, bg=PANEL, fg=TEXT).pack(anchor="w")
            self.pin_input1 = PinInput(inner, digits=4, on_submit=self._validar_pin)
            self.pin_input1.pack(pady=(12, 20))

            self.login_btn = pill_button(
                inner, "Acceder al Sistema  ➔", self._validar_pin,
                bg=ACCENT, fg="#111", hover=ACCENT_HOVER,
                font=F_LABEL_B, padx=28, pady=11,
            )
            self.login_btn.pack(fill="x")

        self.login_error = tk.Label(inner, text=" ", font=F_SMALL, bg=PANEL, fg=DANGER)
        self.login_error.pack(pady=(13, 0))

        self.pin_input1.focus()

    def _crear_pin(self):
        p1 = self.pin_input1.get()
        p2 = self.pin_input2.get()

        if len(p1) < 4 or not p1.isdigit():
            self.login_error.config(text="El PIN debe contener 4 dígitos.")
            return
        if p1 != p2:
            self.login_error.config(text="Los PIN ingresados no coinciden.")
            return

        guardar_pin(p1)
        self._start_app()

    def _validar_pin(self):
        pin = self.pin_input1.get()
        if verificar_pin(pin):
            self._start_app()
        else:
            self.login_error.config(text="PIN incorrecto. Intente nuevamente.")
            self.pin_input1.clear()

    def _start_app(self):
        self.login.destroy()
        self._build_main()

    # --------------------------------------------------------
    # Interfaz principal
    # --------------------------------------------------------

    def _build_main(self):
        root = tk.Frame(self, bg=BG)
        root.pack(fill="both", expand=True)

        # Sidebar
        sidebar = tk.Frame(root, bg=PANEL, width=315)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Frame(root, bg=BORDER, width=1).pack(side="left", fill="y")

        sb = tk.Frame(sidebar, bg=PANEL, padx=22, pady=24)
        sb.pack(fill="both", expand=True)

        top = tk.Frame(sb, bg=PANEL)
        top.pack(fill="x")

        tk.Label(top, text="VEXA", font=("Georgia", 19, "bold"), bg=PANEL, fg=TEXT).pack(side="left")
        tk.Label(top, text="WORKSPACE", font=F_SECTION, bg=PANEL, fg=ACCENT).pack(side="left", padx=(8, 0), pady=(5, 0))

        tk.Label(sb, text="GESTOR DOCUMENTAL", font=F_SECTION, bg=PANEL, fg=TEXT).pack(anchor="w", pady=(28, 2))
        tk.Label(
            sb, text="Añada los documentos que desea consultar. El procesamiento es seguro y local.",
            font=F_SMALL, bg=PANEL, fg=MUTED, wraplength=265, justify="left",
        ).pack(anchor="w", pady=(0, 12))

        # Drop Zone
        self.drop_zone = tk.Frame(
            sb, bg=INPUT, height=105,
            highlightthickness=1, highlightbackground=BORDER, cursor="hand2",
        )
        self.drop_zone.pack(fill="x", pady=(0, 12))
        self.drop_zone.pack_propagate(False)

        tk.Label(self.drop_zone, text="+", font=("Georgia", 24), bg=INPUT, fg=ACCENT).pack(pady=(12, 0))
        tk.Label(self.drop_zone, text="Arrastrar PDF / Word", font=F_SMALL_B, bg=INPUT, fg=TEXT_2).pack()
        tk.Label(self.drop_zone, text="o haga clic para explorar", font=F_SMALL, bg=INPUT, fg=FAINT).pack(pady=(1, 0))

        self.drop_zone.bind("", lambda e: self._subir_documentos())

        if DND_AVAILABLE:
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind("<>", self._drop_files)
            for child in self.drop_zone.winfo_children():
                child.drop_target_register(DND_FILES)
                child.dnd_bind("<>", self._drop_files)

        # Header documentos
        docs_header = tk.Frame(sb, bg=PANEL)
        docs_header.pack(fill="x", pady=(2, 6))
        tk.Label(docs_header, text="ARCHIVOS CARGADOS", font=("Segoe UI", 8, "bold"), bg=PANEL, fg=FAINT).pack(side="left")
        self.docs_count_label = tk.Label(docs_header, text="0", font=F_SMALL_B, bg=PANEL, fg=ACCENT)
        self.docs_count_label.pack(side="right")

        self.doc_cards_frame = tk.Frame(sb, bg=PANEL)
        self.doc_cards_frame.pack(fill="x")

        self.btn_procesar = pill_button(
            sb, "Procesar Documentos", self._procesar_documentos_thread,
            bg=ACCENT, fg="#111", hover=ACCENT_HOVER, font=F_LABEL_B, padx=14, pady=10,
        )
        self.btn_procesar.pack(fill="x", pady=(12, 0))

        self.estado = tk.Label(sb, text="", font=F_SMALL, bg=PANEL, fg=SUCCESS, wraplength=265, justify="left")
        self.estado.pack(fill="x", pady=(9, 0))

        separator(sb).pack(fill="x", pady=18)

        tk.Label(sb, text="MOTOR DE INTELIGENCIA", font=F_SECTION, bg=PANEL, fg=TEXT).pack(anchor="w")
        tk.Label(sb, text="Procesamiento local mediante Ollama", font=F_SMALL, bg=PANEL, fg=FAINT).pack(anchor="w", pady=(2, 8))

        self.modelo_dropdown = make_pill_dropdown(sb, self.modelo_var, core.MODELOS_DISPONIBLES)
        self.modelo_dropdown.pack(fill="x")

        separator(sb).pack(fill="x", pady=18)

        self.btn_clear = pill_button(
            sb, "Limpiar Conversación", self._limpiar_chat,
            bg=PANEL, fg=TEXT_2, hover=CARD, font=F_SMALL, padx=5, pady=8,
        )
        self.btn_clear.pack(fill="x", side="bottom")

        # Chat Area
        chat_area = tk.Frame(root, bg=BG)
        chat_area.pack(side="left", fill="both", expand=True)

        header = tk.Frame(chat_area, bg=BG, padx=34, pady=22)
        header.pack(fill="x")

        title_row = tk.Frame(header, bg=BG)
        title_row.pack(fill="x")

        tk.Label(title_row, text="Asistente Ejecutivo", font=F_TITLE, bg=BG, fg=TEXT).pack(side="left")

        tk.Label(
            header, text="Consulte su base documental corporativa con privacidad garantizada.",
            font=F_SUBTITLE, bg=BG, fg=MUTED,
        ).pack(anchor="w", pady=(2, 0))

        separator(chat_area).pack(fill="x")

        chat_frame = tk.Frame(chat_area, bg=BG, padx=26)
        chat_frame.pack(fill="both", expand=True)

        self.chat = ChatScrollable(chat_frame)
        self.chat.pack(fill="both", expand=True, pady=(14, 8))

        self._agregar_bienvenida()

        # Input Area
        bottom = tk.Frame(chat_area, bg=BG, padx=26, pady=16)
        bottom.pack(fill="x")

        selected_header = tk.Frame(bottom, bg=BG)
        selected_header.pack(fill="x", pady=(0, 7))

        tk.Label(selected_header, text="CONTEXTO ACTIVO:", font=("Segoe UI", 8, "bold"), bg=BG, fg=FAINT).pack(side="left")

        self.selection_hint = tk.Label(selected_header, text="Todos los documentos", font=("Segoe UI", 8), bg=BG, fg=MUTED)
        self.selection_hint.pack(side="right")

        self.pills_frame = tk.Frame(bottom, bg=BG)
        self.pills_frame.pack(fill="x", pady=(0, 8))

        input_shell = tk.Frame(bottom, bg=INPUT, highlightthickness=1, highlightbackground=BORDER)
        input_shell.pack(fill="x")

        self.entry_pregunta = tk.Entry(
            input_shell, bg=INPUT, fg=TEXT, insertbackground=ACCENT,
            relief="flat", bd=0, highlightthickness=0, font=F_CHAT,
        )
        self.entry_pregunta.pack(side="left", fill="x", expand=True, ipady=14, padx=(17, 8))
        self.entry_pregunta.insert(0, "Escriba su consulta aquí...")
        self.entry_pregunta.bind("", self._limpiar_placeholder)
        self.entry_pregunta.bind("", self._restaurar_placeholder)
        self.entry_pregunta.bind("", lambda e: self._enviar_pregunta())

        self.btn_enviar = pill_button(
            input_shell, "Enviar", self._enviar_pregunta,
            bg=ACCENT, fg="#111", hover=ACCENT_HOVER,
            font=F_SMALL_B, padx=24, pady=9,
        )
        self.btn_enviar.pack(side="right", padx=6, pady=6)

        self._refresh_document_cards()
        self._refresh_selected_pills()

    def _limpiar_placeholder(self, event):
        if self.entry_pregunta.get() == "Escriba su consulta aquí...":
            self.entry_pregunta.delete(0, "end")
            self.entry_pregunta.config(fg=TEXT)

    def _restaurar_placeholder(self, event):
        if not self.entry_pregunta.get().strip():
            self.entry_pregunta.insert(0, "Escriba su consulta aquí...")
            self.entry_pregunta.config(fg=MUTED)

    # --------------------------------------------------------
    # Manejo de documentos
    # --------------------------------------------------------

    def _drop_files(self, event):
        try:
            rutas = list(self.tk.splitlist(event.data))
        except Exception:
            rutas = [event.data]
        self._agregar_rutas(rutas)

    def _subir_documentos(self):
        rutas = filedialog.askopenfilenames(
            parent=self,
            title="Seleccione uno o varios documentos",
            filetypes=[
                ("Documentos soportados", "*.pdf *.docx"),
                ("PDF", "*.pdf"),
                ("Word", "*.docx"),
            ],
        )
        self._agregar_rutas(rutas)

    def _agregar_rutas(self, rutas):
        aceptadas = []
        for ruta in rutas:
            ruta = str(ruta).strip().strip("{}")
            if not ruta or not ruta.lower().endswith((".pdf", ".docx")):
                continue
            if ruta not in self.rutas_documentos:
                self.rutas_documentos.append(ruta)
                self.documentos_seleccionados.add(ruta)
                aceptadas.append(ruta)

        if aceptadas:
            self.estado.config(
                text=f"{len(aceptadas)} archivo(s) agregado(s).",
                fg=TEXT_2,
            )
            self._refresh_document_cards()
            self._refresh_selected_pills()

    def _toggle_documento(self, ruta):
        if ruta in self.documentos_seleccionados:
            self.documentos_seleccionados.remove(ruta)
        else:
            self.documentos_seleccionados.add(ruta)

        self._refresh_document_cards()
        self._refresh_selected_pills()

    def _quitar_documento(self, ruta):
        if ruta in self.rutas_documentos:
            self.rutas_documentos.remove(ruta)
        self.documentos_seleccionados.discard(ruta)
        self._refresh_document_cards()
        self._refresh_selected_pills()

    def _refresh_document_cards(self):
        if self.doc_cards_frame is None:
            return

        for child in self.doc_cards_frame.winfo_children():
            child.destroy()

        self.docs_count_label.config(text=str(len(self.rutas_documentos)))

        if not self.rutas_documentos:
            tk.Label(
                self.doc_cards_frame, text="Sin documentos cargados.",
                font=F_SMALL, bg=PANEL, fg=FAINT, pady=8,
            ).pack(anchor="w")
            return

        for ruta in self.rutas_documentos:
            selected = ruta in self.documentos_seleccionados
            name = os.path.basename(ruta)
            ext = Path(name).suffix.lower().replace(".", "").upper()

            card = tk.Frame(
                self.doc_cards_frame,
                bg=CARD_2 if selected else CARD,
                highlightthickness=1,
                highlightbackground=ACCENT_DIM if selected else BORDER,
                cursor="hand2",
            )
            card.pack(fill="x", pady=3)

            icon = tk.Label(
                card, text="PDF" if ext == "PDF" else "DOC",
                font=("Segoe UI", 7, "bold"),
                bg=ACCENT_DIM if selected else PANEL, fg=TEXT if selected else TEXT_2,
                padx=6, pady=4,
            )
            icon.pack(side="left", padx=(7, 7), pady=7)

            text_frame = tk.Frame(card, bg=card.cget("bg"))
            text_frame.pack(side="left", fill="x", expand=True, pady=6)

            tk.Label(text_frame, text=name, font=F_SMALL_B, bg=card.cget("bg"), fg=TEXT, anchor="w").pack(fill="x")
            tk.Label(
                text_frame,
                text="Activo en búsqueda" if selected else "Excluido",
                font=("Segoe UI", 8), bg=card.cget("bg"),
                fg=SUCCESS if selected else FAINT, anchor="w",
            ).pack(fill="x")

            remove = tk.Label(card, text="✕", font=("Segoe UI", 12), bg=card.cget("bg"), fg=FAINT, cursor="hand2")
            remove.pack(side="right", padx=10)

            def bind_all(widget, path=ruta):
                widget.bind("", lambda e: self._toggle_documento(path))

            for widget in (card, icon, text_frame):
                bind_all(widget)
            for child in text_frame.winfo_children():
                bind_all(child)

            remove.bind("", lambda e, path=ruta: self._quitar_documento(path))

    def _refresh_selected_pills(self):
        if self.pills_frame is None:
            return

        for child in self.pills_frame.winfo_children():
            child.destroy()

        if not self.documentos_seleccionados:
            self.selection_hint.config(text="Todos los documentos", fg=MUTED)
            return

        self.selection_hint.config(
            text=f"{len(self.documentos_seleccionados)} Archivos seleccionados", fg=SUCCESS,
        )

        for ruta in self.documentos_seleccionados:
            name = os.path.basename(ruta)
            if len(name) > 30:
                name = name[:27] + "..."

            pill = tk.Frame(self.pills_frame, bg=CARD_2, highlightthickness=1, highlightbackground=BORDER)
            pill.pack(side="left", padx=(0, 7), pady=1)

            tk.Label(pill, text=f"  {name}", font=("Segoe UI", 8, "bold"), bg=CARD_2, fg=TEXT, padx=4, pady=5).pack(side="left")
            close = tk.Label(pill, text="✕", font=("Segoe UI", 10), bg=CARD_2, fg=TEXT_2, cursor="hand2", padx=5, pady=4)
            close.pack(side="left")
            close.bind("", lambda e, path=ruta: self._toggle_documento(path))

    # --------------------------------------------------------
    # Procesamiento en segundo plano
    # --------------------------------------------------------

    def _procesar_documentos_thread(self):
        if not self.rutas_documentos:
            messagebox.showwarning("Atención", "Por favor, añada al menos un archivo PDF o DOCX.")
            return

        set_enabled(self.btn_procesar, False)
        self.btn_procesar.config(text="Procesando...")
        self.estado.config(text="Extrayendo texto y construyendo índice...", fg=TEXT_2)

        threading.Thread(target=self._procesar_documentos, daemon=True).start()

    def _procesar_documentos(self):
        try:
            indice = core.procesar_documentos(self.rutas_documentos)
            self.indice = indice
            self.after(
                0,
                lambda: self._fin_proceso(
                    f"Completado. {len(self.rutas_documentos)} archivo(s) listos para consulta.", True,
                ),
            )
        except Exception as exc:
            self.after(0, lambda: self._fin_proceso(f"Error en el procesamiento: {exc}", False))

    def _fin_proceso(self, mensaje, ok):
        self.estado.config(text=mensaje, fg=SUCCESS if ok else DANGER)
        self.btn_procesar.config(text="Procesar Documentos")
        set_enabled(self.btn_procesar, True)

    # --------------------------------------------------------
    # Chat y renderizado visual
    # --------------------------------------------------------

    def _agregar_bienvenida(self):
        self._agregar_mensaje(
            "Vexa",
            "Bienvenido a su entorno de trabajo seguro.\n\n"
            "Puede comenzar añadiendo documentos en el panel lateral izquierdo. "
            "Una vez procesados, podré asistirle respondiendo preguntas o resumiendo la información contenida en ellos.\n\n"
            "Toda la información se mantiene estrictamente en su equipo local.",
            False,
        )

    def _agregar_mensaje(self, remitente, texto, es_usuario):
        row = tk.Frame(self.chat.inner, bg=BG)
        row.pack(fill="x", pady=(10, 5), padx=4)

        wrap = tk.Frame(row, bg=BG)
        wrap.pack(anchor="e" if es_usuario else "w", padx=(120 if es_usuario else 0, 0))

        head = tk.Frame(wrap, bg=BG)
        head.pack(anchor="e" if es_usuario else "w")

        tk.Label(head, text=remitente, font=F_SMALL_B, bg=BG, fg=TEXT if es_usuario else ACCENT).pack(side="left")
        tk.Label(head, text=time.strftime("%H:%M"), font=("Segoe UI", 8), bg=BG, fg=MUTED).pack(side="left", padx=(7, 0))

        bubble_bg = CARD_2 if es_usuario else CARD
        bubble_border = BORDER

        bubble = tk.Frame(wrap, bg=bubble_bg, highlightthickness=1, highlightbackground=bubble_border)
        bubble.pack(anchor="e" if es_usuario else "w", pady=(6, 0))

        msg_text = tk.Text(
            bubble, bg=bubble_bg, fg=TEXT, bd=0, highlightthickness=0,
            wrap="word", relief="flat", spacing1=4, spacing2=4, spacing3=4,
            cursor="arrow", width=75,
        )
        msg_text.pack(padx=20, pady=16, fill="x", expand=True)

        insertar_texto_en_chat(msg_text, texto, es_usuario)

        self.chat.bottom()
        return row

    def _agregar_fuentes(self, fuentes):
        if not fuentes:
            return

        row = tk.Frame(self.chat.inner, bg=BG)
        row.pack(fill="x", pady=(2, 6), padx=12)

        tk.Label(row, text="Fuentes consultadas:", font=("Segoe UI", 8, "bold"), bg=BG, fg=TEXT_2).pack(anchor="w")

        for fuente in fuentes:
            tk.Label(
                row, text=f"• {fuente}", font=("Segoe UI", 9), bg=BG, fg=MUTED,
                wraplength=650, justify="left",
            ).pack(anchor="w", padx=10)

        self.chat.bottom()

    def _mostrar_escribiendo(self):
        self.burbuja_escribiendo = self._agregar_mensaje("Vexa", "Analizando documentos...", False)

    def _ocultar_escribiendo(self):
        if self.burbuja_escribiendo:
            self.burbuja_escribiendo.destroy()
            self.burbuja_escribiendo = None

    def _enviar_pregunta(self):
        pregunta = self.entry_pregunta.get().strip()
        if not pregunta or pregunta == "Escriba su consulta aquí...":
            return

        self.entry_pregunta.delete(0, "end")
        self._agregar_mensaje("Usted", pregunta, True)

        if self.indice.esta_vacio():
            self._agregar_mensaje(
                "Vexa",
                "Aún no ha procesado ningún documento. Por favor, añada sus archivos y haga clic en 'Procesar Documentos' antes de consultar.",
                False,
            )
            return

        set_enabled(self.btn_enviar, False)
        self._mostrar_escribiendo()

        seleccion = set(self.documentos_seleccionados)

        threading.Thread(
            target=self._responder_pregunta,
            args=(pregunta, seleccion), daemon=True,
        ).start()

    def _responder_pregunta(self, pregunta, seleccion):
        modelo = self.modelo_var.get()

        if seleccion:
            indice_consulta = core.indice_filtrado_por_documentos(self.indice, seleccion)
        else:
            indice_consulta = self.indice

        top_k = core.determinar_top_k(pregunta, total_chunks=len(indice_consulta.chunks))
        fragmentos = core.buscar_contexto_relevante(pregunta, indice_consulta, top_k=top_k)

        try:
            respuesta = core.consultar_llm(pregunta=pregunta, fragmentos=fragmentos, modelo=modelo)
        except Exception as exc:
            respuesta = f"Ha ocurrido un error de conexión con el motor LLM.\n\nModelo: {modelo}\nDetalle: {exc}"

        fuentes = sorted({c.fuente for c in fragmentos})

        def finalizar():
            self._ocultar_escribiendo()
            self._agregar_mensaje("Vexa", respuesta, False)
            self._agregar_fuentes(fuentes)
            set_enabled(self.btn_enviar, True)

        self.after(0, finalizar)

    def _limpiar_chat(self):
        self.chat.clear()
        self._agregar_bienvenida()


if __name__ == "__main__":
    app = VexaLocalApp()
    app.mainloop()