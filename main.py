import os
import json
import hashlib
import pathlib
import copy
import webview
import rag_core

CARPETA_CONFIG = pathlib.Path.home() / ".vexa_local"
ARCHIVO_CONFIG = CARPETA_CONFIG / "config.json"

def existe_pin_configurado() -> bool:
    return ARCHIVO_CONFIG.exists()

def guardar_pin(pin: str) -> None:
    CARPETA_CONFIG.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(16).hex()
    ARCHIVO_CONFIG.write_text(
        json.dumps({"salt": salt, "pin_hash": hashlib.sha256((salt + pin).encode("utf-8")).hexdigest()}),
        encoding="utf-8",
    )

def verificar_pin(pin: str) -> bool:
    if not ARCHIVO_CONFIG.exists():
        return False
    datos = json.loads(ARCHIVO_CONFIG.read_text(encoding="utf-8"))
    return hashlib.sha256((datos["salt"] + pin).encode("utf-8")).hexdigest() == datos["pin_hash"]


def chunk_es_de_archivo(chunk, nombre_archivo: str) -> bool:
    """Inspecciona el objeto chunk para verificar si proviene del archivo dado."""
    if hasattr(chunk, '__dict__'):
        contenido = str(chunk.__dict__).lower()
    else:
        contenido = str(chunk).lower()
    return nombre_archivo.lower() in contenido


class API:
    def __init__(self):
        self.window = None
        self.indice = None
        self.archivos_cargados = []

    def set_window(self, window):
        self.window = window

    def requiere_pin(self):
        return existe_pin_configurado()

    def validar_o_crear_pin(self, pin):
        if not existe_pin_configurado():
            if len(pin) == 4 and pin.isdigit():
                guardar_pin(pin)
                return {"ok": True, "mensaje": "PIN configurado con éxito."}
            return {"ok": False, "mensaje": "El PIN debe ser de 4 dígitos numéricos."}
        else:
            if verificar_pin(pin):
                return {"ok": True, "mensaje": "Acceso concedido."}
            return {"ok": False, "mensaje": "PIN incorrecto."}

    def procesar_rutas(self, rutas):
        if not rutas:
            return {"ok": False, "mensaje": "No se recibieron archivos.", "archivos": self.archivos_cargados}

        try:
            self.indice = rag_core.procesar_documentos(rutas)
            nuevos = [os.path.basename(r) for r in rutas]
            for n in nuevos:
                if n not in self.archivos_cargados:
                    self.archivos_cargados.append(n)

            return {
                "ok": True,
                "mensaje": f"Procesados {len(nuevos)} archivo(s). Sistema listo.",
                "archivos": self.archivos_cargados
            }
        except Exception as e:
            return {"ok": False, "mensaje": f"Error al procesar: {e}", "archivos": self.archivos_cargados}

    def seleccionar_documentos(self):
        if not self.window:
            return {"ok": False, "mensaje": "Ventana no disponible.", "archivos": self.archivos_cargados}

        archivos = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=True,
            file_types=("Documentos (*.pdf;*.docx)", "Todos los archivos (*.*)")
        )
        return self.procesar_rutas(archivos)

    def responder_pregunta(self, pregunta, archivos_seleccionados=None):
        if not pregunta or not pregunta.strip():
            return "Escribe una pregunta antes de enviar."

        if not self.indice or self.indice.esta_vacio():
            return "Primero debes cargar y procesar documentos antes de consultar."

        try:
            indice_filtrado = copy.copy(self.indice)

            # Filtro estricto: solo incluir fragmentos que pertenezcan a los archivos marcados
            if archivos_seleccionados is not None:
                chunks_filtrados = [
                    c for c in self.indice.chunks
                    if any(chunk_es_de_archivo(c, arch) for arch in archivos_seleccionados)
                ]
                indice_filtrado.chunks = chunks_filtrados

            if len(indice_filtrado.chunks) == 0:
                return "No hay documentos marcados o activos para responder a esta consulta."

            top_k = rag_core.determinar_top_k(pregunta, total_chunks=len(indice_filtrado.chunks))
            fragmentos = rag_core.buscar_contexto_relevante(pregunta, indice_filtrado, top_k=top_k)
            respuesta = rag_core.consultar_llm(
                pregunta=pregunta,
                fragmentos=fragmentos,
                modelo=rag_core.MODELOS_DISPONIBLES[0]
            )
            return respuesta
        except Exception as e:
            return f"Error al consultar el modelo: {e}"


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(base_dir, "interface.html")

    api = API()
    window = webview.create_window(
        "VEXA",
        url=html_path,
        js_api=api,
        width=1400,
        height=850,
        min_size=(1000, 650),
        resizable=True,
        background_color="#0a0d14"
    )
    api.set_window(window)
    webview.start(debug=False)

if __name__ == "__main__":
    main()