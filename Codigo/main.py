import os
import json
import hashlib
import pathlib
import copy
import time
import webview
import rag_core

CARPETA_CONFIG = pathlib.Path.home() / ".vexa_local"
ARCHIVO_CONFIG = CARPETA_CONFIG / "config.json"
ARCHIVO_ARCHIVOS_ACTIVOS = CARPETA_CONFIG / "archivos_activos.json"

# Tiempo por defecto si el usuario no elige nada explícitamente (segundos).
# El usuario puede elegir su propio tiempo por archivo desde la interfaz;
# esto solo se usa como respaldo. None = sin límite.
TIEMPO_LIMITE_POR_DEFECTO_SEGUNDOS = 2 * 60 * 60  # 2 horas


def _cargar_archivos_info() -> dict:
    """Lee del disco el registro de archivos activos (nombre -> ruta/hora de carga/límite)."""
    if not ARCHIVO_ARCHIVOS_ACTIVOS.exists():
        return {}
    try:
        return json.loads(ARCHIVO_ARCHIVOS_ACTIVOS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

def _guardar_archivos_info(info: dict) -> None:
    """Persiste el registro de archivos activos en disco."""
    CARPETA_CONFIG.mkdir(parents=True, exist_ok=True)
    ARCHIVO_ARCHIVOS_ACTIVOS.write_text(json.dumps(info), encoding="utf-8")


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


def _formatear_tiempo_restante(segundos: float) -> str:
    segundos = max(0, int(segundos))
    horas = segundos // 3600
    minutos = (segundos % 3600) // 60
    if horas > 0:
        return f"{horas}h {minutos}m"
    if minutos > 0:
        return f"{minutos}m"
    return "menos de 1m"


class API:
    def __init__(self):
        self.window = None
        self.indice = None
        # nombre_archivo -> {"ruta": str, "cargado_en": float(timestamp), "tiempo_limite": float|None}
        # tiempo_limite en segundos; None significa "sin límite".
        # Se recupera del disco para que el tiempo de expiración sea real,
        # incluso si la app estuvo cerrada.
        self.archivos_info = _cargar_archivos_info()
        self._limpiar_archivos_expirados()
        self._reconstruir_indice()

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

    # ------------------------------------------------------------------
    # Manejo de archivos activos (carga, expiración elegible, reconstrucción)
    # ------------------------------------------------------------------

    def _limpiar_archivos_expirados(self) -> bool:
        """Elimina del registro los archivos que superaron SU tiempo límite
        individual (cada archivo puede tener uno distinto, o ninguno).
        Devuelve True si hubo cambios."""
        ahora = time.time()
        expirados = []
        for nombre, info in self.archivos_info.items():
            limite = info.get("tiempo_limite", TIEMPO_LIMITE_POR_DEFECTO_SEGUNDOS)
            if limite is None:
                continue  # "sin límite": nunca expira
            if ahora - info["cargado_en"] >= limite:
                expirados.append(nombre)

        for nombre in expirados:
            del self.archivos_info[nombre]
        if expirados:
            _guardar_archivos_info(self.archivos_info)
        return len(expirados) > 0

    def _reconstruir_indice(self):
        """Reconstruye el índice BM25 a partir de todos los archivos activos
        (no expirados). Si un archivo fue movido/borrado del disco, se ignora
        silenciosamente en vez de romper el resto."""
        rutas_validas = []
        hubo_cambios = False
        for nombre, info in list(self.archivos_info.items()):
            if os.path.exists(info["ruta"]):
                rutas_validas.append(info["ruta"])
            else:
                del self.archivos_info[nombre]
                hubo_cambios = True

        if hubo_cambios:
            _guardar_archivos_info(self.archivos_info)

        if rutas_validas:
            self.indice = rag_core.procesar_documentos(rutas_validas)
        else:
            self.indice = None

    def _lista_archivos_activos(self):
        ahora = time.time()
        resultado = []
        for nombre, info in sorted(self.archivos_info.items(), key=lambda kv: kv[1]["cargado_en"]):
            limite = info.get("tiempo_limite", TIEMPO_LIMITE_POR_DEFECTO_SEGUNDOS)
            if limite is None:
                resultado.append({
                    "nombre": nombre,
                    "segundos_restantes": None,
                    "tiempo_restante_texto": "Sin límite",
                    "por_vencer": False,
                })
                continue
            restante = limite - (ahora - info["cargado_en"])
            resultado.append({
                "nombre": nombre,
                "segundos_restantes": max(0, int(restante)),
                "tiempo_restante_texto": _formatear_tiempo_restante(restante),
                "por_vencer": restante <= 15 * 60,  # últimos 15 minutos: aviso visual
            })
        return resultado

    def estado_archivos(self):
        """Llamado periódicamente desde el frontend para refrescar la lista
        de archivos y detectar expiraciones sin que el usuario haga nada."""
        hubo_cambios = self._limpiar_archivos_expirados()
        if hubo_cambios:
            self._reconstruir_indice()
        return {
            "archivos": self._lista_archivos_activos(),
            "expiraron": hubo_cambios,
        }

    def procesar_rutas(self, rutas, tiempo_limite_segundos=None):
        """tiempo_limite_segundos: elegido libremente por el usuario en la
        interfaz. 0 o None significa "sin límite". Si no se envía nada,
        se usa el valor por defecto."""
        if not rutas:
            return {"ok": False, "mensaje": "No se recibieron archivos.", "archivos": self._lista_archivos_activos()}

        if tiempo_limite_segundos is None:
            limite = TIEMPO_LIMITE_POR_DEFECTO_SEGUNDOS
        elif tiempo_limite_segundos == 0:
            limite = None  # sin límite
        else:
            limite = tiempo_limite_segundos

        try:
            self._limpiar_archivos_expirados()
            ahora = time.time()
            for ruta in rutas:
                nombre = os.path.basename(ruta)
                # Volver a cargar un archivo reinicia su tiempo de vida
                # con el límite elegido en ese momento.
                self.archivos_info[nombre] = {"ruta": ruta, "cargado_en": ahora, "tiempo_limite": limite}
            _guardar_archivos_info(self.archivos_info)

            self._reconstruir_indice()

            texto_limite = "sin límite de tiempo" if limite is None else f"activo por {_formatear_tiempo_restante(limite)}"
            return {
                "ok": True,
                "mensaje": f"Procesados {len(rutas)} archivo(s), {texto_limite}.",
                "archivos": self._lista_archivos_activos(),
            }
        except Exception as e:
            return {"ok": False, "mensaje": f"Error al procesar: {e}", "archivos": self._lista_archivos_activos()}

    def eliminar_archivo(self, nombre):
        """Quita un archivo del contexto activo manualmente (antes de que expire)."""
        if nombre in self.archivos_info:
            del self.archivos_info[nombre]
            _guardar_archivos_info(self.archivos_info)
            self._reconstruir_indice()
            return {"ok": True, "mensaje": f"'{nombre}' fue retirado del contexto.", "archivos": self._lista_archivos_activos()}
        return {"ok": False, "mensaje": "Archivo no encontrado.", "archivos": self._lista_archivos_activos()}

    def seleccionar_documentos(self, tiempo_limite_segundos=None):
        if not self.window:
            return {"ok": False, "mensaje": "Ventana no disponible.", "archivos": self._lista_archivos_activos()}

        archivos = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=True,
            file_types=("Documentos (*.pdf;*.docx)", "Todos los archivos (*.*)")
        )
        return self.procesar_rutas(archivos, tiempo_limite_segundos)

    # ------------------------------------------------------------------
    # Consulta al modelo (con citación de fuentes)
    # ------------------------------------------------------------------

    def responder_pregunta(self, pregunta, archivos_seleccionados=None):
        """Siempre devuelve un dict: {"texto": str, "fuentes": [str, ...]}."""
        if not pregunta or not pregunta.strip():
            return {"texto": "Escribe una pregunta antes de enviar.", "fuentes": []}

        # Antes de responder, asegura que ningún archivo vencido siga
        # aportando contexto.
        if self._limpiar_archivos_expirados():
            self._reconstruir_indice()

        if not self.indice or self.indice.esta_vacio():
            return {"texto": "Primero debes cargar y procesar documentos antes de consultar (o tus archivos ya vencieron).", "fuentes": []}

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
                return {"texto": "No hay documentos marcados o activos para responder a esta consulta.", "fuentes": []}

            top_k = rag_core.determinar_top_k(pregunta, total_chunks=len(indice_filtrado.chunks))
            fragmentos = rag_core.buscar_contexto_relevante(pregunta, indice_filtrado, top_k=top_k)
            respuesta = rag_core.consultar_llm(
                pregunta=pregunta,
                fragmentos=fragmentos,
                modelo=rag_core.MODELOS_DISPONIBLES[0]
            )

            # Citación de fuentes: cada Chunk trae su propia etiqueta legible
            # (archivo + página) a través de la propiedad `fuente`.
            fuentes_unicas = []
            for frag in fragmentos:
                etiqueta = frag.fuente
                if etiqueta not in fuentes_unicas:
                    fuentes_unicas.append(etiqueta)

            return {"texto": respuesta, "fuentes": fuentes_unicas}
        except Exception as e:
            return {"texto": f"Error al consultar el modelo: {e}", "fuentes": []}


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
